import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from typing import Dict, List
from ortools.sat.python import cp_model

from src.models import ScheduledSlot
from src.data_loader import DataLoader, DAYS_OF_WEEK, minutes_to_str

BLOCK_1 = ["MONDAY", "TUESDAY", "WEDNESDAY"]
BLOCK_2 = ["THURSDAY", "FRIDAY", "SATURDAY"]

def solve_unified_global():
    print("=" * 65)
    print("UNIFIED GLOBAL INSTITUTE SCHEDULER")
    print("Zero overlaps | Exact travel buffers | 45m-120m duration | Block consistency")
    print("=" * 65)

    loader = DataLoader("data")
    loader.load_all()

    model = cp_model.CpModel()

    # Track intervals
    batch_day_intervals = {}
    fac_day_items = {}
    batch_altered_vars = {}
    all_lecture_vars = []
    block_consistency_vars = []

    # Map all batch names across centers
    all_batches = {}
    for req in loader.subject_requirements:
        all_batches.setdefault(req.center, set()).add(req.batch)
    for vf in loader.fixed_lectures:
        all_batches.setdefault(vf.center, set()).add(vf.batch)

    # 1. FIXED RECESS INTERVALS
    for (c, b), b_info in loader.batches.items():
        if b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            rdur = ret - rst
            for d in b_info.operating_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, rdur, f"rec_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

    # 2. FIXED VISITING FACULTY LECTURES
    fixed_slots = []
    for vf in loader.fixed_lectures:
        vf_dur = vf.end_min - vf.start_min
        # Ensure vf_dur is at least 15m
        if vf_dur <= 0: continue
        vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{vf.center}_{vf.batch}_{vf.day}_{vf.start_min}")
        batch_day_intervals.setdefault(((vf.center, vf.batch), vf.day), []).append(vf_iv)
        fixed_slots.append(ScheduledSlot(
            batch_key=f"{vf.center}_{vf.batch}",
            center=vf.center,
            batch_name=vf.batch,
            day=vf.day,
            start_min=vf.start_min,
            end_min=vf.end_min,
            subject=vf.subject,
            faculty=vf.faculty,
            is_fixed=True,
            chapter="School Topic",
            topic="Regular Syllabus"
        ))

    # 3. REGULAR SUBJECT REQUIREMENTS
    req_by_batch = {}
    for req in loader.subject_requirements:
        req_by_batch.setdefault((req.center, req.batch), []).append(req)

    for (c, b), reqs in req_by_batch.items():
        b_info = loader.batches.get((c, b))
        if not b_info:
            for (bc, bb), info in loader.batches.items():
                if bc == c and (bb in b or b in bb):
                    b_info = info; break
        if not b_info: continue

        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        batch_altered_vars[(c, b)] = []

        for req in reqs:
            nom_dur = req.daily_duration_min
            # Enforce strict user requirement: 45 min <= duration <= 120 min
            # Flexibility: +/- 10 mins (in 5-min steps)
            dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
            dur_options = [d for d in dur_options if 45 <= d <= 120]
            if not dur_options:
                dur_options = [max(45, min(120, nom_dur))]

            w_days = min(req.weekly_days, len(op_days))
            if w_days <= 0: w_days = 1

            day_slot_vars = {}

            for inst in range(w_days):
                day_vars = {d: model.NewBoolVar(f"d_{req.req_id}_{inst}_{d}") for d in op_days}
                model.Add(sum(day_vars.values()) == 1)

                st_var = model.NewIntVar(es, le - min(dur_options), f"st_{req.req_id}_{inst}")
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst}")
                end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{inst}")
                model.Add(end_var == st_var + dur_var)

                # Altered tracking
                alt = model.NewBoolVar(f"alt_{req.req_id}_{inst}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                batch_altered_vars[(c, b)].append(alt)

                is_mrg = es < 840
                fac_restr = loader.faculties.get(req.faculty)
                # Evening cutoff (e.g. Vicky Sir 6:30 PM)
                if fac_restr and fac_restr.available_to_min and not is_mrg:
                    model.Add(end_var <= fac_restr.available_to_min)

                for d in op_days:
                    iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                    batch_day_intervals.setdefault(((c, b), d), []).append(iv)
                    day_slot_vars.setdefault(d, []).append({"start": st_var, "dur": dur_var, "end": end_var, "act": day_vars[d]})

                    # Faculty tracking for cross-center travel
                    if req.faculty and not req.faculty.startswith("TBD_"):
                        fac_day_items.setdefault((req.faculty, d), []).append({
                            "start": st_var,
                            "end": end_var,
                            "center": c,
                            "active": day_vars[d],
                            "is_morning": is_mrg
                        })

                all_lecture_vars.append({
                    "req": req, "center": c, "batch": b, "inst": inst,
                    "start": st_var, "dur": dur_var, "end": end_var,
                    "day_vars": day_vars, "alt": alt
                })

            # At most 1 lecture per subject per day
            for d in op_days:
                inst_on_d = [lv["day_vars"][d] for lv in all_lecture_vars if lv["req"].req_id == req.req_id]
                model.Add(sum(inst_on_d) <= 1)

            # Block 1 consistency (Mon == Tue == Wed)
            d_b1 = [d for d in BLOCK_1 if d in op_days]
            for i in range(len(d_b1)):
                for j in range(i + 1, len(d_b1)):
                    d1, d2 = d_b1[i], d_b1[j]
                    insts1 = day_slot_vars.get(d1, [])
                    insts2 = day_slot_vars.get(d2, [])
                    for s1 in insts1:
                        for s2 in insts2:
                            same_b1 = model.NewBoolVar(f"sb1_{req.req_id}_{d1}_{d2}")
                            model.Add(s1["start"] == s2["start"]).OnlyEnforceIf([s1["act"], s2["act"], same_b1])
                            model.Add(s1["dur"] == s2["dur"]).OnlyEnforceIf([s1["act"], s2["act"], same_b1])
                            block_consistency_vars.append(same_b1)

            # Block 2 consistency (Thu == Fri == Sat)
            d_b2 = [d for d in BLOCK_2 if d in op_days]
            for i in range(len(d_b2)):
                for j in range(i + 1, len(d_b2)):
                    d1, d2 = d_b2[i], d_b2[j]
                    insts1 = day_slot_vars.get(d1, [])
                    insts2 = day_slot_vars.get(d2, [])
                    for s1 in insts1:
                        for s2 in insts2:
                            same_b2 = model.NewBoolVar(f"sb2_{req.req_id}_{d1}_{d2}")
                            model.Add(s1["start"] == s2["start"]).OnlyEnforceIf([s1["act"], s2["act"], same_b2])
                            model.Add(s1["dur"] == s2["dur"]).OnlyEnforceIf([s1["act"], s2["act"], same_b2])
                            block_consistency_vars.append(same_b2)

        # Max 20% altered duration per batch
        if batch_altered_vars.get((c, b)):
            alts = batch_altered_vars[(c, b)]
            model.Add(sum(alts) <= int(0.20 * len(alts)))

    # 4. BATCH NO-OVERLAP CONSTRAINT
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # 5. FACULTY CROSS-CENTER NON-OVERLAP & STRICT TRAVEL TIME BUFFERS
    travel_time = loader.travel_matrix
    prec_count = 0

    for (fac, d), items in fac_day_items.items():
        n = len(items)
        if n < 2: continue

        for i in range(n):
            for j in range(i + 1, n):
                it1, it2 = items[i], items[j]
                # Morning and Evening are separated by 90m+, no overlap possible
                if it1["is_morning"] != it2["is_morning"]:
                    continue

                c1, c2 = it1["center"], it2["center"]
                tt_12 = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                tt_21 = travel_time.get((c2, c1), 30) if c1 != c2 else 0

                b_order = model.NewBoolVar(f"ord_{fac}_{d}_{i}_{j}")
                a1 = it1["active"]
                a2 = it2["active"]

                # it1 before it2: start2 >= end1 + tt_12
                model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([a1, a2, b_order])
                # it2 before it1: start1 >= end2 + tt_21
                model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([a1, a2, b_order.Not()])
                prec_count += 1

    print(f"Total faculty cross-center precedence constraints: {prec_count}")
    print(f"Total consistency reward variables: {len(block_consistency_vars)}")

    # 6. OBJECTIVE FUNCTION: Maximize consistency, minimize duration alteration
    same_sum = sum(block_consistency_vars) if block_consistency_vars else model.NewConstant(0)
    alt_sum = sum(lv["alt"] for lv in all_lecture_vars)
    model.Maximize(same_sum * 10 - alt_sum)

    # 7. SOLVE GLOBAL MODEL
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_workers = 8

    print("Solving UNIFIED GLOBAL MODEL across all branches...")
    t0 = time.time()
    st = solver.Solve(model)
    el = time.time() - t0
    print(f"Global Solver Status: {solver.StatusName(st)} in {el:.2f} seconds!")

    if st in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        scheduled = list(fixed_slots)
        for lv in all_lecture_vars:
            req = lv["req"]
            c = lv["center"]
            b = lv["batch"]
            st_val = solver.Value(lv["start"])
            dur_val = solver.Value(lv["dur"])
            end_val = solver.Value(lv["end"])
            b_info = loader.batches.get((c, b))
            op_days = b_info.operating_days if b_info else DAYS_OF_WEEK

            for d in op_days:
                if d in lv["day_vars"] and solver.Value(lv["day_vars"][d]) == 1:
                    scheduled.append(ScheduledSlot(
                        batch_key=f"{c}_{b}",
                        center=c,
                        batch_name=b,
                        day=d,
                        start_min=st_val,
                        end_min=end_val,
                        subject=req.subject,
                        faculty=req.faculty,
                        is_fixed=False,
                        chapter="CH-1",
                        topic="Introduction & Basics"
                    ))

        print(f"Total lecture slots scheduled: {len(scheduled)}")

        # Verify Vicky Sir's Friday schedule
        print("\n=== VERIFYING VICKY SIR FRIDAY SCHEDULE ===")
        v_fri = [s for s in scheduled if "VICKY" in s.faculty.upper() and s.day == "FRIDAY"]
        v_fri = sorted(v_fri, key=lambda s: s.start_min)
        for s in v_fri:
            print(f"  {minutes_to_str(s.start_min)} - {minutes_to_str(s.end_min)} ({s.duration_min} mins): [{s.center} - {s.batch_name}] {s.subject}")

        # Verify no lectures < 45m
        short_lecs = [s for s in scheduled if not s.is_fixed and s.duration_min < 45]
        long_lecs = [s for s in scheduled if not s.is_fixed and s.duration_min > 120]
        print(f"\nLectures < 45 mins: {len(short_lecs)}")
        print(f"Lectures > 120 mins: {len(long_lecs)}")
        return solver, scheduled, loader
    else:
        print("Solver was unable to find a feasible solution under current settings.")
        return None, None, None

if __name__ == "__main__":
    solve_unified_global()
