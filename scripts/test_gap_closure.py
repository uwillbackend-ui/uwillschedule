import sys, os
sys.path.insert(0, os.path.abspath("."))
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str
import openpyxl, re

loader = DataLoader("data")
loader.load_all()
travel_time = loader.travel_matrix

recess_map = {}
for (c, b), b_info in loader.batches.items():
    if b_info.recess_start_min and b_info.recess_end_min:
        recess_map[(c, b)] = (b_info.recess_start_min, b_info.recess_end_min)

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
    slots.append({
        "center": c, "batch": b, "day": d,
        "st": st, "et": et, "subj": subj, "fac": fac,
        "is_test": ("TEST" in (subj or "") or "TEST" in (fac or ""))
    })

# Group by batch and day
batch_day = {}
for s in slots:
    batch_day.setdefault((s["center"], s["batch"], s["day"]), []).append(s)

# Close small gaps <= 20 mins
closed_count = 0
for (c, b, d), slist in batch_day.items():
    slist.sort(key=lambda x: x["st"])
    rec = recess_map.get((c, b))
    for i in range(len(slist)):
        s = slist[i]
        # Check gap before recess
        if rec and 0 < rec[0] - s["et"] <= 20:
            next_is_after_rec = (i == len(slist)-1) or (slist[i+1]["st"] >= rec[1])
            if next_is_after_rec:
                add = rec[0] - s["et"]
                s["et"] += add
                closed_count += 1
        # Check gap after recess
        if rec and 0 < s["st"] - rec[1] <= 20:
            prev_is_before_rec = (i == 0) or (slist[i-1]["et"] <= rec[0])
            if prev_is_before_rec:
                sub = s["st"] - rec[1]
                s["st"] -= sub
                closed_count += 1

    # Check direct gap between consecutive slots
    for i in range(len(slist)-1):
        s1 = slist[i]
        s2 = slist[i+1]
        gap = s2["st"] - s1["et"]
        if 0 < gap <= 20:
            # If recess between them, already handled
            if rec and s1["et"] <= rec[0] and s2["st"] >= rec[1]:
                continue
            # Close gap
            if not s1["is_test"]:
                s1["et"] += gap
                closed_count += 1
            else:
                s2["st"] -= gap
                closed_count += 1

print(f"Total gaps closed: {closed_count}")

# Check remaining gaps <= 20 mins
rem_gaps = 0
for (c, b, d), slist in batch_day.items():
    slist.sort(key=lambda x: x["st"])
    rec = recess_map.get((c, b))
    for i in range(len(slist)-1):
        s1 = slist[i]
        s2 = slist[i+1]
        gap = s2["st"] - s1["et"]
        if 0 < gap <= 20:
            if rec and s1["et"] <= rec[0] and s2["st"] >= rec[1]:
                continue
            rem_gaps += 1
            print(f"Remaining gap: {c} {b} {d}: {s1['et']} to {s2['st']} ({gap}m)")

print(f"Remaining small gaps <= 20 mins: {rem_gaps}")

# Check for any overlaps created
overlaps = 0
for (c, b, d), slist in batch_day.items():
    slist.sort(key=lambda x: x["st"])
    for i in range(len(slist)-1):
        if slist[i]["et"] > slist[i+1]["st"]:
            overlaps += 1
            print(f"OVERLAP in {c} {b} {d}: {slist[i]['st']}-{slist[i]['et']} vs {slist[i+1]['st']}-{slist[i+1]['et']}")

print(f"Batch overlaps after closing gaps: {overlaps}")

# Check faculty overlaps and travel violations
fac_day = {}
for s in slots:
    f = (s["fac"] or "").strip().upper()
    if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
        fac_day.setdefault((f, s["day"]), []).append(s)

fac_overlaps = 0
travel_viols = 0
for (f, d), flist in fac_day.items():
    flist.sort(key=lambda x: x["st"])
    for i in range(len(flist)-1):
        s1, s2 = flist[i], flist[i+1]
        c1, c2 = s1["center"], s2["center"]
        st1, et1 = s1["st"], s1["et"]
        st2, et2 = s2["st"], s2["et"]
        if et1 > st2:
            fac_overlaps += 1
            print(f"FAC OVERLAP for {f} on {d}: {c1} ({st1}-{et1}) vs {c2} ({st2}-{et2})")
        elif c1 != c2:
            tt = travel_time.get((c1, c2), 30)
            if (st1 < 840) == (st2 < 840) and st2 - et1 < tt:
                travel_viols += 1
                print(f"TRAVEL VIOLATION for {f} on {d}: {c1}->{c2} buf={st2-et1}m < {tt}m")

print(f"Faculty overlaps: {fac_overlaps}")
print(f"Travel violations: {travel_viols}")

