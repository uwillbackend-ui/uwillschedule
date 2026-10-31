import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from ortools.sat.python import cp_model
from src.data_loader import DataLoader

def find_conflict():
    loader = DataLoader("data")
    loader.load_all()

    # Get list of unique faculties
    fac_list = sorted(list({req.faculty for req in loader.subject_requirements if req.faculty and not req.faculty.startswith("TBD_")}))

    for test_fac in fac_list:
        model = cp_model.CpModel()
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
            if not b_info: continue

            op_days = b_info.operating_days
            es, le = b_info.earliest_start_min, b_info.latest_end_min
            batch_altered_vars[(c, b)] = []

            if b_info.recess_start_min and b_info.recess_end_min:
                rst, ret = b_info.recess_start_min, b_info.recess_end_min
                for d in op_days:
                    r_iv = model.NewFixedSizeIntervalVar(rst, ret - rst, f"rec_{c}_{b}_{d}")
                    batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

            for vf in loader.fixed_lectures:
                if vf.center == c and (vf.batch == b or vf.batch in b or b in vf.batch):
                    vf_dur = vf.end_min - vf.start_min
                    vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{c}_{b}_{vf.day}_{vf.start_min}")
                    batch_day_intervals.setdefault(((c, b), vf.day), []).append(vf_iv)
                    if vf.faculty == test_fac:
                        true_var = model.NewBoolVar(f"true_{vf.faculty}_{vf.day}_{vf.start_min}")
                        model.Add(true_var == 1)
                        fac_day_items.setdefault((vf.faculty, vf.day), []).append({
                            "start": model.NewConstant(vf.start_min),
                            "end": model.NewConstant(vf.end_min),
                            "center": c,
                            "active": true_var,
                            "is_morning": vf.start_min < 840
                        })

            for req in reqs:
                w_days = min(req.weekly_days, len(op_days))
                nom_dur = req.daily_duration_min
                dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
                dur_options = [d for d in dur_options if d >= 40]

                for inst in range(w_days):
                    day_vars = {d: model.NewBoolVar(f"d_{req.req_id}_{inst}_{d}") for d in op_days}
                    model.Add(sum(day_vars.values()) == 1)

                    st_var = model.NewIntVar(es, le - min(dur_options), f"st_{req.req_id}_{inst}")
                    dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst}")
                    end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{inst}")
                    model.Add(end_var == st_var + dur_var)

                    alt = model.NewBoolVar(f"alt_{req.req_id}_{inst}")
                    model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                    model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                    batch_altered_vars[(c, b)].append(alt)

                    is_mrg = es < 840
                    fac_restr = loader.faculties.get(req.faculty)
                    if fac_restr and fac_restr.available_to_min:
                        model.Add(end_var <= fac_restr.available_to_min)

                    for d in op_days:
                        iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                        batch_day_intervals.setdefault(((c, b), d), []).append(iv)
                        if req.faculty == test_fac:
                            fac_day_items.setdefault((req.faculty, d), []).append({
                                "start": st_var,
                                "end": end_var,
                                "center": c,
                                "active": day_vars[d],
                                "is_morning": is_mrg
                            })

                    all_lectures.append({"req": req, "inst": inst, "day_vars": day_vars})

                for d in op_days:
                    inst_on_d = [lv["day_vars"][d] for lv in all_lectures if lv["req"].req_id == req.req_id]
                    model.Add(sum(inst_on_d) <= 1)

        # Batch constraints
        for (c, b), alts in batch_altered_vars.items():
            if alts:
                model.Add(sum(alts) <= int(0.20 * len(alts)))
        for ((c, b), d), ivs in batch_day_intervals.items():
            model.AddNoOverlap(ivs)

        # Add precedence for test_fac only
        travel_time = loader.travel_matrix
        for (fac, d), items in fac_day_items.items():
            n = len(items)
            for i in range(n):
                for j in range(i + 1, n):
                    it1, it2 = items[i], items[j]
                    if it1["is_morning"] != it2["is_morning"]: continue
                    c1, c2 = it1["center"], it2["center"]
                    tt_12 = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                    tt_21 = travel_time.get((c2, c1), 30) if c1 != c2 else 0
                    b_order = model.NewBoolVar(f"ord_{fac}_{d}_{i}_{j}")
                    a1, a2 = it1["active"], it2["active"]
                    model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([a1, a2, b_order])
                    model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([a1, a2, b_order.Not()])

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 2.0
        st = solver.Solve(model)
        status = solver.StatusName(st)
        if status != "OPTIMAL" and status != "FEASIBLE":
            print(f"FAILED on faculty: {test_fac} -> {status}")
        else:
            print(f"Passed faculty: {test_fac}")

if __name__ == "__main__":
    find_conflict()
