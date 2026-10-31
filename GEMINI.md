# Standing Institutional Timetable Rules

This project enforces institutional scheduling invariants for all branches, batches, and academic years.

## Mandatory Google Spreadsheet Tab Reference
Standing institutional rules are maintained directly in the dedicated **`Standing Rules`** tab on each academic year's Google Spreadsheet:
- **2026-27 Sheet**: `https://docs.google.com/spreadsheets/d/1oZIhdOJoo--kWjSYLQUGyWppJaRSc8OAgb_tiT4GVt4/edit` -> Synced to `data/standing_rules.csv`
- **2027-28 Sheet**: `https://docs.google.com/spreadsheets/d/1j4ALHK-etY5CyJ1fx1jywi5fle9xMARebiyqq_tWsyI/edit` -> Synced to `data_2027_28/standing_rules.csv`

## Mandatory Invariants to Always Enforce
Whenever you generate, modify, or audit any timetable schedule:
1. **Always consult `data/standing_rules.csv`** (or `data_2027_28/standing_rules.csv`).
2. **Honor all rules where `Active == YES`**:
   - `RULE_001` (`NO_TEST_DAY`): No test may ever be scheduled on Monday at any branch or batch.
   - `RULE_002` (`NO_EMPTY_SLOTS`): In all afternoon/evening batches, there must be 0 empty slots between consecutive lectures or tests.
   - `RULE_003` (`NO_REPEAT_BRANCH_DAY`): No faculty may visit the same branch twice on any day (e.g., Deepika Madam at Jai Ambe then DAPS then Jai Ambe is strictly forbidden). All lectures at a center must be finished in one visit before traveling.
   - `RULE_004` (`BACKUP_FACULTY_PRIORITY`): Priority must be given to all primary faculties. Remaining empty slots assigned to backup faculties only after primary faculty allocations are fulfilled.
   - `RULE_005` (`EDGE_SLOT_ONLY`): In CBSE evening batches, Maths lecture must always be either the first slot or the last slot of the day.
   - `RULE_006` (`EDGE_SLOT_ONLY`): In all evening batches, lectures of Gujarati/Hindi, Computer, and English must always be either the first slot or the last slot of the day.
   - `RULE_007` (`MAX_ONE_AUX_PER_DAY`): There must not be Gujarati, English, or Computer lectures on the same day in any evening batch (maximum 1 auxiliary subject per day).
   - `RULE_008` (`UNIFORM_START_TIME`): The batch start time across all 6 operating days (Mon-Sat) for each evening batch must be identical.
   - Any other active rules configured in the `Standing Rules` tab.
3. **Run Standing Rules Verification**:
   - After any timetable generation or modification, run:
     ```bash
     .venv/bin/python3 scripts/verify_standing_rules.py --year all
     ```
   - Confirm that all active rules pass with 0 violations.
