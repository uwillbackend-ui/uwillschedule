import sys, os
sys.path.insert(0, os.path.abspath("."))
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str, DAYS_OF_WEEK
from src.models import ScheduledSlot
import openpyxl

def test_unified():
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

    print(f"Loaded {len(all_slots)} slots.")

    # 1. Close gaps in all_slots
    fac_events = {}
    for s in all_slots:
        f = (s.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
            fac_events.setdefault((f, s.day), []).append(s)
    for k in fac_events:
        fac_events[k].sort(key=lambda x: x.start_min)

    batch_events = {}
    for s in all_slots:
        batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)
    for k in batch_events:
        batch_events[k].sort(key=lambda x: x.start_min)

    closed_slots = 0
    for (c, b, d), slist in batch_events.items():
        rec = recess_map.get((c, b))
        for i in range(len(slist) - 1):
            s1, s2 = slist[i], slist[i + 1]
            gap = s2.start_min - s1.end_min
            if 0 < gap <= 15:
                # Do not close if recess is between them
                if rec and s1.end_min <= rec[0] and s2.start_min >= rec[1]:
                    continue
                # Try extending s1
                f1 = (s1.faculty or "").strip().upper()
                fl1 = fac_events.get((f1, d), [])
                idx1 = fl1.index(s1) if s1 in fl1 else -1
                next_f1 = fl1[idx1 + 1] if (idx1 >= 0 and idx1 + 1 < len(fl1)) else None
                can_ext_s1 = True
                if next_f1:
                    tt = travel_time.get((s1.center, next_f1.center), 30) if s1.center != next_f1.center else 0
                    if s2.start_min + tt > next_f1.start_min:
                        can_ext_s1 = False

                # Try shifting s2
                f2 = (s2.faculty or "").strip().upper()
                fl2 = fac_events.get((f2, d), [])
                idx2 = fl2.index(s2) if s2 in fl2 else -1
                prev_f2 = fl2[idx2 - 1] if idx2 > 0 else None
                can_shift_s2 = True
                if prev_f2:
                    tt = travel_time.get((prev_f2.center, s2.center), 30) if prev_f2.center != s2.center else 0
                    if prev_f2.end_min + tt > s1.end_min:
                        can_shift_s2 = False

                is_test1 = ("TEST" in (s1.subject or "") or "TEST" in (s1.faculty or ""))
                is_test2 = ("TEST" in (s2.subject or "") or "TEST" in (s2.faculty or ""))

                if not is_test1 and can_ext_s1:
                    s1.end_min = s2.start_min
                    closed_slots += 1
                elif not is_test2 and can_shift_s2:
                    s2.start_min = s1.end_min
                    closed_slots += 1

    print(f"Closed {closed_slots} small gaps in slot data.")

    # 2. Test Contiguous Formatter
    def format_batch(b_slots, recess_info):
        pts = set()
        for s in b_slots:
            pts.add(s.start_min)
            pts.add(s.end_min)
        if recess_info:
            pts.add(recess_info[0])
            pts.add(recess_info[1])
        sorted_pts = sorted(list(pts))

        slices = []
        for i in range(len(sorted_pts)-1):
            st, et = sorted_pts[i], sorted_pts[i+1]
            is_rec = recess_info and (st >= recess_info[0] and et <= recess_info[1])
            slices.append([st, et, is_rec])

        merged = []
        for sl in slices:
            if not merged:
                merged.append(sl)
                continue
            prev = merged[-1]
            dur = sl[1] - sl[0]
            prev_dur = prev[1] - prev[0]

            if prev[2] != sl[2]:
                merged.append(sl)
            elif dur < 25 and not sl[2]:
                prev[1] = sl[1]
            elif prev_dur < 25 and not prev[2]:
                prev[1] = sl[1]
            elif prev[2] and sl[2]:
                prev[1] = sl[1]
            else:
                merged.append(sl)

        # Ensure no gaps between intervals
        for i in range(len(merged)-1):
            if merged[i][1] < merged[i+1][0]:
                merged[i][1] = merged[i+1][0]

        # If any interval is >= 110 mins and not recess, split evenly
        final_intervals = []
        for st, et, is_rec in merged:
            dur = et - st
            if dur >= 110 and not is_rec:
                half = (dur // 10) * 5
                final_intervals.append([st, st + half, is_rec])
                final_intervals.append([st + half, et, is_rec])
            else:
                final_intervals.append([st, et, is_rec])

        grid_rows = []
        for (st, et, is_recess_slot) in final_intervals:
            time_label = f"{minutes_to_str(st)} TO {minutes_to_str(et)}"
            row_data = {
                "time_label": time_label,
                "start_min": st,
                "end_min": et,
                "is_recess": is_recess_slot,
                "day_cells": {}
            }
            for d in DAYS_OF_WEEK:
                if is_recess_slot:
                    row_data["day_cells"][d] = {"type": "recess", "faculty": "RECESS / BREAK"}
                    continue
                day_s = [s for s in b_slots if s.day == d]
                best_s = None
                best_ov = 0
                for s in day_s:
                    ov = max(0, min(s.end_min, et) - max(s.start_min, st))
                    if ov > best_ov and (ov >= 20 or ov >= (s.end_min - s.start_min) * 0.35):
                        best_ov = ov
                        best_s = s
                if best_s:
                    is_test = ("TEST" in (best_s.subject or "") or "TEST" in (best_s.faculty or ""))
                    row_data["day_cells"][d] = {
                        "type": "test" if is_test else "lecture",
                        "faculty": best_s.faculty,
                        "subject": best_s.subject,
                        "chapter": best_s.chapter,
                        "topic": best_s.topic
                    }
                else:
                    row_data["day_cells"][d] = {"type": "free", "faculty": "---", "subject": ""}

            grid_rows.append(row_data)

        return grid_rows

    # Audit all batches for gaps between rows
    total_row_gaps = 0
    batch_map = {}
    for s in all_slots:
        batch_map.setdefault((s.center, s.batch_name), []).append(s)

    for (c, b), b_slots in batch_map.items():
        rec = recess_map.get((c, b))
        rows = format_batch(b_slots, rec)
        for i in range(len(rows)-1):
            r1, r2 = rows[i], rows[i+1]
            if r1["end_min"] != r2["start_min"]:
                total_row_gaps += 1
                print(f"Row gap in {c} {b}: {r1['time_label']} -> {r2['time_label']}")

    print(f"\nFinal Audit: Total row gaps across all 36 batches = {total_row_gaps}!")

if __name__ == "__main__":
    test_unified()
