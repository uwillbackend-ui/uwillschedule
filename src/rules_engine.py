import os
import re
from typing import List, Dict, Optional, Any
import openpyxl

ALL_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

def time_to_minutes(t_val: Any) -> Optional[int]:
    """Convert time string (e.g. '7:30 AM', '15:30', '07:30', '7:30') or time object to minutes from midnight."""
    if t_val is None:
        return None
    if isinstance(t_val, int):
        return t_val
    t_str = str(t_val).strip().upper()
    if not t_str or t_str in ["ANY", "NONE", "-"]:
        return None
    
    # Check for HH:MM AM/PM
    m_ampm = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", t_str)
    if m_ampm:
        h, m, period = int(m_ampm.group(1)), int(m_ampm.group(2)), m_ampm.group(3)
        if period == "PM" and h != 12:
            h += 12
        elif period == "AM" and h == 12:
            h = 0
        return h * 60 + m
    
    # Check for 24h format HH:MM
    m_24 = re.match(r"^(\d{1,2}):(\d{2})$", t_str)
    if m_24:
        h, m = int(m_24.group(1)), int(m_24.group(2))
        return h * 60 + m

    return None

def parse_time_window(tw_str: str) -> tuple[Optional[int], Optional[int]]:
    """Parse time window string like '07:30 - 08:30' into (start_min, end_min)."""
    if not tw_str or str(tw_str).strip().upper() in ["ANY", "NONE", "-"]:
        return None, None
    parts = re.split(r"[-–—]", str(tw_str))
    if len(parts) == 2:
        s = time_to_minutes(parts[0].strip())
        e = time_to_minutes(parts[1].strip())
        return s, e
    return None, None

def minutes_to_display(m: int) -> str:
    """Convert minutes to human readable 12-hour string (e.g. 450 -> '7:30 AM')."""
    h = m // 60
    mins = m % 60
    period = "AM" if h < 12 else "PM"
    disp_h = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
    return f"{disp_h}:{mins:02d} {period}"

class StandingRule:
    def __init__(
        self,
        rule_id: str,
        active: bool,
        rule_type: str,
        branch: str,
        standard_batch: str,
        days: str,
        time_window: str,
        subject: str,
        faculty: str,
        description: str
    ):
        self.rule_id = rule_id.strip()
        self.active = active
        self.rule_type = rule_type.strip().upper()
        self.raw_branch = branch.strip()
        self.raw_standard_batch = standard_batch.strip()
        self.raw_days = days.strip()
        self.time_window = time_window.strip()
        self.subject = subject.strip().upper()
        self.faculty = faculty.strip().upper()
        self.description = description.strip()

        # Parse branches
        if self.raw_branch.upper() in ["ALL", "*", "ANY"]:
            self.branches = ["ALL"]
        else:
            self.branches = [b.strip().upper() for b in self.raw_branch.split(",") if b.strip()]

        # Parse days
        if self.raw_days.upper() in ["ALL", "*", "ANY"]:
            self.days = ALL_DAYS[:]
        else:
            day_tokens = [d.strip().upper() for d in self.raw_days.split(",") if d.strip()]
            self.days = []
            for dt in day_tokens:
                for full_d in ALL_DAYS:
                    if dt in full_d:
                        if full_d not in self.days:
                            self.days.append(full_d)

        # Parse time window
        self.start_min, self.end_min = parse_time_window(self.time_window)

    def matches_branch(self, branch_name: str) -> bool:
        if "ALL" in self.branches:
            return True
        b_up = branch_name.strip().upper()
        return any(b == b_up or b in b_up for b in self.branches)

    def matches_batch(self, batch_name: str, earliest_start_min: Optional[int] = None) -> bool:
        target = self.raw_standard_batch.upper()
        if target in ["ALL", "*", "ANY"]:
            return True
        if target == "EVENING_BATCHES":
            if earliest_start_min is not None and earliest_start_min >= 900:  # 3:00 PM
                return True
            return "EVE" in batch_name.upper()
        if target == "MORNING_BATCHES":
            if earliest_start_min is not None and earliest_start_min < 900:
                return True
            return "MRG" in batch_name.upper() or "MORNING" in batch_name.upper()
        # Direct or substring match (e.g. '11TH', '12TH', '11TH GSEB')
        return target in batch_name.upper()

    def __repr__(self):
        return f"<StandingRule {self.rule_id} [{self.rule_type}] Active={self.active}>"

def load_standing_rules(csv_path: Optional[str] = None, academic_year: str = "2026-27") -> List[StandingRule]:
    """Load standing rules from data/<academic_year>/standing_rules.csv synced from Google Sheets."""
    rules = []
    
    if not csv_path:
        target_dir = "data" if academic_year == "2026-27" else "data_2027_28"
        csv_path = os.path.join(target_dir, "standing_rules.csv")
        if not os.path.exists(csv_path):
            csv_path = "data/standing_rules.csv"

    if os.path.exists(csv_path):
        import csv
        try:
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Clean keys (support Rule_ID and "Rule ID", etc.)
                    clean_row = {re.sub(r"[\s_]+", "_", k.strip().upper()): v for k, v in row.items() if k}
                    r_id = clean_row.get("RULE_ID")
                    if not r_id:
                        continue
                    active_val = str(clean_row.get("ACTIVE", "")).strip().upper()
                    rule = StandingRule(
                        rule_id=str(r_id),
                        active=(active_val in ["YES", "TRUE", "1", "Y"]),
                        rule_type=clean_row.get("RULE_TYPE", ""),
                        branch=clean_row.get("BRANCH", "ALL"),
                        standard_batch=clean_row.get("STANDARD_BATCH", "ALL"),
                        days=clean_row.get("DAYS", "ALL"),
                        time_window=clean_row.get("TIME_WINDOW", "ANY"),
                        subject=clean_row.get("SUBJECT", "ANY"),
                        faculty=clean_row.get("FACULTY", "ANY"),
                        description=clean_row.get("DESCRIPTION", "")
                    )
                    rules.append(rule)
        except Exception as e:
            print(f"[Rules Engine Notice] Error reading standing rules CSV ({csv_path}): {e}")

    return rules

def audit_schedule_against_rules(
    all_slots: List[Any],
    rules: Optional[List[StandingRule]] = None,
    loader: Optional[Any] = None
) -> Dict[str, Any]:
    """Audit all scheduled slots against the standing rules. Returns detailed validation report."""
    if rules is None:
        rules = load_standing_rules()

    results = []
    all_passed = True

    active_rules = [r for r in rules if r.active]
    inactive_rules = [r for r in rules if not r.active]

    # Pre-calculate earliest start per batch if loader available
    batch_earliest_starts = {}
    if loader and hasattr(loader, "batches"):
        for (c, b), b_info in loader.batches.items():
            batch_earliest_starts[(c.upper(), b.upper())] = b_info.earliest_start_min
    else:
        for s in all_slots:
            c = getattr(s, "center", "").upper()
            b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
            st = getattr(s, "start_min", 0)
            key = (c, b)
            if key not in batch_earliest_starts:
                batch_earliest_starts[key] = st
            else:
                batch_earliest_starts[key] = min(batch_earliest_starts[key], st)

    for rule in active_rules:
        violations = []

        if rule.rule_type == "NO_TEST_DAY":
            # Rule: no test on forbidden day(s)
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                d = getattr(s, "day", "").upper()
                subj = getattr(s, "subject", "").upper()
                fac = getattr(s, "faculty", "").upper()
                is_test = ("TEST" in subj) or ("EXAM" in subj) or ("TEST" in fac)
                if not is_test:
                    continue
                
                # Check branch, batch, and day match
                es = batch_earliest_starts.get((c, b))
                if rule.matches_branch(c) and rule.matches_batch(b, es) and d in rule.days:
                    st_str = minutes_to_display(getattr(s, "start_min", 0))
                    violations.append(f"Test found on {d} at {c} - {b} ({st_str})")

        elif rule.rule_type == "NO_EMPTY_SLOTS":
            # Rule: no internal gaps between consecutive lectures/tests on the same day
            batch_day_slots = {}
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                d = getattr(s, "day", "").upper()
                es = batch_earliest_starts.get((c, b))
                if rule.matches_branch(c) and rule.matches_batch(b, es):
                    key = (c, b, d)
                    batch_day_slots.setdefault(key, []).append(s)

            for (c, b, d), slots in batch_day_slots.items():
                if len(slots) <= 1:
                    continue
                sorted_slots = sorted(slots, key=lambda x: getattr(x, "start_min", 0))
                for i in range(len(sorted_slots) - 1):
                    curr_end = getattr(sorted_slots[i], "end_min", 0)
                    next_start = getattr(sorted_slots[i+1], "start_min", 0)
                    if next_start > curr_end:
                        gap_dur = next_start - curr_end
                        gap_st = minutes_to_display(curr_end)
                        gap_et = minutes_to_display(next_start)
                        violations.append(f"Gap of {gap_dur}m at {c} - {b} on {d} between {gap_st} and {gap_et}")

        elif rule.rule_type == "FIXED_SLOT":
            # Rule: pin a subject / faculty at a specific time or slot
            for d in rule.days:
                # Find matching batches
                matching_batches = set()
                for s in all_slots:
                    c = getattr(s, "center", "").upper()
                    b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                    es = batch_earliest_starts.get((c, b))
                    if rule.matches_branch(c) and rule.matches_batch(b, es):
                        matching_batches.add((c, b))

                for (c, b) in matching_batches:
                    day_slots = [
                        s for s in all_slots
                        if getattr(s, "center", "").upper() == c
                        and getattr(s, "batch_name", getattr(s, "batch", "")).upper() == b
                        and getattr(s, "day", "").upper() == d
                    ]
                    # Check if matching slot exists
                    found = False
                    for s in day_slots:
                        st = getattr(s, "start_min", 0)
                        et = getattr(s, "end_min", 0)
                        subj = getattr(s, "subject", "").upper()
                        fac = getattr(s, "faculty", "").upper()
                        
                        time_match = True
                        if rule.start_min is not None and rule.end_min is not None:
                            time_match = (st == rule.start_min and et == rule.end_min)
                        elif rule.start_min is not None:
                            time_match = (st == rule.start_min)

                        subj_match = (rule.subject in ["ANY", "*", ""] or rule.subject in subj)
                        fac_match = (rule.faculty in ["ANY", "*", ""] or rule.faculty in fac)

                        if time_match and subj_match and fac_match:
                            found = True
                            break

                    if not found:
                        tw = rule.time_window if rule.time_window != "ANY" else "specified window"
                        violations.append(f"Missing {rule.subject} at {c} - {b} on {d} during {tw}")

        elif rule.rule_type == "FORBIDDEN_DAY":
            # Rule: faculty or subject not scheduled on forbidden days
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                d = getattr(s, "day", "").upper()
                subj = getattr(s, "subject", "").upper()
                fac = getattr(s, "faculty", "").upper()
                if d in rule.days:
                    subj_match = (rule.subject not in ["ANY", "*", ""] and rule.subject in subj)
                    fac_match = (rule.faculty not in ["ANY", "*", ""] and rule.faculty in fac)
                    if subj_match or fac_match:
                        st_str = minutes_to_display(getattr(s, "start_min", 0))
                        target = rule.subject if subj_match else rule.faculty
                        violations.append(f"Forbidden assignment {target} found at {c} - {b} on {d} at {st_str}")

        elif rule.rule_type == "NO_REPEAT_BRANCH_DAY":
            # Rule: No faculty may visit the same branch twice on any day
            fac_day_slots = {}
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                d = getattr(s, "day", "").upper()
                fac = getattr(s, "faculty", "").strip().upper()
                if not fac or fac in ["WEEKLY TEST", "TEST", "EXAM"] or fac.startswith("TBD"):
                    continue
                fac_names = [f.strip() for f in fac.split("/")] if "/" in fac else [fac]
                for fn in fac_names:
                    if fn == "ASIF SIR": fn = "AASIF SIR"
                    fac_day_slots.setdefault((fn, d), []).append((getattr(s, "start_min", 0), c))

            for (fn, d), items in fac_day_slots.items():
                sorted_items = sorted(items, key=lambda x: x[0])
                visit_seq = []
                for _, center in sorted_items:
                    if not visit_seq or visit_seq[-1] != center:
                        visit_seq.append(center)
                if len(visit_seq) != len(set(visit_seq)):
                    violations.append(f"{fn} on {d}: repeated center visit sequence {visit_seq}")

        elif rule.rule_type == "EDGE_SLOT_ONLY":
            # Rule: Specified subject(s) must be either first slot or last slot of the day
            target_subjs = [s.strip().upper() for s in rule.subject.split(",") if s.strip()]
            batch_day_slots = {}
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                d = getattr(s, "day", "").upper()
                es = batch_earliest_starts.get((c, b))
                is_cbse_eve = ("CBSE" in b) and (es is not None and es >= 900 or "EVE" in b)
                match_batch = False
                if rule.raw_standard_batch.upper() == "CBSE_EVENING":
                    match_batch = is_cbse_eve
                else:
                    match_batch = rule.matches_batch(b, es)

                if rule.matches_branch(c) and match_batch and d in rule.days:
                    batch_day_slots.setdefault((c, b, d), []).append(s)

            for (c, b, d), slots in batch_day_slots.items():
                if len(slots) <= 2:
                    continue
                sorted_slots = sorted(slots, key=lambda x: getattr(x, "start_min", 0))
                n = len(sorted_slots)
                for idx in range(1, n - 1):
                    slot_subj = getattr(sorted_slots[idx], "subject", "").upper()
                    if any(ts in slot_subj for ts in target_subjs):
                        st_str = minutes_to_display(getattr(sorted_slots[idx], "start_min", 0))
                        violations.append(f"{c} - {b} on {d}: {slot_subj} at slot {idx+1}/{n} ({st_str}) - must be first or last")

        elif rule.rule_type == "MAX_ONE_AUX_PER_DAY":
            # Rule: No Gujarati, English, and Computer on the same day (max 1 aux subject per day)
            target_subjs = [s.strip().upper() for s in rule.subject.split(",") if s.strip()]
            batch_day_slots = {}
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                d = getattr(s, "day", "").upper()
                es = batch_earliest_starts.get((c, b))
                if rule.matches_branch(c) and rule.matches_batch(b, es) and d in rule.days:
                    batch_day_slots.setdefault((c, b, d), []).append(s)

            for (c, b, d), slots in batch_day_slots.items():
                found_aux = []
                for s in slots:
                    slot_subj = getattr(s, "subject", "").upper()
                    matched_aux = [ts for ts in target_subjs if ts in slot_subj]
                    if matched_aux:
                        found_aux.append(matched_aux[0])
                unique_aux = list(set(found_aux))
                if len(unique_aux) > 1:
                    violations.append(f"{c} - {b} on {d}: multiple aux subjects {unique_aux} on same day")

        elif rule.rule_type == "UNIFORM_START_TIME":
            # Rule: Batch start time for all 6 days must be identical
            batch_starts = {}
            for s in all_slots:
                c = getattr(s, "center", "").upper()
                b = getattr(s, "batch_name", getattr(s, "batch", "")).upper()
                d = getattr(s, "day", "").upper()
                es = batch_earliest_starts.get((c, b))
                if rule.matches_branch(c) and rule.matches_batch(b, es):
                    key = (c, b)
                    st = getattr(s, "start_min", 0)
                    batch_starts.setdefault(key, {}).setdefault(d, []).append(st)

            for (c, b), day_map in batch_starts.items():
                earliest_per_day = {d: min(starts) for d, starts in day_map.items()}
                unique_starts = set(earliest_per_day.values())
                if len(unique_starts) > 1:
                    disp_starts = {d: minutes_to_display(st) for d, st in earliest_per_day.items()}
                    violations.append(f"{c} - {b}: fluctuating daily starts: {disp_starts}")

        is_passed = (len(violations) == 0)
        if not is_passed:
            all_passed = False

        results.append({
            "rule_id": rule.rule_id,
            "rule_type": rule.rule_type,
            "description": rule.description,
            "active": True,
            "status": "PASS" if is_passed else "FAIL",
            "violation_count": len(violations),
            "violations": violations[:10]  # sample first 10
        })

    # Record inactive rules for transparency
    for rule in inactive_rules:
        results.append({
            "rule_id": rule.rule_id,
            "rule_type": rule.rule_type,
            "description": rule.description,
            "active": False,
            "status": "DISABLED",
            "violation_count": 0,
            "violations": []
        })

    return {
        "is_valid": all_passed,
        "total_active_rules": len(active_rules),
        "passed_count": sum(1 for r in results if r["status"] == "PASS"),
        "failed_count": sum(1 for r in results if r["status"] == "FAIL"),
        "disabled_count": len(inactive_rules),
        "results": results
    }

def print_audit_report(audit_result: Dict[str, Any], title: str = "SCHEDULE STANDING RULES AUDIT"):
    """Format and print an executive summary table of the standing rules audit."""
    print("\n" + "=" * 78)
    print(f" {title.center(76)} ")
    print("=" * 78)
    print(f"{'STATUS':<10} | {'RULE ID':<10} | {'TYPE':<16} | {'DESCRIPTION'}")
    print("-" * 78)

    for r in audit_result["results"]:
        status = r["status"]
        r_id = r["rule_id"]
        r_type = r["rule_type"]
        desc = (r["description"][:36] + "...") if len(r["description"]) > 36 else r["description"]
        print(f"[{status:<8}] | {r_id:<10} | {r_type:<16} | {desc}")

        if status == "FAIL":
            for v in r["violations"]:
                print(f"   └── [VIOLATION] {v}")

    print("=" * 78)
    if audit_result["is_valid"]:
        print(f" RESULT: ALL {audit_result['passed_count']} ACTIVE STANDING RULES VERIFIED 100% SATISFIED! ")
    else:
        print(f" RESULT: FAILED! {audit_result['failed_count']} RULES VIOLATED. IMMEDIATE RESOLUTION REQUIRED. ")
    print("=" * 78 + "\n")
