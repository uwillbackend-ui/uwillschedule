import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from ortools.sat.python import cp_model
from src.data_loader import DataLoader, DAYS_OF_WEEK, minutes_to_str

def solve_full():
    loader = DataLoader("data")
    loader.load_all()

    model = cp_model.CpModel()

    # Organize requirements by batch
    batch_reqs = {}
    for req in loader.subject_requirements:
        key = (req.center, req.batch)
        batch_reqs.setdefault(key, []).append(req)

    batch_day_intervals = {}
    fac_day_items = {}
    batch_altered_vars = {}
    all_lectures = []

    for (c, b), reqs in batch_reqs.items():
        b_info = loader.batches.get((c, b))
        if not b_info:
            for (bc, bb), info in loader.batches.items():
                if bc == c and (bb in b or b in bb):
                    b_info = info; break
        if not b_info:
            print(f"Skipping unknown batch {c} - {b}")
            continue

        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        batch_altered_vars[(c, b)] = []

        # Recess
        if b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            for d in op_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, ret - rst, f"rec_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

        # Fixed visiting faculty
        for vf in loader.fixed_lectures:
            if vf.center == c and (vf.batch == b or vf.batch in b or b in vf.batch):
                vf_dur = vf.end_min - vf.start_min
                vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{c}_{b}_{vf.day}_{vf.start_min}")
                batch_day_intervals.setdefault(((c, b), vf.day), []).append(vf_iv)
                
                # Fixed active var is a constant True
                true_var = model.NewBoolVar(f"true_{vf.faculty}_{vf.day}_{vf.start_min}")
                model.Add(true_var == 1)
                fac_day_items.setdefault((vf.faculty, vf.day), []).append({
                    "start": model.NewConstant(vf.start_min),
                    "end": model.NewConstant(vf.end_min),
                    "center": c,
                    "active": true_var,
                    "is_morning": vf.start_min < 840
                })

        # Subject requirements
        for req in reqs:
            w_days = min(req.weekly_days, len(op_days))
            nom_dur = req.daily_duration_min
            dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
            dur_options = [d for d in dur_options if d >= 40]

            for inst in range(w_days):
                day_vars = {d: model.NewBoolVar(f"d_{req.req_id}_{inst}_{d}") for d in op_days}
                # Exactly 1 day selected
                model.Add(sum(day_vars.values()) == 1)

                st_var = model.NewIntVar(es, le - min(dur_options), f"st_{req.req_id}_{inst}")
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst}")
                end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{inst}")
                model.Add(end_var == st_var + dur_var)

                # Altered duration tracking (up to 20%)
                alt = model.NewBoolVar(f"alt_{req.req_id}_{inst}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                batch_altered_vars[(c, b)].append(alt)

                is_mrg = es < 840

                # Faculty restriction on end time if any
                fac_restr = loader.faculties.get(req.faculty)
                if fac_restr:
                    if fac_restr.available_to_min:
                        model.Add(end_var <= fac_restr.available_to_min)

                for d in op_days:
                    iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                    batch_day_intervals.setdefault(((c, b), d), []).append(iv)

                    fac_day_items.setdefault((req.faculty, d), []).append({
                        "start": st_var,
                        "end": end_var,
                        "center": c,
                        "active": day_vars[d],
                        "is_morning": is_mrg
                    })

                all_lectures.append({
                    "req": req,
                    "inst": inst,
                    "start": st_var,
                    "dur": dur_var,
                    "end": end_var,
                    "day_vars": day_vars,
                    "alt": alt
                })

            # At most 1 lecture per subject per day
            for d in op_days:
                inst_on_d = [lv["day_vars"][d] for lv in all_lectures if lv["req"].req_id == req.req_id]
                model.Add(sum(inst_on_d) <= 1)

    # Constraint: Max 20% altered lectures per batch
    for (c, b), alts in batch_altered_vars.items():
        if alts:
            model.Add(sum(alts) <= int(0.20 * len(alts)))

    # Constraint: No batch overlap
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # Constraint: Faculty no-overlap & travel time
    travel_time = loader.travel_matrix
    prec_added = 0

    for (fac, d), items in fac_day_items.items():
        if not fac or fac.startswith("TBD_"):
            continue
        n = len(items)
        if n < 2:
            continue

        for i in range(n):
            for j in range(i + 1, n):
                it1, it2 = items[i], items[j]
                # If one is morning and other is evening, no conflict possible (min 90m gap)
                if it1["is_morning"] != it2["is_morning"]:
                    continue

                c1, c2 = it1["center"], it2["center"]
                tt_12 = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                tt_21 = travel_time.get((c2, c1), 30) if c1 != c2 else 0

                b_order = model.NewBoolVar(f"ord_{fac}_{d}_{i}_{j}")
                a1 = it1["active"]
                a2 = it2["active"]

                # it1 before it2
                model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([a1, a2, b_order])
                # it2 before it1
                model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([a1, a2, b_order.Not()])
                prec_added += 1

    print(f"Total lectures created: {len(all_lectures)}")
    print(f"Total cross-center precedence constraints: {prec_added}")

    # Objective: Minimize duration deviations (prefer nominal duration)
    total_alts = [lv["alt"] for lv in all_lectures]
    model.Minimize(sum(total_alts))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_workers = 8

    print("Solving full institute CP-SAT model...")
    t0 = time.time()
    st = solver.Solve(model)
    el = time.time() - t0
    print(f"Solver Status: {solver.StatusName(st)} in {el:.2f} seconds!")

    if st in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        altered_count = sum(solver.Value(lv["alt"]) for lv in all_lectures)
        print(f"Lectures with adjusted duration (+/- 10 mins): {altered_count} / {len(all_lectures)}")
        return solver, all_lectures, loader
    return None, None, None

if __name__ == "__main__":
    solve_full()
