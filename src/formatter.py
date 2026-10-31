from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from src.models import ScheduledSlot
from src.data_loader import DAYS_OF_WEEK, minutes_to_str

class TimetableFormatter:
    """
    Formats weekly schedule into clean vertical timetable matrices.
    """

    def __init__(self, start_date_str: str = "05/10/2026"):
        self.start_date_str = start_date_str

    def format_vertical_matrix(self, slots: List[ScheduledSlot], recess_info: Optional[Tuple[int, int]] = None) -> Dict:
        """
        Builds a grid for batch schedule:
        Columns: Days (Mon-Sat)
        Rows: Non-overlapping consolidated lecture time slots
        """
        # Find all distinct lecture intervals for this batch
        # To avoid over-fragmentation, we use the actual scheduled lecture intervals
        slot_intervals = set()
        for s in slots:
            slot_intervals.add((s.start_min, s.end_min))
        if recess_info:
            slot_intervals.add((recess_info[0], recess_info[1]))

        # Sort intervals by start time
        sorted_intervals = sorted(list(slot_intervals), key=lambda x: (x[0], x[1]))

        # Consolidate overlapping / boundary intervals into clean contiguous display rows
        time_points = set()
        for st, et in sorted_intervals:
            time_points.add(st)
            time_points.add(et)
        sorted_times = sorted(list(time_points))

        slices = []
        for i in range(len(sorted_times) - 1):
            st, et = sorted_times[i], sorted_times[i + 1]
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
                # Merge consecutive recess slices
                prev[1] = sl[1]
            else:
                merged.append(sl)

        # Guarantee strictly contiguous periods (zero gap between rows)
        for i in range(len(merged) - 1):
            if merged[i][1] < merged[i + 1][0]:
                merged[i][1] = merged[i + 1][0]

        # If any non-recess period is very long (>= 110 mins), split into two clean periods
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
            grid_rows.append({
                "time_label": time_label,
                "start_min": st,
                "end_min": et,
                "is_recess": is_recess_slot,
                "day_cells": {}
            })

        # Slot matching per day with multi-row span and exact time support
        for d in DAYS_OF_WEEK:
            day_slots = sorted([s for s in slots if s.day == d], key=lambda x: x.start_min)

            # Step 1: For each row, calculate overlap with each slot
            row_slot_candidates = defaultdict(list)
            for s_idx, s in enumerate(day_slots):
                for r_idx, r in enumerate(grid_rows):
                    if r["is_recess"]:
                        continue
                    ov = max(0, min(s.end_min, r["end_min"]) - max(s.start_min, r["start_min"]))
                    r_dur = r["end_min"] - r["start_min"]
                    if ov >= 15 or ov >= r_dur * 0.35:
                        row_slot_candidates[r_idx].append((ov, s_idx, s))

            # Step 2: Assign best slot to each row (the one with max overlap)
            row_assigned_slot = {}
            for r_idx, candidates in row_slot_candidates.items():
                candidates.sort(key=lambda x: x[0], reverse=True)
                row_assigned_slot[r_idx] = candidates[0][2]

            # Step 3: Determine span_start and span_count for consecutive rows sharing same slot
            slot_consecutive_rows = defaultdict(list)
            curr_s = None
            curr_run = []
            for r_idx, r in enumerate(grid_rows):
                if r["is_recess"]:
                    curr_s = None
                    curr_run = []
                    continue
                s = row_assigned_slot.get(r_idx)
                if s is not None and s == curr_s:
                    curr_run.append(r_idx)
                else:
                    curr_s = s
                    curr_run = [r_idx] if s is not None else []
                    if s is not None:
                        slot_consecutive_rows[id(s)].append(curr_run)

            # Step 4: Build day_cells
            for r_idx, r in enumerate(grid_rows):
                if r["is_recess"]:
                    r["day_cells"][d] = {
                        "type": "recess",
                        "faculty": "RECESS / BREAK",
                        "subject": "",
                        "chapter": "",
                        "topic": ""
                    }
                    continue
                s = row_assigned_slot.get(r_idx)
                if s is None:
                    r["day_cells"][d] = {
                        "type": "free",
                        "faculty": "---",
                        "subject": "",
                        "chapter": "",
                        "topic": ""
                    }
                else:
                    is_test = (s.subject == "WEEKLY TEST" or "TEST" in (s.faculty or "").upper())
                    dur_m = s.end_min - s.start_min
                    time_range_str = f"{minutes_to_str(s.start_min)} - {minutes_to_str(s.end_min)}"

                    runs = slot_consecutive_rows.get(id(s), [])
                    matching_run = next((run for run in runs if r_idx in run), [r_idx])

                    is_start = (r_idx == matching_run[0])
                    span_cnt = len(matching_run) if is_start else 1
                    is_cont = not is_start

                    r["day_cells"][d] = {
                        "type": "test" if is_test else "lecture",
                        "faculty": "WEEKLY TEST" if is_test else s.faculty,
                        "subject": "1 HOUR EXAM" if is_test else s.subject,
                        "chapter": s.chapter or ("Weekly Test" if is_test else "CH-1"),
                        "topic": s.topic or ("1 Hour Exam" if is_test else "TOPIC-1"),
                        "time_range": time_range_str,
                        "duration_min": dur_m,
                        "duration_label": f"{dur_m} mins",
                        "is_span_start": is_start and len(matching_run) > 1,
                        "span_count": span_cnt,
                        "is_span_continuation": is_cont
                    }

        return {
            "days": DAYS_OF_WEEK,
            "rows": grid_rows
        }

    def format_faculty_vertical_matrix(self, slots: List[ScheduledSlot], travel_matrix: Dict = None) -> Dict:
        """
        Builds a TIME-BASED personal timetable for an individual faculty member.
        Rows represent chronological time slots (e.g. 3:00 PM - 4:00 PM) rather than arbitrary lecture numbers.
        If a faculty has a lecture on Monday from 3pm to 4pm, but starts at 4pm on other days,
        the 3pm - 4pm row will show the lecture on Monday and blank (---) on all other days.
        """
        # Separate slots into Morning (< 3:00 PM / 900m) and Evening (>= 3:00 PM / 900m)
        mrg_slots = [s for s in slots if s.start_min < 900]
        eve_slots = [s for s in slots if s.start_min >= 900]

        if not mrg_slots and not eve_slots:
            return {"days": DAYS_OF_WEEK, "rows": []}

        def align_slots_into_rows(half_slots):
            if not half_slots:
                return []

            # Group by day and sort chronologically
            day_slots = {d: [] for d in DAYS_OF_WEEK}
            for s in half_slots:
                if s.day in day_slots:
                    day_slots[s.day].append(s)

            for d in DAYS_OF_WEEK:
                # Deduplicate identical simultaneous slots if any (e.g. combined batches)
                deduped = []
                for s in sorted(day_slots[d], key=lambda x: (x.start_min, x.end_min)):
                    if not deduped or deduped[-1]["start_min"] != s.start_min or deduped[-1]["end_min"] != s.end_min or deduped[-1]["center"] != s.center:
                        deduped.append({
                            "slot": s,
                            "start_min": s.start_min,
                            "end_min": s.end_min,
                            "center": s.center,
                            "batch_name": s.batch_name,
                            "subject": s.subject,
                            "chapter": s.chapter or "CH-1",
                            "topic": s.topic or "TOPIC-1"
                        })
                    else:
                        if s.batch_name not in deduped[-1]["batch_name"]:
                            deduped[-1]["batch_name"] += f" / {s.batch_name}"
                day_slots[d] = deduped

            # Progressive time-based row alignment
            rows = []

            all_items = []
            for d in DAYS_OF_WEEK:
                for idx, item in enumerate(day_slots[d]):
                    all_items.append((item["start_min"], item["end_min"], d, idx, item))
            all_items.sort(key=lambda x: (x[0], x[1]))

            for st_m, et_m, d, idx, item in all_items:
                best_row_idx = None
                best_score = -1e9

                for r_i, r in enumerate(rows):
                    if d in r["day_cells"]:
                        continue

                    # Chronological order consistency check:
                    # Previous lectures on day d must be placed in rows < r_i
                    violates_order = False
                    for prev_idx in range(idx):
                        prev_item = day_slots[d][prev_idx]
                        for check_r_i, check_r in enumerate(rows):
                            if check_r["day_cells"].get(d) is prev_item and check_r_i >= r_i:
                                violates_order = True
                                break
                        if violates_order:
                            break
                    if violates_order:
                        continue

                    # Subsequent lectures on day d already placed must be in rows > r_i
                    for next_idx in range(idx + 1, len(day_slots[d])):
                        next_item = day_slots[d][next_idx]
                        for check_r_i, check_r in enumerate(rows):
                            if check_r["day_cells"].get(d) is next_item and check_r_i <= r_i:
                                violates_order = True
                                break
                        if violates_order:
                            break
                    if violates_order:
                        continue

                    # Temporal alignment check:
                    # Must overlap significantly and have proximate start times
                    r_st, r_et = r["start_min"], r["end_min"]
                    ov = max(0, min(et_m, r_et) - max(st_m, r_st))
                    start_diff = abs(st_m - r_st)

                    if start_diff <= 40 and ov >= 20:
                        score = ov * 2 - start_diff
                        if score > best_score:
                            best_score = score
                            best_row_idx = r_i

                if best_row_idx is not None:
                    r = rows[best_row_idx]
                    r["day_cells"][d] = item
                    r["start_min"] = min(r["start_min"], st_m)
                    r["end_min"] = max(r["end_min"], et_m)
                else:
                    new_row = {
                        "day_cells": {d: item},
                        "start_min": st_m,
                        "end_min": et_m
                    }
                    insert_idx = len(rows)
                    for i, existing_r in enumerate(rows):
                        if existing_r["start_min"] > st_m or (existing_r["start_min"] == st_m and existing_r["end_min"] > et_m):
                            insert_idx = i
                            break
                    rows.insert(insert_idx, new_row)

            # Build standardized grid_rows dictionaries
            formatted_rows = []
            for r in rows:
                time_label = f"{minutes_to_str(r['start_min'])} - {minutes_to_str(r['end_min'])}"
                row_data = {
                    "time_label": time_label,
                    "start_min": r["start_min"],
                    "end_min": r["end_min"],
                    "is_recess": False,
                    "is_lunch_break": False,
                    "day_cells": {}
                }
                for d in DAYS_OF_WEEK:
                    item = r["day_cells"].get(d)
                    if item:
                        dur_m = item["end_min"] - item["start_min"]
                        time_range = f"{minutes_to_str(item['start_min'])} - {minutes_to_str(item['end_min'])}"
                        dur_str = f"({dur_m} mins)"
                        row_data["day_cells"][d] = {
                            "type": "lecture",
                            "time_range": time_range,
                            "duration": dur_str,
                            "center_batch": f"{item['center']} ({item['batch_name']})",
                            "subject": item["subject"],
                            "chapter": item["chapter"],
                            "topic": item["topic"]
                        }
                    else:
                        row_data["day_cells"][d] = {
                            "type": "free",
                            "center_batch": "---",
                            "subject": "",
                            "chapter": "",
                            "topic": ""
                        }
                formatted_rows.append(row_data)

            return formatted_rows

        grid_rows = []
        mrg_rows = align_slots_into_rows(mrg_slots)
        grid_rows.extend(mrg_rows)

        # Visual Divider: LUNCH BREAK before Evening Lectures (starting from 3:00 PM)
        if eve_slots:
            lunch_row = {
                "time_label": "LUNCH BREAK",
                "is_recess": True,
                "is_lunch_break": True,
                "day_cells": {
                    d: {
                        "type": "recess",
                        "faculty": "LUNCH BREAK",
                        "center_batch": "LUNCH BREAK",
                        "subject": "",
                        "chapter": "",
                        "topic": ""
                    } for d in DAYS_OF_WEEK
                }
            }
            grid_rows.append(lunch_row)

            eve_rows = align_slots_into_rows(eve_slots)
            grid_rows.extend(eve_rows)

        return {
            "days": DAYS_OF_WEEK,
            "rows": grid_rows
        }
