#!/usr/bin/env python3
"""
Standing Rules Verification Script
Audits generated schedules against standing institutional conditions defined in Standing_Rules.xlsx.
"""

import sys
import os
import argparse
from typing import Optional
import openpyxl

sys.path.insert(0, os.path.abspath("."))
from src.rules_engine import load_standing_rules, audit_schedule_against_rules, print_audit_report, time_to_minutes
from src.models import ScheduledSlot

def load_slots_from_excel(path: str):
    if not os.path.exists(path):
        print(f"[ERROR] Schedule file not found: {path}")
        return []
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows or len(rows) < 2:
        return []
    
    slots = []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        c, b, d, st_str, et_str, dur, subj, fac = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]
        st = time_to_minutes(st_str)
        et = time_to_minutes(et_str)
        slots.append(ScheduledSlot(
            batch_key=f"{c}_{b}",
            center=str(c).strip(),
            batch_name=str(b).strip(),
            day=str(d).strip().upper(),
            start_min=st,
            end_min=et,
            subject=str(subj).strip(),
            faculty=str(fac).strip()
        ))
    return slots

def verify_year(year: str, rules_csv: Optional[str] = None) -> bool:
    target_excel = f"output/excel/Weekly_Schedule_Input_Topics_{year.replace('-', '_')}.xlsx"
    if not os.path.exists(target_excel):
        target_excel = "output/excel/Weekly_Schedule_Input_Topics.xlsx"
    
    print(f"\nAuditing Academic Year [{year}] using schedule from: {target_excel}")
    slots = load_slots_from_excel(target_excel)
    if not slots:
        print(f"[FAIL] No scheduled slots loaded from {target_excel}")
        return False
    
    data_dir = "data" if year == "2026-27" else "data_2027_28"
    csv_file = rules_csv or os.path.join(data_dir, "standing_rules.csv")
    rules = load_standing_rules(csv_path=csv_file, academic_year=year)
    result = audit_schedule_against_rules(slots, rules)
    print_audit_report(result, title=f"STANDING RULES VERIFICATION REPORT [{year}] (Source: {csv_file})")
    return result["is_valid"]

def main():
    parser = argparse.ArgumentParser(description="Verify Timetable Against Standing Institutional Rules")
    parser.add_argument("--year", default="all", help="Academic year (2026-27, 2027-28, or all)")
    parser.add_argument("--rules", default=None, help="Optional path to standing_rules.csv")
    args = parser.parse_args()

    years = ["2026-27", "2027-28"] if args.year.lower() == "all" else [args.year]
    all_ok = True

    for y in years:
        ok = verify_year(y, rules_csv=args.rules)
        if not ok:
            all_ok = False

    if all_ok:
        print("\n>>> OVERALL RESULT: SUCCESS! All academic schedules comply with 100% of active standing rules.\n")
        sys.exit(0)
    else:
        print("\n>>> OVERALL RESULT: WARNING! One or more standing rules were violated. Please check details above.\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
