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

travel_time = loader.travel_matrix

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
    is_fixed = any(fl.center==c and fl.batch==b and fl.day==d and fl.start_min==st for fl in loader.fixed_lectures)
    slots.append(ScheduledSlot(
        batch_key=f"{c}_{b}", center=c, batch_name=b, day=d,
        start_min=st, end_min=et, subject=str(subj or ""), faculty=str(fac or ""),
        is_fixed=is_fixed, chapter=str(chap), topic=str(top)
    ))

print(f"Loaded {len(slots)} slots.")

# Precision adjustments
# 1. Jai Ambe 11th GSEB - C 12:30 PM cutoff
for s in slots:
    if s.center == "JAI AMBE" and "11TH" in s.batch_name and "C" in s.batch_name:
        if s.end_min > 750:
            shift = s.end_min - 750
            s.end_min = 750
            s.start_min = max(s.start_min - shift, 660)

# 2. DAPS 12th GSEB Monday latest end (810m = 1:30 PM)
for s in slots:
    if s.center == "DAPS" and "12TH" in s.batch_name:
        if s.end_min > 810:
            diff = s.end_min - 810
            s.end_min = 810
            s.start_min = max(s.start_min - diff, 720)

# 3. THS Precision Rebalancing
for s in slots:
    if s.center == "THS":
        if s.faculty == "KAILASH SIR":
            if s.start_min == 510 and s.end_min == 555:
                s.start_min = 505 # 8:25 - 9:15 (50m)
            elif s.start_min == 450 and s.end_min == 510:
                s.end_min = 505 # 7:30 - 8:25 (55m)
        elif s.faculty == "MOHSIN SIR" and s.start_min == 450 and s.end_min == 495:
            s.end_min = 505 # 7:30 - 8:25 (55m)
        elif s.faculty == "KANAKLATA MADAM" and s.start_min == 675 and s.end_min == 720:
            s.start_min = 660 # 11:00 - 12:00 (60m)

# 4. Ambe Manjalpur pre-recess touch
for s in slots:
    if s.center == "AMBE MANJ" and s.faculty == "KANAKLATA MADAM" and s.start_min == 495 and s.end_min == 555:
        s.end_min = 560 # 8:15 - 9:20 (65m), touches 9:20 recess!

# 5. Gap closure multi-pass
for iteration in range(5):
    fac_ev = {}
    for s in slots:
        f = s.faculty.strip().upper()
        if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
            fac_ev.setdefault((f, s.day), []).append(s)
    for k in fac_ev: fac_ev[k].sort(key=lambda x: x.start_min)

    batch_ev = {}
    for s in slots: batch_ev.setdefault((s.center, s.batch_name, s.day), []).append(s)
    for k in batch_ev: batch_ev[k].sort(key=lambda x: x.start_min)

    closed = 0
    for (c, b, d), sl in batch_ev.items():
        rec = recess_map.get((c, b))
        b_info = batch_limits.get((c, b))
        day_es = b_info.day_earliest_start.get(d, b_info.earliest_start_min) if b_info else 420
        day_le = b_info.day_latest_end.get(d, b_info.latest_end_min) if b_info else 1200

        for i in range(len(sl)-1):
            s1, s2 = sl[i], sl[i+1]
            f1, f2 = s1.faculty.strip().upper(), s2.faculty.strip().upper()
            is_test1 = "TEST" in s1.subject.upper() or "TEST" in f1
            is_test2 = "TEST" in s2.subject.upper() or "TEST" in f2

            # Recess gap handling
            if rec and s1.end_min <= rec[0] and s2.start_min >= rec[1]:
                # Gap before recess
                if s1.end_min < rec[0] and not s1.is_fixed and not is_test1:
                    cur_dur = s1.end_min - s1.start_min
                    gap = rec[0] - s1.end_min
                    if cur_dur + gap <= 90:
                        fl1 = fac_ev.get((f1, d), [])
                        next_f1 = min((x for x in fl1 if x != s1 and x.start_min >= s1.end_min), key=lambda x: x.start_min, default=None)
                        tt1 = travel_time.get((s1.center, next_f1.center), 30) if (next_f1 and s1.center != next_f1.center) else 0
                        if (next_f1 is None) or (rec[0] + tt1 <= next_f1.start_min):
                            s1.end_min = rec[0]
                            closed += 1

                # Gap after recess
                if s2.start_min > rec[1] and not s2.is_fixed and not is_test2:
                    cur_dur = s2.end_min - s2.start_min
                    gap = s2.start_min - rec[1]
                    if cur_dur + gap <= 90:
                        fl2 = fac_ev.get((f2, d), [])
                        prev_f2 = max((x for x in fl2 if x != s2 and x.end_min <= s2.start_min), key=lambda x: x.end_min, default=None)
                        tt2 = travel_time.get((prev_f2.center, s2.center), 30) if (prev_f2 and prev_f2.center != s2.center) else 0
                        if (prev_f2 is None) or (prev_f2.end_min + tt2 <= rec[1]):
                            s2.start_min = rec[1]
                            closed += 1
                continue

            # Direct gap handling
            gap = s2.start_min - s1.end_min
            if 0 < gap <= 45:
                if not s2.is_fixed:
                    fl2 = fac_ev.get((f2, d), [])
                    prev_f2 = max((x for x in fl2 if x != s2 and x.end_min <= s2.start_min), key=lambda x: x.end_min, default=None)
                    tt2 = travel_time.get((prev_f2.center, s2.center), 30) if (prev_f2 and prev_f2.center != s2.center) else 0
                    if (prev_f2 is None) or (prev_f2.end_min + tt2 <= s1.end_min):
                        if is_test2:
                            s2.start_min = s1.end_min
                            s2.end_min = s1.end_min + 60
                            closed += 1
                        elif not is_test2:
                            if (s2.end_min - s1.end_min) <= 90:
                                s2.start_min = s1.end_min
                                closed += 1
                elif not s1.is_fixed and not is_test1:
                    fl1 = fac_ev.get((f1, d), [])
                    next_f1 = min((x for x in fl1 if x != s1 and x.start_min >= s1.end_min), key=lambda x: x.start_min, default=None)
                    tt1 = travel_time.get((s1.center, next_f1.center), 30) if (next_f1 and s1.center != next_f1.center) else 0
                    if (next_f1 is None) or (s2.start_min + tt1 <= next_f1.start_min):
                        if (s2.start_min - s1.start_min) <= 90:
                            s1.end_min = s2.start_min
                            closed += 1

    print(f"Pass {iteration+1}: closed {closed} gaps.")
    if closed == 0: break

# Audit
bad_tests = [s for s in slots if "TEST" in s.subject.upper() and (s.end_min - s.start_min) != 60]
bad_ends = []
for s in slots:
    b_info = batch_limits.get((s.center, s.batch_name))
    if b_info:
        d_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min)
        d_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min)
        if s.end_min > d_le: bad_ends.append((s, f"End {s.end_min} > {d_le}"))
        if s.start_min < d_es: bad_ends.append((s, f"Start {s.start_min} < {d_es}"))
short_lecs = [s for s in slots if "TEST" not in s.subject.upper() and not s.is_fixed and (s.end_min - s.start_min) < 50]

batch_ev = {}
for s in slots: batch_ev.setdefault((s.center, s.batch_name, s.day), []).append(s)
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

print("\n--- FINAL AUDIT RESULT ---")
print(f"1. Test duration != 60m: {len(bad_tests)}")
print(f"2. Operating hours breaches: {len(bad_ends)}")
print(f"4. Regular lectures < 50m: {len(short_lecs)}")
print(f"3. Unintended gaps: {len(gaps)}")
