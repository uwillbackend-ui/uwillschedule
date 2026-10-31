import csv
from collections import defaultdict
from src.data_loader import DataLoader, minutes_to_str

loader = DataLoader("data")
loader.load_all()

print("=== 1. CHECK VISITING FACULTY OVERLAPS ===")
vf_by_fac_day = defaultdict(list)
for vf in loader.fixed_lectures:
    vf_by_fac_day[(vf.faculty, vf.day)].append(vf)

for (fac, day), vfs in vf_by_fac_day.items():
    if len(vfs) > 1:
        # Check overlaps
        for i in range(len(vfs)):
            for j in range(i + 1, len(vfs)):
                v1, v2 = vfs[i], vfs[j]
                # overlap or travel conflict
                tt = loader.travel_matrix.get((v1.center, v2.center), 30) if v1.center != v2.center else 0
                if not (v1.end_min + tt <= v2.start_min or v2.end_min + tt <= v1.start_min):
                    print(f"VF CONFLICT for {fac} on {day}:")
                    print(f"  {v1.center} {v1.batch} {minutes_to_str(v1.start_min)}-{minutes_to_str(v1.end_min)}")
                    print(f"  {v2.center} {v2.batch} {minutes_to_str(v2.start_min)}-{minutes_to_str(v2.end_min)}")

print("\n=== 2. CHECK BATCH TIME CAPACITY VS ASSIGNED SUBJECT HOURS ===")
batch_reqs = defaultdict(list)
for req in loader.subject_requirements:
    batch_reqs[(req.center, req.batch)].append(req)

for (c, b), b_info in loader.batches.items():
    reqs = batch_reqs.get((c, b), [])
    tot_req_weekly_hrs = sum(r.weekly_hours for r in reqs)
    # count fixed vf weekly hrs
    vf_hrs = sum((vf.end_min - vf.start_min)/60.0 for vf in loader.fixed_lectures if vf.center == c and (vf.batch == b or vf.batch in b or b in vf.batch))
    
    op_days = len(b_info.operating_days)
    daily_avail_min = b_info.latest_end_min - b_info.earliest_start_min
    if b_info.recess_start_min and b_info.recess_end_min:
        daily_avail_min -= (b_info.recess_end_min - b_info.recess_start_min)
    
    weekly_avail_hrs = (daily_avail_min * op_days) / 60.0
    tot_needed_hrs = tot_req_weekly_hrs + (vf_hrs / 6.0) # vf is already weekly
    
    if tot_req_weekly_hrs + vf_hrs > weekly_avail_hrs:
        print(f"OVERLOAD in [{c} - {b}]: Needed {tot_req_weekly_hrs + vf_hrs:.1f} hrs (Subj: {tot_req_weekly_hrs}h, VF: {vf_hrs}h) > Avail {weekly_avail_hrs:.1f} hrs!")

print("\n=== 3. CHECK FACULTY DETAILS CUTOFFS VS BATCH TIMINGS ===")
for req in loader.subject_requirements:
    fac = req.faculty
    if fac in loader.faculties:
        f_info = loader.faculties[fac]
        b_info = loader.batches.get((req.center, req.batch))
        if b_info and f_info.available_to_min:
            if b_info.earliest_start_min >= f_info.available_to_min:
                print(f"CUTOFF CONFLICT: {fac} available to {minutes_to_str(f_info.available_to_min)}, but [{req.center} - {req.batch}] earliest start is {minutes_to_str(b_info.earliest_start_min)}!")
