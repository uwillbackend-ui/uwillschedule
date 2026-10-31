import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from ortools.sat.python import cp_model
from src.data_loader import DataLoader, DAYS_OF_WEEK, minutes_to_str

def run_test():
    loader = DataLoader("data")
    loader.load_all()

    model = cp_model.CpModel()

    # Step 1: Let us organize requirements by batch
    batch_reqs = {}
    for req in loader.subject_requirements:
        key = (req.center, req.batch)
        if key not in batch_reqs:
            batch_reqs[key] = []
        batch_reqs[key].append(req)

    print(f"Total batches with requirements: {len(batch_reqs)}")

    # For each batch, let us inspect available operating days
    # And create lecture instances
    lecture_vars = []  # list of dicts with var info

    # Variable storage by (batch, day) and (faculty, day)
    batch_day_intervals = {}
    fac_day_intervals = {}

    # Track alteration booleans per batch
    batch_altered_vars = {}

    for (c, b), reqs in batch_reqs.items():
        b_info = loader.batches.get((c, b))
        if not b_info:
            # find fuzzy
            for (bc, bb), info in loader.batches.items():
                if bc == c and (bb in b or b in bb):
                    b_info = info
                    break
        if not b_info:
            print(f"Warning: Batch info not found for {c} - {b}")
            continue

        op_days = b_info.operating_days
        es = b_info.earliest_start_min
        le = b_info.latest_end_min

        batch_altered_vars[(c, b)] = []

        # Add fixed recess as interval if applicable
        if b_info.recess_start_min and b_info.recess_end_min:
            rst = b_info.recess_start_min
            ret = b_info.recess_end_min
            rdur = ret - rst
            for d in op_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, rdur, f"recess_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

        # Add fixed visiting faculty lectures
        for vf in loader.fixed_lectures:
            if vf.center == c and (vf.batch == b or vf.batch in b or b in vf.batch):
                vf_dur = vf.end_min - vf.start_min
                vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{c}_{b}_{vf.day}_{vf.start_min}")
                batch_day_intervals.setdefault(((c, b), vf.day), []).append(vf_iv)

                # Also add to faculty if known visiting faculty
                fac_day_intervals.setdefault((vf.faculty, vf.day), []).append({
                    "interval": vf_iv,
                    "start": vf.start_min,
                    "end": vf.end_min,
                    "center": c,
                    "is_fixed": True
                })

        # Now for each subject requirement, we need req.weekly_days lectures scheduled
        for req in reqs:
            w_days = min(req.weekly_days, len(op_days))
            nom_dur = req.daily_duration_min
            # 5-minute multiples: nom_dur is usually 60 or 75
            # Allowed durations: nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10
            dur_options = [nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
            # filter valid (> 0)
            dur_options = [d for d in dur_options if d >= 40]

            for inst_idx in range(w_days):
                # Day selection variable or pattern
                # For each possible day d in op_days, a boolean var day_active
                day_active_vars = {}
                for d in op_days:
                    day_active_vars[d] = model.NewBoolVar(f"act_{req.req_id}_{inst_idx}_{d}")

                # Exactly one day chosen for this instance
                model.Add(sum(day_active_vars.values()) == 1)

                # Start time, duration, end time
                # Bounds
                start_var = model.NewIntVar(es, le - min(dur_options), f"start_{req.req_id}_{inst_idx}")
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst_idx}")
                end_var = model.NewIntVar(es + min(dur_options), le, f"end_{req.req_id}_{inst_idx}")
                model.Add(end_var == start_var + dur_var)

                # Altered boolean
                is_altered = model.NewBoolVar(f"altered_{req.req_id}_{inst_idx}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(is_altered)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(is_altered.Not())
                batch_altered_vars[(c, b)].append(is_altered)

                # For each day d, create optional interval
                for d in op_days:
                    opt_iv = model.NewOptionalIntervalVar(
                        start_var, dur_var, end_var, day_active_vars[d],
                        f"opt_iv_{req.req_id}_{inst_idx}_{d}"
                    )
                    batch_day_intervals.setdefault(((c, b), d), []).append(opt_iv)

                    fac_day_intervals.setdefault((req.faculty, d), []).append({
                        "interval": opt_iv,
                        "start": start_var,
                        "end": end_var,
                        "center": c,
                        "is_fixed": False,
                        "active": day_active_vars[d]
                    })

                lecture_vars.append({
                    "req": req,
                    "inst_idx": inst_idx,
                    "start": start_var,
                    "dur": dur_var,
                    "end": end_var,
                    "day_active": day_active_vars,
                    "is_altered": is_altered
                })

            # Ensure this subject has at most 1 lecture per day in this batch
            for d in op_days:
                # Sum of day_active for all instances of this req on day d <= 1
                inst_on_d = [lv["day_active"][d] for lv in lecture_vars if lv["req"].req_id == req.req_id]
                model.Add(sum(inst_on_d) <= 1)

    print(f"Total lecture variables: {len(lecture_vars)}")

    # Constraint: max 20% altered per batch
    for (c, b), alt_list in batch_altered_vars.items():
        if alt_list:
            max_allowed = int(0.20 * len(alt_list))
            model.Add(sum(alt_list) <= max_allowed)

    # Constraint: No overlap within batch on each day
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # Constraint: Faculty no overlap & travel time
    travel_time = loader.travel_matrix
    precedence_count = 0

    for (fac, d), f_items in fac_day_intervals.items():
        if not fac or fac.startswith("TBD_"):
            continue
        n = len(f_items)
        if n < 2:
            continue

        # If all at same center, simple AddNoOverlap
        centers = {item["center"] for item in f_items}
        if len(centers) == 1:
            model.AddNoOverlap([item["interval"] for item in f_items])
        else:
            # Pairwise precedence with travel time
            for i in range(n):
                for j in range(i + 1, n):
                    item1 = f_items[i]
                    item2 = f_items[j]
                    c1 = item1["center"]
                    c2 = item2["center"]
                    tt_12 = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                    tt_21 = travel_time.get((c2, c1), 30) if c1 != c2 else 0

                    # If both active, either 1 finishes before 2 starts + tt_12, or 2 finishes before 1 starts + tt_21
                    b_prec = model.NewBoolVar(f"prec_{fac}_{d}_{i}_{j}")

                    act1 = item1.get("active")
                    act2 = item2.get("active")

                    # If item1 is before item2:
                    # start2 >= end1 + tt_12
                    cond1 = [b_prec]
                    if act1 is not None: cond1.append(act1)
                    if act2 is not None: cond1.append(act2)
                    model.Add(item2["start"] >= item1["end"] + tt_12).OnlyEnforceIf(cond1)

                    # If item2 is before item1:
                    # start1 >= end2 + tt_21
                    cond2 = [b_prec.Not()]
                    if act1 is not None: cond2.append(act1)
                    if act2 is not None: cond2.append(act2)
                    model.Add(item1["start"] >= item2["end"] + tt_21).OnlyEnforceIf(cond2)

                    precedence_count += 1

    print(f"Total faculty cross-center precedence constraints: {precedence_count}")

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    solver.parameters.num_workers = 8

    print("Solving CP-SAT model...")
    t0 = time.time()
    status = solver.Solve(model)
    elapsed = time.time() - t0
    print(f"Solver status: {solver.StatusName(status)} in {elapsed:.2f} seconds")

if __name__ == "__main__":
    run_test()
