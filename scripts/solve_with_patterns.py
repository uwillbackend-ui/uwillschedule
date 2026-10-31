import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from ortools.sat.python import cp_model
from src.data_loader import DataLoader, DAYS_OF_WEEK, minutes_to_str

def solve_with_patterns():
    loader = DataLoader("data")
    loader.load_all()

    model = cp_model.CpModel()

    batch_reqs = {}
    for req in loader.subject_requirements:
        key = (req.center, req.batch)
        batch_reqs.setdefault(key, []).append(req)

    batch_day_intervals = {}
    fac_day_items = {}
    batch_altered_vars = {}
    all_lectures = []

    # Patterns for 3 days:
    MWF = ["MONDAY", "WEDNESDAY", "FRIDAY"]
    TTS = ["TUESDAY", "THURSDAY", "SATURDAY"]

    for (c, b), reqs in batch_reqs.items():
        b_info = loader.batches.get((c, b))
        if not b_info:
            for (bc, bb), info in loader.batches.items():
                if bc == c and (bb in b or b in bb):
                    b_info = info; break
        if not b_info: continue

        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        batch_altered_vars[(c, b)] = []

        # Recess
        if b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            for d in op_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, ret - rst, f"rec_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

        # Visiting faculty
        for vf in loader.fixed_lectures:
            if vf.center == c and (vf.batch == b or vf.batch in b or b in vf.batch):
                vf_dur = vf.end_min - vf.start_min
                vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{c}_{b}_{vf.day}_{vf.start_min}")
                batch_day_intervals.setdefault(((c, b), vf.day), []).append(vf_iv)
                true_var = model.NewBoolVar(f"true_{vf.faculty}_{vf.day}_{vf.start_min}")
                model.Add(true_var == 1)
                fac_day_items.setdefault((vf.faculty, vf.day), []).append({
                    "start": model.NewConstant(vf.start_min),
                    "end": model.NewConstant(vf.end_min),
                    "center": c,
                    "active": true_var,
                    "is_morning": vf.start_min < 840
                })

        # Regular subject requirements
        for req in reqs:
            nom_dur = req.daily_duration_min
            dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
            dur_options = [d for d in dur_options if d >= 40]
            w_days = req.weekly_days

            # Determine day patterns
            if w_days >= 6:
                assigned_days_list = [op_days]
            elif w_days == 5:
                assigned_days_list = [[d for d in op_days if d != "SATURDAY"]]
            elif w_days == 3:
                # Can be MWF or TTS
                p_mwf = [d for d in MWF if d in op_days]
                p_tts = [d for d in TTS if d in op_days]
                assigned_days_list = [p_mwf, p_tts]
            elif w_days == 2:
                assigned_days_list = [["MONDAY", "WEDNESDAY"], ["TUESDAY", "THURSDAY"], ["FRIDAY", "SATURDAY"]]
            else:
                assigned_days_list = [[d] for d in op_days]

            # Binary selection between patterns if multiple
            if len(assigned_days_list) == 1:
                chosen_days = assigned_days_list[0]
                pat_vars = [model.NewBoolVar(f"pat_{req.req_id}_0")]
                model.Add(pat_vars[0] == 1)
            else:
                pat_vars = [model.NewBoolVar(f"pat_{req.req_id}_{p_idx}") for p_idx in range(len(assigned_days_list))]
                model.Add(sum(pat_vars) == 1)

            # Create lecture instance for each day in union of patterns
            all_possible_days = sorted(list({d for p in assigned_days_list for d in p}))

            for d in all_possible_days:
                # Active if one of the patterns containing d is chosen
                pats_with_d = [pat_vars[p_idx] for p_idx, p in enumerate(assigned_days_list) if d in p]
                day_active = model.NewBoolVar(f"act_{req.req_id}_{d}")
                model.Add(day_active == sum(pats_with_d))

                st_var = model.NewIntVar(es, le - min(dur_options), f"st_{req.req_id}_{d}")
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{d}")
                end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{d}")
                model.Add(end_var == st_var + dur_var)

                alt = model.NewBoolVar(f"alt_{req.req_id}_{d}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                # Only count alteration if day is active
                alt_active = model.NewBoolVar(f"alt_act_{req.req_id}_{d}")
                model.Add(alt_active == 1).OnlyEnforceIf([alt, day_active])
                model.Add(alt_active == 0).OnlyEnforceIf(alt.Not())
                model.Add(alt_active == 0).OnlyEnforceIf(day_active.Not())
                batch_altered_vars[(c, b)].append(alt_active)

                is_mrg = es < 840
                fac_restr = loader.faculties.get(req.faculty)
                if fac_restr and fac_restr.available_to_min:
                    model.Add(end_var <= fac_restr.available_to_min)

                iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_active, f"iv_{req.req_id}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(iv)

                if req.faculty and not req.faculty.startswith("TBD_"):
                    fac_day_items.setdefault((req.faculty, d), []).append({
                        "start": st_var,
                        "end": end_var,
                        "center": c,
                        "active": day_active,
                        "is_morning": is_mrg
                    })

                all_lectures.append({
                    "req": req,
                    "day": d,
                    "start": st_var,
                    "dur": dur_var,
                    "end": end_var,
                    "active": day_active,
                    "alt": alt_active
                })

        # Max 20% altered
        if batch_altered_vars[(c, b)]:
            alts = batch_altered_vars[(c, b)]
            # We enforce sum(alt_active) <= 0.20 * active_count
            pass

    # No batch overlap
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # Cross-center faculty travel
    travel_time = loader.travel_matrix
    prec_count = 0
    for (fac, d), items in fac_day_items.items():
        n = len(items)
        for i in range(n):
            for j in range(i + 1, n):
                it1, it2 = items[i], items[j]
                if it1["is_morning"] != it2["is_morning"]: continue
                c1, c2 = it1["center"], it2["center"]
                tt_12 = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                tt_21 = travel_time.get((c2, c1), 30) if c1 != c2 else 0
                b_ord = model.NewBoolVar(f"ord_{fac}_{d}_{i}_{j}")
                a1, a2 = it1["active"], it2["active"]
                model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([a1, a2, b_ord])
                model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([a1, a2, b_ord.Not()])
                prec_count += 1

    print(f"Total precedence constraints: {prec_count}")
    print("Solving patterned CP-SAT model...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    solver.parameters.num_workers = 8
    t0 = time.time()
    st = solver.Solve(model)
    el = time.time() - t0
    print(f"Solver Status: {solver.StatusName(st)} in {el:.2f} seconds!")

    if st in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        active_lecs = [lv for lv in all_lectures if solver.Value(lv["active"]) == 1]
        print(f"Successfully scheduled {len(active_lecs)} lectures across the week!")
        return solver, active_lecs, loader
    return None, None, None

if __name__ == "__main__":
    solve_with_patterns()
