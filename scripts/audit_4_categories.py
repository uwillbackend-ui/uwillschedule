import openpyxl
from src.data_loader import DataLoader, parse_time_to_minutes

loader = DataLoader("data")
loader.load_all()

recess_map = {}
batch_limits = {}
for (c, b), b_info in loader.batches.items():
    if b_info.recess_start_min and b_info.recess_end_min:
        recess_map[(c, b)] = (b_info.recess_start_min, b_info.recess_end_min)
    batch_limits[(c, b)] = b_info

wb = openpyxl.load_workbook("output/excel/Weekly_Schedule_Input_Topics.xlsx")
ws = wb.active

slots = []
for r in range(2, ws.max_row+1):
    c = ws.cell(r, 1).value
    b = ws.cell(r, 2).value
    d = ws.cell(r, 3).value
    st_s = ws.cell(r, 4).value
    et_s = ws.cell(r, 5).value
    dur = ws.cell(r, 6).value
    subj = ws.cell(r, 7).value
    fac = ws.cell(r, 8).value
    if not (c and b and d and st_s and et_s): continue
    st = parse_time_to_minutes(st_s)
    et = parse_time_to_minutes(et_s)
    dur = int(dur) if dur else (et - st)
    slots.append({
        "center": c, "batch": b, "day": d,
        "st": st, "et": et, "dur": dur,
        "subj": str(subj or ""), "fac": str(fac or ""),
        "st_s": st_s, "et_s": et_s
    })

print("=" * 65)
print("AUDIT RESULTS FOR 4 CATEGORIES")
print("=" * 65)
print(f"Total slots loaded: {len(slots)}")

# CATEGORY 1: Test duration != 60m
bad_tests = [s for s in slots if "TEST" in s["subj"].upper() and s["dur"] != 60]
print(f"\n1. TEST DURATION != 60m: {len(bad_tests)}")
for s in bad_tests:
    c, b, d, sub, du, sts, ets = s['center'], s['batch'], s['day'], s['subj'], s['dur'], s['st_s'], s['et_s']
    print(f"   {c} {b} {d}: {sub} dur={du} ({sts} - {ets})")

# CATEGORY 2: Latest end / operating hours breaches
bad_ends = []
for s in slots:
    b_info = batch_limits.get((s["center"], s["batch"]))
    if not b_info:
        for (bc, bb), info in batch_limits.items():
            if bc.strip().upper() == s["center"].strip().upper() and bb.strip().upper() == s["batch"].strip().upper():
                b_info = info
                break
    if b_info:
        d_le = b_info.day_latest_end.get(s["day"], b_info.latest_end_min)
        d_es = b_info.day_earliest_start.get(s["day"], b_info.earliest_start_min)
        if s["et"] > d_le:
            bad_ends.append((s, f"End time {s['et_s']} ({s['et']}m) exceeds limit {d_le//60:02d}:{d_le%60:02d} ({d_le}m)"))
        if s["st"] < d_es:
            bad_ends.append((s, f"Start time {s['st_s']} ({s['st']}m) earlier than limit {d_es//60:02d}:{d_es%60:02d} ({d_es}m)"))

print(f"\n2. OPERATING HOURS BREACHES: {len(bad_ends)}")
for s, reason in bad_ends:
    c, b, d, sub = s['center'], s['batch'], s['day'], s['subj']
    print(f"   {c} {b} {d}: {sub} {reason}")

# CATEGORY 4: Regular non-fixed lectures < 50 mins
short_lecs = []
for s in slots:
    if "TEST" in s["subj"].upper(): continue
    # check if fixed lecture
    is_fixed = False
    for fl in loader.fixed_lectures:
        if fl.center == s["center"] and fl.batch == s["batch"] and fl.day == s["day"] and fl.start_min == s["st"]:
            is_fixed = True
            break
    if not is_fixed and s["dur"] < 50:
        short_lecs.append(s)

print(f"\n4. REGULAR NON-FIXED LECTURES < 50m: {len(short_lecs)}")
for s in short_lecs:
    c, b, d, sub, fa, du, sts, ets = s['center'], s['batch'], s['day'], s['subj'], s['fac'], s['dur'], s['st_s'], s['et_s']
    print(f"   {c} {b} {d}: {sub} ({fa}) dur={du}m ({sts} - {ets})")

# CATEGORY 3: Non-recess gaps
slots_by_bd = {}
for s in slots:
    slots_by_bd.setdefault((s["center"], s["batch"], s["day"]), []).append(s)

gaps = []
for (c, b, d), slist in sorted(slots_by_bd.items()):
    slist.sort(key=lambda x: x["st"])
    rec = recess_map.get((c, b))
    for i in range(len(slist)-1):
        s1 = slist[i]
        s2 = slist[i+1]
        gap = s2["st"] - s1["et"]
        if gap > 0:
            is_rec_between = False
            if rec:
                if s1["et"] <= rec[0] and s2["st"] >= rec[1]:
                    is_rec_between = True
                    rec_gap_before = rec[0] - s1["et"]
                    rec_gap_after = s2["st"] - rec[1]
                    rec_st_str = f"{rec[0]//60:02d}:{rec[0]%60:02d}"
                    rec_et_str = f"{rec[1]//60:02d}:{rec[1]%60:02d}"
                    if rec_gap_before > 0:
                        gaps.append((c, b, d, f"Gap before recess: {rec_gap_before}m ({s1['et_s']} to recess {rec_st_str})"))
                    if rec_gap_after > 0:
                        gaps.append((c, b, d, f"Gap after recess: {rec_gap_after}m (recess {rec_et_str} to {s2['st_s']})"))
            if not is_rec_between:
                gaps.append((c, b, d, f"Direct gap between lectures: {gap}m ({s1['et_s']} to {s2['st_s']}) ({s1['subj']} -> {s2['subj']})"))

print(f"\n3. UNINTENDED NON-RECESS GAPS: {len(gaps)}")
for c, b, d, msg in gaps[:30]:
    print(f"   {c} {b} {d}: {msg}")
if len(gaps) > 30:
    print(f"   ... and {len(gaps)-30} more")
