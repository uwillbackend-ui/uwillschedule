import os
import re
import json
import uuid
import openpyxl
from typing import Dict, List, Optional, Tuple
from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str, DAYS_OF_WEEK
from src.ai_assistant import get_excel_path, load_timetable_slots, call_gemini_raw

# In-memory store for pending proposals: token -> proposal dict
PENDING_PROPOSALS: Dict[str, dict] = {}

def get_loader():
    loader = DataLoader("data")
    loader.load_all()
    return loader

def parse_time_range(t_str: str) -> Tuple[Optional[int], Optional[int]]:
    if not t_str:
        return None, None
    clean = t_str.replace("–", "-").replace("TO", "-").replace("to", "-")
    parts = clean.split("-")
    if len(parts) == 2:
        st = parse_time_to_minutes(parts[0].strip())
        et = parse_time_to_minutes(parts[1].strip())
        return st, et
    st = parse_time_to_minutes(parts[0].strip())
    return st, None

def find_matching_slots(slots: list, faculty: str = None, subject: str = None,
                        center: str = None, batch: str = None, day: str = None) -> list:
    res = list(slots)
    if day:
        day_clean = day.strip().upper()
        res = [s for s in res if s["day"] == day_clean or day_clean in s["day"]]
    if center:
        c_clean = center.strip().upper()
        res = [s for s in res if c_clean in s["center"].upper()]
    if batch:
        b_clean = batch.strip().upper()
        res = [s for s in res if b_clean in s["batch"].upper()]
    if faculty:
        f_clean = faculty.strip().upper().replace(" SIR", "").replace(" MADAM", "")
        res = [s for s in res if f_clean in s["faculty"].upper()]
    if subject:
        s_clean = subject.strip().upper()
        res = [s for s in res if s_clean in s["subject"].upper()]
    return res

def parse_reschedule_intent(user_instruction: str, active_slots: list) -> dict:
    """Uses Gemini to parse user's rescheduling instruction into structured parameters,
    with heuristic fallback if LLM is unavailable."""
    system_prompt = """You are an Operations Research Timetable Assistant for U WILL CLASSES.
Analyze the user's plain-English timetable modification instruction and output ONLY a valid JSON object.
Schema:
{
  "action": "MOVE" | "SWAP" | "ADD" | "DELETE" | "REPLACE_FACULTY",
  "faculty": string or null,
  "subject": string or null,
  "center": string or null,
  "batch": string or null,
  "source_day": "MONDAY"|"TUESDAY"|"WEDNESDAY"|"THURSDAY"|"FRIDAY"|"SATURDAY" or null,
  "source_time": string or null,
  "target_day": "MONDAY"|"TUESDAY"|"WEDNESDAY"|"THURSDAY"|"FRIDAY"|"SATURDAY" or null,
  "target_time": string or null (e.g. "8:30 AM" or "8:30 AM - 9:30 AM"),
  "duration_min": integer or null (e.g. 45, 60, 75, 90),
  "new_faculty": string or null (for REPLACE_FACULTY),
  "new_subject": string or null,
  "target_center": string or null,
  "target_batch": string or null,
  "notes": string
}
Do not include markdown fences or other text, only the raw JSON.
"""
    raw_json = call_gemini_raw(system_prompt, f"Instruction: {user_instruction}", timeout=6)
    proposal = None
    if raw_json:
        try:
            clean_str = raw_json.strip()
            if clean_str.startswith("```"):
                clean_str = re.sub(r"^```[a-z]*\n", "", clean_str)
                clean_str = re.sub(r"\n```$", "", clean_str)
            proposal = json.loads(clean_str)
        except Exception:
            proposal = None

    if not proposal:
        # Heuristic fallback parser
        q = user_instruction.upper()
        action = "MOVE"
        if "SWAP" in q: action = "SWAP"
        elif "ADD" in q or "FILL" in q: action = "ADD"
        elif "CANCEL" in q or "DELETE" in q or "REMOVE" in q: action = "DELETE"
        elif "REPLACE" in q or "SUBSTITUTE" in q or "CHANGE" in q: action = "REPLACE_FACULTY"

        days_found = [d for d in DAYS_OF_WEEK if d in q or d[:3] in q]
        src_day = days_found[0] if len(days_found) > 0 else None
        tgt_day = days_found[1] if len(days_found) > 1 else src_day

        time_match = re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM)\b", q)
        tgt_time = time_match[0] if time_match else None

        fac = None
        new_fac = None
        for f in ["VICKY", "NILESH", "DARSHAN", "SUKETU", "KAILASH", "AASIF", "DHAVAL", "KAMAL", "MOHSIN", "KANAKLATA", "VAIDEHI", "BHAVESH", "SAHDEV"]:
            if f in q:
                resolved_f = f"{f} SIR" if f not in ["KANAKLATA", "VAIDEHI"] else f"{f} MADAM"
                if action == "REPLACE_FACULTY" and " WITH " in q and f in q.split(" WITH ", 1)[1]:
                    new_fac = resolved_f
                else:
                    fac = resolved_f

        subj = None
        new_subj = None
        all_subjects = ["ACCOUNTS", "STATISTICS", "STATS", "ECONOMICS", "BUSINESS STUDIES", "BST", "OCM", "ENGLISH", "YOGA", "IP/PE/MATHS", "ME", "IED"]
        if action == "REPLACE_FACULTY" and " WITH " in q:
            part_before, part_after = q.split(" WITH ", 1)
            for s in all_subjects:
                if s in part_before and not subj:
                    subj = "STATISTICS" if s == "STATS" else ("BUSINESS STUDIES" if s == "BST" else s)
                if s in part_after and not new_subj:
                    new_subj = "STATISTICS" if s == "STATS" else ("BUSINESS STUDIES" if s == "BST" else s)
        else:
            for s in all_subjects:
                if s in q:
                    subj = "STATISTICS" if s == "STATS" else ("BUSINESS STUDIES" if s == "BST" else s)
                    break

        center = None
        for c in ["BRIGHT", "JAI AMBE", "AMBE MANJ", "OP", "VB", "NZM", "PNG", "SG", "SUB", "THS", "DAPS"]:
            if c in q:
                center = c
                break

        proposal = {
            "action": action,
            "faculty": fac,
            "subject": subj,
            "center": center,
            "batch": None,
            "source_day": src_day,
            "source_time": None,
            "target_day": tgt_day,
            "target_time": tgt_time,
            "duration_min": 60,
            "new_faculty": new_fac,
            "new_subject": new_subj,
            "target_center": center,
            "target_batch": None,
            "notes": user_instruction
        }

    # Post-process and ensure center, batch, faculty, and subject are resolved from active_slots
    q = user_instruction.upper()
    if not proposal.get("center"):
        for c in sorted(list(set(s["center"] for s in active_slots)), key=len, reverse=True):
            if c in q:
                proposal["center"] = c
                break

    if not proposal.get("batch"):
        target_center = proposal.get("center")
        candidate_batches = sorted(list(set(s["batch"] for s in active_slots if (not target_center or s["center"] == target_center))), key=len, reverse=True)
        if not candidate_batches:
            candidate_batches = sorted(list(set(s["batch"] for s in active_slots)), key=len, reverse=True)

        for b in candidate_batches:
            b_norm = b.replace(" - ", " ").replace("-", " ")
            if b in q or b_norm in q or b.replace(" - ", "") in q:
                proposal["batch"] = b
                break

        if not proposal.get("batch"):
            for b in candidate_batches:
                b_tokens = [tok for tok in re.split(r"[\s\-_]+", b.upper()) if tok and tok not in ("TH", "11TH", "12TH", "SECTION")]
                if b_tokens and all(bool(re.search(r"\b" + re.escape(tok) + r"\b", q)) for tok in b_tokens):
                    proposal["batch"] = b
                    break

    if not proposal.get("faculty"):
        for f in sorted(list(set(s["faculty"] for s in active_slots)), key=len, reverse=True):
            f_clean = f.replace(" SIR", "").replace(" MADAM", "")
            if f in q or f_clean in q:
                proposal["faculty"] = f
                break

    if not proposal.get("subject"):
        for s in sorted(list(set(s["subject"] for s in active_slots)), key=len, reverse=True):
            if s in q or (s == "STATISTICS" and "STATS" in q) or (s == "BUSINESS STUDIES" and "BST" in q):
                proposal["subject"] = s
                break

    return proposal

def validate_and_simulate_change(proposal: dict, active_slots: list) -> dict:
    """Validates feasibility, checks for clashes, and simulates before/after state."""
    loader = get_loader()
    action = proposal.get("action", "MOVE")
    fac = proposal.get("faculty")
    subj = proposal.get("subject")
    center = proposal.get("center")
    batch = proposal.get("batch")
    src_day = proposal.get("source_day")
    tgt_day = proposal.get("target_day") or src_day
    tgt_time_str = proposal.get("target_time")
    dur_min = proposal.get("duration_min") or 60

    conflicts = []
    affected_batches = set()
    affected_faculties = set()

    # Find the target slot to move/delete/swap
    matching_slots = []
    if action in ["MOVE", "SWAP", "DELETE", "REPLACE_FACULTY"]:
        if center and batch and src_day:
            if subj:
                matching_slots = find_matching_slots(active_slots, subject=subj, center=center, batch=batch, day=src_day)
            if not matching_slots and fac:
                matching_slots = find_matching_slots(active_slots, faculty=fac, center=center, batch=batch, day=src_day)
        if not matching_slots:
            matching_slots = find_matching_slots(active_slots, faculty=fac, subject=subj,
                                                 center=center, batch=batch, day=src_day)
        if not matching_slots:
            # Relax center or subject filter
            matching_slots = find_matching_slots(active_slots, faculty=fac, day=src_day)

    target_slot = matching_slots[0] if matching_slots else None

    if action in ["MOVE", "SWAP", "DELETE", "REPLACE_FACULTY"] and not target_slot:
        return {
            "valid": False,
            "action": action,
            "error": f"Could not find an existing lecture for {fac or ''} {subj or ''} on {src_day or 'the specified day'}. Please specify the center/batch or day.",
            "conflicts": [f"No matching lecture found for instruction."]
        }

    # Set parameters from found slot if missing
    if target_slot:
        center = center or target_slot["center"]
        batch = batch or target_slot["batch"]
        fac = fac or target_slot["faculty"]
        subj = subj or target_slot["subject"]
        src_day = src_day or target_slot["day"]
        dur_min = dur_min or target_slot.get("dur", 60)

    tgt_st_min = None
    tgt_et_min = None
    if tgt_time_str:
        st_p, et_p = parse_time_range(tgt_time_str)
        tgt_st_min = st_p
        tgt_et_min = et_p if et_p else (tgt_st_min + dur_min if tgt_st_min is not None else None)
    elif target_slot and action in ["REPLACE_FACULTY"]:
        tgt_st_min = parse_time_to_minutes(target_slot["start"])
        tgt_et_min = parse_time_to_minutes(target_slot["end"])

    if tgt_st_min is None and action in ["MOVE", "ADD"]:
        # Find earliest available gap in the batch on target_day
        b_info = loader.batches.get((center, batch))
        if b_info:
            es = b_info.day_earliest_start.get(tgt_day, b_info.earliest_start_min)
            le = b_info.day_latest_end.get(tgt_day, b_info.latest_end_min)
            # Find occupied ranges on tgt_day
            occupied = []
            for s in active_slots:
                if s["center"] == center and s["batch"] == batch and s["day"] == tgt_day:
                    occupied.append((parse_time_to_minutes(s["start"]), parse_time_to_minutes(s["end"])))
            if b_info.recess_start_min and b_info.recess_end_min:
                occupied.append((b_info.recess_start_min, b_info.recess_end_min))
            occupied.sort()

            # Search for free slot
            cand = es
            for occ_s, occ_e in occupied:
                if occ_s - cand >= dur_min:
                    tgt_st_min = cand
                    tgt_et_min = cand + dur_min
                    break
                cand = max(cand, occ_e)
            if tgt_st_min is None and le - cand >= dur_min:
                tgt_st_min = cand
                tgt_et_min = cand + dur_min

        if tgt_st_min is None:
            tgt_st_min = 465 # default 7:45 AM
            tgt_et_min = tgt_st_min + dur_min

    # CHECK CONFLICTS FOR THE PROPOSED TARGET
    if tgt_st_min is not None and tgt_et_min is not None and action in ["MOVE", "ADD", "SWAP"]:
        # 1. Batch overlap check
        for s in active_slots:
            if s["center"] == center and s["batch"] == batch and s["day"] == tgt_day:
                if target_slot and s == target_slot: continue # ignore itself
                s_st = parse_time_to_minutes(s["start"])
                s_et = parse_time_to_minutes(s["end"])
                if max(tgt_st_min, s_st) < min(tgt_et_min, s_et):
                    conflicts.append(f"Batch Overlap: {center} {batch} already has {s['subject']} ({s['faculty']}) from {s['start']} to {s['end']} on {tgt_day}.")

        # 2. Recess overlap check
        b_info = loader.batches.get((center, batch))
        if b_info and b_info.recess_start_min and b_info.recess_end_min:
            if max(tgt_st_min, b_info.recess_start_min) < min(tgt_et_min, b_info.recess_end_min):
                conflicts.append(f"Recess Conflict: Lecture overlaps with designated recess break ({minutes_to_str(b_info.recess_start_min)} to {minutes_to_str(b_info.recess_end_min)}).")

        # 3. Faculty clash check (another center)
        active_fac = proposal.get("new_faculty") if action == "REPLACE_FACULTY" else fac
        if active_fac and not active_fac.startswith("TBD_"):
            for s in active_slots:
                if s["faculty"] == active_fac and s["day"] == tgt_day:
                    if target_slot and s == target_slot: continue
                    s_st = parse_time_to_minutes(s["start"])
                    s_et = parse_time_to_minutes(s["end"])
                    # Direct overlap
                    if max(tgt_st_min, s_st) < min(tgt_et_min, s_et):
                        conflicts.append(f"Faculty Double-Booking: {active_fac} is already teaching {s['subject']} at {s['center']} ({s['batch']}) from {s['start']} to {s['end']} on {tgt_day}.")
                    # Travel buffer check if different center
                    elif s["center"] != center:
                        tt = loader.travel_matrix.get((s["center"], center), 30)
                        if s_et <= tgt_st_min and (tgt_st_min - s_et) < tt:
                            conflicts.append(f"Travel Collision: {active_fac} ends lecture at {s['center']} at {s['end']}, requiring {tt} mins travel to {center}, but proposed lecture starts at {minutes_to_str(tgt_st_min)}.")
                        tt_rev = loader.travel_matrix.get((center, s["center"]), 30)
                        if tgt_et_min <= s_st and (s_st - tgt_et_min) < tt_rev:
                            conflicts.append(f"Travel Collision: Proposed lecture ends at {minutes_to_str(tgt_et_min)}, but {active_fac} must reach {s['center']} by {s['start']} (needs {tt_rev} mins travel).")

        # 4. Strict Faculty Availability Restrictions (from faculty details)
        if active_fac and not active_fac.startswith("TBD_"):
            fac_clean = active_fac.strip().upper()
            if fac_clean == "ASIF SIR":
                fac_clean = "AASIF SIR"
            fac_restr = loader.faculties.get(active_fac) or loader.faculties.get(fac_clean)
            if fac_restr and tgt_day in fac_restr.day_limits:
                lim = fac_restr.day_limits[tgt_day]
                is_mrg = tgt_st_min < 840
                if is_mrg:
                    if lim.get("mrg_from") is not None and lim.get("mrg_to") is not None and lim["mrg_from"] == lim["mrg_to"]:
                        conflicts.append(f"Faculty Restriction: {active_fac} is completely unavailable on {tgt_day} morning.")
                    else:
                        if lim.get("mrg_from") is not None and tgt_st_min < lim["mrg_from"]:
                            conflicts.append(f"Faculty Restriction: {active_fac} cannot start before {minutes_to_str(lim['mrg_from'])} on {tgt_day} (proposed start {minutes_to_str(tgt_st_min)}).")
                        if lim.get("mrg_to") is not None and tgt_et_min > lim["mrg_to"]:
                            conflicts.append(f"Faculty Restriction: {active_fac} cannot teach past {minutes_to_str(lim['mrg_to'])} on {tgt_day} (proposed end {minutes_to_str(tgt_et_min)}).")
                else:
                    if lim.get("eve_from") is not None and lim.get("eve_to") is not None and lim["eve_from"] == lim["eve_to"]:
                        conflicts.append(f"Faculty Restriction: {active_fac} is completely unavailable on {tgt_day} evening.")
                    else:
                        if lim.get("eve_from") is not None and tgt_st_min < lim["eve_from"]:
                            conflicts.append(f"Faculty Restriction: {active_fac} cannot start evening lectures before {minutes_to_str(lim['eve_from'])} on {tgt_day} (proposed start {minutes_to_str(tgt_st_min)}).")
                        if lim.get("eve_to") is not None and tgt_et_min > lim["eve_to"]:
                            conflicts.append(f"Faculty Restriction: {active_fac} cannot teach past {minutes_to_str(lim['eve_to'])} on {tgt_day} (proposed end {minutes_to_str(tgt_et_min)}).")

    affected_batches.add(f"{center} - {batch}")
    if fac: affected_faculties.add(fac)
    if proposal.get("new_faculty"): affected_faculties.add(proposal["new_faculty"])

    # SIMULATE NEW SLOTS
    simulated_slots = [dict(s) for s in active_slots]
    changes_summary = []

    if action == "MOVE" and target_slot:
        # Remove target slot
        simulated_slots = [s for s in simulated_slots if s != target_slot]
        # Insert updated slot
        new_slot = dict(target_slot)
        new_slot["day"] = tgt_day
        new_slot["start"] = minutes_to_str(tgt_st_min)
        new_slot["end"] = minutes_to_str(tgt_et_min)
        new_slot["dur"] = tgt_et_min - tgt_st_min
        simulated_slots.append(new_slot)

        changes_summary.append({
            "type": "MOVE",
            "desc": f"Moved {target_slot['subject']} ({target_slot['faculty']}) from {target_slot['day']} {target_slot['start']}-{target_slot['end']} to {tgt_day} {new_slot['start']}-{new_slot['end']}",
            "center": center, "batch": batch, "faculty": fac,
            "old_day": target_slot["day"], "old_time": f"{target_slot['start']} - {target_slot['end']}",
            "new_day": tgt_day, "new_time": f"{new_slot['start']} - {new_slot['end']}"
        })

    elif action == "DELETE" and target_slot:
        simulated_slots = [s for s in simulated_slots if s != target_slot]
        changes_summary.append({
            "type": "DELETE",
            "desc": f"Cancelled {target_slot['subject']} ({target_slot['faculty']}) on {target_slot['day']} {target_slot['start']}-{target_slot['end']} at {center} {batch}",
            "center": center, "batch": batch, "faculty": fac,
            "old_day": target_slot["day"], "old_time": f"{target_slot['start']} - {target_slot['end']}"
        })

    elif action == "ADD":
        new_slot = {
            "center": center,
            "batch": batch,
            "day": tgt_day,
            "start": minutes_to_str(tgt_st_min),
            "end": minutes_to_str(tgt_et_min),
            "dur": tgt_et_min - tgt_st_min,
            "subject": subj or "EXTRA LECTURE",
            "faculty": fac or "FACULTY",
            "chapter": "School Topic",
            "topic": "Regular Syllabus"
        }
        simulated_slots.append(new_slot)
        changes_summary.append({
            "type": "ADD",
            "desc": f"Added {new_slot['subject']} ({new_slot['faculty']}) on {tgt_day} {new_slot['start']}-{new_slot['end']} at {center} {batch}",
            "center": center, "batch": batch, "faculty": fac,
            "new_day": tgt_day, "new_time": f"{new_slot['start']} - {new_slot['end']}"
        })

    elif action == "REPLACE_FACULTY" and target_slot:
        new_fac = proposal.get("new_faculty") or fac
        new_sub = proposal.get("new_subject")
        if target_slot.get("faculty"):
            affected_faculties.add(target_slot["faculty"])
        if new_fac:
            affected_faculties.add(new_fac)
        for s in simulated_slots:
            if s == target_slot:
                if new_fac:
                    s["faculty"] = new_fac
                if new_sub:
                    s["subject"] = new_sub
        changes_summary.append({
            "type": "REPLACE_FACULTY",
            "desc": f"Updated lecture on {target_slot['day']} {target_slot['start']}-{target_slot['end']} at {center} {batch}: Faculty: {target_slot['faculty']} -> {new_fac or target_slot['faculty']}" + (f", Subject: {target_slot['subject']} -> {new_sub}" if new_sub else ""),
            "center": center, "batch": batch, "faculty": new_fac or target_slot['faculty'],
            "day": target_slot["day"], "time": f"{target_slot['start']} - {target_slot['end']}"
        })

    # GENERATE DIFF PREVIEW
    diff_preview = generate_diff_preview(active_slots, simulated_slots, list(affected_batches), list(affected_faculties), src_day, tgt_day)

    token = f"chg_{uuid.uuid4().hex[:8]}"
    pending_record = {
        "token": token,
        "proposal": proposal,
        "target_slot": target_slot,
        "simulated_slots": simulated_slots,
        "changes_summary": changes_summary,
        "affected_batches": list(affected_batches),
        "affected_faculties": list(affected_faculties),
        "conflicts": conflicts,
        "is_valid": len(conflicts) == 0
    }
    PENDING_PROPOSALS[token] = pending_record

    return {
        "valid": len(conflicts) == 0,
        "token": token,
        "action": action,
        "summary": changes_summary[0]["desc"] if changes_summary else "No changes detected.",
        "conflicts": conflicts,
        "affected_batches": list(affected_batches),
        "affected_faculties": list(affected_faculties),
        "changes": changes_summary,
        "diff_preview": diff_preview
    }

def generate_diff_preview(original_slots: list, new_slots: list, affected_batches: list,
                          affected_faculties: list, src_day: str = None, tgt_day: str = None) -> dict:
    """Creates a visual markdown/table representation of BEFORE vs AFTER for affected entities."""
    relevant_days = set()
    if src_day: relevant_days.add(src_day)
    if tgt_day: relevant_days.add(tgt_day)
    if not relevant_days:
        relevant_days = set(DAYS_OF_WEEK)

    days_order = {d: i for i, d in enumerate(DAYS_OF_WEEK)}

    preview = {
        "batches": {},
        "faculties": {}
    }

    # Batches diff
    for b_label in affected_batches:
        parts = b_label.split(" - ", 1)
        c, b = parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""

        orig_b_slots = [s for s in original_slots if s["center"] == c and s["batch"] == b and s["day"] in relevant_days]
        new_b_slots = [s for s in new_slots if s["center"] == c and s["batch"] == b and s["day"] in relevant_days]

        orig_b_slots.sort(key=lambda s: (days_order.get(s["day"], 9), parse_time_to_minutes(s["start"])))
        new_b_slots.sort(key=lambda s: (days_order.get(s["day"], 9), parse_time_to_minutes(s["start"])))

        preview["batches"][b_label] = {
            "before": orig_b_slots,
            "after": new_b_slots
        }

    # Faculties diff
    for fac in affected_faculties:
        orig_f_slots = [s for s in original_slots if s["faculty"] == fac and s["day"] in relevant_days]
        new_f_slots = [s for s in new_slots if s["faculty"] == fac and s["day"] in relevant_days]

        orig_f_slots.sort(key=lambda s: (days_order.get(s["day"], 9), parse_time_to_minutes(s["start"])))
        new_f_slots.sort(key=lambda s: (days_order.get(s["day"], 9), parse_time_to_minutes(s["start"])))

        preview["faculties"][fac] = {
            "before": orig_f_slots,
            "after": new_f_slots
        }

    return preview

def apply_and_lock_schedule(token: str) -> dict:
    """Permanently commits the pending proposal to Weekly_Schedule_Input_Topics.xlsx
    and regenerates all batch & faculty PDFs and Excel matrices."""
    if token not in PENDING_PROPOSALS:
        return {"success": False, "message": "Proposal expired or not found. Please propose the change again."}

    rec = PENDING_PROPOSALS.pop(token)
    simulated_slots = rec["simulated_slots"]
    excel_path = get_excel_path()
    if not excel_path:
        return {"success": False, "message": "Excel workbook path not found."}

    days_order = {d: i for i, d in enumerate(DAYS_OF_WEEK)}
    # Sort slots chronologically
    simulated_slots.sort(key=lambda s: (
        s["center"], s["batch"],
        days_order.get(s["day"], 9),
        parse_time_to_minutes(s["start"]) or 0
    ))

    # Write to Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lecture_Topics_Editor"

    headers = [
        "Center", "Batch", "Day", "Start Time", "End Time",
        "Duration (mins)", "Subject", "Faculty", "Chapter", "Topic"
    ]
    ws.append(headers)

    for s in simulated_slots:
        ws.append([
            s["center"],
            s["batch"],
            s["day"],
            s["start"],
            s["end"],
            s.get("dur", 60),
            s["subject"],
            s["faculty"],
            s.get("chapter", "CH-1"),
            s.get("topic", "Introduction & Basics")
        ])

    wb.save(excel_path)

    # Sync cache
    from src.ai_assistant import _SLOTS_CACHE
    _SLOTS_CACHE["slots"] = simulated_slots
    _SLOTS_CACHE["mtime"] = os.path.getmtime(excel_path)

    # Trigger PDF and Matrix regeneration
    import update_topics_and_export_pdfs
    from web_app import get_output_base
    out_base = get_output_base()
    update_topics_and_export_pdfs.update_and_export(excel_path, output_dir_base=out_base)

    batches_str = ", ".join(rec["affected_batches"])
    faculties_str = ", ".join(rec["affected_faculties"])
    msg = f"Successfully applied and locked changes! Master schedule updated. Batch PDFs ({batches_str}) and Faculty PDFs ({faculties_str}) are regenerated."

    return {
        "success": True,
        "message": msg,
        "summary": rec["changes_summary"]
    }

def format_reschedule_markdown(sim: dict) -> str:
    md = []
    action_icons = {
        "MOVE": "🔄", "SWAP": "🔀", "ADD": "➕", "DELETE": "🗑️", "REPLACE_FACULTY": "👤"
    }
    icon = action_icons.get(sim.get("action"), "📋")
    md.append(f"### {icon} Proposed Schedule Modification")
    md.append(f"**Action**: `{sim.get('action')}`  \n**Summary**: {sim.get('summary')}")
    md.append("")

    if sim.get("valid"):
        md.append("✅ **Status: FEASIBLE • 0 Overlaps • Transit Buffers Preserved**")
    else:
        md.append("⚠️ **Status: CONFLICT DETECTED**")
        for c in sim.get("conflicts", []):
            md.append(f"- ❌ {c}")
        md.append("\n*You can modify the time, day, or faculty to resolve this conflict.*")
    md.append("")

    batches = sim.get("affected_batches", [])
    faculties = sim.get("affected_faculties", [])
    md.append("#### 👥 Impacted Entities:")
    if batches:
        md.append(f"* **Affected Batches**: {', '.join(batches)}")
    if faculties:
        md.append(f"* **Affected Faculties**: {', '.join(faculties)}")
    md.append("")

    diff = sim.get("diff_preview", {})
    if diff.get("batches"):
        md.append("#### 🏫 Batch Timetable Changes:")
        for b_name, b_diff in diff["batches"].items():
            md.append(f"**Batch: {b_name}**")
            md.append("| Time Slot | Before Change | After Change |")
            md.append("| :--- | :--- | :--- |")
            all_times = set()
            b_map = {f"{s['day']} {s['start']}-{s['end']}": f"{s['subject']} ({s['faculty']})" for s in b_diff["before"]}
            a_map = {f"{s['day']} {s['start']}-{s['end']}": f"{s['subject']} ({s['faculty']})" for s in b_diff["after"]}
            for k in list(b_map.keys()) + list(a_map.keys()):
                all_times.add(k)
            for t in sorted(list(all_times)):
                b_val = b_map.get(t, "—")
                a_val = a_map.get(t, "—")
                status_tag = ""
                if b_val != a_val:
                    if b_val == "—":
                        status_tag = " `[NEW]`"
                    elif a_val == "—":
                        status_tag = " `[REMOVED]`"
                    else:
                        status_tag = " `[MODIFIED]`"
                md.append(f"| **{t}** | {b_val} | **{a_val}**{status_tag} |")
            md.append("")

    if diff.get("faculties"):
        md.append("#### 👨‍🏫 Faculty Timetable Changes:")
        for f_name, f_diff in diff["faculties"].items():
            md.append(f"**Faculty: {f_name}**")
            md.append("| Time Slot | Before Change | After Change |")
            md.append("| :--- | :--- | :--- |")
            all_times = set()
            b_map = {f"{s['day']} {s['start']}-{s['end']}": f"{s['center']} {s['batch']} ({s['subject']})" for s in f_diff["before"]}
            a_map = {f"{s['day']} {s['start']}-{s['end']}": f"{s['center']} {s['batch']} ({s['subject']})" for s in f_diff["after"]}
            for k in list(b_map.keys()) + list(a_map.keys()):
                all_times.add(k)
            for t in sorted(list(all_times)):
                b_val = b_map.get(t, "—")
                a_val = a_map.get(t, "—")
                status_tag = ""
                if b_val != a_val:
                    if b_val == "—":
                        status_tag = " `[NEW]`"
                    elif a_val == "—":
                        status_tag = " `[REMOVED]`"
                    else:
                        status_tag = " `[MODIFIED]`"
                md.append(f"| **{t}** | {b_val} | **{a_val}**{status_tag} |")
            md.append("")

    token = sim.get("token")
    if token and sim.get("valid"):
        md.append("💡 *Ready for approval:* Use the **Approve & Lock** button below to commit changes permanently and update all PDFs, or type adjustments to modify.")

    return "\n".join(md)
