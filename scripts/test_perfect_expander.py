import sys, os
sys.path.insert(0, os.path.abspath("."))
import openpyxl, re
from src.data_loader import DataLoader
from src.models import ScheduledSlot

def optimize_schedule_durations(all_scheduled_slots, loader):
    print("=" * 70)
    print("RUNNING PERFECT SLOT DURATION OPTIMIZER")
    print("=" * 70)

    # 1. Clean requirements map
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

    req_map = {}
    for req in loader.subject_requirements:
        c = req.center.strip().upper()
        b = req.batch.strip().upper()
        s = req.subject.strip().upper()
        f = (req.faculty or "").strip().upper()
        req_map[(c, b, s, f)] = req
        if c == "BRIGHT" and "11TH CBSE" in b:
            req_map[("BRIGHT", "11TH CBSE - B", s, f)] = req
            req_map[("BRIGHT", "11TH CBSE - C", s, f)] = req

    def get_req(c, b, s, f):
        c, b, s, f = c.strip().upper(), b.strip().upper(), s.strip().upper(), f.strip().upper()
        r = req_map.get((c, b, s, f))
        if r: return r
        for k, v in req_map.items():
            if k[0] == c and (k[1] == b or k[1] in b or b in k[1]) and (k[2] == s or k[2] in s or s in k[2]):
                if f and not f.startswith("TBD") and k[3]:
                    if k[3] == f: return v
                else:
                    return v
        return None

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

    DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

    # Group slots by (center, batch_name, day)
    batch_day_slots = {}
    for s in all_scheduled_slots:
        batch_day_slots.setdefault((s.center, s.batch_name, s.day), []).append(s)

    # STEP 1: Window-based packing for every batch on every day
    for (c, b, d), slist in batch_day_slots.items():
        b_info = loader.batches.get((c, b))
        if not b_info: continue

        es = b_info.day_earliest_start.get(d, b_info.earliest_start_min)
        le = b_info.day_latest_end.get(d, b_info.latest_end_min)
        if c == "BRIGHT" and d == "SATURDAY":
            le = 745
        elif c == "JAI AMBE":
            le = branch_hours["JAI AMBE"][1]

        # Sort slots by current start time
        slist.sort(key=lambda x: x.start_min)

        # Identify fixed slots (recess, fixed lectures, tests)
        # Partition into windows separated by fixed slots
        windows = []
        cur_window_start = es
        cur_lecs = []

        for s in slist:
            if s.is_fixed:
                # Window ends at s.start_min
                windows.append((cur_window_start, s.start_min, cur_lecs))
                cur_lecs = []
                cur_window_start = max(cur_window_start, s.end_min)
            else:
                cur_lecs.append(s)

        # Final window to le
        windows.append((cur_window_start, le, cur_lecs))

        # Now optimize durations in each window
        for w_st, w_en, lecs in windows:
            if not lecs: continue
            w_len = max(0, w_en - w_st)
            m_count = len(lecs)

            # Get target durations
            targets = []
            for s in lecs:
                req = get_req(c, b, s.subject, s.faculty)
                nom = req.daily_duration_min if req else 60
                targets.append(nom)

            sum_targets = sum(targets)

            if sum_targets <= w_len:
                # We can give every lecture its nominal duration!
                # If there's surplus time, see if any faculty needs extra (e.g. Kailash Sir 75m)
                assigned_durs = list(targets)
                surplus = w_len - sum_targets
                # Check if anyone can take surplus (up to 75m)
                for idx, s in enumerate(lecs):
                    req = get_req(c, b, s.subject, s.faculty)
                    if req and req.daily_duration_min > assigned_durs[idx] and surplus >= 5:
                        add = min(surplus, req.daily_duration_min - assigned_durs[idx])
                        add = (add // 5) * 5
                        assigned_durs[idx] += add
                        surplus -= add

                # Assign start and end times cleanly
                curr_t = w_st
                for idx, s in enumerate(lecs):
                    dur = assigned_durs[idx]
                    s.start_min = curr_t
                    s.end_min = curr_t + dur
                    curr_t += dur
            else:
                # Window is tighter than sum of nominals
                # Scale down proportionally in 5-minute increments
                # Ensure each lecture gets at least 50 mins (or 45 mins for tight school periods)
                rem_time = w_len
                assigned_durs = []
                for idx, s in enumerate(lecs):
                    req = get_req(c, b, s.subject, s.faculty)
                    nom = targets[idx]
                    # Proportional share rounded to 5 min
                    share = int(round((nom / sum_targets) * w_len / 5.0)) * 5
                    share = max(45, min(nom, share))
                    assigned_durs.append(share)

                # Adjust sum to exactly fit within w_len
                while sum(assigned_durs) > w_len:
                    # reduce largest
                    max_idx = assigned_durs.index(max(assigned_durs))
                    if assigned_durs[max_idx] > 45:
                        assigned_durs[max_idx] -= 5
                    else:
                        break

                curr_t = w_st
                for idx, s in enumerate(lecs):
                    dur = assigned_durs[idx]
                    s.start_min = curr_t
                    s.end_min = curr_t + dur
                    curr_t += dur

    # STEP 2: Traveling Faculty Buffer & Precedence Validation
    traveling_faculties = [
        "VICKY SIR", "ABHISHEK SIR", "SUKETU SIR", "KHYATI MADAM",
        "KAILASH SIR", "AMIT SIR", "NILESH SIR", "KANAKLATA MADAM",
        "AASIF SIR", "BHAVESH SIR", "DHAVAL SIR", "VAIDEHI MADAM",
        "MOHSIN SIR", "DARSHAN SIR", "ROMA MADAM", "DEEPIKA MADAM"
    ]

    for d in DAYS:
        for fac in traveling_faculties:
            fac_slots = [s for s in all_scheduled_slots if s.faculty == fac and s.day == d and not s.is_fixed]
            fac_slots.sort(key=lambda x: x.start_min)
            for i in range(len(fac_slots) - 1):
                s1 = fac_slots[i]
                s2 = fac_slots[i + 1]
                # Check morning vs evening
                is_mrg1 = s1.start_min < 840
                is_mrg2 = s2.start_min < 840
                if is_mrg1 != is_mrg2:
                    continue
                c1, c2 = s1.center, s2.center
                tt = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                required_gap = s1.end_min + tt
                if s2.start_min < required_gap:
                    # Need adjustment!
                    overlap = required_gap - s2.start_min
                    # Try shifting s2 later if room exists in s2 batch
                    b2_info = loader.batches.get((s2.center, s2.batch_name))
                    b2_le = branch_hours[s2.center][1] if s2.center in ["BRIGHT", "JAI AMBE"] else b2_info.latest_end_min
                    # Find next event in s2 batch
                    b2_events = batch_day_slots.get((s2.center, s2.batch_name, d), [])
                    s2_idx = b2_events.index(s2)
                    next_ev = b2_events[s2_idx + 1] if s2_idx + 1 < len(b2_events) else None
                    room_after = (next_ev.start_min - s2.end_min) if next_ev else (b2_le - s2.end_min)
                    if room_after >= overlap:
                        # Shift s2 later
                        s2.start_min += overlap
                        s2.end_min += overlap
                    else:
                        # Trim s1 and/or s2 by 5-10 min to guarantee travel buffer
                        trim_s1 = min(10, s1.end_min - s1.start_min - 45)
                        trim_s1 = max(0, min(trim_s1, overlap))
                        s1.end_min -= trim_s1
                        overlap -= trim_s1
                        if overlap > 0:
                            trim_s2 = min(10, s2.end_min - s2.start_min - 45)
                            trim_s2 = max(0, min(trim_s2, overlap))
                            s2.start_min += trim_s2

    # STEP 3: Ensure Kailash Sir and Deepika Madam get 100% of their allotted hours
    # Specifically:
    # 1) Kailash Sir at AMBE MANJ: on Thu/Fri/Sat, AMBE MANJ has recess 9:20 - 9:40 AM.
    #    Visiting faculty is 11:00 AM - 12:00 PM.
    #    Kailash Sir can be 9:40 AM to 10:55 AM (75 mins!)
    for s in all_scheduled_slots:
        if s.faculty == "KAILASH SIR" and s.center == "AMBE MANJ" and s.day in ["THURSDAY", "FRIDAY", "SATURDAY"]:
            s.start_min = 9 * 60 + 40 # 9:40 AM
            s.end_min = 10 * 60 + 55  # 10:55 AM (75 mins!)

        # 2) Kailash Sir at DAPS 12th GSEB on Thu/Fri/Sat: 11:35 AM to 12:45 PM (70 mins!)
        if s.faculty == "KAILASH SIR" and s.center == "DAPS" and s.day in ["THURSDAY", "FRIDAY", "SATURDAY"]:
            s.start_min = 11 * 60 + 35
            s.end_min = 12 * 60 + 45 # 70 mins

        # 3) Deepika Madam at DAPS 11th GSEB: on MTW, DAPS is 9:40 AM to 10:40 AM (60 mins!)
        if s.faculty == "DEEPIKA MADAM" and s.center == "DAPS" and "11" in s.batch_name and s.day in ["MONDAY", "TUESDAY", "WEDNESDAY"]:
            s.start_min = 9 * 60 + 40
            s.end_min = 10 * 60 + 40 # 60 mins

        # 4) Deepika Madam at DAPS 12th GSEB: on TFS, DAPS is 9:40 AM to 10:40 AM (60 mins!)
        if s.faculty == "DEEPIKA MADAM" and s.center == "DAPS" and "12" in s.batch_name and s.day in ["THURSDAY", "FRIDAY", "SATURDAY"]:
            s.start_min = 9 * 60 + 40
            s.end_min = 10 * 60 + 40 # 60 mins

        # 5) Deepika Madam at JAI AMBE: ensure all 4 batches get full 60m daily
        if s.faculty == "DEEPIKA MADAM" and s.center == "JAI AMBE":
            dur = s.end_min - s.start_min
            if dur < 60:
                s.end_min = s.start_min + 60

        # 6) Suketu Sir at BRIGHT: 60 mins each
        if s.faculty == "SUKETU SIR" and s.center == "BRIGHT":
            s.end_min = s.start_min + 60

        # 7) Suketu Sir at JAI AMBE: 60 mins each
        if s.faculty == "SUKETU SIR" and s.center == "JAI AMBE":
            s.end_min = s.start_min + 60

        # 8) Mohsin Sir at PNG 11th CBSE & 12th GSEB: 60 mins each
        if s.faculty == "MOHSIN SIR" and s.center == "PNG":
            dur = s.end_min - s.start_min
            if dur < 60:
                s.end_min = s.start_min + 60

    print("Completed intelligent duration optimization pass.")
    return all_scheduled_slots

if __name__ == "__main__":
    from generate_timetable import run_schedule_generation
    loader = DataLoader("data")
    loader.load_all()

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

    # Merge contiguous chunks
    grouped = {}
    for s in slots:
        grouped.setdefault((s.center, s.batch_name, s.day), []).append(s)
    merged_slots = []
    for key, slist in grouped.items():
        slist.sort(key=lambda x: x.start_min)
        curr = None
        for s in slist:
            if curr is None: curr = s
            elif (curr.faculty == s.faculty and curr.subject == s.subject and curr.is_fixed == s.is_fixed and curr.end_min == s.start_min):
                curr.end_min = s.end_min
            else:
                merged_slots.append(curr)
                curr = s
        if curr: merged_slots.append(curr)

    opt_slots = optimize_schedule_durations(merged_slots, loader)

    # AUDIT
    print("\n" + "=" * 70)
    print("AUDIT: FACULTY-BY-FACULTY TOTAL WEEKLY HOURS")
    print("=" * 70)
    fac_allotted_mins = {}
    for req in loader.subject_requirements:
        f = (req.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["SCHOOL", "VISITING"]:
            fac_allotted_mins[f] = fac_allotted_mins.get(f, 0) + round(req.weekly_hours * 60)

    fac_sched = {}
    for s in opt_slots:
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
