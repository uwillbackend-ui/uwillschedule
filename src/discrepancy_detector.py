import os
from typing import List, Dict, Any, Optional
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str, DAYS_OF_WEEK

def detect_discrepancies(academic_year: str = "2026-27", user_resolutions: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """
    Detects mathematical or institutional rule contradictions in the scheduling data.
    If user_resolutions are provided and resolve a discrepancy, that discrepancy is marked resolved.
    """
    data_dir = "data" if academic_year == "2026-27" else "data_2027_28"
    loader = DataLoader(data_dir)
    loader.load_all()

    discrepancies = []
    user_res = user_resolutions or {}

    # 1. Batch Operating Days vs Subject Weekly Days (e.g. 6 lectures assigned to a 5-day batch)
    for (c, b), b_info in loader.batches.items():
        op_days = b_info.operating_days
        reqs = [r for r in loader.subject_requirements if r.center == c and r.batch == b]
        for r in reqs:
            if r.weekly_days > len(op_days):
                disc_id = f"DISC_BATCH_DAYS_{c}_{b.replace(' ', '_').replace('-', '_')}_{r.subject.replace(' ', '_')}"
                discrepancies.append({
                    "id": disc_id,
                    "category": "Weekly Frequency vs Operating Days",
                    "center": c,
                    "batch": b,
                    "subject": r.subject,
                    "title": f"{c} {b}: {r.subject} Requires {r.weekly_days} Days but Batch Operates Only {len(op_days)} Days",
                    "explanation": (
                        f"At {c} center, batch '{b}' operates on {len(op_days)} days ({', '.join(op_days)}). "
                        f"However, {r.subject} is assigned {r.weekly_days} weekly lectures in 'Faculty Master'. "
                        f"Since institutional rules strictly enforce at most one lecture per day per subject, "
                        f"it is mathematically impossible to schedule {r.weekly_days} sessions within {len(op_days)} days."
                    ),
                    "options": [
                        {
                            "id": "adjust_to_operating_days",
                            "label": f"Adjust {r.subject} to {len(op_days)} lectures (1 lecture per operating day) (Recommended)",
                            "description": f"Schedules 1 high-impact session on each of the {len(op_days)} operating days, satisfying the full syllabus within standard branch operating days."
                        },
                        {
                            "id": "add_operating_day",
                            "label": "Add Monday as an active operating day for this batch",
                            "description": f"Expands the batch schedule to include Monday ({minutes_to_str(b_info.earliest_start_min)} – {minutes_to_str(b_info.latest_end_min)}) to accommodate the 6th lecture."
                        },
                        {
                            "id": "allow_two_on_one_day",
                            "label": "Allow two sessions of this subject on one operating day",
                            "description": "Permits scheduling a double period (two separate lecture slots) on one day of the week."
                        }
                    ],
                    "default_option": "adjust_to_operating_days",
                    "selected_option": user_res.get(disc_id, "adjust_to_operating_days")
                })

    # 2. Batch Capacity Deficits (Requirements + Tests + Fixed + Recesses > Available Batch Hours or Daily Slots)
    for (c, b), b_info in loader.batches.items():
        es = b_info.earliest_start_min
        le = b_info.latest_end_min
        reqs = [r for r in loader.subject_requirements if r.center == c and r.batch == b]
        if not reqs:
            continue

        fixed_m = sum((vf.end_min - vf.start_min) for vf in loader.fixed_lectures if vf.center == c and vf.batch == b)
        recess_m = 0
        for d in b_info.operating_days:
            if b_info.recess_mode == "Flexible" and b_info.recess_duration_min:
                recess_m += b_info.recess_duration_min
            elif b_info.recess_start_min and b_info.recess_end_min:
                recess_m += (b_info.recess_end_min - b_info.recess_start_min)

        tot_min_avail = 0
        max_daily_slots_total = 0
        for d in b_info.operating_days:
            d_es = b_info.day_earliest_start.get(d, es)
            d_le = b_info.day_latest_end.get(d, le)
            d_avail = (d_le - d_es)
            tot_min_avail += d_avail
            # Max 60m slots that can fit in day
            d_fixed = sum((vf.end_min - vf.start_min) for vf in loader.fixed_lectures if vf.center == c and vf.batch == b and vf.day == d)
            d_rec = b_info.recess_duration_min if b_info.recess_mode == "Flexible" else ((b_info.recess_end_min - b_info.recess_start_min) if b_info.recess_start_min else 0)
            d_net = d_avail - d_fixed - d_rec
            max_daily_slots_total += max(0, d_net // 60)

        tot_min_needed = sum(r.weekly_days * r.daily_duration_min for r in reqs)
        # Tests: 2 weekly tests for non-B.COM and non-PNG MRG batches
        has_tests = ("B.COM" not in b and not (c == "PNG" and "MRG" in b))
        test_min = 120 if has_tests else 0
        test_count = 2 if has_tests else 0

        tot_min_with_all = tot_min_needed + test_min + fixed_m + recess_m
        time_deficit = tot_min_with_all - tot_min_avail

        tot_sessions = sum(r.weekly_days for r in reqs) + test_count
        slot_deficit = tot_sessions - max_daily_slots_total

        if time_deficit > 0 or slot_deficit > 0:
            disc_id = f"DISC_BATCH_CAPACITY_{c}_{b.replace(' ', '_').replace('-', '_')}"
            tot_lec_count = sum(r.weekly_days for r in reqs)
            deficit_desc = f"{time_deficit} minutes" if time_deficit > 0 else f"{slot_deficit} slot(s)"

            explanation = (
                f"At {c} center, batch '{b}' requires {tot_lec_count} lectures ({tot_min_needed} mins)"
                f"{f' plus {test_count} weekly tests ({test_min} mins)' if test_count else ''}"
                f"{f' plus fixed school periods ({fixed_m} mins)' if fixed_m else ''}"
                f"{f' and daily recesses ({recess_m} mins)' if recess_m else ''}, totaling {tot_min_with_all} mins. "
                f"However, the batch operating hours provide only {tot_min_avail} mins across the week "
                f"(maximum {max_daily_slots_total} discrete 60-minute slots across operating days), "
                f"resulting in a mathematical deficit of {deficit_desc}."
            )

            options = [
                {
                    "id": "extend_hours",
                    "label": "Extend batch operating hours to fit all sessions (Recommended)",
                    "description": f"Expands the batch daily/Saturday window so all {tot_sessions} sessions fit cleanly without cutting any classes."
                },
                {
                    "id": "reduce_days",
                    "label": "Balance subject frequencies to match available batch capacity",
                    "description": "Adjusts core subjects by 1 session each to match the batch's current operating window exactly."
                },
                {
                    "id": "reduce_tests",
                    "label": "Conduct 1 weekly test instead of 2 tests",
                    "description": "Saves 60 minutes each week by scheduling 1 comprehensive test instead of 2."
                }
            ]
            if c == "BRIGHT":
                options[0] = {
                    "id": "subject_rules_and_tests",
                    "label": "Enforce Subject Rules frequency (Accounts 4d, Eco 2d, BST 2d, Stats 2d + 2 tests) (Recommended)",
                    "description": "Aligns with Bright School's 12 available slots so all curriculum lectures and weekly tests fit exactly."
                }

            discrepancies.append({
                "id": disc_id,
                "category": "Batch Capacity Deficit",
                "center": c,
                "batch": b,
                "title": f"{c} {b}: Required Sessions Exceed Batch Capacity ({deficit_desc} deficit)",
                "explanation": explanation,
                "options": options,
                "default_option": options[0]["id"],
                "selected_option": user_res.get(disc_id, options[0]["id"])
            })

    # 3. Block 2 Consistency vs Shift Change on Saturday (e.g. PNG GSEB MRG)
    for (c, b), b_info in loader.batches.items():
        es = b_info.earliest_start_min
        op_days = b_info.operating_days
        if "THURSDAY" in op_days and "SATURDAY" in op_days:
            thu_es = b_info.day_earliest_start.get("THURSDAY", es)
            sat_es = b_info.day_earliest_start.get("SATURDAY", es)
            if abs(thu_es - sat_es) >= 180:
                disc_id = f"DISC_BLOCK_SHIFT_{c}_{b.replace(' ', '_').replace('-', '_')}"
                discrepancies.append({
                    "id": disc_id,
                    "category": "Operating Shift vs Block Consistency",
                    "center": c,
                    "batch": b,
                    "title": f"{c} {b}: Morning vs Afternoon Shift Contradicts Thu-Sat Consistency",
                    "explanation": (
                        f"At {c} center, batch '{b}' operates in the morning on Thursday and Friday "
                        f"({minutes_to_str(thu_es)}), but shifts to an afternoon window on Saturday ({minutes_to_str(sat_es)}). "
                        f"Standing institutional rules require Thursday, Friday, and Saturday (Block 2) to maintain identical "
                        f"lecture start times. It is mathematically impossible for a lecture starting at {minutes_to_str(thu_es)} "
                        f"on Thursday to also start at {minutes_to_str(thu_es)} on Saturday when the center does not open until {minutes_to_str(sat_es)}."
                    ),
                    "options": [
                        {
                            "id": "exempt_saturday",
                            "label": "Enforce consistency on Thu-Fri, allow Saturday flexible timing (Recommended)",
                            "description": "Maintains identical start times and durations between Thursday and Friday, while allowing Saturday afternoon slots to be scheduled flexibly within its afternoon hours."
                        },
                        {
                            "id": "unify_morning",
                            "label": f"Shift Saturday hours to morning ({minutes_to_str(thu_es)})",
                            "description": f"Standardizes Saturday operating hours to match Thursday & Friday morning ({minutes_to_str(thu_es)} start), achieving 100% Thu-Sat uniformity."
                        },
                        {
                            "id": "separate_schedule",
                            "label": "Treat Saturday as an independent test/revision day",
                            "description": "Schedules regular curriculum lectures on Thu-Fri with full consistency, and reserves Saturday strictly for weekly tests and special sessions."
                        }
                    ],
                    "default_option": "exempt_saturday",
                    "selected_option": user_res.get(disc_id, "exempt_saturday")
                })

    # 4. Kautik Sir Morning Window
    kautik_restr = loader.faculties.get("KAUTIK SIR")
    if kautik_restr and kautik_restr.day_limits:
        mrg_from = kautik_restr.day_limits.get("MONDAY", {}).get("mrg_from")
        if mrg_from and mrg_from >= 600:
            kautik_mrg_reqs = [
                r for r in loader.subject_requirements
                if "KAUTIK" in (r.faculty or "").upper() and loader.batches.get((r.center, r.batch)) and loader.batches[(r.center, r.batch)].earliest_start_min < 840
            ]
            if kautik_mrg_reqs:
                disc_id = "DISC_KAUTIK_SIR_MORNING_WINDOW"
                tot_sessions = sum(r.weekly_days for r in kautik_mrg_reqs)
                batch_names = list(set(f"{r.center} {r.batch}" for r in kautik_mrg_reqs))
                discrepancies.append({
                    "id": disc_id,
                    "category": "Faculty Availability Window",
                    "faculty": "KAUTIK SIR",
                    "title": "Kautik Sir Morning Availability Starts After Batch Opening",
                    "explanation": (
                        f"In 'Faculty Details', Kautik Sir's morning availability begins at {minutes_to_str(mrg_from)} (10:00 AM). "
                        f"However, he is assigned {tot_sessions} morning lectures across {len(batch_names)} batches "
                        f"({', '.join(batch_names[:3])}{'...' if len(batch_names) > 3 else ''}) that operate starting at 8:00 AM or 9:00 AM. "
                        f"Starting at {minutes_to_str(mrg_from)} leaves only 2.5 hours before batch closing, making it impossible "
                        f"to schedule all assigned morning sessions without starting earlier."
                    ),
                    "options": [
                        {
                            "id": "allow_9am",
                            "label": "Allow Kautik Sir morning lectures to start from 9:00 AM (Recommended)",
                            "description": "Adjusts Kautik Sir's morning start availability to 9:00 AM so his assigned B.COM and Flexi morning sessions can be scheduled cleanly."
                        },
                        {
                            "id": "compress_to_60m",
                            "label": "Keep 10:00 AM start and compress lecture durations to 60 mins",
                            "description": "Maintains strict 10:00 AM start and compresses sessions into 60-minute slots between 10:00 AM and 12:30 PM."
                        },
                        {
                            "id": "reassign_backup",
                            "label": "Reassign early morning sessions (< 10:00 AM) to Backup Faculty",
                            "description": "Keeps Kautik Sir strictly after 10:00 AM and assigns any lectures requiring earlier start times to visiting/backup faculty."
                        }
                    ],
                    "default_option": "allow_9am",
                    "selected_option": user_res.get(disc_id, "allow_9am")
                })

    # 5. Vicky Sir evening window at VB
    vicky_restr = loader.faculties.get("VICKY SIR")
    if vicky_restr and vicky_restr.day_limits:
        eve_to = vicky_restr.day_limits.get("MONDAY", {}).get("eve_to")
        if eve_to and eve_to <= 1110:
            vicky_vb_eve = [
                r for r in loader.subject_requirements
                if "VICKY" in (r.faculty or "").upper() and r.center == "VB" and "12TH GSEB" in r.batch
            ]
            if vicky_vb_eve:
                disc_id = "DISC_VICKY_SIR_VB_EVENING"
                discrepancies.append({
                    "id": disc_id,
                    "category": "Faculty Availability Window",
                    "faculty": "VICKY SIR",
                    "title": "Vicky Sir Evening Availability Cutoff at VB Center",
                    "explanation": (
                        f"In 'Faculty Details', Vicky Sir's evening availability ends at {minutes_to_str(eve_to)} (6:30 PM). "
                        f"At VB Center, the 12th GSEB evening batch operates until 7:10 PM / 7:30 PM. "
                        f"If Vicky Sir is assigned to the second lecture of the evening block, it extends until ~7:10 PM, "
                        f"exceeding his configured 6:30 PM departure limit by ~40 minutes."
                    ),
                    "options": [
                        {
                            "id": "extend_to_710pm",
                            "label": "Allow Vicky Sir's VB evening lecture to conclude by 7:10 PM (Recommended)",
                            "description": "Permits his evening departure at VB center to extend to 7:10 PM so the full evening curriculum can be delivered."
                        },
                        {
                            "id": "first_slot_only",
                            "label": "Pin Vicky Sir to the first evening slot (ends by 6:00 PM)",
                            "description": "Strictly places Vicky Sir in slot 1 (4:30 PM – 5:50 PM), leaving the second slot (5:50 PM – 7:10 PM) for other faculties."
                        },
                        {
                            "id": "reassign_vb_eve",
                            "label": "Reassign VB 12th GSEB evening Statistics to Backup Faculty",
                            "description": "Leaves Vicky Sir's schedule free of the VB evening slot and assigns it to backup faculty."
                        }
                    ],
                    "default_option": "extend_to_710pm",
                    "selected_option": user_res.get(disc_id, "extend_to_710pm")
                })

    # 6. Manish Sir B.COM 90m duration vs batch operating window
    manish_reqs = [
        r for r in loader.subject_requirements
        if "MANISH" in (r.faculty or "").upper() and "B.COM" in r.batch and r.daily_duration_min >= 85
    ]
    if manish_reqs:
        disc_id = "DISC_MANISH_SIR_BCOM_DURATION"
        discrepancies.append({
            "id": disc_id,
            "category": "Lecture Duration vs Batch Window",
            "faculty": "MANISH SIR",
            "title": "Manish Sir B.COM 90-Minute Nominal Duration vs 60-Minute Batch Window",
            "explanation": (
                "In 'Subject Rules', Manish Sir's B.COM Corporate Accounting lectures specify a 90-minute nominal duration. "
                "However, the available morning operating window for OP & PNG SY B.COM is 11:30 AM to 12:30 PM (60 minutes). "
                "Enforcing a strict 90-minute session causes the lecture to breach the batch's 12:30 PM closing time by 30 minutes."
            ),
            "options": [
                {
                    "id": "allow_60m",
                    "label": "Allow 60-minute lecture duration for B.COM morning sessions (Recommended)",
                    "description": "Fits Manish Sir's B.COM sessions perfectly into the 11:30 AM – 12:30 PM slot without altering branch hours."
                },
                {
                    "id": "extend_batch_to_1pm",
                    "label": "Extend batch closing time to 1:00 PM on lecture days",
                    "description": "Extends the SY B.COM batch hours to 1:00 PM to give Manish Sir a full 90-minute teaching window."
                },
                {
                    "id": "split_into_two",
                    "label": "Split into two 45-minute sessions across the week",
                    "description": "Keeps total teaching time unchanged by dividing the syllabus into two 45-minute lecture slots."
                }
            ],
            "default_option": "allow_60m",
            "selected_option": user_res.get(disc_id, "allow_60m")
        })

    return discrepancies

def apply_resolutions_to_loader(loader: DataLoader, resolutions: Optional[Dict[str, str]] = None) -> None:
    """
    Applies the user-chosen resolution decisions directly to the DataLoader instances
    (batches, subject requirements, faculty availability windows) before timetable generation.
    """
    if not resolutions:
        # Default all detected discrepancies to their recommended default options
        discs = detect_discrepancies(loader.data_dir.split('_')[-1] if '_' in loader.data_dir else "2026-27")
        resolutions = {d["id"]: d["default_option"] for d in discs}

    for disc_id, choice in resolutions.items():
        # 1. VB 12th CBSE Flexi Accounts frequency vs operating days
        if "DISC_BATCH_DAYS_VB" in disc_id and "ACCOUNTS" in disc_id:
            if choice == "adjust_to_operating_days":
                for r in loader.subject_requirements:
                    if r.center == "VB" and r.batch == "12TH CBSE (FLEXI)" and "ACCOUNTS" in r.subject:
                        r.weekly_days = 5
                        r.weekly_hours = round(r.weekly_days * r.daily_duration_min / 60.0, 2)
            elif choice == "add_operating_day":
                b_info = loader.batches.get(("VB", "12TH CBSE (FLEXI)"))
                if b_info and "MONDAY" not in b_info.operating_days:
                    b_info.operating_days.insert(0, "MONDAY")
            elif choice == "allow_two_on_one_day":
                for r in loader.subject_requirements:
                    if r.center == "VB" and r.batch == "12TH CBSE (FLEXI)" and "ACCOUNTS" in r.subject:
                        r.max_per_day = 2

        # 2. BRIGHT 11th CBSE Capacity Deficit
        elif "DISC_BATCH_CAPACITY_BRIGHT_11TH_CBSE" in disc_id:
            if choice in ["subject_rules_and_tests", "reduce_days"]:
                for r in loader.subject_requirements:
                    if r.center == "BRIGHT":
                        if "ACCOUNTS" in r.subject:
                            r.weekly_days = 4
                            r.weekly_hours = round(r.weekly_days * r.daily_duration_min / 60.0, 2)
                        elif "ECONOMICS" in r.subject:
                            r.weekly_days = 2
                            r.weekly_hours = round(r.weekly_days * r.daily_duration_min / 60.0, 2)
                        elif "BUSINESS" in r.subject:
                            r.weekly_days = 2
                            r.weekly_hours = round(r.weekly_days * r.daily_duration_min / 60.0, 2)
            elif choice == "reduce_tests":
                for r in loader.subject_requirements:
                    if r.center == "BRIGHT" and "ACCOUNTS" in r.subject:
                        r.weekly_days = 4
                        r.weekly_hours = round(r.weekly_days * r.daily_duration_min / 60.0, 2)
            elif choice == "extend_hours":
                for b_name in ["11TH CBSE - B", "11TH CBSE - C"]:
                    b_info = loader.batches.get(("BRIGHT", b_name))
                    if b_info:
                        b_info.latest_end_min = max(b_info.latest_end_min, 840)

        # 3. OP 11th GSEB Capacity Deficit
        elif "DISC_BATCH_CAPACITY_OP_11TH_GSEB" in disc_id:
            if choice == "extend_hours":
                b_op11 = loader.batches.get(("OP", "11TH GSEB"))
                if b_op11:
                    b_op11.latest_end_min = max(b_op11.latest_end_min, 1200)
                    for d in b_op11.operating_days:
                        b_op11.day_latest_end[d] = max(b_op11.day_latest_end.get(d, 0), 1200)
            elif choice in ["reduce_days", "reduce_tests"]:
                for r in loader.subject_requirements:
                    if r.center == "OP" and r.batch == "11TH GSEB" and "ACCOUNTS" in r.subject:
                        r.weekly_days = 4
                        r.weekly_hours = round(r.weekly_days * r.daily_duration_min / 60.0, 2)

        # 4. PNG 12th GSEB MRG Saturday hours
        elif "DISC_BATCH_CAPACITY_PNG_12TH_GSEB" in disc_id:
            if choice == "extend_hours":
                b_png12 = loader.batches.get(("PNG", "12TH GSEB - MRG"))
                if b_png12:
                    b_png12.day_latest_end["SATURDAY"] = 1080 # 6:00 PM
                    b_png12.latest_end_min = max(b_png12.latest_end_min, 1080)

        # 5. PNG Block Shift
        elif "DISC_BLOCK_SHIFT_PNG" in disc_id:
            if choice == "unify_morning":
                batch_name = "11TH GSEB - MRG" if "11TH" in disc_id else "12TH GSEB - MRG"
                b_info = loader.batches.get(("PNG", batch_name))
                if b_info:
                    thu_es = b_info.day_earliest_start.get("THURSDAY", 450)
                    b_info.day_earliest_start["SATURDAY"] = thu_es

        # 6. Kautik Sir morning window
        elif disc_id == "DISC_KAUTIK_SIR_MORNING_WINDOW":
            if choice == "allow_9am":
                kautik = loader.faculties.get("KAUTIK SIR")
                if kautik and kautik.day_limits:
                    for d, lim in kautik.day_limits.items():
                        if lim.get("mrg_from") and lim["mrg_from"] > 540:
                            lim["mrg_from"] = 540
            elif choice == "compress_to_60m":
                for r in loader.subject_requirements:
                    if "KAUTIK" in (r.faculty or "").upper() and loader.batches.get((r.center, r.batch)) and loader.batches[(r.center, r.batch)].earliest_start_min < 840:
                        r.daily_duration_min = 60
            elif choice == "reassign_backup":
                for r in loader.subject_requirements:
                    if "KAUTIK" in (r.faculty or "").upper() and loader.batches.get((r.center, r.batch)) and loader.batches[(r.center, r.batch)].earliest_start_min < 600:
                        r.faculty = "BACKUP FACULTY"

        # 7. Vicky Sir evening VB departure
        elif disc_id == "DISC_VICKY_SIR_VB_EVENING":
            if choice == "extend_to_710pm":
                vicky = loader.faculties.get("VICKY SIR")
                if vicky and vicky.day_limits:
                    for d, lim in vicky.day_limits.items():
                        if lim.get("eve_to") and lim["eve_to"] < 1150:
                            lim["eve_to"] = 1150
            elif choice == "reassign_vb_eve":
                for r in loader.subject_requirements:
                    if "VICKY" in (r.faculty or "").upper() and r.center == "VB" and "12TH GSEB" in r.batch:
                        r.faculty = "BACKUP FACULTY"

        # 8. Manish Sir B.COM duration
        elif disc_id == "DISC_MANISH_SIR_BCOM_DURATION":
            if choice in ["allow_60m", "split_into_two"]:
                for r in loader.subject_requirements:
                    if "MANISH" in (r.faculty or "").upper() and "B.COM" in r.batch:
                        r.daily_duration_min = 60 if choice == "allow_60m" else 45
            elif choice == "extend_batch_to_1pm":
                for b_key in [("OP", "SY B.COM"), ("PNG", "SY B.COM")]:
                    b_info = loader.batches.get(b_key)
                    if b_info:
                        b_info.latest_end_min = max(b_info.latest_end_min, 780)
                        for d in b_info.operating_days:
                            b_info.day_latest_end[d] = max(b_info.day_latest_end.get(d, 0), 780)

