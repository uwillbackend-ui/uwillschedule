import sys, os, time
sys.path.insert(0, os.path.abspath("."))
from ortools.sat.python import cp_model
from src.data_loader import DataLoader, DAYS_OF_WEEK
from src.models import ScheduledSlot
from src.rules_engine import load_standing_rules, audit_schedule_against_rules, print_audit_report

def run_test(academic_year="2026-27"):
    print(f"\n=======================================================")
    print(f" TESTING ALL-RULES UNIFIED SOLVER [{academic_year}]")
    print(f"=======================================================")
    data_dir = "data" if academic_year == "2026-27" else "data_2027_28"
    loader = DataLoader(data_dir)
    loader.load_all()

    branch_hours = {}
    for (c, b), b_info in loader.batches.items():
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        if c not in branch_hours: branch_hours[c] = [es, le]
        else:
            branch_hours[c][0] = min(branch_hours[c][0], es)
            branch_hours[c][1] = max(branch_hours[c][1], le)

    # Clean requirements
    cleaned_requirements = []
    for req in loader.subject_requirements:
        if req.center == "VB" and req.batch == "12TH GSEB" and req.subject == "STATISTICS":
            req.faculty = "VICKY SIR"; req.weekly_days = 3; req.daily_duration_min = 60
        elif req.center == "SG" and req.batch == "12TH GSEB" and req.subject == "STATISTICS":
            req.faculty = "VICKY SIR"; req.weekly_days = 3; req.daily_duration_min = 60
        elif req.center == "BRIGHT" and req.subject == "ECONOMICS":
            req.weekly_days = 3; req.daily_duration_min = 60
        elif req.center in ["OP", "PNG", "NZM"] and "SY B.COM" in req.batch and "CORPORATE" in req.subject:
            req.weekly_days = 2; req.daily_duration_min = 60
        cleaned_requirements.append(req)
    loader.subject_requirements = cleaned_requirements

    model = cp_model.CpModel()
    batch_day_intervals = {}
    fac_day_items = {}
    batch_altered_vars = {}
    all_lecture_vars = []

    BLOCK_1 = ["MONDAY", "TUESDAY", "WEDNESDAY"]
    BLOCK_2 = ["THURSDAY", "FRIDAY", "SATURDAY"]

    # 1. Recesses
    for (c, b), b_info in loader.batches.items():
        if b_info.recess_mode == "Flexible" and b_info.recess_earliest_start_min and b_info.recess_latest_end_min:
            dur = b_info.recess_duration_min or 30
            es_rec, le_rec = b_info.recess_earliest_start_min, b_info.recess_latest_end_min
            rec_step = model.NewIntVar(0, (le_rec - dur - es_rec) // 5, f"rec_step_{c}_{b}")
            rec_st = model.NewIntVar(es_rec, le_rec - dur, f"rec_st_{c}_{b}")
            model.Add(rec_st == es_rec + rec_step * 5)
            rec_end = model.NewIntVar(es_rec + dur, le_rec, f"rec_end_{c}_{b}")
            model.Add(rec_end == rec_st + dur)
            for d in b_info.operating_days:
                batch_day_intervals.setdefault(((c, b), d), []).append(model.NewIntervalVar(rec_st, dur, rec_end, f"rec_{c}_{b}_{d}"))
        elif b_info.recess_start_min and b_info.recess_end_min:
            rst, ret = b_info.recess_start_min, b_info.recess_end_min
            for d in b_info.operating_days:
                batch_day_intervals.setdefault(((c, b), d), []).append(model.NewFixedSizeIntervalVar(rst, ret - rst, f"rec_{c}_{b}_{d}"))

    # 2. Fixed visiting lectures
    fixed_slots = []
    for vf in loader.fixed_lectures:
        dur = vf.end_min - vf.start_min
        if dur <= 0: continue
        batch_day_intervals.setdefault(((vf.center, vf.batch), vf.day), []).append(model.NewFixedSizeIntervalVar(vf.start_min, dur, f"vf_{vf.center}_{vf.batch}_{vf.day}_{vf.start_min}"))
        fac_clean = (vf.faculty or "").strip().upper()
        fac_list = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
        for fn in fac_list:
            if fn == "ASIF SIR": fn = "AASIF SIR"
            if fn in loader.faculties:
                fac_day_items.setdefault((fn, vf.day), []).append({
                    "start": model.NewConstant(vf.start_min), "end": model.NewConstant(vf.end_min),
                    "center": vf.center, "active": model.NewConstant(1), "is_morning": vf.start_min < 840
                })
        fixed_slots.append(ScheduledSlot(
            batch_key=f"{vf.center}_{vf.batch}", center=vf.center, batch_name=vf.batch,
            day=vf.day, start_min=vf.start_min, end_min=vf.end_min, subject=vf.subject,
            faculty=vf.faculty, is_fixed=True
        ))

    # 3. Regular Requirements
    req_by_batch = {}
    for req in loader.subject_requirements:
        req_by_batch.setdefault((req.center, req.batch), []).append(req)

    for (c, b), reqs in req_by_batch.items():
        b_info = loader.batches.get((c, b))
        if not b_info: continue
        op_days = b_info.operating_days
        es, le = b_info.earliest_start_min, b_info.latest_end_min
        max_batch_le = le
        batch_altered_vars[(c, b)] = []

        for req in reqs:
            nom_dur = req.daily_duration_min
            fac_upper = (req.faculty or "").strip().upper()
            if fac_upper == "MANISH SIR": dur_options = [75, 90] if nom_dur >= 85 else [60]
            elif fac_upper == "VIJAY SIR": dur_options = [75]
            elif req.daily_duration_min == 90: dur_options = [60, 75, 90]
            elif fac_upper == "VICKY SIR" and c == "AMBE MANJ": dur_options = [60]
            elif fac_upper == "KAILASH SIR" and c == "AMBE MANJ": dur_options = [60]
            elif fac_upper == "KAILASH SIR" and c == "DAPS" and "12TH" in b: dur_options = [60]
            elif fac_upper == "SAGAR SIR" and c == "OP": dur_options = [75]
            elif any(fn in fac_upper for fn in ["MANSI", "NAMRATA", "SUNIL", "TRUPTI", "RAMESH", "ARJITA"]): dur_options = [60]
            elif fac_upper == "KANAKLATA MADAM": dur_options = [nom_dur] if nom_dur <= 50 else [60]
            elif fac_upper == "MOHSIN SIR": dur_options = [90] if nom_dur >= 85 else ([75] if nom_dur >= 70 else [60])
            elif fac_upper == "SUKETU SIR" and c == "SUB": dur_options = [60]
            else:
                dur_options = [nom_dur - 15, nom_dur - 10, nom_dur - 5, nom_dur, nom_dur + 5, nom_dur + 10]
                min_allowed = 50 if c != "THS" else 45
                dur_options = [d for d in dur_options if min_allowed <= d <= 120]
                if not dur_options: dur_options = [max(min_allowed, nom_dur)]

            w_days = min(req.weekly_days, len(op_days))
            if w_days <= 0: w_days = 1
            is_3day = (w_days == 3 and len(op_days) == 6 and c != "THS")
            b1_var = model.NewBoolVar(f"b1_{req.req_id}") if is_3day else None

            # Block Affinities
            fac_up = (req.faculty or "").strip().upper()
            if is_3day and fac_up == "VICKY SIR":
                if c == "JAI AMBE": model.Add(b1_var == 0)
                elif c in ["SG", "AMBE MANJ", "NZM", "VB"]: model.Add(b1_var == 1)
                elif c == "SUB": model.Add(b1_var == 0)
            if is_3day and fac_up == "KAILASH SIR":
                if c == "AMBE MANJ" or (c == "THS" and "11TH" in b): model.Add(b1_var == 1)
                elif c == "DAPS" or (c == "THS" and "12TH" in b): model.Add(b1_var == 0)
            if is_3day and fac_up == "ROMA MADAM" and c == "SG": model.Add(b1_var == 0)
            if is_3day and fac_up == "KANAKLATA MADAM" and c == "AMBE MANJ": model.Add(b1_var == 1)
            # if is_3day and fac_up == "MOHSIN SIR":
            #     if c == "THS" and "11TH" in b: model.Add(b1_var == 1)
            #     elif c == "THS" and "12TH" in b: model.Add(b1_var == 0)
            if is_3day and fac_up == "AMIT SIR":
                if c == "OP": model.Add(b1_var == 1)
                elif c == "VB": model.Add(b1_var == 0)
            if is_3day and fac_up == "BHAVESH SIR":
                if c == "OP": model.Add(b1_var == 1)
                elif c == "VB": model.Add(b1_var == 0)
            if is_3day and fac_up == "AASIF SIR":
                if c == "SG": model.Add(b1_var == 1)
                elif c == "JAI AMBE" and "B" in b: model.Add(b1_var == 0)
                elif c == "JAI AMBE" and "C" in b: model.Add(b1_var == 1)
            if is_3day and fac_up == "DEEPIKA MADAM":
                if c == "DAPS" and "11" in b: model.Add(b1_var == 1)
                elif c == "DAPS" and "12" in b: model.Add(b1_var == 0)
            if is_3day and fac_up == "ABHISHEK SIR":
                if c == "SUB": model.Add(b1_var == 1)
                elif c == "VB": model.Add(b1_var == 0)
            if is_3day and fac_up == "DARSHAN SIR":
                if c == "BRIGHT": model.Add(b1_var == 1)
                # elif c == "DAPS": model.Add(b1_var == 1)
                # elif c in ["VB", "AMBE MANJ"]: model.Add(b1_var == 0)

            for inst in range(w_days):
                day_vars = {d: model.NewBoolVar(f"d_{req.req_id}_{inst}_{d}") for d in op_days}
                model.Add(sum(day_vars.values()) == 1)
                if is_3day:
                    model.Add(day_vars[BLOCK_1[inst]] == 1).OnlyEnforceIf(b1_var)
                    model.Add(day_vars[BLOCK_2[inst]] == 1).OnlyEnforceIf(b1_var.Not())
                if c == "THS" and w_days == 3 and "SATURDAY" in day_vars: model.Add(day_vars["SATURDAY"] == 0)

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

                is_mrg = es < 840
                fac_clean = (req.faculty or "").strip().upper()
                if fac_clean == "ASIF SIR": fac_clean = "AASIF SIR"

                for d in op_days:
                    day_es = b_info.day_earliest_start.get(d, es)
                    day_le = b_info.day_latest_end.get(d, le)
                    if day_es > es:
                        model.Add(st_var >= day_es).OnlyEnforceIf(day_vars[d])
                    if day_le < le:
                        model.Add(end_var <= day_le).OnlyEnforceIf(day_vars[d])

                    # Strictly enforce day-specific faculty restrictions from "faculty details"
                    fac_names_check = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
                    for fn in fac_names_check:
                        if fn == "ASIF SIR": fn = "AASIF SIR"
                        f_restr = loader.faculties.get(fn)
                        if f_restr and d in f_restr.day_limits:
                            lim = f_restr.day_limits[d]
                            if is_mrg:
                                if lim.get("mrg_from") is not None and lim.get("mrg_to") is not None and lim["mrg_from"] == lim["mrg_to"]:
                                    model.Add(day_vars[d] == 0)
                                else:
                                    if lim.get("mrg_from") is not None:
                                        model.Add(st_var >= lim["mrg_from"]).OnlyEnforceIf(day_vars[d])
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

                    batch_day_intervals.setdefault(((c, b), d), []).append(
                        model.NewOptionalIntervalVar(st_var, dur_var, end_var, day_vars[d], f"iv_{req.req_id}_{inst}_{d}")
                    )
                    fac_names = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
                    for fn in fac_names:
                        if fn == "ASIF SIR": fn = "AASIF SIR"
                        if fn and not fn.startswith("TBD_"):
                            fac_day_items.setdefault((fn, d), []).append({
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

    # English / Computer clustering on same day for Vishal Sir & Priyanka Madam:
    for center_code in ["SUB", "OP", "NZM", "VB", "PNG", "DAPS"]:
        v_lvs = [lv for lv in all_lecture_vars if lv["req"].faculty == "VISHAL SIR" and lv["center"] == center_code]
        p_lvs = [lv for lv in all_lecture_vars if lv["req"].faculty == "PRIYANKA MADAM" and lv["center"] == center_code]
        if v_lvs and p_lvs:
            for d in DAYS_OF_WEEK:
                v_acts = [lv["day_vars"][d] for lv in v_lvs if d in lv["day_vars"]]
                p_acts = [lv["day_vars"][d] for lv in p_lvs if d in lv["day_vars"]]
                if v_acts and p_acts:
                    v_on_d = model.NewBoolVar(f"v_{center_code}_{d}")
                    p_on_d = model.NewBoolVar(f"p_{center_code}_{d}")
                    model.AddMaxEquality(v_on_d, v_acts)
                    model.AddMaxEquality(p_on_d, p_acts)
                    model.Add(v_on_d == p_on_d)

    # 4. Weekly Tests (RULE_001: No test on Monday)
    all_test_vars = []
    for (c, b), b_info in loader.batches.items():
        if "B.COM" in b or (c == "PNG" and "MRG" in b): continue
        op_days = b_info.operating_days
        test_days = [d for d in op_days if d != "MONDAY"]
        es, le = b_info.earliest_start_min, b_info.latest_end_min

        t1_day_vars = {d: model.NewBoolVar(f"t1_d_{c}_{b}_{d}") for d in test_days}
        t2_day_vars = {d: model.NewBoolVar(f"t2_d_{c}_{b}_{d}") for d in test_days}
        model.Add(sum(t1_day_vars.values()) == 1)
        model.Add(sum(t2_day_vars.values()) == 1)

        t1_day_idx = sum(idx * t1_day_vars[d] for idx, d in enumerate(DAYS_OF_WEEK) if d in t1_day_vars)
        t2_day_idx = sum(idx * t2_day_vars[d] for idx, d in enumerate(DAYS_OF_WEEK) if d in t2_day_vars)
        model.Add(t2_day_idx >= t1_day_idx + 2)

        t1_st_vars, t2_st_vars = {}, {}
        for d in test_days:
            day_es = b_info.day_earliest_start.get(d, es)
            day_le = b_info.day_latest_end.get(d, le)

            t1_st_d = model.NewIntVar(day_es, day_le - 60, f"t1_st_{c}_{b}_{d}")
            t1_step_d = model.NewIntVar(0, (day_le - 60 - day_es) // 5, f"t1_step_{c}_{b}_{d}")
            model.Add(t1_st_d == day_es + t1_step_d * 5)
            t1_st_vars[d] = t1_st_d
            batch_day_intervals.setdefault(((c, b), d), []).append(model.NewOptionalIntervalVar(t1_st_d, 60, t1_st_d + 60, t1_day_vars[d], f"iv_t1_{c}_{b}_{d}"))

            t2_st_d = model.NewIntVar(day_es, day_le - 60, f"t2_st_{c}_{b}_{d}")
            t2_step_d = model.NewIntVar(0, (day_le - 60 - day_es) // 5, f"t2_step_{c}_{b}_{d}")
            model.Add(t2_st_d == day_es + t2_step_d * 5)
            t2_st_vars[d] = t2_st_d
            batch_day_intervals.setdefault(((c, b), d), []).append(model.NewOptionalIntervalVar(t2_st_d, 60, t2_st_d + 60, t2_day_vars[d], f"iv_t2_{c}_{b}_{d}"))

        all_test_vars.append({"center": c, "batch": b, "t1_st_vars": t1_st_vars, "t1_days": t1_day_vars, "t2_st_vars": t2_st_vars, "t2_days": t2_day_vars})

    # Batch No-Overlap
    for ((c, b), d), ivs in batch_day_intervals.items():
        model.AddNoOverlap(ivs)

    # 5. RULE_003: PREVENT REPEATED VISITS ACROSS ALL FACULTIES
    travel_time = loader.travel_matrix

    for (fac, d), items in fac_day_items.items():
        n = len(items)
        if n < 2: continue
        centers_list = sorted(list(set(it["center"] for it in items)))
        if len(centers_list) < 2: continue

        for ci in range(len(centers_list)):
            for cj in range(ci + 1, len(centers_list)):
                c1, c2 = centers_list[ci], centers_list[cj]
                c1_items = [it for it in items if it["center"] == c1]
                c2_items = [it for it in items if it["center"] == c2]
                tt_12 = travel_time.get((c1, c2), 30)
                tt_21 = travel_time.get((c2, c1), 30)

                b_order = model.NewBoolVar(f"cent_{fac}_{d}_{c1}_{c2}")
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

    # Mohsin Sir: THS morning before PNG
    mohsin_ths = [lv for lv in all_lecture_vars if lv["req"].faculty == "MOHSIN SIR" and lv["center"] == "THS"]
    mohsin_png = [lv for lv in all_lecture_vars if lv["req"].faculty == "MOHSIN SIR" and lv["center"] == "PNG"]
    for mths in mohsin_ths:
        for mpng in mohsin_png:
            for d in DAYS_OF_WEEK:
                if d in mths["day_vars"] and d in mpng["day_vars"]:
                    model.Add(mpng["start"] >= mths["end"] + 30).OnlyEnforceIf([mths["day_vars"][d], mpng["day_vars"][d]])

    # Sunil Sir: finishes SG in the early morning before Bright fixed (which starts at 640)
    sunil_sg = [lv for lv in all_lecture_vars if lv["req"].faculty == "SUNIL SIR" and lv["center"] == "SG"]
    for ssg in sunil_sg:
        if "TUESDAY" in ssg["day_vars"]:
            model.Add(ssg["day_vars"]["TUESDAY"] == 0)
        for d in ["THURSDAY", "FRIDAY", "SATURDAY"]:
            if d in ssg["day_vars"]:
                model.Add(ssg["end"] <= 610).OnlyEnforceIf(ssg["day_vars"][d])

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
        base_es = 960 if (c == "PNG" and "CBSE" in b) else b_info.earliest_start_min
        b_start_var = model.NewIntVar(base_es, base_es + 30, f"bstart_{c}_{b}")
        b_step = model.NewIntVar(0, 2, f"bstep_{c}_{b}")
        model.Add(b_start_var == base_es + b_step * 15)

        for d, (bmin, any_act, ev_list) in day_dict.items():
            for ev in ev_list:
                model.Add(ev["start"] >= b_start_var).OnlyEnforceIf(ev["act"])
            first_indicators = []
            for k, ev in enumerate(ev_list):
                is_f = model.NewBoolVar(f"isf_{c}_{b}_{d}_{k}")
                model.Add(ev["start"] == b_start_var).OnlyEnforceIf(is_f)
                model.Add(is_f <= ev["act"])
                first_indicators.append(is_f)
            model.Add(sum(first_indicators) == 1).OnlyEnforceIf(any_act)

    alt_sum = sum(lv["alt"] for lv in all_lecture_vars)
    model.Minimize(sum(eve_gap_penalties) * 10000 + alt_sum * 10)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 75.0
    solver.parameters.num_workers = 8
    print("Solving full unified CP-SAT model with ALL rules...")
    t0 = time.time()
    st = solver.Solve(model)
    el = time.time() - t0
    print(f"Solver Status: {solver.StatusName(st)} in {el:.2f}s!")

    if st not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print("Model could not find feasible solution!")
        return False

    # Extract all slots
    all_scheduled_slots = list(fixed_slots)
    for lv in all_lecture_vars:
        req = lv["req"]
        st_val = solver.Value(lv["start"])
        end_val = solver.Value(lv["end"])
        for d in loader.batches[lv["center"], lv["batch"]].operating_days:
            if d in lv["day_vars"] and solver.Value(lv["day_vars"][d]) == 1:
                all_scheduled_slots.append(ScheduledSlot(
                    batch_key=f"{lv['center']}_{lv['batch']}", center=lv["center"], batch_name=lv["batch"],
                    day=d, start_min=st_val, end_min=end_val, subject=req.subject, faculty=req.faculty, is_fixed=False
                ))

    for tv in all_test_vars:
        c, b = tv["center"], tv["batch"]
        t1_d = [d for d in tv["t1_days"] if solver.Value(tv["t1_days"][d]) == 1][0]
        t2_d = [d for d in tv["t2_days"] if solver.Value(tv["t2_days"][d]) == 1][0]
        t1_st = solver.Value(tv["t1_st_vars"][t1_d])
        t2_st = solver.Value(tv["t2_st_vars"][t2_d])
        all_scheduled_slots.append(ScheduledSlot(
            batch_key=f"{c}_{b}", center=c, batch_name=b, day=t1_d,
            start_min=t1_st, end_min=t1_st + 60, subject="WEEKLY TEST", faculty="WEEKLY TEST", is_fixed=True
        ))
        all_scheduled_slots.append(ScheduledSlot(
            batch_key=f"{c}_{b}", center=c, batch_name=b, day=t2_d,
            start_min=t2_st, end_min=t2_st + 60, subject="WEEKLY TEST", faculty="WEEKLY TEST", is_fixed=True
        ))

    standing_rules = load_standing_rules(academic_year=academic_year)
    pre_audit = audit_schedule_against_rules(all_scheduled_slots, standing_rules, loader=loader)
    print_audit_report(pre_audit, title=f"PRE-EXPANSION AUDIT [{academic_year}] (DIRECT FROM CP-SAT)")

    from scripts.enforce_zero_deficits import enforce_zero_deficits
    all_scheduled_slots = enforce_zero_deficits(all_scheduled_slots, loader, branch_hours)

    audit_res = audit_schedule_against_rules(all_scheduled_slots, standing_rules, loader=loader)
    print_audit_report(audit_res, title=f"COMPREHENSIVE AUDIT REPORT [{academic_year}]")
    return audit_res["is_valid"]

if __name__ == "__main__":
    run_test("2026-27")
