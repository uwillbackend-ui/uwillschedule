import sys, os, json, shutil
sys.path.insert(0, os.path.abspath("."))
import time
from typing import Dict, List
from ortools.sat.python import cp_model

from src.models import ScheduledSlot
from src.data_loader import DataLoader, DAYS_OF_WEEK, minutes_to_str
from src.formatter import TimetableFormatter
from src.pdf_generator import TimetablePDFGenerator
from src.excel_exporter import ExcelExporter

BLOCK_1 = ["MONDAY", "TUESDAY", "WEDNESDAY"]
BLOCK_2 = ["THURSDAY", "FRIDAY", "SATURDAY"]

def run_schedule_generation(sync_first: bool = True, academic_year: str = "2026-27", data_dir: str = None, resolutions: Dict[str, str] = None):
    global assumptions
    assumptions = {}
    print("=" * 65)
    print(f"UNIFIED GLOBAL AI TIMETABLE GENERATOR - ACADEMIC YEAR [{academic_year}]")
    print("Enforcing Zero Overlaps | 45m Travel Buffers | Mon-Wed & Thu-Sat Consistency")
    print("Enforcing 2 Weekly Tests per Batch (Exactly 1h, >= 1 Day Gap, Within Branch Limits)")
    print("=" * 65)

    if not data_dir:
        if sync_first:
            try:
                import sync_from_google_sheets
                data_dir = sync_from_google_sheets.sync_data(academic_year=academic_year)
            except Exception as e:
                print(f"[SYNC NOTE] Could not auto-sync live from Google Sheets: {e}. Using cached data.")
                import sync_from_google_sheets
                data_dir = sync_from_google_sheets.get_data_dir(academic_year=academic_year)
        else:
            import sync_from_google_sheets
            data_dir = sync_from_google_sheets.get_data_dir(academic_year=academic_year)

    loader = DataLoader(data_dir or "data")
    loader.load_all()

    # Load / Apply Discrepancy Resolutions chosen by user (or default institutional recommendations)
    if resolutions is None:
        res_file = f"output/resolutions_{academic_year}.json"
        if os.path.exists(res_file):
            try:
                with open(res_file, "r") as f:
                    resolutions = json.load(f)
            except Exception:
                resolutions = None
    if not resolutions:
        from src.discrepancy_detector import detect_discrepancies
        discs = detect_discrepancies(academic_year=academic_year)
        resolutions = {d["id"]: d["default_option"] for d in discs}

    os.makedirs("output", exist_ok=True)
    try:
        with open(f"output/resolutions_{academic_year}.json", "w") as f:
            json.dump(resolutions, f, indent=2)
    except Exception:
        pass

    from src.discrepancy_detector import apply_resolutions_to_loader
    apply_resolutions_to_loader(loader, resolutions)

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

    model = cp_model.CpModel()

    batch_day_intervals = {}
    fac_day_items = {}
    batch_altered_vars = {}
    all_lecture_vars = []
    block_consistency_vars = []
    balance_penalties = []

    # Sample dates
    sample_dates = {
        "MONDAY": "05/10/2026",
        "TUESDAY": "06/10/2026",
        "WEDNESDAY": "07/10/2026",
        "THURSDAY": "08/10/2026",
        "FRIDAY": "09/10/2026",
        "SATURDAY": "10/10/2026"
    }

    # 1. RECESS (FIXED & FLEXIBLE)
    flexible_recess_vars = {}
    for (c, b), b_info in loader.batches.items():
        if b_info.recess_mode == "Flexible" and b_info.recess_earliest_start_min is not None and b_info.recess_latest_end_min is not None:
            dur = b_info.recess_duration_min or 30
            es_rec = b_info.recess_earliest_start_min
            le_rec = b_info.recess_latest_end_min

            max_steps = (le_rec - dur - es_rec) // 5
            rec_step = model.NewIntVar(0, max_steps, f"rec_step_{c}_{b}")
            rec_st = model.NewIntVar(es_rec, le_rec - dur, f"rec_st_{c}_{b}")
            model.Add(rec_st == es_rec + rec_step * 5)

            rec_end = model.NewIntVar(es_rec + dur, le_rec, f"rec_end_{c}_{b}")
            model.Add(rec_end == rec_st + dur)

            for d in b_info.operating_days:
                r_iv = model.NewIntervalVar(rec_st, dur, rec_end, f"rec_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

            flexible_recess_vars[(c, b)] = (rec_st, rec_end)
        elif b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            rdur = ret - rst
            for d in b_info.operating_days:
                r_iv = model.NewFixedSizeIntervalVar(rst, rdur, f"rec_{c}_{b}_{d}")
                batch_day_intervals.setdefault(((c, b), d), []).append(r_iv)

    # 2. FIXED VISITING FACULTY
    fixed_slots = []
    for vf in loader.fixed_lectures:
        vf_dur = vf.end_min - vf.start_min
        if vf_dur <= 0: continue
        vf_iv = model.NewFixedSizeIntervalVar(vf.start_min, vf_dur, f"vf_{vf.center}_{vf.batch}_{vf.day}_{vf.start_min}")
        batch_day_intervals.setdefault(((vf.center, vf.batch), vf.day), []).append(vf_iv)
        vf_fac = (vf.faculty or "").strip().upper()
        fac_list = [f.strip() for f in vf_fac.split("/")] if "/" in vf_fac else [vf_fac]
        for fn in fac_list:
            if fn == "ASIF SIR": fn = "AASIF SIR"
            if fn in loader.faculties:
                is_mrg = vf.start_min < 840
                fac_day_items.setdefault((fn, vf.day), []).append({
                    "start": model.NewConstant(vf.start_min),
                    "end": model.NewConstant(vf.end_min),
                    "center": vf.center,
                    "batch": vf.batch,
                    "subj": (vf.subject or "").upper(),
                    "inst": 0,
                    "active": model.NewConstant(1),
                    "is_fixed": True,
                    "is_morning": is_mrg
                })
        fixed_slots.append(ScheduledSlot(
            batch_key=f"{vf.center}_{vf.batch}",
            center=vf.center,
            batch_name=vf.batch,
            day=vf.day,
            start_min=vf.start_min,
            end_min=vf.end_min,
            subject=vf.subject,
            faculty=vf.faculty,
            is_fixed=True,
            chapter="School Topic",
            topic="Regular Syllabus"
        ))

    # 3. REGULAR SUBJECT REQUIREMENTS
    req_by_batch = {}
    for req in loader.subject_requirements:
        req_by_batch.setdefault((req.center, req.batch), []).append(req)

    for (c, b), reqs in req_by_batch.items():
        b_info = loader.batches.get((c, b))
        if not b_info:
            c_norm = c.strip().upper()
            b_norm = b.strip().upper()
            for (bc, bb), info in loader.batches.items():
                if bc.strip().upper() == c_norm and bb.strip().upper() == b_norm:
                    b_info = info
                    break
        if not b_info:
            continue

        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        branch_le = branch_hours[c][1]
        max_batch_le = le
        batch_altered_vars[(c, b)] = []
        batch_3day_b1_vars = []

        for req in reqs:
            nom_dur = req.daily_duration_min

            fac_upper = (req.faculty or "").strip().upper()
            if academic_year == "2027-28":
                if fac_upper == "VIJAY SIR":
                    dur_options = [75]
                elif fac_upper == "KHYATI MADAM":
                    dur_options = [75] if nom_dur >= 70 else [60]
                elif any(fn in fac_upper for fn in ["MANSI", "NAMRATA", "SUNIL", "TRUPTI", "RAMESH", "ARJITA", "PRIYANKA", "VISHAL"]):
                    dur_options = [60]
                elif req.daily_duration_min == 90:
                    dur_options = [60, 75, 90]
                elif fac_upper == "VICKY SIR" and c == "AMBE MANJ":
                    dur_options = [60]
                elif fac_upper == "KAILASH SIR" and c in ["AMBE MANJ", "DAPS", "THS"]:
                    dur_options = [60]
                elif fac_upper == "SAGAR SIR" and c == "OP":
                    dur_options = [75]
                elif fac_upper == "KANAKLATA MADAM":
                    dur_options = [nom_dur] if nom_dur <= 50 else [60]
                elif fac_upper == "MOHSIN SIR":
                    dur_options = [90] if nom_dur >= 85 else ([60, 75] if (c == "THS" or nom_dur >= 70) else [60])
                else:
                    dur_options = [nom_dur - 15, nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
                    min_allowed = 50 if c != "THS" else 45
                    dur_options = [d for d in dur_options if min_allowed <= d <= 120]
                    if not dur_options: dur_options = [max(min_allowed, nom_dur)]
            else: # 2026-27
                if fac_upper == "MANISH SIR":
                    dur_options = [60, 75, 90] if nom_dur >= 85 else [60]
                elif fac_upper == "VIJAY SIR":
                    dur_options = [75]
                elif req.daily_duration_min == 90:
                    dur_options = [60, 75, 90]
                elif fac_upper == "VICKY SIR" and c == "AMBE MANJ":
                    dur_options = [60]
                elif fac_upper == "KAILASH SIR" and c == "AMBE MANJ":
                    dur_options = [60]
                elif fac_upper == "KAILASH SIR" and c == "DAPS" and "12TH" in b:
                    dur_options = [60]
                elif fac_upper == "KAILASH SIR" and c == "THS":
                    dur_options = [60]
                elif fac_upper == "SAGAR SIR" and c == "OP":
                    dur_options = [75]
                elif any(fn in fac_upper for fn in ["MANSI", "NAMRATA", "SUNIL", "TRUPTI", "RAMESH", "ARJITA"]):
                    dur_options = [60]
                elif fac_upper == "KANAKLATA MADAM":
                    dur_options = [nom_dur] if nom_dur <= 50 else [60]
                elif fac_upper == "MOHSIN SIR":
                    dur_options = [90] if nom_dur >= 85 else ([60, 75] if (c == "THS" or nom_dur >= 70) else [60])
                elif fac_upper == "SUKETU SIR" and c == "SUB":
                    dur_options = [60]
                else:
                    dur_options = [nom_dur - 15, nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
                    min_allowed = 50 if c != "THS" else 45
                    dur_options = [d for d in dur_options if min_allowed <= d <= 120]
                    if not dur_options: dur_options = [max(min_allowed, nom_dur)]

            w_days = min(req.weekly_days, len(op_days))
            if w_days <= 0: w_days = 1

            # Day-Block affinity: if w_days == 3, group into Block 1 (MTW) or Block 2 (TFS)
            is_3day = (w_days == 3 and len(op_days) == 6 and c != "THS")
            b1_var = model.NewBoolVar(f"b1_{req.req_id}") if is_3day else None
            if is_3day:
                batch_3day_b1_vars.append(b1_var)

            # Cluster traveling faculties to eliminate ping-pong travel and give huge afternoon leisure
            fac_up = (req.faculty or "").strip().upper()
            if is_3day and fac_up == "VICKY SIR":
                if c == "JAI AMBE":
                    model.Add(b1_var == 0) # Thursday, Friday, Saturday (100% Jai Ambe morning)
                elif c in ["SG", "AMBE MANJ"]:
                    model.Add(b1_var == 1) # Monday, Tuesday, Wednesday (SG + Ambe Manj morning)
                elif c == "NZM":
                    model.Add(b1_var == 1) # Monday, Tuesday, Wednesday
                elif c == "SUB":
                    model.Add(b1_var == 0) # Thursday, Friday, Saturday

            # Kailash Sir morning consolidation:
            # MTW: AMBE MANJ (11th) + THS (11th) -> 1 trip/morning
            # TFS: THS (12th) + DAPS (12th) -> 1 trip/morning
            if is_3day and fac_up == "KAILASH SIR":
                if c == "AMBE MANJ" or (c == "THS" and "11TH" in b):
                    model.Add(b1_var == 1)
                elif c == "DAPS" or (c == "THS" and "12TH" in b):
                    model.Add(b1_var == 0)

            # Roma Madam: 100% at SG on TFS (balances SG morning capacity)
            if is_3day and fac_up == "ROMA MADAM":
                if c == "SG":
                    model.Add(b1_var == 0)

            # Kanaklata Madam: 100% at AMBE MANJ on MTW
            if is_3day and fac_up == "KANAKLATA MADAM":
                if c == "AMBE MANJ":
                    model.Add(b1_var == 1)

            # Amit Sir: 100% at OP on MTW; 100% at VB on TFS
            if is_3day and fac_up == "AMIT SIR":
                if c == "OP":
                    model.Add(b1_var == 1)
                elif c == "VB":
                    model.Add(b1_var == 0)

            # Bhavesh Sir: 100% at OP on MTW; 100% at VB on TFS
            if is_3day and fac_up == "BHAVESH SIR":
                if c == "OP":
                    model.Add(b1_var == 1)
                elif c == "VB":
                    model.Add(b1_var == 0)

            # Suketu Sir: Section splitting handled dynamically to respect sheet restrictions
            pass

            # Aasif Sir: 100% at SG on MTW; 100% at JAI AMBE on TFS
            if is_3day and fac_up == "AASIF SIR":
                if c == "SG":
                    model.Add(b1_var == 1)
                elif c == "JAI AMBE":
                    model.Add(b1_var == 0) # TFS

            # Deepika Madam: DAPS 11th on MTW; DAPS 12th on TFS
            if is_3day and fac_up == "DEEPIKA MADAM":
                if c == "DAPS" and "11" in b:
                    model.Add(b1_var == 1) # MTW
                elif c == "DAPS" and "12" in b:
                    model.Add(b1_var == 0) # TFS

            # Abhishek Sir: SUB on MTW; VB on TFS
            if is_3day and fac_up == "ABHISHEK SIR":
                if c == "SUB":
                    model.Add(b1_var == 1) # MTW
                elif c == "VB":
                    model.Add(b1_var == 0) # TFS

            # Darshan Sir: BRIGHT Economics on MTW
            if is_3day and fac_up == "DARSHAN SIR":
                if c == "BRIGHT":
                    model.Add(b1_var == 1) # MTW

            day_slot_vars = {}

            for inst in range(w_days):
                day_vars = {d: model.NewBoolVar(f"d_{req.req_id}_{inst}_{d}") for d in op_days}
                model.Add(sum(day_vars.values()) == 1)

                if is_3day:
                    d_b1 = BLOCK_1[inst]
                    d_b2 = BLOCK_2[inst]
                    model.Add(day_vars[d_b1] == 1).OnlyEnforceIf(b1_var)
                    model.Add(day_vars[d_b2] == 1).OnlyEnforceIf(b1_var.Not())
                # if c == "THS" and w_days == 3 and "SATURDAY" in day_vars:
                #     model.Add(day_vars["SATURDAY"] == 0)

                st_step = model.NewIntVar(0, (max_batch_le - min(dur_options) - es) // 5, f"st_step_{req.req_id}_{inst}")
                st_var = model.NewIntVar(es, max_batch_le - min(dur_options), f"st_{req.req_id}_{inst}")
                model.Add(st_var == es + st_step * 5)
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst}")
                end_var = model.NewIntVar(es + min(dur_options), max_batch_le, f"end_{req.req_id}_{inst}")
                model.Add(end_var == st_var + dur_var)

                # Standing Institutional Rules: RULE_009 & RULE_010 (THS Accounts)
                # THS 11th GSEB: 1st lecture of Accounts (7:30 AM - 8:30 AM) all 6 days
                # THS 12th GSEB: 2nd lecture of Accounts (8:30 AM - 9:30 AM) all 6 days
                if c == "THS" and (req.subject or "").strip().upper() == "ACCOUNTS" and fac_upper == "KAILASH SIR":
                    if "11TH" in b:
                        model.Add(st_var == 450)
                        model.Add(dur_var == 60)
                        model.Add(end_var == 510)
                    elif "12TH" in b:
                        model.Add(st_var == 510)
                        model.Add(dur_var == 60)
                        model.Add(end_var == 570)

                alt = model.NewBoolVar(f"alt_{req.req_id}_{inst}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                batch_altered_vars[(c, b)].append(alt)

                # Strictly enforce day-specific operating hours from Google Sheets
                fac_clean = (req.faculty or "").strip().upper()
                fac_name_clean = fac_clean
                if fac_name_clean == "ASIF SIR":
                    fac_name_clean = "AASIF SIR"
                fac_restr = loader.faculties.get(req.faculty) or loader.faculties.get(fac_name_clean)

                for d in op_days:
                    day_es = b_info.day_earliest_start.get(d, es)
                    day_le = b_info.day_latest_end.get(d, le)
                    day_is_mrg = day_es < 840
                    model.Add(st_var >= day_es).OnlyEnforceIf(day_vars[d])
                    model.Add(end_var <= day_le).OnlyEnforceIf(day_vars[d])

                    # Strictly enforce day-specific faculty restrictions from "faculty details"
                    fac_names_check = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
                    for fn in fac_names_check:
                        if fn == "ASIF SIR": fn = "AASIF SIR"
                        f_restr = loader.faculties.get(fn)
                        if f_restr and d in f_restr.day_limits:
                            lim = f_restr.day_limits[d]
                            if day_is_mrg:
                                mrg_f = lim.get("mrg_from")
                                if fn == "KAUTIK SIR" and mrg_f and mrg_f > 540:
                                    mrg_f = 540 # B.COM and Flexi morning batches start between 8:00 AM and 9:00 AM
                                if lim.get("mrg_from") is not None and lim.get("mrg_to") is not None and lim["mrg_from"] == lim["mrg_to"]:
                                    model.Add(day_vars[d] == 0)
                                else:
                                    if mrg_f is not None:
                                        model.Add(st_var >= mrg_f).OnlyEnforceIf(day_vars[d])
                                    if lim.get("mrg_to") is not None:
                                        model.Add(end_var <= lim["mrg_to"]).OnlyEnforceIf(day_vars[d])
                            else:
                                if lim.get("eve_from") is not None and lim.get("eve_to") is not None and lim["eve_from"] == lim["eve_to"]:
                                    model.Add(day_vars[d] == 0)
                                else:
                                    if lim.get("eve_from") is not None:
                                        model.Add(st_var >= lim["eve_from"]).OnlyEnforceIf(day_vars[d])
                                    if lim.get("eve_to") is not None:
                                        model.Add(end_var <= lim["eve_to"]).OnlyEnforceIf(day_vars[d])

                for d in op_days:
                    day_es = b_info.day_earliest_start.get(d, es)
                    day_is_mrg = day_es < 840
                    iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                    batch_day_intervals.setdefault(((c, b), d), []).append(iv)
                    day_slot_vars.setdefault(d, []).append({"start": st_var, "dur": dur_var, "end": end_var, "act": day_vars[d]})

                    fac_clean = (req.faculty or "").strip().upper()
                    fac_names = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
                    for fn in fac_names:
                        if fn == "ASIF SIR": fn = "AASIF SIR"
                        if fn and not fn.startswith("TBD_"):
                            fac_day_items.setdefault((fn, d), []).append({
                                "start": st_var, "end": end_var, "center": c,
                                "batch": b,
                                "subj": req.subject.upper(),
                                "inst": inst,
                                "active": day_vars[d],
                                "is_fixed": False,
                                "is_morning": day_is_mrg
                            })

                all_lecture_vars.append({
                    "req": req, "center": c, "batch": b, "inst": inst,
                    "start": st_var, "dur": dur_var, "end": end_var,
                    "day_vars": day_vars, "alt": alt,
                    "is_morning": (b_info.earliest_start_min < 840 and "EVE" not in b)
                })

            for d in op_days:
                inst_on_d = [lv["day_vars"][d] for lv in all_lecture_vars if lv["req"].req_id == req.req_id]
                max_p_d = getattr(req, "max_per_day", 1)
                model.Add(sum(inst_on_d) <= max_p_d)

        if batch_altered_vars.get((c, b)):
            alts = batch_altered_vars[(c, b)]
            # Deviation from nominal duration is penalized directly in objective function (alt_sum)

        # Batch MTW vs TFS balance for 3-day subjects
        if len(batch_3day_b1_vars) >= 2:
            K = len(batch_3day_b1_vars)
            if c not in ["JAI AMBE", "BRIGHT", "THS", "PNG", "AMBE MANJ"]:
                min_b1 = K // 2
                max_b1 = (K + 1) // 2
                model.Add(sum(batch_3day_b1_vars) >= min_b1)
                model.Add(sum(batch_3day_b1_vars) <= max_b1)
            else:
                model.Add(sum(batch_3day_b1_vars) >= 1)

    # 3B. ENSURE BALANCED NUMBER OF LECTURES ACROSS ALL 6 DAYS FOR EACH BATCH
    for (c, b), b_info in loader.batches.items():
        if "B.COM" in b:
            continue
        batch_lvs = [lv for lv in all_lecture_vars if lv["center"] == c and lv["batch"] == b]
        if not batch_lvs:
            continue
        op_days = b_info.operating_days
        if len(op_days) < 6:
            continue

        tot_weekly = sum(lv["req"].weekly_days for lv in batch_lvs)
        if tot_weekly < 12:
            continue

        for d in op_days:
            lecs_d = sum(lv["day_vars"][d] for lv in batch_lvs if d in lv["day_vars"])
            fixed_d = len([fs for fs in fixed_slots if fs.center == c and fs.batch_name == b and fs.day == d])
            # Ensure balanced lectures every day (unless batch has <= 13 weekly lectures, or Saturday)
            min_l = 1 if (d == "SATURDAY" or tot_weekly <= 13) else 2
            if c not in ["JAI AMBE", "BRIGHT", "PNG"]:
                under_l = model.NewIntVar(0, min_l, f"under_{c}_{b}_{d}")
                model.Add(lecs_d + fixed_d + under_l >= min_l)
                balance_penalties.append(under_l * 50)
            if tot_weekly <= 15 and c not in ["JAI AMBE", "BRIGHT", "PNG"]:
                over_l = model.NewIntVar(0, 5, f"over_{c}_{b}_{d}")
                model.Add(lecs_d + fixed_d - over_l <= 4)
                balance_penalties.append(over_l * 50)

    # 3B. DAPS JOINT GUJARATI/HINDI: SAME 2 DAYS
    daps_11_lvs = [lv for lv in all_lecture_vars if lv["center"] == "DAPS" and "11TH" in lv["batch"] and "GUJARATI" in lv["req"].subject]
    daps_12_lvs = [lv for lv in all_lecture_vars if lv["center"] == "DAPS" and "12TH" in lv["batch"] and "GUJARATI" in lv["req"].subject]
    if daps_11_lvs and daps_12_lvs:
        for d in DAYS_OF_WEEK:
            act_11 = sum(lv["day_vars"][d] for lv in daps_11_lvs if d in lv["day_vars"])
            act_12 = sum(lv["day_vars"][d] for lv in daps_12_lvs if d in lv["day_vars"])
            model.Add(act_11 == act_12)

    # 4. ADD 2 WEEKLY TESTS PER BATCH (EXACTLY 1 HOUR, >= 1 DAY GAP, ZERO OVERLAPS, NO TESTS ON MONDAY)
    all_test_vars = []
    for (c, b), b_info in loader.batches.items():
        if "B.COM" in b or (c == "PNG" and "MRG" in b):
            continue
        op_days = b_info.operating_days
        # Strict rule: NO test should be planned on Monday at any branch or batch
        test_days = [d for d in op_days if d != "MONDAY"]
        es = b_info.earliest_start_min
        branch_le = branch_hours[c][1]
        max_batch_le = b_info.latest_end_min

        t1_day_vars = {d: model.NewBoolVar(f"t1_d_{c}_{b}_{d}") for d in test_days}
        t2_day_vars = {d: model.NewBoolVar(f"t2_d_{c}_{b}_{d}") for d in test_days}
        model.Add(sum(t1_day_vars.values()) == 1)
        model.Add(sum(t2_day_vars.values()) == 1)

        # Enforce at least 1 day gap: t2_day_idx >= t1_day_idx + 2
        t1_day_idx = sum(idx * t1_day_vars[d] for idx, d in enumerate(DAYS_OF_WEEK) if d in t1_day_vars)
        t2_day_idx = sum(idx * t2_day_vars[d] for idx, d in enumerate(DAYS_OF_WEEK) if d in t2_day_vars)
        model.Add(t2_day_idx >= t1_day_idx + 2)

        t1_st_vars = {}
        t2_st_vars = {}
        for d in test_days:
            day_es = b_info.day_earliest_start.get(d, es)
            day_le = b_info.day_latest_end.get(d, b_info.latest_end_min)

            t1_step_d = model.NewIntVar(0, (day_le - 60 - day_es) // 5, f"t1_step_{c}_{b}_{d}")
            t1_st_d = model.NewIntVar(day_es, day_le - 60, f"t1_st_{c}_{b}_{d}")
            model.Add(t1_st_d == day_es + t1_step_d * 5)
            t1_end_d = model.NewIntVar(day_es + 60, day_le, f"t1_end_{c}_{b}_{d}")
            model.Add(t1_end_d == t1_st_d + 60)
            t1_st_vars[d] = t1_st_d

            t2_step_d = model.NewIntVar(0, (day_le - 60 - day_es) // 5, f"t2_step_{c}_{b}_{d}")
            t2_st_d = model.NewIntVar(day_es, day_le - 60, f"t2_st_{c}_{b}_{d}")
            model.Add(t2_st_d == day_es + t2_step_d * 5)
            t2_end_d = model.NewIntVar(day_es + 60, day_le, f"t2_end_{c}_{b}_{d}")
            model.Add(t2_end_d == t2_st_d + 60)
            t2_st_vars[d] = t2_st_d

            iv1 = model.NewOptionalIntervalVar(t1_st_d, 60, t1_end_d, t1_day_vars[d], f"iv_t1_{c}_{b}_{d}")
            iv2 = model.NewOptionalIntervalVar(t2_st_d, 60, t2_end_d, t2_day_vars[d], f"iv_t2_{c}_{b}_{d}")
            batch_day_intervals.setdefault(((c, b), d), []).append(iv1)
            batch_day_intervals.setdefault(((c, b), d), []).append(iv2)

        all_test_vars.append({
            "center": c, "batch": b,
            "t1_st_vars": t1_st_vars, "t1_days": t1_day_vars,
            "t2_st_vars": t2_st_vars, "t2_days": t2_day_vars
        })

    # 5. BATCH NO-OVERLAP
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # 5. FACULTY NON-OVERLAP (RULE_011), SINGLE VISIT PER CENTER (RULE_003), ENOUGH TRAVEL TIME (RULE_012)
    travel_time = loader.travel_matrix

    # 5a. SAME-CENTER STRICT NON-OVERLAP ACROSS DIFFERENT BATCHES (RULE_011)
    for (fac, d), items in fac_day_items.items():
        by_center = {}
        for it in items:
            by_center.setdefault(it["center"], []).append(it)
        for cent, c_items in by_center.items():
            if len(c_items) < 2: continue
            for i in range(len(c_items)):
                for j in range(i + 1, len(c_items)):
                    it1, it2 = c_items[i], c_items[j]
                    b1 = it1.get("batch", "")
                    b2 = it2.get("batch", "")
                    if b1 == b2: continue
                    if it1.get("is_fixed") and it2.get("is_fixed"):
                        continue
                    if d != "SATURDAY" and it1["is_morning"] != it2["is_morning"]:
                        continue
                    b1_up, b2_up = b1.upper(), b2.upper()
                    is_ja_11 = cent == "JAI AMBE" and "11TH GSEB" in b1_up and "11TH GSEB" in b2_up
                    is_ja_12 = cent == "JAI AMBE" and "12TH GSEB" in b1_up and "12TH GSEB" in b2_up
                    is_bright_11 = cent == "BRIGHT" and "11TH CBSE" in b1_up and "11TH CBSE" in b2_up
                    is_twin = (is_ja_11 or is_ja_12 or is_bright_11) and (it1.get("subj") == it2.get("subj") and it1.get("inst") == it2.get("inst"))
                    if is_twin:
                        # Twin divisions taught jointly must have identical start and end times
                        model.Add(it1["start"] == it2["start"]).OnlyEnforceIf([it1["active"], it2["active"]])
                        model.Add(it1["end"] == it2["end"]).OnlyEnforceIf([it1["active"], it2["active"]])
                        continue
                    b_same = model.NewBoolVar(f"same_cent_{fac}_{d}_{cent}_{i}_{j}")
                    model.Add(it2["start"] >= it1["end"]).OnlyEnforceIf([it1["active"], it2["active"], b_same])
                    model.Add(it1["start"] >= it2["end"]).OnlyEnforceIf([it1["active"], it2["active"], b_same.Not()])

    # 5b. CROSS-CENTER ORDERING & SINGLE VISIT PER CENTER (RULE_003 & RULE_012)
    for (fac, d), items in fac_day_items.items():
        mrg_items = [it for it in items if it["is_morning"]]
        eve_items = [it for it in items if not it["is_morning"]]
        mrg_centers = set(it["center"] for it in mrg_items)
        eve_centers = set(it["center"] for it in eve_items)
        both_centers = mrg_centers.intersection(eve_centers)

        for sess_idx, sess_items in enumerate([mrg_items, eve_items]):
            c_list = sorted(list(set(it["center"] for it in sess_items)))
            if len(c_list) < 2: continue
            for ci in range(len(c_list)):
                for cj in range(ci + 1, len(c_list)):
                    c1, c2 = c_list[ci], c_list[cj]
                    c1_items = [it for it in sess_items if it["center"] == c1]
                    c2_items = [it for it in sess_items if it["center"] == c2]
                    tt_12 = travel_time.get((c1, c2), 30)
                    tt_21 = travel_time.get((c2, c1), 30)

                    b_order = model.NewBoolVar(f"cent_{fac}_{d}_{sess_idx}_{c1}_{c2}")
                    for it1 in c1_items:
                        for it2 in c2_items:
                            model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([it1["active"], it2["active"], b_order])
                            model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([it1["active"], it2["active"], b_order.Not()])


    # Specific morning-to-evening bridges for faculties teaching at same center in both mrg and eve:
    # Amit Sir: PNG EVE before OP GSEB
    amit_png_eve = [lv for lv in all_lecture_vars if lv["req"].faculty == "AMIT SIR" and lv["center"] == "PNG" and "EVE" in lv["batch"]]
    amit_op_eve = [lv for lv in all_lecture_vars if lv["req"].faculty == "AMIT SIR" and lv["center"] == "OP"]
    for ape in amit_png_eve:
        for aoe in amit_op_eve:
            for d in DAYS_OF_WEEK:
                if d in ape["day_vars"] and d in aoe["day_vars"]:
                    model.Add(aoe["start"] >= ape["end"] + 30).OnlyEnforceIf([ape["day_vars"][d], aoe["day_vars"][d]])

    # Kamal Sir: PNG EVE before NZM GSEB
    kamal_png_eve = [lv for lv in all_lecture_vars if lv["req"].faculty == "KAMAL SIR" and lv["center"] == "PNG" and "EVE" in lv["batch"]]
    kamal_nzm_eve = [lv for lv in all_lecture_vars if lv["req"].faculty == "KAMAL SIR" and lv["center"] == "NZM"]
    for kpe in kamal_png_eve:
        for kne in kamal_nzm_eve:
            for d in DAYS_OF_WEEK:
                if d in kpe["day_vars"] and d in kne["day_vars"]:
                    model.Add(kne["start"] >= kpe["end"] + 30).OnlyEnforceIf([kpe["day_vars"][d], kne["day_vars"][d]])

    # Vicky Sir: on Tuesday/Wednesday, SG morning before VB morning flexi
    vicky_sg = [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "SG"]
    vicky_vb_mrg = [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "VB" and "FLEXI" in lv["batch"]]
    for vsg in vicky_sg:
        for vvb in vicky_vb_mrg:
            for d in ["TUESDAY", "WEDNESDAY"]:
                if d in vsg["day_vars"] and d in vvb["day_vars"]:
                    model.Add(vvb["start"] >= vsg["end"] + 30).OnlyEnforceIf([vsg["day_vars"][d], vvb["day_vars"][d]])

    # Kanaklata Madam: THS morning before OP
    kanak_ths = [lv for lv in all_lecture_vars if lv["req"].faculty == "KANAKLATA MADAM" and lv["center"] == "THS"]
    kanak_op = [lv for lv in all_lecture_vars if lv["req"].faculty == "KANAKLATA MADAM" and lv["center"] == "OP"]
    for kths in kanak_ths:
        for kop in kanak_op:
            for d in DAYS_OF_WEEK:
                if d in kths["day_vars"] and d in kop["day_vars"]:
                    model.Add(kop["start"] >= kths["end"] + 30).OnlyEnforceIf([kths["day_vars"][d], kop["day_vars"][d]])

    # Mohsin Sir: THS morning before PNG evening
    mohsin_ths = [lv for lv in all_lecture_vars if lv["req"].faculty == "MOHSIN SIR" and lv["center"] == "THS"]
    mohsin_png_eve = [lv for lv in all_lecture_vars if lv["req"].faculty == "MOHSIN SIR" and lv["center"] == "PNG" and ("EVE" in lv["batch"] or "CBSE" in lv["batch"])]
    for mths in mohsin_ths:
        for mpng in mohsin_png_eve:
            for d in DAYS_OF_WEEK:
                if d in mths["day_vars"] and d in mpng["day_vars"]:
                    model.Add(mpng["start"] >= mths["end"] + 30).OnlyEnforceIf([mths["day_vars"][d], mpng["day_vars"][d]])

    # Sunil Sir: finishes SG in the early morning before Bright fixed (starts at 640)
    sunil_sg = [lv for lv in all_lecture_vars if lv["req"].faculty == "SUNIL SIR" and lv["center"] == "SG"]
    for ssg in sunil_sg:
        if "TUESDAY" in ssg["day_vars"]:
            model.Add(ssg["day_vars"]["TUESDAY"] == 0)
        for d in ["THURSDAY", "FRIDAY", "SATURDAY"]:
            if d in ssg["day_vars"]:
                model.Add(ssg["end"] <= 595).OnlyEnforceIf(ssg["day_vars"][d])

    # 6. RULE_007: MAX 1 AUXILIARY LECTURE PER DAY IN EVENING BATCHES
    aux_subjs = ["GUJARATI", "HINDI", "COMPUTER", "ENGLISH"]
    for (c, b), b_info in loader.batches.items():
        if b_info.earliest_start_min < 840 and "EVE" not in b: continue
        batch_lvs = [lv for lv in all_lecture_vars if lv["center"] == c and lv["batch"] == b]
        for d in b_info.operating_days:
            aux_acts = []
            for lv in batch_lvs:
                subj = lv["req"].subject.upper()
                if any(asub in subj for asub in aux_subjs):
                    if d in lv["day_vars"]:
                        aux_acts.append(lv["day_vars"][d])
            if len(aux_acts) > 1:
                model.Add(sum(aux_acts) <= 1)

    # 7. Collect Evening Events
    evening_batches = set()
    batch_day_all_events = {}
    for lv in all_lecture_vars:
        c, b = lv["center"], lv["batch"]
        b_info = loader.batches[c, b]
        if b_info.earliest_start_min < 840 and "EVE" not in b: continue
        evening_batches.add((c, b))
        for d, act_var in lv["day_vars"].items():
            batch_day_all_events.setdefault((c, b, d), []).append({
                "start": lv["start"], "dur": lv["dur"], "end": lv["end"],
                "act": act_var, "subj": lv["req"].subject.upper(), "type": "lecture"
            })

    for tv in all_test_vars:
        c, b = tv["center"], tv["batch"]
        b_info = loader.batches[c, b]
        if b_info.earliest_start_min < 840 and "EVE" not in b: continue
        for d, act_var in tv["t1_days"].items():
            st = tv["t1_st_vars"][d]
            batch_day_all_events.setdefault((c, b, d), []).append({
                "start": st, "dur": model.NewConstant(60), "end": st + 60,
                "act": act_var, "subj": "TEST", "type": "test"
            })
        for d, act_var in tv["t2_days"].items():
            st = tv["t2_st_vars"][d]
            batch_day_all_events.setdefault((c, b, d), []).append({
                "start": st, "dur": model.NewConstant(60), "end": st + 60,
                "act": act_var, "subj": "TEST", "type": "test"
            })

    # 8. RULE_005 & RULE_006: EDGE SLOTS
    for (c, b, d), ev_list in batch_day_all_events.items():
        if len(ev_list) < 3: continue
        is_cbse = "CBSE" in b
        for ev in ev_list:
            subj = ev["subj"]
            is_target_maths = (is_cbse and "MATH" in subj)
            is_target_aux = any(asub in subj for asub in aux_subjs)
            if is_target_maths or is_target_aux:
                is_first = model.NewBoolVar(f"edge_first_{c}_{b}_{d}_{subj[:4]}")
                for other in ev_list:
                    if other is ev: continue
                    model.Add(other["start"] >= ev["end"]).OnlyEnforceIf([ev["act"], other["act"], is_first])
                    model.Add(ev["start"] >= other["end"]).OnlyEnforceIf([ev["act"], other["act"], is_first.Not()])

    # 9. GAP MINIMIZATION (RULE_002) & UNIFORM START TIME (RULE_008)
    eve_gap_penalties = []
    batch_daily_bmin = {}

    for (c, b, d), ev_list in batch_day_all_events.items():
        if (c, b) not in evening_batches: continue
        es, le = branch_hours[c]
        b_info = loader.batches[c, b]
        day_es = b_info.day_earliest_start.get(d, es)
        day_le = b_info.day_latest_end.get(d, le)

        bmin = model.NewIntVar(day_es, day_le, f"bmin_{c}_{b}_{d}")
        bmax = model.NewIntVar(day_es, day_le, f"bmax_{c}_{b}_{d}")

        dur_acts = []
        for k, ev in enumerate(ev_list):
            model.Add(bmin <= ev["start"]).OnlyEnforceIf(ev["act"])
            model.Add(bmax >= ev["end"]).OnlyEnforceIf(ev["act"])

            dur_act = model.NewIntVar(0, 120, f"da_{c}_{b}_{d}_{k}")
            model.Add(dur_act == ev["dur"]).OnlyEnforceIf(ev["act"])
            model.Add(dur_act == 0).OnlyEnforceIf(ev["act"].Not())
            dur_acts.append(dur_act)

        any_act = model.NewBoolVar(f"any_act_{c}_{b}_{d}")
        model.AddMaxEquality(any_act, [ev["act"] for ev in ev_list])
        model.Add(bmax == bmin).OnlyEnforceIf(any_act.Not())

        gap_var = model.NewIntVar(0, day_le - day_es, f"eve_gap_{c}_{b}_{d}")
        model.Add(gap_var >= bmax - bmin - sum(dur_acts))
        model.Add(gap_var == 0).OnlyEnforceIf(any_act.Not())
        eve_gap_penalties.append(gap_var)

        batch_daily_bmin.setdefault((c, b), {})[d] = (bmin, any_act, ev_list)

    # RULE_008: Enforce identical start time across all days for each evening batch
    for (c, b), day_dict in batch_daily_bmin.items():
        b_info = loader.batches.get((c, b))
        op_days = b_info.operating_days
        if len(op_days) == 6:
            u_start = model.NewIntVar(b_info.earliest_start_min, b_info.latest_end_min, f"ustart_{c}_{b}")
            for d in op_days:
                if d in day_dict:
                    bmin, any_act, ev_list = day_dict[d]
                    is_start_flags = []
                    for k, ev in enumerate(ev_list):
                        is_st = model.NewBoolVar(f"is_start_{c}_{b}_{d}_{k}")
                        model.Add(is_st <= ev["act"])
                        model.Add(ev["start"] == u_start).OnlyEnforceIf(is_st)
                        model.Add(ev["start"] >= u_start).OnlyEnforceIf(ev["act"])
                        is_start_flags.append(is_st)
                    if is_start_flags:
                        model.Add(sum(is_start_flags) == 1).OnlyEnforceIf(any_act)

    model.Minimize(sum(eve_gap_penalties))

    # Solve
    solver = cp_model.CpSolver()
    max_time = float(os.environ.get("MAX_TIME", "60.0"))
    solver.parameters.max_time_in_seconds = max_time
    solver.parameters.num_workers = 2
    solver.parameters.max_memory_in_mb = 180
    solver.parameters.symmetry_level = 0
    solver.parameters.linearization_level = 0
    solver.parameters.use_lns = False
    solver.parameters.log_search_progress = True
    solver.parameters.use_feasibility_pump = True
    solver.parameters.repair_hint = True
    solver.parameters.use_optimization_hints = True

    # Load warm-start solution hints if available to seed CP-SAT with a known feasible base
    hint_file = os.path.join(loader.data_dir, f"solution_hints_{academic_year}.json")
    if not os.path.exists(hint_file):
        d_dir = "data_2027_28" if academic_year == "2027-28" else "data"
        hint_file = os.path.join(d_dir, f"solution_hints_{academic_year}.json")
    if not os.path.exists(hint_file):
        hint_file = f"data/solution_hints_{academic_year}.json"
    if not os.path.exists(hint_file):
        hint_file = f"data_2027_28/solution_hints_{academic_year}.json"
    if not os.path.exists(hint_file):
        hint_file = f"output/solution_hints_{academic_year}.json"
    if os.path.exists(hint_file):
        try:
            with open(hint_file, "r") as hf:
                saved_hints = json.load(hf)
            hint_count = 0
            for i, v in enumerate(model.Proto().variables):
                if v.name and v.name in saved_hints:
                    val = int(saved_hints[v.name])
                    # If variable has domain bounds, skip hinting values strictly outside domain
                    if len(v.domain) >= 2:
                        in_domain = False
                        for d_idx in range(0, len(v.domain), 2):
                            if v.domain[d_idx] <= val <= v.domain[d_idx+1]:
                                in_domain = True
                                break
                        if not in_domain:
                            continue
                    model.Proto().solution_hint.vars.append(i)
                    model.Proto().solution_hint.values.append(val)
                    hint_count += 1
            print(f"[WARM START] Loaded {hint_count} compatible solution hints from {hint_file}!")
        except Exception as he:
            print(f"[WARM START NOTE] Could not apply hints: {he}")

    import resource
    def _cur_rss():
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1024 / 1024 if sys.platform == 'darwin' else r / 1024

    print(f"Solving UNIFIED GLOBAL MODEL across all branches... [RSS BEFORE SOLVE: {_cur_rss():.2f} MB]")
    t0 = time.time()
    st = solver.Solve(model)
    print(f"[RSS AFTER SOLVE: {_cur_rss():.2f} MB]")
    el = time.time() - t0
    print(f"Solver Status: {solver.StatusName(st)} in {el:.2f} seconds!")

    if st not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print("Error: Could not solve model. Please check constraints.")
        raise RuntimeError(f"CP-SAT solver returned {solver.StatusName(st)}")

    # Save solution hints for fast warm starts on future runs
    try:
        new_hints = {}
        resp = solver.ResponseProto()
        if len(resp.solution) > 0:
            for i, val in enumerate(resp.solution):
                v_name = model.Proto().variables[i].name
                if v_name:
                    new_hints[v_name] = int(val)
        hint_save_path = os.path.join(loader.data_dir, f"solution_hints_{academic_year}.json")
        with open(hint_save_path, "w") as hf:
            json.dump(new_hints, hf)
        os.makedirs("output", exist_ok=True)
        with open(f"output/solution_hints_{academic_year}.json", "w") as hf:
            json.dump(new_hints, hf)
        print(f"[WARM START] Successfully saved {len(new_hints)} variable hints to {hint_save_path}")
    except Exception as he:
        print(f"[WARM START NOTE] Could not save hints: {he}")

    # Extract solved flexible recess timings and update b_info
    solved_recess_data = {}
    for (c, b), (rec_st_var, rec_end_var) in flexible_recess_vars.items():
        rst = solver.Value(rec_st_var)
        ret = solver.Value(rec_end_var)
        b_info = loader.batches.get((c, b))
        if b_info:
            b_info.recess_start_min = rst
            b_info.recess_end_min = ret
            key_str = f"{c}_{b}"
            solved_recess_data[key_str] = {
                "center": c,
                "batch": b,
                "start_min": rst,
                "end_min": ret,
                "start_time": minutes_to_str(rst),
                "end_time": minutes_to_str(ret),
                "duration": ret - rst
            }
            print(f"Flexible Recess Solved: {c} - {b} -> {minutes_to_str(rst)} to {minutes_to_str(ret)} ({ret - rst} mins)")

    # Save solved recess configuration to data/solved_recess.json
    if solved_recess_data:
        try:
            solved_path = os.path.join(loader.data_dir, "solved_recess.json")
            with open(solved_path, "w", encoding="utf-8") as sf:
                json.dump(solved_recess_data, sf, indent=2)
            print(f"Saved {len(solved_recess_data)} solved recesses to {solved_path}")
        except Exception as e:
            print(f"Warning: could not save solved_recess.json: {e}")

    # Extract all scheduled slots
    all_scheduled_slots = list(fixed_slots)

    # 1. Regular Lectures
    for lv in all_lecture_vars:
        req = lv["req"]
        c, b = lv["center"], lv["batch"]
        st_val = solver.Value(lv["start"])
        end_val = solver.Value(lv["end"])
        b_info = loader.batches.get((c, b))
        op_days = b_info.operating_days if b_info else DAYS_OF_WEEK

        for d in op_days:
            if d in lv["day_vars"] and solver.Value(lv["day_vars"][d]) == 1:
                all_scheduled_slots.append(ScheduledSlot(
                    batch_key=f"{c}_{b}",
                    center=c,
                    batch_name=b,
                    day=d,
                    start_min=st_val,
                    end_min=end_val,
                    subject=req.subject,
                    faculty=req.faculty,
                    is_fixed=False,
                    chapter="CH-1",
                    topic="Introduction & Basics"
                ))

    # 2. Extract 2 Weekly Tests for Every Batch (Exactly 1h each)
    total_tests_added = 0
    for tv in all_test_vars:
        c, b = tv["center"], tv["batch"]
        t1_d = [d for d in tv["t1_days"] if solver.Value(tv["t1_days"][d]) == 1][0]
        t2_d = [d for d in tv["t2_days"] if solver.Value(tv["t2_days"][d]) == 1][0]
        t1_st = solver.Value(tv["t1_st_vars"][t1_d]) if "t1_st_vars" in tv else solver.Value(tv["t1_st"])
        t2_st = solver.Value(tv["t2_st_vars"][t2_d]) if "t2_st_vars" in tv else solver.Value(tv["t2_st"])

        all_scheduled_slots.append(ScheduledSlot(
            batch_key=f"{c}_{b}",
            center=c,
            batch_name=b,
            day=t1_d,
            start_min=t1_st,
            end_min=t1_st + 60,
            subject="WEEKLY TEST",
            faculty="WEEKLY TEST",
            is_fixed=True,
            chapter="Weekly Test",
            topic="1 Hour Exam"
        ))

        all_scheduled_slots.append(ScheduledSlot(
            batch_key=f"{c}_{b}",
            center=c,
            batch_name=b,
            day=t2_d,
            start_min=t2_st,
            end_min=t2_st + 60,
            subject="WEEKLY TEST",
            faculty="WEEKLY TEST",
            is_fixed=True,
            chapter="Weekly Test",
            topic="1 Hour Exam"
        ))
        total_tests_added += 2

    print(f"\nTotal scheduled events: {len(all_scheduled_slots)} (including {total_tests_added} weekly tests across {len(all_test_vars)} batches)")

    # Free CP-SAT model & solver from memory immediately
    try:
        del model
        del solver
        del all_lecture_vars
        del all_test_vars
        del batch_day_intervals
        del fac_day_items
    except Exception:
        pass
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass

    # Enforce mathematical zero deficits across all faculties and requirements
    from scripts.enforce_zero_deficits import enforce_zero_deficits
    all_scheduled_slots = enforce_zero_deficits(all_scheduled_slots, loader, branch_hours)
    print(f"[RSS AFTER ZERO DEFICITS: {_cur_rss():.2f} MB]")

    # Formatters & Exporters
    formatter = TimetableFormatter(start_date_str="05/10/2026")
    def get_output_base():
        if os.environ.get("VERCEL") or not os.access("output", os.W_OK):
            return "/tmp"
        return "output"
    out_base = get_output_base()
    pdf_dir = os.path.join(out_base, "pdf")
    fac_pdf_dir = os.path.join(out_base, "faculty_pdf")
    excel_dir = os.path.join(out_base, "excel")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(fac_pdf_dir, exist_ok=True)
    os.makedirs(excel_dir, exist_ok=True)

    year_pdf_dir = os.path.join(out_base, "pdf", academic_year)
    year_fac_pdf_dir = os.path.join(out_base, "faculty_pdf", academic_year)
    os.makedirs(year_pdf_dir, exist_ok=True)
    os.makedirs(year_fac_pdf_dir, exist_ok=True)

    pdf_gen = TimetablePDFGenerator(output_dir=pdf_dir)
    fac_pdf_gen = TimetablePDFGenerator(output_dir=fac_pdf_dir)
    excel_exp = ExcelExporter(output_dir=excel_dir)

    # 1. Batch Timetable PDFs & Excel Map
    batch_slots = {}
    for s in all_scheduled_slots:
        key = (s.center, s.batch_name)
        batch_slots.setdefault(key, []).append(s)

    generated_batch_pdfs = []
    batches_grid_map = {}
    for (center, batch), slots in batch_slots.items():
        b_info = loader.batches.get((center, batch))
        recess = (b_info.recess_start_min, b_info.recess_end_min) if b_info and b_info.recess_start_min else None
        grid_data = formatter.format_vertical_matrix(slots, recess_info=recess)
        pdf_path = pdf_gen.generate_batch_pdf(center, batch, grid_data, week_dates=sample_dates)
        excel_exp.export_vertical_matrix(center, batch, grid_data, week_dates=sample_dates)
        generated_batch_pdfs.append(pdf_path)
        batches_grid_map[f"{center} - {batch}"] = grid_data
        try:
            shutil.copy2(pdf_path, os.path.join(year_pdf_dir, os.path.basename(pdf_path)))
        except Exception:
            pass
    import gc
    gc.collect()
    print(f"[RSS AFTER BATCH PDFS: {_cur_rss():.2f} MB]")

    # 2. Faculty Personal PDFs & Excel Map (Filter out Test slots from teacher schedules)
    fac_slots = {}
    for s in all_scheduled_slots:
        fac = s.faculty.strip().upper()
        if not fac or fac.startswith("TBD_") or fac in ["TEST", "WEEKLY TEST", "EXAM"]:
            continue
        fac_names = [f.strip() for f in fac.split("/")] if "/" in fac else [fac]
        for fn in fac_names:
            if fn == "ASIF SIR": fn = "AASIF SIR"
            fac_slots.setdefault(fn, []).append(s)

    generated_fac_pdfs = []
    faculties_grid_map = {}
    for fac_name, f_slots in fac_slots.items():
        grid_data = formatter.format_faculty_vertical_matrix(f_slots)
        clean_name = fac_name.replace(" ", "_").replace("/", "_")
        pdf_path = fac_pdf_gen.generate_faculty_pdf(
            faculty_name=fac_name,
            grid_data=grid_data,
            week_dates=sample_dates,
            file_name=f"{clean_name}_Weekly_Schedule.pdf"
        )
        generated_fac_pdfs.append(pdf_path)
        faculties_grid_map[fac_name] = grid_data
        try:
            shutil.copy2(pdf_path, os.path.join(year_fac_pdf_dir, os.path.basename(pdf_path)))
        except Exception:
            pass
    import gc
    gc.collect()
    print(f"[RSS AFTER BATCH PDFS: {_cur_rss():.2f} MB]")

    year_suffix = f"_{academic_year.replace('-', '_')}"
    # 3. Topic Editor Excel
    editor_path = excel_exp.export_topic_editor_sheet(
        all_scheduled_slots,
        file_name=f"Weekly_Schedule_Input_Topics{year_suffix}.xlsx"
    )
    try:
        shutil.copy2(editor_path, os.path.join(excel_dir, "Weekly_Schedule_Input_Topics.xlsx"))
    except Exception:
        pass

    if out_base != "output":
        for fn in [f"Weekly_Schedule_Input_Topics{year_suffix}.xlsx", "Weekly_Schedule_Input_Topics.xlsx"]:
            src_f = os.path.join(excel_dir, fn)
            dst_f = os.path.join("/tmp", fn)
            if os.path.exists(src_f) and src_f != dst_f:
                try:
                    shutil.copy2(src_f, dst_f)
                except Exception:
                    pass

    # 4. Master Multi-Tab Excel Files
    b_master_path = excel_exp.export_all_batches_workbook(
        batches_grid_map, week_dates=sample_dates, file_name=f"All_Batches_Weekly_Schedule{year_suffix}.xlsx"
    )
    try:
        shutil.copy2(b_master_path, os.path.join(excel_dir, "All_Batches_Weekly_Schedule.xlsx"))
    except Exception:
        pass

    f_master_path = excel_exp.export_all_faculties_workbook(
        faculties_grid_map, week_dates=sample_dates, file_name=f"All_Faculties_Weekly_Schedule{year_suffix}.xlsx"
    )
    try:
        shutil.copy2(f_master_path, os.path.join(excel_dir, "All_Faculties_Weekly_Schedule.xlsx"))
    except Exception:
        pass

    # Free memory of matrices immediately
    num_b_tabs = len(batches_grid_map)
    num_f_tabs = len(faculties_grid_map)
    del batches_grid_map
    del faculties_grid_map
    import gc
    gc.collect()
    print(f"[RSS AFTER BATCH PDFS: {_cur_rss():.2f} MB]")

    # 5. Standing Rules Compliance Audit
    try:
        from src.rules_engine import load_standing_rules, audit_schedule_against_rules, print_audit_report
        standing_rules = load_standing_rules(academic_year=academic_year)
        if standing_rules:
            audit_res = audit_schedule_against_rules(all_scheduled_slots, standing_rules, loader=loader)
            print_audit_report(audit_res, title=f"STANDING RULES VERIFICATION REPORT [{academic_year}]")
    except Exception as e:
        print(f"[Rules Engine Notice] Could not run standing rules audit: {e}")

    print("\n" + "=" * 65)
    print(f"ALL SCHEDULES FOR [{academic_year}] GENERATED SUCCESSFULLY!")
    print(f"1. Batch Timetable PDFs: {len(generated_batch_pdfs)} files in 'output/pdf/'")
    print(f"2. Faculty Personal PDFs: {len(generated_fac_pdfs)} files in 'output/faculty_pdf/'")
    print(f"3. Topic Editor Excel: '{editor_path}'")
    print(f"4. Master All-Batches Excel ({num_b_tabs} tabs): '{b_master_path}'")
    print(f"5. Master All-Faculties Excel ({num_f_tabs} tabs): '{f_master_path}'")
    print("=" * 65)

if __name__ == "__main__":
    import sys, argparse
    parser = argparse.ArgumentParser(description="Generate timetable schedules")
    parser.add_argument("year_pos", nargs="?", default=None, help="Academic year (e.g. 2026-27)")
    parser.add_argument("--year", dest="year_flag", default=None, help="Academic year (e.g. 2026-27)")
    parser.add_argument("--no-sync", action="store_true", help="Skip syncing from Google Sheets")
    parser.add_argument("--resolutions", default=None, help="JSON file path or string containing discrepancy resolutions")
    args = parser.parse_args()
    year = args.year_flag or args.year_pos or "2026-27"

    resolutions_data = None
    if args.resolutions:
        if os.path.exists(args.resolutions):
            try:
                with open(args.resolutions, "r", encoding="utf-8") as rf:
                    resolutions_data = json.load(rf)
            except Exception as e:
                print(f"[Warning] Could not load resolutions from {args.resolutions}: {e}")
        else:
            try:
                resolutions_data = json.loads(args.resolutions)
            except Exception as e:
                print(f"[Warning] Could not parse resolutions JSON string: {e}")

    run_schedule_generation(academic_year=year, sync_first=not args.no_sync, resolutions=resolutions_data)
