# Standing Institutional Timetable Rules

Standing rules are maintained directly in the **`Standing Rules`** tab on each year's Google Spreadsheet:
- 2026-27: `https://docs.google.com/spreadsheets/d/1oZIhdOJoo--kWjSYLQUGyWppJaRSc8OAgb_tiT4GVt4/edit`
- 2027-28: `https://docs.google.com/spreadsheets/d/1j4ALHK-etY5CyJ1fx1jywi5fle9xMARebiyqq_tWsyI/edit`

Whenever generating, modifying, or auditing a timetable schedule:
1. Consult `data/standing_rules.csv` or `data_2027_28/standing_rules.csv` for active conditions (`Active == YES`).
2. Strictly enforce:
   - `RULE_001`: No tests on Monday across all branches/batches.
   - `RULE_002`: Zero empty slots in afternoon/evening batches.
   - `RULE_003`: No faculty visits the same branch twice on any day (no bounce travel).
   - `RULE_004`: Priority to primary faculties before backup faculties.
   - `RULE_005`: In CBSE evening batches, Maths must always be first or last.
   - `RULE_006`: In all evening batches, Gujarati/Hindi, Computer, and English must always be first or last.
   - `RULE_007`: In all evening batches, no Gujarati, English, and Computer on the same day (max 1 auxiliary per day).
   - `RULE_008`: In all evening batches, start time for all 6 days must be identical.
3. Verify compliance with `.venv/bin/python3 scripts/verify_standing_rules.py --year all`.
