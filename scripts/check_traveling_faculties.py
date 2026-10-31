import sys, os
sys.path.insert(0, os.path.abspath("."))
from src.data_loader import DataLoader
from ortools.sat.python import cp_model

loader = DataLoader("data")
loader.load_all()

# Find all traveling faculties
fac_centers = {}
for req in loader.subject_requirements:
    if req.faculty and not req.faculty.startswith("TBD_"):
        fac_centers.setdefault(req.faculty, set()).add(req.center)

traveling = [f for f, cs in fac_centers.items() if len(cs) > 1]
print(f"Testing {len(traveling)} traveling faculties:")

# Test each one individually in the global model to see which one fails
for test_fac in traveling:
    model = cp_model.CpModel()
    batch_day_intervals = {}
    fac_day_items = {}
    batch_altered_vars = {}
    all_lecture_vars = []

    for (c, b), b_info in loader.batches.items():
        if b_info.recess_start_min and b_info.recess_end_min:
            for d in b_info.operating_days:
                r_iv = model.NewFixedSizeIntervalVar(b_info.recess_start_min, b_info.recess_end_min - b_info.recess_start_min, f"r_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

    for vf in loader.fixed_lectures:
        dur = vf.end_min - vf.start_min
        if dur > 0:
            iv = model.NewFixedSizeIntervalVar(vf.start_min, dur, f"vf_{vf.center}_{vf.batch}_{vf.day}_{vf.start_min}")
            batch_day_intervals.setdefault(((vf.center, vf.batch), vf.day), []).append(iv)

    for req in loader.subject_requirements:
        c, b = req.center, req.batch
        b_info = loader.batches.get((c, b))
        if not b_info:
            for (bc, bb), info in loader.batches.items():
                if bc == c and (bb in b or b in bb):
                    b_info = info; break
        if not b_info: continue

        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        nom_dur = req.daily_duration_min
        dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
        dur_options = [d for d in dur_options if 45 <= d <= 120]
        if not dur_options: dur_options = [max(45, min(120, nom_dur))]
        w_days = min(req.weekly_days, len(op_days))
        if w_days <= 0: w_days = 1
        is_mrg = es < 840

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
            batch_altered_vars.setdefault((c, b), []).append(alt)

            fac_restr = loader.faculties.get(req.faculty)
            if fac_restr and fac_restr.available_to_min and not is_mrg:
                model.Add(end_var <= fac_restr.available_to_min)

            for d in op_days:
                iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(iv)
                if req.faculty == test_fac:
                    fac_day_items.setdefault((req.faculty, d), []).append({
                        "start": st_var, "end": end_var, "center": c, "active": day_vars[d], "is_morning": is_mrg
                    })

            all_lecture_vars.append({"req": req, "day_vars": day_vars})

        for d in op_days:
            inst_on_d = [lv["day_vars"][d] for lv in all_lecture_vars if lv["req"].req_id == req.req_id]
            model.Add(sum(inst_on_d) <= 1)

    for (c, b), alts in batch_altered_vars.items():
        if alts: model.Add(sum(alts) <= int(0.20 * len(alts)))

    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # Add travel precedence for test_fac
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
                b_ord = model.NewBoolVar(f"ord_{fac}_{d}_{i}_{j}")
                a1, a2 = it1["active"], it2["active"]
                model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([a1, a2, b_ord])
                model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([a1, a2, b_ord.Not()])

    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 2.0
    st = s.Solve(model)
    st_name = s.StatusName(st)
    if st_name != "OPTIMAL" and st_name != "FEASIBLE":
        print(f"  ❌ FAILED on: {test_fac} -> {st_name}")
    else:
        print(f"  ✅ PASSED: {test_fac}")
