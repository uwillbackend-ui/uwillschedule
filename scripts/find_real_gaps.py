import sys, os
sys.path.insert(0, os.path.abspath("."))
import openpyxl, re
from src.data_loader import DataLoader, parse_time_to_minutes

loader = DataLoader("data")
loader.load_all()

recess_map = {}
for (c, b), b_info in loader.batches.items():
    if b_info.recess_start_min and b_info.recess_end_min:
        recess_map[(c, b)] = (b_info.recess_start_min, b_info.recess_end_min)

wb = openpyxl.load_workbook("output/excel/Weekly_Schedule_Input_Topics.xlsx")
ws = wb.active

slots_by_bd = {}
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
    slots_by_bd.setdefault((c, b, d), []).append({
        "st": st, "et": et, "dur": dur, "subj": subj, "fac": fac,
        "st_s": st_s, "et_s": et_s
    })

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
                        gaps.append((c, b, d, f"Gap before recess: {rec_gap_before}m ({s1['et_s']} to recess {rec_st_str})", s1, s2))
                    if rec_gap_after > 0:
                        gaps.append((c, b, d, f"Gap after recess: {rec_gap_after}m (recess {rec_et_str} to {s2['st_s']})", s1, s2))
            if not is_rec_between:
                gaps.append((c, b, d, f"Direct gap between lectures: {gap}m ({s1['et_s']} to {s2['st_s']})", s1, s2))

print(f"Total gaps identified in actual schedule: {len(gaps)}")
for g in gaps:
    print(f"  {g[0]:10s} | {g[1]:22s} | {g[2]:9s} | {g[3]} | {g[4]['fac']} -> {g[5]['fac']}")
