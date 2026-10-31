import sys, os
sys.path.insert(0, os.path.abspath("."))
from src.models import ScheduledSlot
from src.data_loader import DataLoader, DAYS_OF_WEEK

def check_fac_allowed_bounds(fac_name, day, start_min, end_min, loader):
    fac_clean = (fac_name or "").strip().upper()
    fac_names = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
    for fn in fac_names:
        if fn == "ASIF SIR": fn = "AASIF SIR"
        fac_obj = loader.faculties.get(fn)
        if not fac_obj or not fac_obj.day_limits:
            continue
        lim = fac_obj.day_limits.get(day)
        if not lim:
            continue
        is_mrg = start_min < 840
        if is_mrg:
            if lim.get("mrg_from") is not None and lim.get("mrg_to") is not None and lim["mrg_from"] == lim["mrg_to"]:
                return False
            if lim.get("mrg_from") is not None and start_min < lim["mrg_from"]:
                return False
            if lim.get("mrg_to") is not None and end_min > lim["mrg_to"]:
                return False
        else:
            if lim.get("eve_from") is not None and lim.get("eve_to") is not None and lim["eve_from"] == lim["eve_to"]:
                return False
            if lim.get("eve_from") is not None and start_min < lim["eve_from"]:
                return False
            if lim.get("eve_to") is not None and end_min > lim["eve_to"]:
                return False
    return True

def check_fac_no_overlap(f_name, day, s_curr, new_st, new_et, all_slots, travel_time):
    fac_clean = (f_name or "").strip().upper()
    if not fac_clean or fac_clean.startswith("TBD") or fac_clean in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
        return True
    facs_1 = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
    facs_1 = ["AASIF SIR" if f == "ASIF SIR" else f for f in facs_1]

    for other in all_slots:
        if other is s_curr or other.day != day:
            continue
        of_clean = (other.faculty or "").strip().upper()
        if not of_clean or of_clean.startswith("TBD") or of_clean in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
            continue
        facs_2 = [f.strip() for f in of_clean.split("/")] if "/" in of_clean else [of_clean]
        facs_2 = ["AASIF SIR" if f == "ASIF SIR" else f for f in facs_2]

        if not set(facs_1).intersection(set(facs_2)):
            continue
        if (new_st < 840) != (other.start_min < 840):
            continue
        tt = travel_time.get((s_curr.center, other.center), 30) if s_curr.center != other.center else 0
        if not (new_et + tt <= other.start_min or new_st >= other.end_min + tt):
            return False
    return True

def enforce_zero_deficits(all_scheduled_slots, loader, branch_hours):
    print("=" * 70)
    print("ENFORCING ZERO-DEFICIT DURATION EXPANSION ACROSS ALL FACULTIES")
    print("=" * 70)

    travel_time = loader.travel_matrix

    recess_map = {}
    for (c, b), b_info in loader.batches.items():
        if b_info.recess_start_min and b_info.recess_end_min:
            recess_map[(c, b)] = [b_info.recess_start_min, b_info.recess_end_min]

    # 1. Clean requirements map exactly as in timetable generator
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
        elif req.center in ["OP", "PNG", "NZM"] and "SY B.COM" in req.batch and "CORPORATE" in req.subject:
            req.weekly_days = 2
            req.weekly_hours = 2.0
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

    # Step 1: Multi-pass ripple expansion respecting batch room and faculty travel buffers
    total_added_mins = 0
    for pass_num in range(1, 10):
        batch_events = {}
        for s in all_scheduled_slots:
            batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)
        for k in batch_events:
            batch_events[k].sort(key=lambda x: x.start_min)

        fac_events = {}
        for s in all_scheduled_slots:
            f = s.faculty.strip().upper()
            if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
                fac_events.setdefault((f, s.day), []).append(s)
        for k in fac_events:
            fac_events[k].sort(key=lambda x: x.start_min)

        req_totals = {}
        for s in all_scheduled_slots:
            if s.is_fixed: continue
            r = get_req(s.center, s.batch_name, s.subject, s.faculty)
            if r:
                dur = s.end_min - s.start_min
                req_totals[r.req_id] = req_totals.get(r.req_id, 0) + dur

        expanded_count = 0

        # Forward expansion pass (latest to earliest)
        for s in sorted(all_scheduled_slots, key=lambda x: -x.start_min):
            if s.is_fixed: continue
            r = get_req(s.center, s.batch_name, s.subject, s.faculty)
            target_weekly = round(r.weekly_hours * 60) if r else 180
            nom_dur = r.daily_duration_min if r else 60
            cur_dur = s.end_min - s.start_min
            cur_weekly = req_totals.get(r.req_id, 0) if r else target_weekly

            max_allowed_dur = max(nom_dur, 75)
            if cur_dur >= max_allowed_dur and cur_weekly >= target_weekly:
                continue

            b_list = batch_events.get((s.center, s.batch_name, s.day), [])
            s_idx = b_list.index(s)
            next_b = b_list[s_idx + 1] if s_idx + 1 < len(b_list) else None

            b_info = loader.batches.get((s.center, s.batch_name))
            day_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min) if b_info else 1200

            batch_room = (next_b.start_min - s.end_min) if next_b else (day_le - s.end_min)
            batch_room = max(0, batch_room)

            rec = recess_map.get((s.center, s.batch_name))
            if rec and s.end_min <= rec[0]:
                batch_room = max(0, min(batch_room, rec[0] - s.end_min))

            f = s.faculty.strip().upper()
            f_list = fac_events.get((f, s.day), [])
            f_idx = f_list.index(s) if s in f_list else -1
            next_f = f_list[f_idx + 1] if (f_idx >= 0 and f_idx + 1 < len(f_list)) else None

            fac_room = 9999
            if next_f:
                if (s.start_min < 840) == (next_f.start_min < 840):
                    tt = travel_time.get((s.center, next_f.center), 30) if s.center != next_f.center else 0
                    fac_room = max(0, next_f.start_min - tt - s.end_min)
            else:
                fac_restr = loader.faculties.get(f) or loader.faculties.get("AASIF SIR" if f == "ASIF SIR" else f)
                if fac_restr and fac_restr.available_to_min and s.start_min >= 840:
                    fac_room = max(0, fac_restr.available_to_min - s.end_min)

            fac_restr = loader.faculties.get(f) or loader.faculties.get("AASIF SIR" if f == "ASIF SIR" else f)
            if fac_restr and fac_restr.day_limits and s.day in fac_restr.day_limits:
                lim = fac_restr.day_limits[s.day]
                if s.start_min < 840 and lim.get("mrg_to") is not None:
                    fac_room = min(fac_room, max(0, lim["mrg_to"] - s.end_min))
                elif s.start_min >= 840 and lim.get("eve_to") is not None:
                    fac_room = min(fac_room, max(0, lim["eve_to"] - s.end_min))

            avail_after = min(batch_room, fac_room)
            avail_after = (avail_after // 5) * 5

            needed = max(0, nom_dur - cur_dur)
            if cur_weekly < target_weekly:
                deficit_left = target_weekly - cur_weekly
                needed = max(needed, min(deficit_left, max_allowed_dur - cur_dur))

            actual_expand = min(avail_after, needed)
            if actual_expand > 0:
                new_et = s.end_min + actual_expand
                if check_fac_no_overlap(f, s.day, s, s.start_min, new_et, all_scheduled_slots, travel_time):
                    s.end_min = new_et
                    if r: req_totals[r.req_id] = req_totals.get(r.req_id, 0) + actual_expand
                    expanded_count += 1
                    total_added_mins += actual_expand

        # Backward expansion pass (earliest to latest)
        for s in sorted(all_scheduled_slots, key=lambda x: x.start_min):
            if s.is_fixed: continue
            r = get_req(s.center, s.batch_name, s.subject, s.faculty)
            target_weekly = round(r.weekly_hours * 60) if r else 180
            nom_dur = r.daily_duration_min if r else 60
            cur_dur = s.end_min - s.start_min
            cur_weekly = req_totals.get(r.req_id, 0) if r else target_weekly

            max_allowed_dur = max(nom_dur, 75)
            if cur_dur >= max_allowed_dur and cur_weekly >= target_weekly:
                continue

            b_list = batch_events.get((s.center, s.batch_name, s.day), [])
            s_idx = b_list.index(s)
            prev_b = b_list[s_idx - 1] if s_idx > 0 else None

            b_info = loader.batches.get((s.center, s.batch_name))
            is_eve = b_info and (b_info.earliest_start_min >= 840 or "EVE" in s.batch_name or s.start_min >= 840)
            if is_eve and prev_b is None:
                continue

            day_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min) if b_info else 420
            batch_room_before = (s.start_min - prev_b.end_min) if prev_b else (0 if is_eve else (s.start_min - day_es))
            batch_room_before = max(0, batch_room_before)

            rec = recess_map.get((s.center, s.batch_name))
            if rec and s.start_min >= rec[1]:
                batch_room_before = max(0, min(batch_room_before, s.start_min - rec[1]))

            f = s.faculty.strip().upper()
            f_list = fac_events.get((f, s.day), [])
            f_idx = f_list.index(s) if s in f_list else -1
            prev_f = f_list[f_idx - 1] if f_idx > 0 else None

            fac_room_before = 9999
            if prev_f:
                if (s.start_min < 840) == (prev_f.start_min < 840):
                    tt = travel_time.get((prev_f.center, s.center), 30) if prev_f.center != s.center else 0
                    fac_room_before = max(0, s.start_min - (prev_f.end_min + tt))

            fac_restr = loader.faculties.get(f) or loader.faculties.get("AASIF SIR" if f == "ASIF SIR" else f)
            if fac_restr and fac_restr.day_limits and s.day in fac_restr.day_limits:
                lim = fac_restr.day_limits[s.day]
                if s.start_min < 840 and lim.get("mrg_from") is not None:
                    fac_room_before = min(fac_room_before, max(0, s.start_min - lim["mrg_from"]))
                elif s.start_min >= 840 and lim.get("eve_from") is not None:
                    fac_room_before = min(fac_room_before, max(0, s.start_min - lim["eve_from"]))

            avail_before = min(batch_room_before, fac_room_before)
            avail_before = (avail_before // 5) * 5

            needed = max(0, nom_dur - cur_dur)
            if cur_weekly < target_weekly:
                deficit_left = target_weekly - cur_weekly
                needed = max(needed, min(deficit_left, max_allowed_dur - cur_dur))

            actual_shift = min(avail_before, needed)
            if actual_shift > 0:
                new_st = s.start_min - actual_shift
                if check_fac_no_overlap(f, s.day, s, new_st, s.end_min, all_scheduled_slots, travel_time):
                    s.start_min = new_st
                    if r: req_totals[r.req_id] = req_totals.get(r.req_id, 0) + actual_shift
                    expanded_count += 1
                    total_added_mins += actual_shift

        if expanded_count == 0:
            break

    print(f"Ripple expansion pass complete: added {total_added_mins} minutes across slots.")

    # Step 2: Targeted faculty-level deficit elimination pass
    # Ensures every faculty meets or exceeds their total weekly allotted hours
    fac_allotted_mins = {}
    for req in loader.subject_requirements:
        f = (req.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["SCHOOL", "VISITING"]:
            facs = [fn.strip() for fn in f.split("/")] if "/" in f else [f]
            for fn in facs:
                if fn == "ASIF SIR": fn = "AASIF SIR"
                fac_allotted_mins[fn] = fac_allotted_mins.get(fn, 0) + round(req.weekly_hours * 60)

    # Re-index
    batch_events = {}
    for s in all_scheduled_slots:
        batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)
    for k in batch_events:
        batch_events[k].sort(key=lambda x: x.start_min)

    fac_events = {}
    for s in all_scheduled_slots:
        f = s.faculty.strip().upper()
        if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
            fac_events.setdefault((f, s.day), []).append(s)
    for k in fac_events:
        fac_events[k].sort(key=lambda x: x.start_min)

    fac_sched = {}
    for s in all_scheduled_slots:
        if s.is_fixed: continue
        f = (s.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["SCHOOL", "VISITING"]:
            facs = [fn.strip() for fn in f.split("/")] if "/" in f else [f]
            for fn in facs:
                if fn == "ASIF SIR": fn = "AASIF SIR"
                if fn in fac_allotted_mins:
                    dur = s.end_min - s.start_min
                    fac_sched[fn] = fac_sched.get(fn, 0) + dur

    for fac, allot_m in fac_allotted_mins.items():
        cur_m = fac_sched.get(fac, 0)
        if cur_m >= allot_m:
            continue
        def_needed = allot_m - cur_m
        fac_s = [s for s in all_scheduled_slots if not s.is_fixed and (s.faculty == fac or (s.faculty == "ASIF SIR" and fac == "AASIF SIR") or (s.faculty and fac in s.faculty))]

        # Prioritize expanding slots with ample surrounding room
        for s in fac_s:
            if def_needed <= 0: break
            cur_dur = s.end_min - s.start_min
            if cur_dur >= 90: continue

            b_list = batch_events.get((s.center, s.batch_name, s.day), [])
            s_idx = b_list.index(s)
            next_b = b_list[s_idx + 1] if s_idx + 1 < len(b_list) else None
            b_info = loader.batches.get((s.center, s.batch_name))
            day_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min) if b_info else 1200
            batch_room = max(0, (next_b.start_min - s.end_min) if next_b else (day_le - s.end_min))
            rec = recess_map.get((s.center, s.batch_name))
            if rec and s.end_min <= rec[0]:
                batch_room = max(0, min(batch_room, rec[0] - s.end_min))

            f_list = fac_events.get((fac, s.day), [])
            f_idx = f_list.index(s) if s in f_list else -1
            next_f = f_list[f_idx + 1] if (f_idx >= 0 and f_idx + 1 < len(f_list)) else None
            fac_room = 9999
            if next_f:
                if (s.start_min < 840) == (next_f.start_min < 840):
                    tt = travel_time.get((s.center, next_f.center), 30) if s.center != next_f.center else 0
                    fac_room = max(0, next_f.start_min - tt - s.end_min)
            else:
                fac_restr = loader.faculties.get(fac) or loader.faculties.get("AASIF SIR" if fac == "ASIF SIR" else fac)
                if fac_restr and fac_restr.available_to_min and s.start_min >= 840:
                    fac_room = max(0, fac_restr.available_to_min - s.end_min)

            fac_restr = loader.faculties.get(fac) or loader.faculties.get("AASIF SIR" if fac == "ASIF SIR" else fac)
            if fac_restr and fac_restr.day_limits and s.day in fac_restr.day_limits:
                lim = fac_restr.day_limits[s.day]
                if s.start_min < 840 and lim.get("mrg_to") is not None:
                    fac_room = min(fac_room, max(0, lim["mrg_to"] - s.end_min))
                elif s.start_min >= 840 and lim.get("eve_to") is not None:
                    fac_room = min(fac_room, max(0, lim["eve_to"] - s.end_min))

            avail_after = (min(batch_room, fac_room) // 5) * 5
            can_add = min(avail_after, def_needed, 90 - cur_dur)
            if can_add > 0:
                s.end_min += can_add
                def_needed -= can_add
                fac_sched[fac] += can_add

            if def_needed > 0:
                cur_dur = s.end_min - s.start_min
                prev_b = b_list[s_idx - 1] if s_idx > 0 else None
                is_eve = b_info and (b_info.earliest_start_min >= 840 or "EVE" in s.batch_name or s.start_min >= 840)
                if cur_dur < 90 and not (is_eve and prev_b is None):
                    day_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min) if b_info else 420
                    batch_room_before = max(0, (s.start_min - prev_b.end_min) if prev_b else (0 if is_eve else (s.start_min - day_es)))
                    if rec and s.start_min >= rec[1]:
                        batch_room_before = max(0, min(batch_room_before, s.start_min - rec[1]))

                    prev_f = f_list[f_idx - 1] if f_idx > 0 else None
                    fac_room_before = 9999
                    if prev_f:
                        if (s.start_min < 840) == (prev_f.start_min < 840):
                            tt = travel_time.get((prev_f.center, s.center), 30) if prev_f.center != s.center else 0
                            fac_room_before = max(0, s.start_min - (prev_f.end_min + tt))

                    fac_restr = loader.faculties.get(fac) or loader.faculties.get("AASIF SIR" if fac == "ASIF SIR" else fac)
                    if fac_restr and fac_restr.day_limits and s.day in fac_restr.day_limits:
                        lim = fac_restr.day_limits[s.day]
                        if s.start_min < 840 and lim.get("mrg_from") is not None:
                            fac_room_before = min(fac_room_before, max(0, s.start_min - lim["mrg_from"]))
                        elif s.start_min >= 840 and lim.get("eve_from") is not None:
                            fac_room_before = min(fac_room_before, max(0, s.start_min - lim["eve_from"]))

                    avail_before = (min(batch_room_before, fac_room_before) // 5) * 5
                    can_shift = min(avail_before, def_needed, 90 - cur_dur)
                    if can_shift > 0:
                        s.start_min -= can_shift
                        def_needed -= can_shift
                        fac_sched[fac] += can_shift

    # Final safety top-up for any faculty still short
    for fac, allot_m in fac_allotted_mins.items():
        if fac_sched.get(fac, 0) < allot_m:
            gap = allot_m - fac_sched[fac]
            for s in all_scheduled_slots:
                if s.faculty == fac and not s.is_fixed and "TEST" not in (s.subject or "").upper():
                    cur_dur = s.end_min - s.start_min
                    if cur_dur < 90:
                        b_list = batch_events.get((s.center, s.batch_name, s.day), [])
                        s_idx = b_list.index(s) if s in b_list else -1
                        next_b = b_list[s_idx + 1] if (s_idx >= 0 and s_idx + 1 < len(b_list)) else None
                        b_info = loader.batches.get((s.center, s.batch_name))
                        day_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min) if b_info else 1200
                        b_room = max(0, (next_b.start_min - s.end_min) if next_b else (day_le - s.end_min))
                        rec = recess_map.get((s.center, s.batch_name))
                        if rec and s.end_min <= rec[0]:
                            b_room = max(0, min(b_room, rec[0] - s.end_min))
                        if b_room >= 5:
                            add_m = min(gap, b_room, 90 - cur_dur)
                            if check_fac_allowed_bounds(fac, s.day, s.start_min, s.end_min + add_m, loader):
                                s.end_min += add_m
                                gap -= add_m
                                fac_sched[fac] += add_m
                                if gap <= 0:
                                    break

                    # Also check room before
                    prev_b = b_list[s_idx - 1] if s_idx > 0 else None
                    b_info = loader.batches.get((s.center, s.batch_name))
                    is_eve = b_info and (b_info.earliest_start_min >= 840 or "EVE" in s.batch_name or s.start_min >= 840)
                    if gap > 0 and cur_dur < 90 and not (is_eve and prev_b is None):
                        day_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min) if b_info else 420
                        b_room_before = max(0, (s.start_min - prev_b.end_min) if prev_b else (0 if is_eve else (s.start_min - day_es)))
                        rec = recess_map.get((s.center, s.batch_name))
                        if rec and s.start_min >= rec[1]:
                            b_room_before = max(0, min(b_room_before, s.start_min - rec[1]))
                        if b_room_before >= 5:
                            shift_m = min(gap, b_room_before, 90 - cur_dur)
                            if check_fac_allowed_bounds(fac, s.day, s.start_min - shift_m, s.end_min, loader):
                                s.start_min -= shift_m
                                gap -= shift_m
                                fac_sched[fac] += shift_m
                                if gap <= 0:
                                    break

    # Step 3: Precision Rebalancing & Gap Elimination
    # A. Jai Ambe 11th GSEB - C 12:30 PM cutoff clamp
    for s in all_scheduled_slots:
        if s.center == "JAI AMBE" and "11TH" in s.batch_name and "C" in s.batch_name:
            if s.end_min > 750:
                shift = s.end_min - 750
                s.end_min = 750
                s.start_min = max(s.start_min - shift, 660)

    # B. DAPS 12th GSEB latest end (810m = 1:30 PM) clamp
    for s in all_scheduled_slots:
        if s.center == "DAPS" and "12TH" in s.batch_name:
            if s.end_min > 810:
                diff = s.end_min - 810
                s.end_min = 810
                s.start_min = max(s.start_min - diff, 720)

    # C. Ambe Manjalpur Pre-Recess Touch (8:15 - 9:20 AM, 0m gap before recess)
    for s in all_scheduled_slots:
        if s.center == "AMBE MANJ" and s.faculty == "KANAKLATA MADAM" and s.start_min == 495 and s.end_min == 555:
            s.end_min = 560 # 8:15 - 9:20 (65m), touches 9:20 recess!

    # E. Multi-Pass Intelligent Chain-Shifting & Gap Elimination
    closed_gaps_count = 0
    for iteration in range(5):
        fac_events = {}
        for s in all_scheduled_slots:
            f = (s.faculty or "").strip().upper()
            if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
                fac_events.setdefault((f, s.day), []).append(s)
        for k in fac_events:
            fac_events[k].sort(key=lambda x: x.start_min)

        batch_events = {}
        for s in all_scheduled_slots:
            batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)
        for k in batch_events:
            batch_events[k].sort(key=lambda x: x.start_min)

        iter_closed = 0
        for (c, b, d), slist in batch_events.items():
            rec = recess_map.get((c, b))
            b_info = loader.batches.get((c, b))
            day_es = b_info.day_earliest_start.get(d, b_info.earliest_start_min) if b_info else 420
            day_le = b_info.day_latest_end.get(d, b_info.latest_end_min) if b_info else 1200

            for i in range(len(slist) - 1):
                s1, s2 = slist[i], slist[i + 1]
                f1 = (s1.faculty or "").strip().upper()
                f2 = (s2.faculty or "").strip().upper()
                is_test1 = ("TEST" in (s1.subject or "").upper() or "TEST" in f1)
                is_test2 = ("TEST" in (s2.subject or "").upper() or "TEST" in f2)
                dur2 = s2.end_min - s2.start_min

                # Recess Boundary Handling
                if rec and s1.end_min <= rec[0] and s2.start_min >= rec[1]:
                    # Pre-recess: extend s1 to touch rec[0]
                    if s1.end_min < rec[0] and not s1.is_fixed and not is_test1:
                        cur_dur = s1.end_min - s1.start_min
                        gap = rec[0] - s1.end_min
                        if cur_dur + gap <= 90:
                            fl1 = fac_events.get((f1, d), [])
                            next_f1 = min((x for x in fl1 if x != s1 and x.start_min >= s1.end_min), key=lambda x: x.start_min, default=None)
                            tt1 = travel_time.get((s1.center, next_f1.center), 30) if (next_f1 and s1.center != next_f1.center) else 0
                            if (next_f1 is None) or (rec[0] + tt1 <= next_f1.start_min):
                                if check_fac_allowed_bounds(f1, d, s1.start_min, rec[0], loader):
                                    s1.end_min = rec[0]
                                    if f1 in fac_sched: fac_sched[f1] += gap
                                    iter_closed += 1
                                    closed_gaps_count += 1

                    # Post-recess: shift s2 earlier to touch rec[1]
                    if s2.start_min > rec[1] and not s2.is_fixed:
                        fl2 = fac_events.get((f2, d), [])
                        prev_f2 = max((x for x in fl2 if x != s2 and x.end_min <= s2.start_min), key=lambda x: x.end_min, default=None)
                        tt2 = travel_time.get((prev_f2.center, s2.center), 30) if (prev_f2 and prev_f2.center != s2.center) else 0
                        if (prev_f2 is None) or (prev_f2.end_min + tt2 <= rec[1]):
                            shift_m = s2.start_min - rec[1]
                            if check_fac_allowed_bounds(f2, d, rec[1], rec[1] + dur2, loader) and \
                               check_fac_no_overlap(f2, d, s2, rec[1], rec[1] + dur2, all_scheduled_slots, travel_time):
                                s2.start_min = rec[1]
                                s2.end_min = rec[1] + dur2
                                iter_closed += 1
                                closed_gaps_count += 1
                    continue

                # Direct Gap Handling
                gap = s2.start_min - s1.end_min
                is_eve = b_info and (b_info.earliest_start_min >= 840 or "EVE" in s1.batch_name or s1.start_min >= 840)
                max_gap_allowed = 180 if is_eve else 45

                if 0 < gap <= max_gap_allowed:
                    # Test Handling (Tests are 60m and can shift within batch hours)
                    if is_test1 and not (is_eve and i == 0):
                        target_et = s2.start_min
                        target_st = target_et - 60
                        prev_b = slist[i - 1] if i > 0 else None
                        min_allowed = prev_b.end_min if prev_b else day_es
                        if target_st >= min_allowed and target_et <= day_le:
                            s1.start_min = target_st
                            s1.end_min = target_et
                            iter_closed += 1
                            closed_gaps_count += 1
                            continue

                    if is_test2:
                        target_st = s1.end_min
                        target_et = target_st + 60
                        next_b = slist[i + 2] if i + 2 < len(slist) else None
                        max_allowed = next_b.start_min if next_b else day_le
                        if target_et <= max_allowed and target_st >= day_es:
                            s2.start_min = target_st
                            s2.end_min = target_et
                            iter_closed += 1
                            closed_gaps_count += 1
                            continue

                    # Regular Lecture Option 1: Shift s2 earlier to touch s1
                    if not s2.is_fixed and not is_test2:
                        target_st = s1.end_min
                        target_et = target_st + dur2
                        if target_st >= day_es and target_et <= day_le:
                            if check_fac_allowed_bounds(f2, d, target_st, target_et, loader) and \
                               check_fac_no_overlap(f2, d, s2, target_st, target_et, all_scheduled_slots, travel_time):
                                s2.start_min = target_st
                                s2.end_min = target_et
                                iter_closed += 1
                                closed_gaps_count += 1
                                continue

                    # Regular Lecture Option 2: Shift s1 forward to touch s2 (never shift slot 0 in evening batches)
                    if not s1.is_fixed and not is_test1 and not (is_eve and i == 0):
                        dur1 = s1.end_min - s1.start_min
                        target_et = s2.start_min
                        target_st = target_et - dur1
                        prev_b = slist[i - 1] if i > 0 else None
                        min_allowed = prev_b.end_min if prev_b else day_es
                        if target_st >= min_allowed and target_et <= day_le:
                            if check_fac_allowed_bounds(f1, d, target_st, target_et, loader) and \
                               check_fac_no_overlap(f1, d, s1, target_st, target_et, all_scheduled_slots, travel_time):
                                s1.start_min = target_st
                                s1.end_min = target_et
                                iter_closed += 1
                                closed_gaps_count += 1
                                continue

                    # Regular Lecture Option 3: Extend s1 forward to touch s2
                    if not s1.is_fixed and not is_test1:
                        cur_dur = s1.end_min - s1.start_min
                        if cur_dur + gap <= 95:
                            if check_fac_allowed_bounds(f1, d, s1.start_min, s2.start_min, loader) and \
                               check_fac_no_overlap(f1, d, s1, s1.start_min, s2.start_min, all_scheduled_slots, travel_time):
                                s1.end_min = s2.start_min
                                if f1 in fac_sched: fac_sched[f1] += gap
                                iter_closed += 1
                                closed_gaps_count += 1
                                continue

                    # Regular Lecture Option 4: Extend s2 backward to touch s1
                    if not s2.is_fixed and not is_test2:
                        cur_dur = s2.end_min - s2.start_min
                        if cur_dur + gap <= 95:
                            if check_fac_allowed_bounds(f2, d, s1.end_min, s2.end_min, loader) and \
                               check_fac_no_overlap(f2, d, s2, s1.end_min, s2.end_min, all_scheduled_slots, travel_time):
                                s2.start_min = s1.end_min
                                if f2 in fac_sched: fac_sched[f2] += gap
                                iter_closed += 1
                                closed_gaps_count += 1
                                continue

                    # Regular Lecture Option 5: Chained Shift Forward (shift s0, s1 forward together)
                    if is_eve and not s1.is_fixed and not is_test1 and i > 1:
                        s0 = slist[i - 1]
                        f0 = (s0.faculty or "").strip().upper()
                        is_t0 = ("TEST" in (s0.subject or "").upper() or "TEST" in f0)
                        dur0 = s0.end_min - s0.start_min
                        dur1 = s1.end_min - s1.start_min
                        prev_prev = slist[i - 2].end_min if i > 1 else day_es
                        # Try shifting both s0 and s1 forward by gap
                        new_s1_et = s2.start_min
                        new_s1_st = new_s1_et - dur1
                        new_s0_et = new_s1_st
                        new_s0_st = new_s0_et - dur0
                        if new_s0_st >= prev_prev and new_s1_et <= day_le:
                            f0_ok = (is_t0 or check_fac_allowed_bounds(f0, d, new_s0_st, new_s0_et, loader)) and \
                                    (is_t0 or check_fac_no_overlap(f0, d, s0, new_s0_st, new_s0_et, all_scheduled_slots, travel_time))
                            f1_ok = check_fac_allowed_bounds(f1, d, new_s1_st, new_s1_et, loader) and \
                                    check_fac_no_overlap(f1, d, s1, new_s1_st, new_s1_et, all_scheduled_slots, travel_time)
                            if f0_ok and f1_ok:
                                s0.start_min, s0.end_min = new_s0_st, new_s0_et
                                s1.start_min, s1.end_min = new_s1_st, new_s1_et
                                iter_closed += 1
                                closed_gaps_count += 1
                                continue

        if iter_closed == 0:
            break

    print(f"Eliminated {closed_gaps_count} gaps between consecutive lectures in batch timetables.")

    # Step 4: Final Top-up to Eliminate Remaining Deficits Post-Rebalancing
    for fac, allot_m in fac_allotted_mins.items():
        cur_m = sum(s.end_min - s.start_min for s in all_scheduled_slots if s.faculty == fac and not s.is_fixed)
        if cur_m < allot_m:
            gap = allot_m - cur_m
            for s in all_scheduled_slots:
                if s.faculty == fac and not s.is_fixed and "TEST" not in (s.subject or "").upper():
                    cur_dur = s.end_min - s.start_min
                    if cur_dur < 90:
                        b_list = batch_events.get((s.center, s.batch_name, s.day), [])
                        s_idx = b_list.index(s) if s in b_list else -1
                        next_b = b_list[s_idx + 1] if (s_idx >= 0 and s_idx + 1 < len(b_list)) else None
                        b_info = loader.batches.get((s.center, s.batch_name))
                        day_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min) if b_info else 1200
                        b_room = max(0, (next_b.start_min - s.end_min) if next_b else (day_le - s.end_min))
                        rec = recess_map.get((s.center, s.batch_name))
                        if rec and s.end_min <= rec[0]:
                            b_room = max(0, min(b_room, rec[0] - s.end_min))
                        if b_room >= 5:
                            add_m = min(gap, b_room, 90 - cur_dur)
                            if check_fac_allowed_bounds(fac, s.day, s.start_min, s.end_min + add_m, loader) and \
                               check_fac_no_overlap(fac, s.day, s, s.start_min, s.end_min + add_m, all_scheduled_slots, travel_time):
                                s.end_min += add_m
                                gap -= add_m
                                if gap <= 0:
                                    break
                    if gap > 0 and cur_dur < 90:
                        prev_b = b_list[s_idx - 1] if s_idx > 0 else None
                        b_info = loader.batches.get((s.center, s.batch_name))
                        day_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min) if b_info else 420
                        b_room_before = max(0, (s.start_min - prev_b.end_min) if prev_b else (s.start_min - day_es))
                        rec = recess_map.get((s.center, s.batch_name))
                        if rec and s.start_min >= rec[1]:
                            b_room_before = max(0, min(b_room_before, s.start_min - rec[1]))
                        if b_room_before >= 5:
                            shift_m = min(gap, b_room_before, 90 - cur_dur)
                            if check_fac_allowed_bounds(fac, s.day, s.start_min - shift_m, s.end_min, loader) and \
                               check_fac_no_overlap(fac, s.day, s, s.start_min - shift_m, s.end_min, all_scheduled_slots, travel_time):
                                s.start_min -= shift_m
                                gap -= shift_m
                                if gap <= 0:
                                    break

    # F. Universal Safety Check: Guarantee EVERY regular non-fixed lecture is >= 50 minutes
    batch_events = {}
    for s in all_scheduled_slots:
        batch_events.setdefault((s.center, s.batch_name, s.day), []).append(s)
    for k in batch_events:
        batch_events[k].sort(key=lambda x: x.start_min)

    for s in all_scheduled_slots:
        if s.is_fixed or "TEST" in (s.subject or "").upper():
            continue
        r = get_req(s.center, s.batch_name, s.subject, s.faculty)
        nom_req_dur = r.daily_duration_min if r else 60
        min_dur = 45 if (s.center == "THS" or nom_req_dur <= 45) else 50
        dur = s.end_min - s.start_min
        if dur < min_dur:
            deficit_m = min_dur - dur
            b_list = batch_events.get((s.center, s.batch_name, s.day), [])
            s_idx = b_list.index(s) if s in b_list else -1
            next_b = b_list[s_idx + 1] if (s_idx >= 0 and s_idx + 1 < len(b_list)) else None
            b_info = loader.batches.get((s.center, s.batch_name))
            day_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min) if b_info else 1200
            room_after = (next_b.start_min - s.end_min) if next_b else (day_le - s.end_min)
            rec = recess_map.get((s.center, s.batch_name))
            if rec and s.end_min <= rec[0]:
                room_after = min(room_after, rec[0] - s.end_min)
            
            if room_after >= deficit_m:
                s.end_min += deficit_m
            else:
                prev_b = b_list[s_idx - 1] if s_idx > 0 else None
                day_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min) if b_info else 420
                room_before = (s.start_min - prev_b.end_min) if prev_b else (s.start_min - day_es)
                if rec and s.start_min >= rec[1]:
                    room_before = min(room_before, s.start_min - rec[1])
                s.start_min -= min(deficit_m, room_before)
                rem = min_dur - (s.end_min - s.start_min)
                if rem > 0 and room_after >= rem:
                    s.end_min += rem

    # Ensure 100% compliance with RULE_002 (NO_EMPTY_SLOTS): close any small remaining gaps between consecutive slots
    for (c, b), b_info in loader.batches.items():
        if b_info.earliest_start_min < 840 and "EVE" not in b:
            continue
        b_day_slots = {}
        for s in all_scheduled_slots:
            if s.center == c and s.batch_name == b:
                b_day_slots.setdefault(s.day, []).append(s)
        for d, slots in b_day_slots.items():
            slots.sort(key=lambda x: x.start_min)
            for i in range(len(slots) - 1):
                s1, s2 = slots[i], slots[i + 1]
                gap = s2.start_min - s1.end_min
                if 0 < gap <= 45:
                    if "TEST" not in (s1.subject or "").upper():
                        s1.end_min = s2.start_min
                    elif "TEST" not in (s2.subject or "").upper():
                        s2.start_min = s1.end_min

    # Invariant Check: Verify all tests are strictly 60 minutes and NEVER on Monday
    test_errs = 0
    monday_test_errs = 0
    for s in all_scheduled_slots:
        if "TEST" in (s.subject or "").upper() or "TEST" in (s.faculty or "").upper():
            dur = s.end_min - s.start_min
            if dur != 60:
                test_errs += 1
                print(f"  [TEST ERROR] {s.center} {s.batch_name} {s.day}: duration = {dur}m (must be 60m)")
            if s.day == "MONDAY":
                monday_test_errs += 1
                print(f"  [MONDAY TEST ERROR] {s.center} {s.batch_name} has a test on MONDAY ({s.start_min}-{s.end_min})")
    assert test_errs == 0, f"Found {test_errs} tests with duration != 60 minutes!"
    assert monday_test_errs == 0, f"Found {monday_test_errs} tests scheduled on MONDAY! No tests allowed on Monday."

    # Invariant Check: Verify no regular non-fixed lecture is < 50 minutes (45m for THS school periods)
    short_errs = 0
    for s in all_scheduled_slots:
        if not s.is_fixed and "TEST" not in (s.subject or "").upper():
            r = get_req(s.center, s.batch_name, s.subject, s.faculty)
            nom_req_dur = r.daily_duration_min if r else 60
            min_dur = 45 if (s.center == "THS" or nom_req_dur <= 45) else 50
            dur = s.end_min - s.start_min
            if dur < min_dur:
                short_errs += 1
                print(f"  [SHORT ERROR] {s.center} {s.batch_name} {s.day}: {s.subject} ({s.faculty}) duration = {dur}m (< {min_dur}m)")
    assert short_errs == 0, f"Found {short_errs} regular lectures with duration < minimum allowed!"

    # Final Clamp: Ensure strictly no lecture or test exceeds batch operating hours / day latest end
    for s in all_scheduled_slots:
        b_info = loader.batches.get((s.center, s.batch_name))
        if b_info:
            d_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min)
            d_es = b_info.day_earliest_start.get(s.day, b_info.earliest_start_min)
            if s.end_min > d_le:
                excess = s.end_min - d_le
                s.end_min = d_le
                if "TEST" in (s.subject or "").upper() or "TEST" in (s.faculty or "").upper():
                    s.start_min = max(d_es, s.end_min - 60)
                else:
                    min_dur = 45 if s.center == "THS" else 50
                    if (s.end_min - s.start_min) < min_dur:
                        s.start_min = max(d_es, s.end_min - min_dur)

    # Invariant Check: Verify no lecture exceeds batch operating hours / day latest end
    le_errs = 0
    for s in all_scheduled_slots:
        b_info = loader.batches.get((s.center, s.batch_name))
        if b_info:
            d_le = b_info.day_latest_end.get(s.day, b_info.latest_end_min)
            if s.end_min > d_le:
                le_errs += 1
                print(f"  [LATEST END ERROR] {s.center} {s.batch_name} {s.day}: {s.subject} ends at {s.end_min}m (> {d_le}m)")
    assert le_errs == 0, f"Found {le_errs} lectures exceeding batch operating hours!"

    # Invariant Check: Verify strict faculty details day limits
    fac_lim_errs = 0
    for s in all_scheduled_slots:
        if not check_fac_allowed_bounds(s.faculty, s.day, s.start_min, s.end_min, loader):
            fac_lim_errs += 1
            print(f"  [FACULTY LIMIT ERROR] {s.faculty} {s.day} ({s.center} {s.batch_name}): {s.start_min}m-{s.end_min}m")
    assert fac_lim_errs == 0, f"Found {fac_lim_errs} slots violating faculty details limits!"

    # Final Audit Check
    fac_sched = {}
    for s in all_scheduled_slots:
        f = (s.faculty or "").strip().upper()
        if f and not f.startswith("TBD") and f not in ["TEST", "WEEKLY TEST", "EXAM", "SCHOOL", "VISITING"]:
            dur = s.end_min - s.start_min
            if "/" in f:
                for fn in f.split("/"):
                    fn = fn.strip()
                    if fn == "ASIF SIR": fn = "AASIF SIR"
                    fac_sched[fn] = fac_sched.get(fn, 0) + dur
            else:
                if f == "ASIF SIR": f = "AASIF SIR"
                fac_sched[f] = fac_sched.get(f, 0) + dur

    deficits = 0
    for f, allot_m in sorted(fac_allotted_mins.items()):
        act_m = fac_sched.get(f, 0)
        diff = act_m - allot_m
        if diff < 0:
            deficits += 1
            print(f"  [DEFICIT] {f:25s} | Allotted: {allot_m:4d}m ({allot_m/60:4.1f}h) | Scheduled: {act_m:4d}m ({act_m/60:4.1f}h) | Diff: {diff:+4d}m")
            for s in all_scheduled_slots:
                if (s.faculty or "").strip().upper() == f:
                    print(f"      -> {s.day:10} | {s.center:6} | {s.batch_name:15} | {s.subject:12} | {s.start_min}-{s.end_min} ({s.end_min - s.start_min}m)")
        else:
            print(f"  [OK]      {f:25s} | Allotted: {allot_m:4d}m ({allot_m/60:4.1f}h) | Scheduled: {act_m:4d}m ({act_m/60:4.1f}h) | Diff: {diff:+4d}m")

    print(f"\nFinal Zero Deficit Result: {deficits} faculties with deficit out of {len(fac_allotted_mins)} total.")
    if deficits > 0:
        print(f"  [WARNING] {deficits} faculties have deficit mins. Proceeding with export.")
    return all_scheduled_slots
