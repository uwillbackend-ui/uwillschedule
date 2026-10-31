import sys, os
sys.path.insert(0, os.path.abspath("."))
import openpyxl
import re
from src.data_loader import DataLoader

def parse_mins_from_cell(cell_str):
    if not cell_str or not cell_str.strip():
        return 0, None, None, None
    s = cell_str.strip()
    if s in ["---", "★ RECESS / BREAK ★"] or "WEEKLY TEST" in s or "RECESS" in s:
        return 0, None, None, None

    # Line 1: "8:00 AM - 9:00 AM (60 mins)"
    lines = s.split("\n")
    m_dur = re.search(r'\((\d+)\s*mins?\)', lines[0], re.IGNORECASE)
    dur = int(m_dur.group(1)) if m_dur else 0
    if dur == 0:
        # Try parsing time interval
        m_time = re.match(r'(\d+):(\d+)\s*(AM|PM)?\s*-\s*(\d+):(\d+)\s*(AM|PM)?', lines[0].strip(), re.IGNORECASE)
        if m_time:
            h1, m1, p1, h2, m2, p2 = m_time.groups()
            h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
            if p1:
                p1 = p1.upper()
                if p1 == "PM" and h1 < 12: h1 += 12
                if p1 == "AM" and h1 == 12: h1 = 0
            if p2:
                p2 = p2.upper()
                if p2 == "PM" and h2 < 12: h2 += 12
                if p2 == "AM" and h2 == 12: h2 = 0
            dur = max(0, (h2 * 60 + m2) - (h1 * 60 + m1))

    batch_line = lines[1].strip() if len(lines) > 1 else ""
    subj_line = lines[2].strip() if len(lines) > 2 else ""

    # Parse center and batch
    # e.g. "SG (12TH GSEB)" or "JAI AMBE (12TH GSEB - C)"
    m_b = re.match(r'([^(]+)\s*\(([^)]+)\)', batch_line)
    if m_b:
        center = m_b.group(1).strip().upper()
        batch = m_b.group(2).strip().upper()
    else:
        center = ""
        batch = batch_line.upper()

    return dur, center, batch, subj_line.upper()

def audit_faculties_and_requirements():
    loader = DataLoader("data")
    loader.load_all()

    # Clean requirements as in generate_timetable.py
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

    # Load All_Faculties_Weekly_Schedule.xlsx
    fac_excel = "output/excel/All_Faculties_Weekly_Schedule.xlsx"
    wb = openpyxl.load_workbook(fac_excel)

    DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

    # Map: fac_name -> list of slots (center, batch, subject, day, mins)
    fac_scheduled_slots = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        fac_name = sheet_name.replace("_", " ").strip().upper()
        fac_scheduled_slots[fac_name] = []

        # Table header is row 4, days are col 2..7
        for r in range(5, ws.max_row + 1):
            slot_label = str(ws.cell(r, 1).value or "").strip()
            if not slot_label.startswith("LECTURE"):
                continue
            for col_idx, day in enumerate(DAYS, start=2):
                cell_val = str(ws.cell(r, col_idx).value or "").strip()
                dur, cent, batch, subj = parse_mins_from_cell(cell_val)
                if dur > 0:
                    fac_scheduled_slots[fac_name].append({
                        "center": cent,
                        "batch": batch,
                        "subject": subj,
                        "day": day,
                        "mins": dur,
                        "text": cell_val
                    })

    print("=" * 80)
    print("AUDIT: FACULTY-BY-FACULTY TOTAL WEEKLY HOURS")
    print("=" * 80)

    # Group requirements by faculty
    fac_allotted_mins = {}
    fac_reqs = {}
    for req in loader.subject_requirements:
        f = (req.faculty or "").strip().upper()
        if not f or f.startswith("TBD_") or f in ["TBD", "SCHOOL", "VISITING"]:
            continue
        req_mins = round(req.weekly_hours * 60)
        fac_allotted_mins[f] = fac_allotted_mins.get(f, 0) + req_mins
        fac_reqs.setdefault(f, []).append(req)

    fac_deficits = []
    for fac, allotted_m in sorted(fac_allotted_mins.items()):
        matched_f_slots = fac_scheduled_slots.get(fac, [])
        if not matched_f_slots:
            for fname, slots in fac_scheduled_slots.items():
                if fname in fac or fac in fname:
                    matched_f_slots = slots
                    break

        act_m = sum(sl["mins"] for sl in matched_f_slots)
        diff = act_m - allotted_m
        status = "OK" if diff >= 0 else f"DEFICIT by {-diff} mins (-{ -diff/60:.2f} hrs)"
        if diff < 0:
            fac_deficits.append((fac, allotted_m, act_m, diff, matched_f_slots))
        print(f"  {fac:25s} | Allotted: {allotted_m:4d}m ({allotted_m/60:4.1f}h) | Scheduled: {act_m:4d}m ({act_m/60:4.1f}h) | Diff: {diff:+4d}m -> {status}")

    print(f"\nTotal Faculties with Deficit: {len(fac_deficits)} out of {len(fac_allotted_mins)}")

    if fac_deficits:
        print("\n" + "=" * 80)
        print("DETAILS OF FACULTIES WITH DEFICITS:")
        print("=" * 80)
        for fac, allotted_m, act_m, diff, slots in fac_deficits:
            print(f"\n--- {fac} (Short by {-diff} mins) ---")
            reqs = fac_reqs.get(fac, [])
            for req in reqs:
                # Find matching slots for this req
                c, b, s = req.center.strip().upper(), req.batch.strip().upper(), req.subject.strip().upper()
                req_slots = [sl for sl in slots if (c in sl["center"] or not sl["center"]) and (b in sl["batch"] or sl["batch"] in b) and (s in sl["subject"] or sl["subject"] in s)]
                sched_mins = sum(sl["mins"] for sl in req_slots)
                expected_mins = round(req.weekly_hours * 60)
                sub_diff = sched_mins - expected_mins
                flag = "OK" if sub_diff >= 0 else f"DEFICIT {-sub_diff}m"
                print(f"    Req: {c} - {b} | {s} | Expected: {expected_mins}m ({req.weekly_days}d x {req.daily_duration_min}m) | Actual: {sched_mins}m ({len(req_slots)} slots: {[sl['mins'] for sl in req_slots]}) -> {flag}")

if __name__ == "__main__":
    audit_faculties_and_requirements()
