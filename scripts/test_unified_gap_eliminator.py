import sys, os
sys.path.insert(0, os.path.abspath("."))
import openpyxl
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str
from src.models import ScheduledSlot

loader = DataLoader("data")
loader.load_all()

recess_map = {}
batch_limits = {}
for (c, b), b_info in loader.batches.items():
    if b_info.recess_start_min and b_info.recess_end_min:
        recess_map[(c, b)] = (b_info.recess_start_min, b_info.recess_end_min)
    batch_limits[(c, b)] = b_info

# Load slots from Weekly_Schedule_Input_Topics.xlsx
wb = openpyxl.load_workbook("output/excel/Weekly_Schedule_Input_Topics.xlsx")
ws = wb.active

slots = []
for r in range(2, ws.max_row+1):
    c = ws.cell(r, 1).value
    b = ws.cell(r, 2).value
    d = ws.cell(r, 3).value
    st_s = ws.cell(r, 4).value
    et_s = ws.cell(r, 5).value
    subj = ws.cell(r, 7).value
    fac = ws.cell(r, 8).value
    chap = ws.cell(r, 9).value or ""
    top = ws.cell(r, 10).value or ""
    if not (c and b and d and st_s and et_s): continue
    st = parse_time_to_minutes(st_s)
    et = parse_time_to_minutes(et_s)
    
    # Check if fixed
    is_fixed = False
    for fl in loader.fixed_lectures:
        if fl.center == c and fl.batch == b and fl.day == d and fl.start_min == st:
            is_fixed = True
            break

    slots.append(ScheduledSlot(
        batch_key=f"{c}_{b}",
        center=c,
        batch_name=b,
        day=d,
        start_min=st,
        end_min=et,
        subject=str(subj or ""),
        faculty=str(fac or ""),
        is_fixed=is_fixed,
        chapter=str(chap),
        topic=str(top)
    ))

print(f"Loaded {len(slots)} slots.")

# Let us run gap closure logic
travel_time = loader.travel_matrix

def audit(s_list, label=""):
    bad_tests = [s for s in s_list if "TEST" in s.subject.upper() and (s.end_min - s.start_min) != 60]
    bad_ends = []
    for s in s_list:
        b_info = batch_limits.get((s.center, s.batch_name))
        if b_info:
            d_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min)
            d_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min)
            if s.end_min > d_le: bad_ends.append((s, f"End {s.end_min} > {d_le}"))
            if s.start_min < d_es: bad_ends.append((s, f"Start {s.start_min} < {d_es}"))
    
    short_lecs = [s for s in s_list if "TEST" not in s.subject.upper() and not s.is_fixed and (s.end_min - s.start_min) < 50]
    
    batch_ev = {}
    for s in s_list: batch_ev.setdefault((s.center, s.batch_name, s.day), []).append(s)
    gaps = []
    for (c, b, d), sl in batch_ev.items():
        sl.sort(key=lambda x: x.start_min)
        rec = recess_map.get((c, b))
        for i in range(len(sl)-1):
            s1, s2 = sl[i], sl[i+1]
            gap = s2.start_min - s1.end_min
            if gap > 0:
                is_rec = False
                if rec:
                    if s1.end_min <= rec[0] and s2.start_min >= rec[1]:
                        is_rec = True
                        if rec[0] - s1.end_min > 0: gaps.append((c, b, d, f"Gap before recess: {rec[0]-s1.end_min}m"))
                        if s2.start_min - rec[1] > 0: gaps.append((c, b, d, f"Gap after recess: {s2.start_min-rec[1]}m"))
                if not is_rec:
                    gaps.append((c, b, d, f"Direct gap: {gap}m ({s1.subject}->{s2.subject})"))
    
    print(f"\n--- AUDIT: {label} ---")
    print(f"1. Test duration != 60m: {len(bad_tests)}")
    print(f"2. Operating hours breaches: {len(bad_ends)}")
    print(f"4. Regular lectures < 50m: {len(short_lecs)}")
    print(f"3. Unintended gaps: {len(gaps)}")
    return len(bad_tests), len(bad_ends), len(short_lecs), len(gaps)

audit(slots, "Before Optimization")
