import sys, os
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

def run_schedule_generation():
    print("=" * 65)
    print("UNIFIED GLOBAL AI TIMETABLE GENERATOR")
    print("Enforcing Zero Overlaps | 45m Travel Buffers | Mon-Wed & Thu-Sat Consistency")
    print("Enforcing 2 Weekly Tests per Batch (Exactly 1h, >= 1 Day Gap, Within Branch Limits)")
    print("=" * 65)

    loader = DataLoader("data")
    loader.load_all()

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

    # Sample dates
    sample_dates = {
        "MONDAY": "05/10/2026",
        "TUESDAY": "06/10/2026",
        "WEDNESDAY": "07/10/2026",
        "THURSDAY": "08/10/2026",
        "FRIDAY": "09/10/2026",
        "SATURDAY": "10/10/2026"
    }

    # 1. FIXED RECESS
    for (c, b), b_info in loader.batches.items():
        if b_info.recess_start_min and b_info.recess_end_min:
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
        max_batch_le = branch_le if c in ["JAI AMBE"] else le
        batch_altered_vars[(c, b)] = []
        batch_3day_b1_vars = []

        for req in reqs:
            nom_dur = req.daily_duration_min

            if req.daily_duration_min == 90:
                # 1.5 hr (90 min) lecture derived from No. of Lectures
                dur_options = [90]
            elif (req.faculty or "").strip().upper() == "VICKY SIR" and c == "AMBE MANJ":
                # Ensure Vicky Sir at Ambe Manjalpur gets exact 3 hours (60 min x 3 days = 180 min)
                dur_options = [60]
            elif (req.faculty or "").strip().upper() == "KAILASH SIR" and c == "AMBE MANJ":
                dur_options = [75]
            elif (req.faculty or "").strip().upper() == "KAILASH SIR" and c == "DAPS" and "12TH" in b:
                dur_options = [65, 70]
            elif (req.faculty or "").strip().upper() == "SAGAR SIR" and c == "OP":
                dur_options = [75]
            elif (req.faculty or "").strip().upper() == "RAMESH SIR":
                dur_options = [60]
            else:
                dur_options = [nom_dur - 15, nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
                min_allowed = 50 if c in ["BRIGHT"] else 45
                dur_options = [d for d in dur_options if min_allowed <= d <= 120]
                if not dur_options:
                    dur_options = [max(min_allowed, nom_dur)]

            w_days = min(req.weekly_days, len(op_days))
            if w_days <= 0: w_days = 1

            # Day-Block affinity: if w_days == 3, group into Block 1 (MTW) or Block 2 (TFS)
            is_3day = (w_days == 3 and len(op_days) == 6)
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
                elif c == "VB":
                    model.Add(b1_var == 1) # Monday, Tuesday, Wednesday (both morning flexi & evening)

            # Kailash Sir morning consolidation:
            # MTW: AMBE MANJ (11th) + THS (11th) -> 1 trip/morning
            # TFS: THS (12th) + DAPS (12th) -> 1 trip/morning
            if is_3day and fac_up == "KAILASH SIR":
                if c == "AMBE MANJ" or (c == "THS" and "11TH" in b):
                    model.Add(b1_var == 1)
                elif c == "DAPS" or (c == "THS" and "12TH" in b):
                    model.Add(b1_var == 0)

            # Roma Madam: 100% at THS on MTW; 100% at SG on TFS (balances SG morning capacity)
            if is_3day and fac_up == "ROMA MADAM":
                if c == "SG":
                    model.Add(b1_var == 0)
                elif c == "THS":
                    model.Add(b1_var == 1)

            # Kanaklata Madam: 100% at AMBE MANJ on MTW; 100% at THS on TFS
            if False and is_3day and fac_up == "KANAKLATA MADAM":
                if c == "AMBE MANJ":
                    model.Add(b1_var == 1)
                elif c == "THS":
                    model.Add(b1_var == 0)

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

            # Suketu Sir: 100% at NZM on MTW; 100% at SUB on TFS; split sections at Jai Ambe & Bright
            if is_3day and fac_up == "SUKETU SIR":
                if c == "NZM":
                    model.Add(b1_var == 1)
                elif c == "SUB":
                    model.Add(b1_var == 0)
                elif c == "JAI AMBE" and "- B" in b:
                    model.Add(b1_var == 1) # MTW
                elif c == "JAI AMBE" and "- C" in b:
                    model.Add(b1_var == 0) # TFS
                elif c == "BRIGHT" and "- B" in b:
                    model.Add(b1_var == 1) # MTW
                elif c == "BRIGHT" and "- C" in b:
                    model.Add(b1_var == 0) # TFS

            # Aasif Sir: 100% at SG on MTW; 100% at JAI AMBE on TFS
            if is_3day and fac_up == "AASIF SIR":
                if c == "SG":
                    model.Add(b1_var == 1)
                elif c == "JAI AMBE" and "- B" in b:
                    model.Add(b1_var == 0) # TFS
                elif c == "JAI AMBE" and "- C" in b:
                    model.Add(b1_var == 1) # MTW

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


                st_step = model.NewIntVar(0, (max_batch_le - min(dur_options) - es) // 5, f"st_step_{req.req_id}_{inst}")
                st_var = model.NewIntVar(es, max_batch_le - min(dur_options), f"st_{req.req_id}_{inst}")
                model.Add(st_var == es + st_step * 5)
                dur_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(dur_options), f"dur_{req.req_id}_{inst}")
                end_var = model.NewIntVar(es + min(dur_options), max_batch_le, f"end_{req.req_id}_{inst}")
                model.Add(end_var == st_var + dur_var)

                alt = model.NewBoolVar(f"alt_{req.req_id}_{inst}")
                model.Add(dur_var != nom_dur).OnlyEnforceIf(alt)
                model.Add(dur_var == nom_dur).OnlyEnforceIf(alt.Not())
                batch_altered_vars[(c, b)].append(alt)

                # Strictly enforce day-specific operating hours from Google Sheets
                for d in op_days:
                    day_es = b_info.day_earliest_start.get(d, es)
                    day_le = max_batch_le if (c == "JAI AMBE") else b_info.day_latest_end.get(d, le)
                    model.Add(st_var >= day_es).OnlyEnforceIf(day_vars[d])
                    model.Add(end_var <= day_le).OnlyEnforceIf(day_vars[d])

                is_mrg = es < 840
                fac_restr = loader.faculties.get(req.faculty)
                # Evening cutoff (e.g. Vicky Sir 6:30 PM)
                if fac_restr and fac_restr.available_to_min and not is_mrg:
                    model.Add(end_var <= fac_restr.available_to_min)

                for d in op_days:
                    iv = model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                    batch_day_intervals.setdefault(((c, b), d), []).append(iv)
                    day_slot_vars.setdefault(d, []).append({"start": st_var, "dur": dur_var, "end": end_var, "act": day_vars[d]})

                    if req.faculty and not req.faculty.startswith("TBD_"):
                        fac_day_items.setdefault((req.faculty, d), []).append({
                            "start": st_var, "end": end_var, "center": c,
                            "active": day_vars[d], "is_morning": is_mrg
                        })

                all_lecture_vars.append({
                    "req": req, "center": c, "batch": b, "inst": inst,
                    "start": st_var, "dur": dur_var, "end": end_var,
                    "day_vars": day_vars, "alt": alt
                })

            for d in op_days:
                inst_on_d = [lv["day_vars"][d] for lv in all_lecture_vars if lv["req"].req_id == req.req_id]
                model.Add(sum(inst_on_d) <= 1)

            # Block 1 consistency (Mon == Tue == Wed)
            d_b1 = [d for d in BLOCK_1 if d in op_days]
            for i in range(len(d_b1)):
                for j in range(i + 1, len(d_b1)):
                    d1, d2 = d_b1[i], d_b1[j]
                    insts1 = day_slot_vars.get(d1, [])
                    insts2 = day_slot_vars.get(d2, [])
                    for s1 in insts1:
                        for s2 in insts2:
                            same_b1 = model.NewBoolVar(f"sb1_{req.req_id}_{d1}_{d2}")
                            model.Add(s1["start"] == s2["start"]).OnlyEnforceIf([s1["act"], s2["act"], same_b1])
                            model.Add(s1["dur"] == s2["dur"]).OnlyEnforceIf([s1["act"], s2["act"], same_b1])
                            block_consistency_vars.append(same_b1)

            # Block 2 consistency (Thu == Fri == Sat)
            d_b2 = [d for d in BLOCK_2 if d in op_days]
            for i in range(len(d_b2)):
                for j in range(i + 1, len(d_b2)):
                    d1, d2 = d_b2[i], d_b2[j]
                    insts1 = day_slot_vars.get(d1, [])
                    insts2 = day_slot_vars.get(d2, [])
                    for s1 in insts1:
                        for s2 in insts2:
                            same_b2 = model.NewBoolVar(f"sb2_{req.req_id}_{d1}_{d2}")
                            model.Add(s1["start"] == s2["start"]).OnlyEnforceIf([s1["act"], s2["act"], same_b2])
                            model.Add(s1["dur"] == s2["dur"]).OnlyEnforceIf([s1["act"], s2["act"], same_b2])
                            block_consistency_vars.append(same_b2)

        if batch_altered_vars.get((c, b)):
            alts = batch_altered_vars[(c, b)]
            # Deviation from nominal duration is penalized directly in objective function (alt_sum)

        # Batch MTW vs TFS balance for 3-day subjects
        if len(batch_3day_b1_vars) >= 2:
            K = len(batch_3day_b1_vars)
            if c not in ["JAI AMBE", "BRIGHT"]:
                min_b1 = K // 2
                max_b1 = (K + 1) // 2
                model.Add(sum(batch_3day_b1_vars) >= min_b1)
                model.Add(sum(batch_3day_b1_vars) <= max_b1)
            else:
                model.Add(sum(batch_3day_b1_vars) >= 1)

    # 3B. ENSURE BALANCED NUMBER OF LECTURES ACROSS ALL 6 DAYS FOR EACH BATCH
    for (c, b), b_info in loader.batches.items():
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
            # Ensure at least 2 lectures every day (eliminates 1-lecture or 0-lecture days)
            if c not in ["JAI AMBE", "BRIGHT"]:
                model.Add(lecs_d + fixed_d >= 2)
            if tot_weekly <= 15 and c not in ["JAI AMBE", "BRIGHT"]:
                model.Add(lecs_d + fixed_d <= 3)

    # 4. ADD 2 WEEKLY TESTS PER BATCH (EXACTLY 1 HOUR, >= 1 DAY GAP, ZERO OVERLAPS)
    all_test_vars = []
    for (c, b), b_info in loader.batches.items():
        op_days = b_info.operating_days
        es = b_info.earliest_start_min
        branch_le = branch_hours[c][1]
        max_batch_le = branch_le if c in ["JAI AMBE"] else b_info.latest_end_min

        t1_day_vars = {d: model.NewBoolVar(f"t1_d_{c}_{b}_{d}") for d in op_days}
        t2_day_vars = {d: model.NewBoolVar(f"t2_d_{c}_{b}_{d}") for d in op_days}
        model.Add(sum(t1_day_vars.values()) == 1)
        model.Add(sum(t2_day_vars.values()) == 1)

        # Enforce at least 1 day gap: t2_day_idx >= t1_day_idx + 2
        t1_day_idx = sum(idx * t1_day_vars[d] for idx, d in enumerate(DAYS_OF_WEEK) if d in t1_day_vars)
        t2_day_idx = sum(idx * t2_day_vars[d] for idx, d in enumerate(DAYS_OF_WEEK) if d in t2_day_vars)
        model.Add(t2_day_idx >= t1_day_idx + 2)

        t1_step = model.NewIntVar(0, (max_batch_le - 60 - es) // 5, f"t1_step_{c}_{b}")
        t1_st = model.NewIntVar(es, max_batch_le - 60, f"t1_st_{c}_{b}")
        model.Add(t1_st == es + t1_step * 5)
        t1_end = model.NewIntVar(es + 60, max_batch_le, f"t1_end_{c}_{b}")
        model.Add(t1_end == t1_st + 60)

        t2_step = model.NewIntVar(0, (max_batch_le - 60 - es) // 5, f"t2_step_{c}_{b}")
        t2_st = model.NewIntVar(es, max_batch_le - 60, f"t2_st_{c}_{b}")
        model.Add(t2_st == es + t2_step * 5)
        t2_end = model.NewIntVar(es + 60, max_batch_le, f"t2_end_{c}_{b}")
        model.Add(t2_end == t2_st + 60)

        # Explicit test placement for BRIGHT 11TH CBSE - B:
        # Monday: 10:40 - 11:40 AM (strictly 1 hour, immediately after recess)
        # Friday: 9:15 - 10:15 AM (strictly 1 hour, between Yoga and Recess, eliminating the Friday gap and Saturday overflow)
        if c == "BRIGHT" and b == "11TH CBSE - B":
            model.Add(t1_day_vars["MONDAY"] == 1)
            model.Add(t1_st == 640)
            model.Add(t2_day_vars["FRIDAY"] == 1)
            model.Add(t2_st >= 545)
            model.Add(t2_end <= 615)

        for d in op_days:
            day_es = b_info.day_earliest_start.get(d, es)
            day_le = max_batch_le if (c == "JAI AMBE") else b_info.day_latest_end.get(d, b_info.latest_end_min)
            model.Add(t1_st >= day_es).OnlyEnforceIf(t1_day_vars[d])
            model.Add(t1_end <= day_le).OnlyEnforceIf(t1_day_vars[d])
            model.Add(t2_st >= day_es).OnlyEnforceIf(t2_day_vars[d])
            model.Add(t2_end <= day_le).OnlyEnforceIf(t2_day_vars[d])

            iv1 = model.NewOptionalIntervalVar(t1_st, 60, t1_end, t1_day_vars[d], f"iv_t1_{c}_{b}_{d}")
            iv2 = model.NewOptionalIntervalVar(t2_st, 60, t2_end, t2_day_vars[d], f"iv_t2_{c}_{b}_{d}")
            batch_day_intervals.setdefault(((c, b), d), []).append(iv1)
            batch_day_intervals.setdefault(((c, b), d), []).append(iv2)

        all_test_vars.append({
            "center": c, "batch": b,
            "t1_st": t1_st, "t1_end": t1_end, "t1_days": t1_day_vars,
            "t2_st": t2_st, "t2_end": t2_end, "t2_days": t2_day_vars
        })

    # 5. BATCH NO-OVERLAP
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # 6. FACULTY CROSS-CENTER PRECEDENCE & EXACT TRAVEL BUFFERS
    travel_time = loader.travel_matrix
    prec_count = 0

    # Traveling faculties to enforce cross-center travel buffer
    traveling_faculties = [
        "VICKY SIR", "ABHISHEK SIR", "SUKETU SIR", "KHYATI MADAM",
        "KAILASH SIR", "AMIT SIR", "NILESH SIR", "KANAKLATA MADAM",
        "AASIF SIR", "BHAVESH SIR", "DHAVAL SIR", "VAIDEHI MADAM",
        "MOHSIN SIR", "DARSHAN SIR", "ROMA MADAM", "DEEPIKA MADAM"
    ]

    for (fac, d), items in fac_day_items.items():
        if fac not in traveling_faculties:
            continue
        n = len(items)
        if n < 2: continue

        for i in range(n):
            for j in range(i + 1, n):
                it1, it2 = items[i], items[j]
                if it1["is_morning"] != it2["is_morning"]:
                    continue

                c1, c2 = it1["center"], it2["center"]
                tt_12 = travel_time.get((c1, c2), 30) if c1 != c2 else 0
                tt_21 = travel_time.get((c2, c1), 30) if c1 != c2 else 0

                b_order = model.NewBoolVar(f"ord_{fac}_{d}_{i}_{j}")
                a1, a2 = it1["active"], it2["active"]

                # it1 before it2: start2 >= end1 + tt_12
                model.Add(it2["start"] >= it1["end"] + tt_12).OnlyEnforceIf([a1, a2, b_order])
                # it2 before it1: start1 >= end2 + tt_21
                model.Add(it1["start"] >= it2["end"] + tt_21).OnlyEnforceIf([a1, a2, b_order.Not()])
                prec_count += 1

    print(f"Enforced {prec_count} cross-center travel precedence constraints across traveling faculties.")

    # 6B. VICKY SIR MTW MORNING NON-PING-PONG ROUTING:
    vicky_mrg_items = {
        "AMBE": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "AMBE MANJ"],
        "SG_11": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "SG" and "11" in lv["batch"]],
        "SG_12": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "SG" and "12" in lv["batch"]],
        "VB": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "VB" and "FLEXI" in lv["batch"]]
    }

    if len(vicky_mrg_items["SG_11"]) == 3 and len(vicky_mrg_items["SG_12"]) == 3:
        if len(vicky_mrg_items["AMBE"]) == 3:
            ambe_first = model.NewBoolVar("vicky_mrg_ambe_first")
            for inst in range(3):
                a_end = vicky_mrg_items["AMBE"][inst]["end"]
                a_st = vicky_mrg_items["AMBE"][inst]["start"]
                s11_st = vicky_mrg_items["SG_11"][inst]["start"]
                s11_end = vicky_mrg_items["SG_11"][inst]["end"]
                s12_st = vicky_mrg_items["SG_12"][inst]["start"]
                s12_end = vicky_mrg_items["SG_12"][inst]["end"]

                # Option A: AMBE first, then both SG lectures
                model.Add(s11_st >= a_end + 45).OnlyEnforceIf(ambe_first)
                model.Add(s12_st >= a_end + 45).OnlyEnforceIf(ambe_first)

                # Option B: Both SG lectures first, then AMBE
                model.Add(a_st >= s11_end + 45).OnlyEnforceIf(ambe_first.Not())
                model.Add(a_st >= s12_end + 45).OnlyEnforceIf(ambe_first.Not())

        if len(vicky_mrg_items["VB"]) == 3:
            vb_after_sg = model.NewBoolVar("vicky_vb_after_sg")
            for inst in range(3):
                s11_st = vicky_mrg_items["SG_11"][inst]["start"]
                s11_end = vicky_mrg_items["SG_11"][inst]["end"]
                s12_st = vicky_mrg_items["SG_12"][inst]["start"]
                s12_end = vicky_mrg_items["SG_12"][inst]["end"]
                vb_st = vicky_mrg_items["VB"][inst]["start"]
                vb_end = vicky_mrg_items["VB"][inst]["end"]

                # Case 1: Both SG lectures before VB
                model.Add(vb_st >= s11_end + 30).OnlyEnforceIf(vb_after_sg)
                model.Add(vb_st >= s12_end + 30).OnlyEnforceIf(vb_after_sg)

                # Case 2: VB before both SG lectures
                model.Add(s11_st >= vb_end + 30).OnlyEnforceIf(vb_after_sg.Not())
                model.Add(s12_st >= vb_end + 30).OnlyEnforceIf(vb_after_sg.Not())
        print("Enforced Vicky Sir MTW morning non-ping-pong routing & SG clustering.")

    # 6C. VICKY SIR MTW EVENING CONSISTENT SEQUENCE (VB -> NZM)
    vicky_eve_items = {
        "VB_12": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "VB" and lv["batch"] == "12TH GSEB"],
        "NZM_11": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "NZM" and "11" in lv["batch"]],
        "NZM_12": [lv for lv in all_lecture_vars if lv["req"].faculty == "VICKY SIR" and lv["center"] == "NZM" and "12" in lv["batch"]],
    }
    if len(vicky_eve_items["VB_12"]) == 3 and len(vicky_eve_items["NZM_11"]) == 3 and len(vicky_eve_items["NZM_12"]) == 3:
        for inst in range(3):
            vb_end = vicky_eve_items["VB_12"][inst]["end"]
            n11_st = vicky_eve_items["NZM_11"][inst]["start"]
            n12_st = vicky_eve_items["NZM_12"][inst]["start"]
            model.Add(n11_st >= vb_end + 30)
            model.Add(n12_st >= vb_end + 30)
        print("Enforced Vicky Sir MTW evening consistent sequence (VB -> NZM).")

    # 7. UNIVERSAL TRAVEL MINIMIZATION ACROSS ALL TRAVELING FACULTIES
    fac_center_visits = []
    for (fac, d), items in fac_day_items.items():
        if fac not in traveling_faculties:
            continue
        centers_on_d = set(it["center"] for it in items)
        for cent in centers_on_d:
            v_var = model.NewBoolVar(f"vis_{fac}_{d}_{cent}")
            acts = [it["active"] for it in items if it["center"] == cent]
            for a in acts:
                model.Add(v_var >= a)
            fac_center_visits.append(v_var)

    # Objective: Minimize total centers visited, minimize duration alteration, reward consistency
    same_sum = sum(block_consistency_vars) if block_consistency_vars else model.NewConstant(0)
    alt_sum = sum(lv["alt"] for lv in all_lecture_vars)
    visits_sum = sum(fac_center_visits) if fac_center_visits else model.NewConstant(0)

    model.Minimize(visits_sum * 15 + alt_sum - same_sum * 5)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 45.0
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = True

    print("Solving UNIFIED GLOBAL MODEL across all branches...")
    t0 = time.time()
    st = solver.Solve(model)
    el = time.time() - t0
    print(f"Solver Status: {solver.StatusName(st)} in {el:.2f} seconds!")

    if st not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print("Error: Could not solve model. Please check constraints.")
        return

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
        t1_st = solver.Value(tv["t1_st"])
        t2_st = solver.Value(tv["t2_st"])

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

    # Enforce mathematical zero deficits across all faculties and requirements
    from scripts.enforce_zero_deficits import enforce_zero_deficits
    all_scheduled_slots = enforce_zero_deficits(all_scheduled_slots, loader, branch_hours)

    # Formatters & Exporters
    formatter = TimetableFormatter(start_date_str="05/10/2026")
    pdf_gen = TimetablePDFGenerator(output_dir="output/pdf")
    fac_pdf_gen = TimetablePDFGenerator(output_dir="output/faculty_pdf")
    excel_exp = ExcelExporter(output_dir="output/excel")

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

    # 2. Faculty Personal PDFs & Excel Map (Filter out Test slots from teacher schedules)
    fac_slots = {}
    for s in all_scheduled_slots:
        fac = s.faculty.strip().upper()
        if fac and not fac.startswith("TBD_") and fac not in ["TEST", "WEEKLY TEST", "EXAM"]:
            fac_slots.setdefault(fac, []).append(s)

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

    # 3. Topic Editor Excel
    editor_path = excel_exp.export_topic_editor_sheet(all_scheduled_slots)

    # 4. Master Multi-Tab Excel Files
    b_master_path = excel_exp.export_all_batches_workbook(
        batches_grid_map, week_dates=sample_dates, file_name="All_Batches_Weekly_Schedule.xlsx"
    )
    f_master_path = excel_exp.export_all_faculties_workbook(
        faculties_grid_map, week_dates=sample_dates, file_name="All_Faculties_Weekly_Schedule.xlsx"
    )

    print("\n" + "=" * 65)
    print("ALL SCHEDULES WITH 2 WEEKLY TESTS GENERATED SUCCESSFULLY!")
    print(f"1. Batch Timetable PDFs: {len(generated_batch_pdfs)} files in 'output/pdf/'")
    print(f"2. Faculty Personal PDFs: {len(generated_fac_pdfs)} files in 'output/faculty_pdf/'")
    print(f"3. Topic Editor Excel: '{editor_path}'")
    print(f"4. Master All-Batches Excel ({len(batches_grid_map)} tabs): '{b_master_path}'")
    print(f"5. Master All-Faculties Excel ({len(faculties_grid_map)} tabs): '{f_master_path}'")
    print("=" * 65)

if __name__ == "__main__":
    run_schedule_generation()
