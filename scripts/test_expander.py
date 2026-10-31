import sys, os
sys.path.insert(0, os.path.abspath("."))
import time
from ortools.sat.python import cp_model

from src.models import ScheduledSlot
from src.data_loader import DataLoader, DAYS_OF_WEEK
from scripts.audit_hours import parse_mins_from_cell

def expand_slot_durations(all_scheduled_slots, loader):
    print("\n" + "=" * 65)
    print("RUNNING INTELLIGENT SLOT DURATION EXPANDER")
    print("=" * 65)

    # Index requirements by (center, batch, subject, faculty)
    req_map = {}
    cleaned_requirements = []
    for req in loader.subject_requirements:
        if req.center == "VB" and req.batch == "12TH GSEB" and req.subject == "STATISTICS":
            req.faculty = "VICKY SIR"
            req.weekly_days = 3
            req.weekly_hours = 3.0
            req.daily_duration_min = 60
            cleaned_requirements.append(req)
        elif req.center == "SG" and req.batch == "12TH GSEB" and req.subject == "STATISTICS":
            req.faculty = "VICKY SIR"
            req.weekly_days = 3
            req.weekly_hours = 3.0
            req.daily_duration_min = 60
            cleaned_requirements.append(req)
        elif req.center == "BRIGHT" and req.subject == "ECONOMICS":
            req.weekly_days = 3
            req.weekly_hours = 3.0
            req.daily_duration_min = 60
            cleaned_requirements.append(req)
        else:
            cleaned_requirements.append(req)
    loader.subject_requirements = cleaned_requirements

    for req in loader.subject_requirements:
        f = (req.faculty or "").strip().upper()
        c = req.center.strip().upper()
        b = req.batch.strip().upper()
        s = req.subject.strip().upper()
        req_map[(c, b, s, f)] = req
        # Also map without section for Bright 11th CBSE
        if c == "BRIGHT" and "11TH CBSE" in b:
            req_map[("BRIGHT", "11TH CBSE - B", s, f)] = req
            req_map[("BRIGHT", "11TH CBSE - C", s, f)] = req

    # Calculate overall operating limits per branch
    branch_hours = {}
    for (c, b), b_info in loader.batches.items():
        es = b_info.earliest_start_min
        le = b_info.latest_end_min
        if c not in branch_hours:
            branch_hours[c] = [es, le]
        else:
            branch_hours[c][0] = min(branch_hours[c][0], es)
            branch_hours[c][1] = max(branch_hours[c][1], le)

    travel_time = loader.travel_matrix

    # Multiple passes of expansion to propagate ripple effects
    for pass_num in range(1, 4):
        # Build batch schedule index: (center, batch, day) -> list of slots sorted by start_min
        batch_events = {}
        for s in all_scheduled_slots:
            batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)

        for key in batch_events:
            batch_events[key].sort(key=lambda x: x.start_min)

        # Build faculty schedule index: (faculty, day) -> list of slots sorted by start_min
        fac_events = {}
        for s in all_scheduled_slots:
            fac = s.faculty.strip().upper()
            if fac and not fac.startswith("TBD") and fac not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
                fac_events.setdefault((fac, s.day), []).append(s)

        for key in fac_events:
            fac_events[key].sort(key=lambda x: x.start_min)

        # Calculate current total minutes per requirement
        req_current_mins = {}
        for s in all_scheduled_slots:
            if s.is_fixed: continue
            fac = s.faculty.strip().upper()
            c = s.center.strip().upper()
            b = s.batch_name.strip().upper()
            subj = s.subject.strip().upper()
            key = (c, b, subj, fac)
            dur = s.end_min - s.start_min
            req_current_mins[key] = req_current_mins.get(key, 0) + dur

        expanded_count = 0
        minutes_added = 0

        for s in all_scheduled_slots:
            if s.is_fixed: continue
            fac = s.faculty.strip().upper()
            c = s.center.strip().upper()
            b = s.batch_name.strip().upper()
            subj = s.subject.strip().upper()
            rkey = (c, b, subj, fac)
            req = req_map.get(rkey)
            if not req:
                # Try partial match
                for mk, mr in req_map.items():
                    if mk[0] == c and (mk[1] == b or mk[1] in b or b in mk[1]) and mk[2] == subj and mk[3] == fac:
                        req = mr
                        rkey = mk
                        break

            target_weekly = round(req.weekly_hours * 60) if req else 180
            cur_weekly = req_current_mins.get(rkey, 0)
            cur_dur = s.end_min - s.start_min
            nom_dur = req.daily_duration_min if req else 60

            # Target duration for this slot: up to nom_dur or max 75 min if deficit remains
            max_allowed_dur = min(85, max(nom_dur, 75))
            if cur_dur >= max_allowed_dur and cur_weekly >= target_weekly:
                continue

            # Check forward expansion into gap after slot
            b_list = batch_events.get((c, b, s.day), [])
            s_idx = b_list.index(s)
            next_b_event = b_list[s_idx + 1] if s_idx + 1 < len(b_list) else None

            b_info = loader.batches.get((c, b))
            max_batch_le = branch_hours[c][1] if c in ["BRIGHT", "JAI AMBE"] else (b_info.latest_end_min if b_info else 1200)
            day_le = max_batch_le if (c == "BRIGHT" and s.day == "SATURDAY") or (c == "JAI AMBE") else (b_info.day_latest_end.get(s.day, max_batch_le) if b_info else max_batch_le)

            batch_room_after = (next_b_event.start_min - s.end_min) if next_b_event else (day_le - s.end_min)
            batch_room_after = max(0, batch_room_after)

            # Check faculty constraint after slot
            f_list = fac_events.get((fac, s.day), [])
            f_idx = f_list.index(s) if s in f_list else -1
            next_f_event = f_list[f_idx + 1] if (f_idx >= 0 and f_idx + 1 < len(f_list)) else None

            fac_room_after = 9999
            if next_f_event:
                # Check if morning vs evening
                is_mrg1 = s.start_min < 840
                is_mrg2 = next_f_event.start_min < 840
                if is_mrg1 == is_mrg2:
                    tt = travel_time.get((s.center, next_f_event.center), 30) if s.center != next_f_event.center else 0
                    fac_room_after = max(0, next_f_event.start_min - tt - s.end_min)
            else:
                fac_restr = loader.faculties.get(fac)
                if fac_restr and fac_restr.available_to_min and s.start_min >= 840:
                    fac_room_after = max(0, fac_restr.available_to_min - s.end_min)

            # Usable expansion after
            expand_after = min(batch_room_after, fac_room_after)
            # Round down to multiple of 5 minutes
            expand_after = (expand_after // 5) * 5

            # Needed expansion
            needed_expansion = max(0, nom_dur - cur_dur)
            if cur_weekly < target_weekly:
                deficit_left = target_weekly - cur_weekly
                needed_expansion = max(needed_expansion, min(deficit_left, max_allowed_dur - cur_dur))

            actual_expand = min(expand_after, needed_expansion)
            if actual_expand > 0:
                s.end_min += actual_expand
                req_current_mins[rkey] = req_current_mins.get(rkey, 0) + actual_expand
                expanded_count += 1
                minutes_added += actual_expand

            # Check backward expansion (can start earlier?)
            cur_dur = s.end_min - s.start_min
            cur_weekly = req_current_mins.get(rkey, 0)
            if cur_weekly < target_weekly or cur_dur < nom_dur:
                prev_b_event = b_list[s_idx - 1] if s_idx > 0 else None
                day_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min) if b_info else 420
                batch_room_before = (s.start_min - prev_b_event.end_min) if prev_b_event else (s.start_min - day_es)
                batch_room_before = max(0, batch_room_before)

                prev_f_event = f_list[f_idx - 1] if f_idx > 0 else None
                fac_room_before = 9999
                if prev_f_event:
                    is_mrg1 = s.start_min < 840
                    is_mrg0 = prev_f_event.start_min < 840
                    if is_mrg1 == is_mrg0:
                        tt = travel_time.get((prev_f_event.center, s.center), 30) if prev_f_event.center != s.center else 0
                        fac_room_before = max(0, s.start_min - (prev_f_event.end_min + tt))

                expand_before = min(batch_room_before, fac_room_before)
                expand_before = (expand_before // 5) * 5

                needed_expansion = max(0, nom_dur - cur_dur)
                if cur_weekly < target_weekly:
                    deficit_left = target_weekly - cur_weekly
                    needed_expansion = max(needed_expansion, min(deficit_left, max_allowed_dur - cur_dur))

                actual_shift = min(expand_before, needed_expansion)
                if actual_shift > 0:
                    s.start_min -= actual_shift
                    req_current_mins[rkey] = req_current_mins.get(rkey, 0) + actual_shift
                    expanded_count += 1
                    minutes_added += actual_shift

        print(f"Pass {pass_num}: Expanded {expanded_count} slots, added {minutes_added} minutes.")

    # Audit faculties after expansion
    print("\n" + "=" * 65)
    print("AUDIT AFTER DURATION EXPANSION:")
    print("=" * 65)
    fac_allotted_mins = {}
    for req in loader.subject_requirements:
        f = (req.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["SCHOOL", "VISITING"]:
            fac_allotted_mins[f] = fac_allotted_mins.get(f, 0) + round(req.weekly_hours * 60)

    fac_sched = {}
    for s in all_scheduled_slots:
        if s.is_fixed: continue
        f = s.faculty.strip().upper()
        if f in fac_allotted_mins:
            dur = s.end_min - s.start_min
            fac_sched[f] = fac_sched.get(f, 0) + dur

    deficits = 0
    for f, allot_m in sorted(fac_allotted_mins.items()):
        act_m = fac_sched.get(f, 0)
        diff = act_m - allot_m
        status = "OK" if diff >= 0 else f"DEFICIT {-diff}m"
        if diff < 0: deficits += 1
        print(f"  {f:25s} | Allotted: {allot_m:4d}m ({allot_m/60:4.1f}h) | Scheduled: {act_m:4d}m ({act_m/60:4.1f}h) | Diff: {diff:+4d}m -> {status}")

    print(f"\nTotal Faculties with Deficit: {deficits} out of {len(fac_allotted_mins)}")
    return all_scheduled_slots

if __name__ == "__main__":
    from generate_timetable import run_schedule_generation
    # Let's run a test
    loader = DataLoader("data")
    loader.load_all()
    # Load slots from excel
    import openpyxl, re
    wb = openpyxl.load_workbook("output/excel/All_Batches_Weekly_Schedule.xlsx")
    slots = []
    DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
    for sname in wb.sheetnames:
        ws = wb[sname]
        c, b = sname.split(" - ", 1)
        c, b = c.strip().upper(), b.strip().upper()
        for r in range(5, ws.max_row + 1):
            time_val = str(ws.cell(r, 1).value or "").strip()
            if not time_val: continue
            m = re.match(r"(\d+):(\d+)\s*(AM|PM)?\s*TO\s*(\d+):(\d+)\s*(AM|PM)?", time_val, re.I)
            if not m: continue
            h1, m1, p1, h2, m2, p2 = m.groups()
            h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
            if p1 and p1.upper() == "PM" and h1 < 12: h1 += 12
            if p1 and p1.upper() == "AM" and h1 == 12: h1 = 0
            if p2 and p2.upper() == "PM" and h2 < 12: h2 += 12
            if p2 and p2.upper() == "AM" and h2 == 12: h2 = 0
            st = h1 * 60 + m1
            en = h2 * 60 + m2
            for c_idx, d in enumerate(DAYS, start=2):
                cell_txt = str(ws.cell(r, c_idx).value or "").strip()
                if not cell_txt or cell_txt == "---": continue
                lines = cell_txt.split("\n")
                fac = lines[0].strip().upper()
                subj = lines[1].strip().upper() if len(lines) > 1 else ""
                is_fix = ("★" in cell_txt or "RECESS" in cell_txt or "TEST" in cell_txt or "EXAM" in cell_txt or "School Topic" in cell_txt)
                slots.append(ScheduledSlot(
                    batch_key=f"{c}_{b}",
                    center=c,
                    batch_name=b,
                    day=d,
                    start_min=st,
                    end_min=en,
                    subject=subj if subj else fac,
                    faculty=fac,
                    is_fixed=is_fix
                ))

    expand_slot_durations(slots, loader)
