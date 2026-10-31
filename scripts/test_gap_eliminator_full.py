import sys, os
sys.path.insert(0, os.path.abspath("."))
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str
from src.models import ScheduledSlot
import openpyxl

def test_gap_elimination():
    loader = DataLoader("data")
    loader.load_all()
    travel_time = loader.travel_matrix

    recess_map = {}
    for (c, b), b_info in loader.batches.items():
        if b_info.recess_start_min and b_info.recess_end_min:
            recess_map[(c, b)] = [b_info.recess_start_min, b_info.recess_end_min]

    wb = openpyxl.load_workbook("output/excel/Weekly_Schedule_Input_Topics.xlsx")
    ws = wb.active

    all_slots = []
    for r in range(2, ws.max_row+1):
        c = ws.cell(r, 1).value
        b = ws.cell(r, 2).value
        d = ws.cell(r, 3).value
        st = parse_time_to_minutes(ws.cell(r, 4).value)
        et = parse_time_to_minutes(ws.cell(r, 5).value)
        subj = ws.cell(r, 7).value
        fac = ws.cell(r, 8).value
        if not (c and b and d and st and et): continue
        all_slots.append(ScheduledSlot(
            batch_key=f"{c}_{b}", center=c, batch_name=b, day=d,
            start_min=st, end_min=et, subject=subj, faculty=fac,
            is_fixed=("TEST" in (subj or "") or "TEST" in (fac or "") or "Regular Syllabus" in (ws.cell(r, 10).value or "")),
            chapter=ws.cell(r, 9).value, topic=ws.cell(r, 10).value
        ))

    print(f"Loaded {len(all_slots)} slots from Topics Excel.")

    # Multi-pass gap closure
    for pass_num in range(1, 5):
        # Index faculty events by (faculty, day)
        fac_events = {}
        for s in all_slots:
            f = (s.faculty or "").strip().upper()
            if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
                fac_events.setdefault((f, s.day), []).append(s)
        for k in fac_events:
            fac_events[k].sort(key=lambda x: x.start_min)

        # Index batch events by (center, batch, day)
        batch_events = {}
        for s in all_slots:
            batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)
        for k in batch_events:
            batch_events[k].sort(key=lambda x: x.start_min)

        closed_in_pass = 0

        for (c, b, d), slist in batch_events.items():
            rec = recess_map.get((c, b))
            b_info = loader.batches.get((c, b))
            max_le = b_info.latest_end_min if b_info else 1200
            day_le = b_info.day_latest_end.get(d, max_le) if b_info else max_le

            # 1. Close gaps before recess
            if rec:
                for s in slist:
                    if 0 < rec[0] - s.end_min <= 30:
                        # Check if s is the slot immediately before recess
                        next_slots = [other for other in slist if other.start_min > s.start_min and other.start_min < rec[0]]
                        if not next_slots:
                            f = (s.faculty or "").strip().upper()
                            flist = fac_events.get((f, d), [])
                            s_fidx = flist.index(s) if s in flist else -1
                            next_f = flist[s_fidx + 1] if (s_fidx >= 0 and s_fidx + 1 < len(flist)) else None
                            can_extend = True
                            if next_f:
                                tt = travel_time.get((s.center, next_f.center), 30) if s.center != next_f.center else 0
                                if rec[0] + tt > next_f.start_min:
                                    can_extend = False
                            if can_extend:
                                s.end_min = rec[0]
                                closed_in_pass += 1

            # 2. Close gaps after recess
            if rec:
                for s in slist:
                    if 0 < s.start_min - rec[1] <= 30:
                        prev_slots = [other for other in slist if other.end_min < s.start_min and other.end_min > rec[1]]
                        if not prev_slots:
                            f = (s.faculty or "").strip().upper()
                            flist = fac_events.get((f, d), [])
                            s_fidx = flist.index(s) if s in flist else -1
                            prev_f = flist[s_fidx - 1] if s_fidx > 0 else None
                            can_shift = True
                            if prev_f:
                                tt = travel_time.get((prev_f.center, s.center), 30) if prev_f.center != s.center else 0
                                if prev_f.end_min + tt > rec[1]:
                                    can_shift = False
                            if can_shift:
                                s.start_min = rec[1]
                                closed_in_pass += 1
                            else:
                                # Faculty travel requires arriving at s.start_min (e.g. Kailash Sir arriving at 9:45 AM from THS)
                                # Align recess end to s.start_min so recess seamlessly touches s!
                                if s.start_min > rec[1]:
                                    rec[1] = s.start_min
                                    closed_in_pass += 1

            # 3. Close direct gaps between consecutive lectures
            for i in range(len(slist) - 1):
                s1, s2 = slist[i], slist[i + 1]
                gap = s2.start_min - s1.end_min
                if 0 < gap <= 30:
                    # Check if recess is between them
                    if rec and s1.end_min <= rec[0] and s2.start_min >= rec[1]:
                        continue

                    # Try extending s1
                    f1 = (s1.faculty or "").strip().upper()
                    flist1 = fac_events.get((f1, d), [])
                    idx1 = flist1.index(s1) if s1 in flist1 else -1
                    next_f1 = flist1[idx1 + 1] if (idx1 >= 0 and idx1 + 1 < len(flist1)) else None
                    can_extend_s1 = True
                    if next_f1:
                        tt1 = travel_time.get((s1.center, next_f1.center), 30) if s1.center != next_f1.center else 0
                        if s2.start_min + tt1 > next_f1.start_min:
                            can_extend_s1 = False

                    # Try shifting s2 earlier
                    f2 = (s2.faculty or "").strip().upper()
                    flist2 = fac_events.get((f2, d), [])
                    idx2 = flist2.index(s2) if s2 in flist2 else -1
                    prev_f2 = flist2[idx2 - 1] if idx2 > 0 else None
                    can_shift_s2 = True
                    if prev_f2:
                        tt2 = travel_time.get((prev_f2.center, s2.center), 30) if prev_f2.center != s2.center else 0
                        if prev_f2.end_min + tt2 > s1.end_min:
                            can_shift_s2 = False

                    is_test1 = ("TEST" in (s1.subject or "") or "TEST" in (s1.faculty or ""))
                    is_test2 = ("TEST" in (s2.subject or "") or "TEST" in (s2.faculty or ""))

                    if not is_test1 and can_extend_s1:
                        s1.end_min = s2.start_min
                        closed_in_pass += 1
                    elif not is_test2 and can_shift_s2:
                        s2.start_min = s1.end_min
                        closed_in_pass += 1
                    elif can_extend_s1:
                        s1.end_min = s2.start_min
                        closed_in_pass += 1
                    elif can_shift_s2:
                        s2.start_min = s1.end_min
                        closed_in_pass += 1

        print(f"Pass {pass_num}: closed {closed_in_pass} gaps.")
        if closed_in_pass == 0:
            break

    # Verification: check remaining gaps <= 20 mins
    rem_gaps = 0
    for (c, b, d), slist in batch_events.items():
        slist.sort(key=lambda x: x.start_min)
        rec = recess_map.get((c, b))
        for i in range(len(slist) - 1):
            s1, s2 = slist[i], slist[i + 1]
            gap = s2.start_min - s1.end_min
            if 0 < gap <= 20:
                if rec and s1.end_min <= rec[0] and s2.start_min >= rec[1]:
                    continue
                rem_gaps += 1
                print(f"  [REMAINING GAP] {c} {b} {d}: {minutes_to_str(s1.end_min)} to {minutes_to_str(s2.start_min)} ({gap}m) | {s1.faculty} -> {s2.faculty}")

    print(f"\nTotal remaining gaps <= 20 mins: {rem_gaps}")

    # Verify batch overlaps
    b_overlaps = 0
    for (c, b, d), slist in batch_events.items():
        slist.sort(key=lambda x: x.start_min)
        for i in range(len(slist) - 1):
            if slist[i].end_min > slist[i + 1].start_min:
                b_overlaps += 1
                print(f"  [OVERLAP] {c} {b} {d}: {slist[i].start_min}-{slist[i].end_min} vs {slist[i+1].start_min}-{slist[i+1].end_min}")

    print(f"Total batch overlaps: {b_overlaps}")

    # Verify faculty travel
    fac_events = {}
    for s in all_slots:
        f = (s.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
            fac_events.setdefault((f, s.day), []).append(s)

    f_travel_viols = 0
    for (f, d), flist in fac_events.items():
        flist.sort(key=lambda x: x.start_min)
        for i in range(len(flist) - 1):
            s1, s2 = flist[i], flist[i + 1]
            if s1.center != s2.center:
                tt = travel_time.get((s1.center, s2.center), 30)
                if (s1.start_min < 840) == (s2.start_min < 840) and s2.start_min - s1.end_min < tt:
                    f_travel_viols += 1
                    print(f"  [TRAVEL VIOLATION] {f} on {d}: {s1.center}->{s2.center} buffer={s2.start_min - s1.end_min}m < {tt}m")

    print(f"Total travel violations: {f_travel_viols}")

if __name__ == "__main__":
    test_gap_elimination()
