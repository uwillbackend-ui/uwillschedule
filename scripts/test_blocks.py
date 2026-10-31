import sys, os
sys.path.insert(0, os.path.abspath("."))
from ortools.sat.python import cp_model
from src.data_loader import DataLoader, DAYS_OF_WEEK, minutes_to_str

def test_center_blocks_balanced(center_name="SUB"):
    loader = DataLoader("data")
    loader.load_all()

    model = cp_model.CpModel()
    c_batches = [b for (bc, bb), b in loader.batches.items() if bc == center_name]
    c_reqs = [r for r in loader.subject_requirements if r.center == center_name]
    c_vfs = [vf for vf in loader.fixed_lectures if vf.center == center_name]

    batch_day_intervals = {}
    batch_altered_vars = {}
    c_lecture_vars = []
    block_consistency_vars = []

    B1 = ["MONDAY", "TUESDAY", "WEDNESDAY"]
    B2 = ["THURSDAY", "FRIDAY", "SATURDAY"]

    for b_info in c_batches:
        b = b_info.name
        batch_altered_vars[b] = []
        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min

        # Recess
        if b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            for d in op_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, ret - rst, f"rec_{b}_{d}")
                batch_day_intervals.setdefault((b, d), []).append(r_iv)

        # Fixed VF
        for vf in c_vfs:
            if vf.batch == b or vf.batch in b or b in vf.batch:
                vf_dur = vf.end_min - vf.start_min
                vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{b}_{vf.day}_{vf.start_min}")
                batch_day_intervals.setdefault((b, vf.day), []).append(vf_iv)

        b_subjs = [r for r in c_reqs if r.batch == b]
        
        # Track 3-day pattern choices for load balancing between B1 and B2
        p1_vars_for_batch = []
        p2_vars_for_batch = []

        for req in b_subjs:
            nom_dur = req.daily_duration_min
            dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
            dur_options = [d for d in dur_options if d >= 40]
            w_days = min(req.weekly_days, len(op_days))

            patterns = []
            if w_days >= 6:
                patterns = [op_days]
            elif w_days == 5:
                patterns = [[d for d in op_days if d != "SATURDAY"]]
            elif w_days == 3:
                p1 = [d for d in B1 if d in op_days]
                p2 = [d for d in B2 if d in op_days]
                if len(p1) == 3: patterns.append(p1)
                if len(p2) == 3: patterns.append(p2)
                if not patterns: patterns = [op_days[:3]]
            elif w_days == 2:
                patterns = [["MONDAY", "TUESDAY"], ["WEDNESDAY", "THURSDAY"], ["FRIDAY", "SATURDAY"]]
                patterns = [p for p in patterns if all(d in op_days for d in p)]
                if not patterns: patterns = [op_days[:2]]
            else:
                patterns = [[d] for d in op_days]

            pat_vars = [model.NewBoolVar(f"pv_{req.req_id}_{i}") for i in range(len(patterns))]
            model.Add(sum(pat_vars) == 1)

            if w_days == 3 and len(patterns) == 2:
                p1_vars_for_batch.append(pat_vars[0])
                p2_vars_for_batch.append(pat_vars[1])

            cand_days = sorted(list({d for p in patterns for d in p}))
            day_slot_vars = {}

            for d in cand_days:
                pats_with_d = [pat_vars[i] for i, p in enumerate(patterns) if d in p]
                act = model.NewBoolVar(f"act_{req.req_id}_{d}")
                model.Add(act == sum(pats_with_d))

                st_var = model.NewIntVar(es, le - min(dur_options), f"st_{req.req_id}_{d}")
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{d}")
                end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{d}")
                model.Add(end_var == st_var + dur_var)

                alt = model.NewBoolVar(f"alt_{req.req_id}_{d}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                alt_act = model.NewBoolVar(f"alt_act_{req.req_id}_{d}")
                model.Add(alt_act == 1).OnlyEnforceIf([alt, act])
                model.Add(alt_act == 0).OnlyEnforceIf(alt.Not())
                model.Add(alt_act == 0).OnlyEnforceIf(act.Not())
                batch_altered_vars[b].append(alt_act)

                iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, act, f"iv_{req.req_id}_{d}")
                batch_day_intervals.setdefault((b, d), []).append(iv)

                day_slot_vars[d] = {"start": st_var, "dur": dur_var, "act": act}
                c_lecture_vars.append({"req": req, "day": d, "start": st_var, "dur": dur_var, "end": end_var, "act": act, "alt": alt_act})

            # B1 consistency
            d_b1 = [d for d in B1 if d in day_slot_vars]
            if len(d_b1) >= 2:
                for i in range(len(d_b1) - 1):
                    d1, d2 = d_b1[i], d_b1[i + 1]
                    s1, s2 = day_slot_vars[d1], day_slot_vars[d2]
                    same_b1 = model.NewBoolVar(f"same_b1_{req.req_id}_{d1}_{d2}")
                    model.Add(s1["start"] == s2["start"]).OnlyEnforceIf([s1["act"], s2["act"], same_b1])
                    model.Add(s1["dur"] == s2["dur"]).OnlyEnforceIf([s1["act"], s2["act"], same_b1])
                    block_consistency_vars.append(same_b1)

            # B2 consistency
            d_b2 = [d for d in B2 if d in day_slot_vars]
            if len(d_b2) >= 2:
                for i in range(len(d_b2) - 1):
                    d1, d2 = d_b2[i], d_b2[i + 1]
                    s1, s2 = day_slot_vars[d1], day_slot_vars[d2]
                    same_b2 = model.NewBoolVar(f"same_b2_{req.req_id}_{d1}_{d2}")
                    model.Add(s1["start"] == s2["start"]).OnlyEnforceIf([s1["act"], s2["act"], same_b2])
                    model.Add(s1["dur"] == s2["dur"]).OnlyEnforceIf([s1["act"], s2["act"], same_b2])
                    block_consistency_vars.append(same_b2)

        # Balance 3-day subjects evenly between B1 and B2
        if p1_vars_for_batch and len(p1_vars_for_batch) >= 2:
            half = (len(p1_vars_for_batch) + 1) // 2
            model.Add(sum(p1_vars_for_batch) <= half)
            model.Add(sum(p2_vars_for_batch) <= half)

        # Max 20% altered
        if batch_altered_vars[b]:
            model.Add(sum(batch_altered_vars[b]) <= int(0.20 * len(batch_altered_vars[b])))

    for (b, d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    alt_sum = sum(lv["alt"] for lv in c_lecture_vars)
    same_sum = sum(block_consistency_vars)
    model.Maximize(same_sum * 10 - alt_sum)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    st = solver.Solve(model)
    print(f"Center {center_name} Balanced Block Solver Status: {solver.StatusName(st)}")

    if st in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        for b_info in c_batches:
            b = b_info.name
            print(f"\n--- BALANCED SCHEDULE FOR BATCH: {b} ---")
            for d in DAYS_OF_WEEK:
                d_lecs = [lv for lv in c_lecture_vars if lv["req"].batch == b and lv["day"] == d and solver.Value(lv["act"]) == 1]
                d_lecs = sorted(d_lecs, key=lambda x: solver.Value(x["start"]))
                lec_strs = [f"{minutes_to_str(solver.Value(x['start']))}-{minutes_to_str(solver.Value(x['end']))} {x['req'].subject} ({x['req'].faculty})" for x in d_lecs]
                print(f"  {d:10s}: {', '.join(lec_strs)}")

if __name__ == "__main__":
    test_center_blocks_balanced("SUB")
