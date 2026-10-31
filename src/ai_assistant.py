import os
import json
import urllib.request
import urllib.error
import time
import openpyxl

DEFAULT_KEY = ""

CANDIDATE_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3.1-pro-preview"
]

_SLOTS_CACHE = {
    "mtime": 0,
    "slots": []
}

def get_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()
    for env_file in [".env.local", ".env"]:
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("GEMINI_API_KEY="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass
    return DEFAULT_KEY

def get_excel_path():
    candidates = [
        "output/excel/Weekly_Schedule_Input_Topics.xlsx",
        "/tmp/Weekly_Schedule_Input_Topics.xlsx",
    ]
    existing = [p for p in candidates if os.path.exists(p)]
    if existing:
        return max(existing, key=os.path.getmtime)
    return None

def load_timetable_slots():
    p = get_excel_path()
    if not p:
        return []

    mtime = os.path.getmtime(p)
    if _SLOTS_CACHE["mtime"] == mtime and _SLOTS_CACHE["slots"]:
        return _SLOTS_CACHE["slots"]

    wb = openpyxl.load_workbook(p, read_only=True)
    ws = wb.active

    slots = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]: continue
        slots.append({
            "center": str(r[0]).strip(),
            "batch": str(r[1]).strip(),
            "day": str(r[2]).strip(),
            "start": str(r[3]).strip(),
            "end": str(r[4]).strip(),
            "dur": r[5],
            "subject": str(r[6]).strip(),
            "faculty": str(r[7]).strip(),
            "chapter": str(r[8] or "").strip(),
            "topic": str(r[9] or "").strip()
        })

    _SLOTS_CACHE["mtime"] = mtime
    _SLOTS_CACHE["slots"] = slots
    return slots

from src.data_loader import parse_time_to_minutes

def call_gemini_raw(system_prompt: str, user_prompt: str, timeout: int = 5) -> str:
    key = get_api_key()

    # Try fast flash models with short timeout
    for m in ["gemini-3.5-flash", "gemini-3.8-flash"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res = json.loads(resp.read().decode())
                cand = res.get("candidates", [])
                if cand and cand[0].get("content", {}).get("parts"):
                    return cand[0]["content"]["parts"][0]["text"].strip()
        except Exception:
            continue

    return ""

def _format_slots_as_markdown(title: str, matched_slots: list) -> str:
    if not matched_slots:
        return f"No scheduled lectures found matching: **{title}**."

    # Sort chronologically by day and actual start time minutes
    days_order = {"MONDAY": 1, "TUESDAY": 2, "WEDNESDAY": 3, "THURSDAY": 4, "FRIDAY": 5, "SATURDAY": 6}
    sorted_slots = sorted(
        matched_slots,
        key=lambda s: (days_order.get(s["day"], 9), parse_time_to_minutes(s["start"]))
    )

    md = [f"### {title}"]
    md.append("")
    md.append("| Day | Time | Duration | Branch & Batch | Subject | Faculty |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for s in sorted_slots:
        dur = s.get("dur", "")
        dur_str = f"{dur} mins" if dur else ""
        bb = f"{s['center']} ({s['batch']})"
        md.append(f"| **{s['day']}** | {s['start']} - {s['end']} | {dur_str} | {bb} | {s['subject']} | {s['faculty']} |")

    md.append("")
    md.append(f"*Total matching lectures: **{len(sorted_slots)}***")
    return "\n".join(md)

def ask_assistant(user_question: str) -> str:
    slots = load_timetable_slots()
    if not slots:
        return "⚠️ Timetable data is not available yet. Please generate the schedule first."

    q = user_question.upper()
    days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
    matched_days = [d for d in days if d in q or d[:3] in q]

    # 0. Check Rescheduling / Modification Command
    reschedule_keywords = [
        "MOVE", "SWAP", "SHIFT", "FILL BLANK", "ADD LECTURE", "EXTRA LECTURE",
        "CANCEL LECTURE", "DELETE LECTURE", "REMOVE LECTURE", "REPLACE",
        "SUBSTITUTE", "CHANGE", "ASSIGN", "RESCHEDULE", "FILL SPACE",
        "FILL GAP", "PUT ", "INSERT"
    ]
    is_reschedule = (
        any(k in q for k in reschedule_keywords) or
        any(k in q for k in ["MOVE ", "SWAP ", "ADD ", "CANCEL ", "DELETE ", "REMOVE "])
    ) and not (q.startswith("SHOW ") or q.startswith("WHAT ") or q.startswith("LIST ") or q.startswith("DISPLAY "))

    if is_reschedule:
        from src import rescheduler
        prop = rescheduler.parse_reschedule_intent(user_question, slots)
        if prop and prop.get("action"):
            sim = rescheduler.validate_and_simulate_change(prop, slots)
            md_text = rescheduler.format_reschedule_markdown(sim)
            return {
                "reply": md_text,
                "reschedule_data": sim
            }

    # 1. Check Faculty Match
    all_faculties = sorted(list(set(s["faculty"] for s in slots if not s["faculty"].startswith("TBD_") and s["faculty"] != "WEEKLY TEST")), key=len, reverse=True)
    matched_fac = None
    for f in all_faculties:
        f_clean = f.replace(" SIR", "").replace(" MADAM", "")
        if f in q or f_clean in q:
            matched_fac = f
            break

    if matched_fac:
        res = [s for s in slots if s["faculty"] == matched_fac]
        day_label = ""
        if matched_days:
            res = [s for s in res if s["day"] in matched_days]
            day_label = f" on {', '.join(matched_days)}"

        title = f"Weekly Schedule for {matched_fac}{day_label}"
        deterministic_ans = _format_slots_as_markdown(title, res)

        # Enhance with Gemini if available
        context_prompt = f"Here is the verified schedule for {matched_fac}:\n" + "\n".join(
            [f"{s['day']} {s['start']}-{s['end']} ({s.get('dur')}m) at {s['center']} {s['batch']} for {s['subject']}" for s in res]
        )
        gemini_ans = call_gemini_raw(
            "You are U WILL CLASSES schedule assistant. Answer the user question accurately based only on the provided schedule data. Use clear markdown formatting.",
            f"{context_prompt}\n\nUser Question: {user_question}"
        )
        return gemini_ans if gemini_ans else deterministic_ans

    # 2. Check Batch Match
    all_batches = sorted(list(set((s["center"], s["batch"]) for s in slots)), key=lambda x: len(f"{x[0]} {x[1]}"), reverse=True)
    matched_b = None
    for c, b in all_batches:
        if f"{c} {b}" in q or (c in q and b in q):
            matched_b = (c, b)
            break

    if matched_b:
        c, b = matched_b
        res = [s for s in slots if s["center"] == c and s["batch"] == b]
        day_label = ""
        if matched_days:
            res = [s for s in res if s["day"] in matched_days]
            day_label = f" on {', '.join(matched_days)}"

        title = f"Timetable for {c} — {b}{day_label}"
        deterministic_ans = _format_slots_as_markdown(title, res)

        context_prompt = f"Here is the verified schedule for {c} - {b}:\n" + "\n".join(
            [f"{s['day']} {s['start']}-{s['end']} ({s.get('dur')}m) - {s['subject']} by {s['faculty']}" for s in res]
        )
        gemini_ans = call_gemini_raw(
            "You are U WILL CLASSES schedule assistant. Answer the user question accurately based on the provided timetable data.",
            f"{context_prompt}\n\nUser Question: {user_question}"
        )
        return gemini_ans if gemini_ans else deterministic_ans

    # 3. Check Weekly Tests Match
    if "TEST" in q or "EXAM" in q:
        res = [s for s in slots if s["faculty"] == "WEEKLY TEST" or "TEST" in s["subject"]]
        centers = list(set(s["center"] for s in slots))
        matched_c = [c for c in centers if c in q]
        if matched_days:
            res = [s for s in res if s["day"] in matched_days]
        if matched_c:
            res = [s for s in res if s["center"] in matched_c]

        title = "Weekly Tests & Exam Schedule"
        if matched_c: title += f" at {', '.join(matched_c)}"
        if matched_days: title += f" on {', '.join(matched_days)}"

        deterministic_ans = _format_slots_as_markdown(title, res)
        return deterministic_ans

    # 4. General Query -> Call Gemini with compact summary
    summary_lines = []
    # Take compact representation of all batches
    for s in slots:
        summary_lines.append(f"{s['day'][:3]}|{s['start']}-{s['end']}|{s['center']}|{s['batch']}|{s['subject']}|{s['faculty']}")

    gemini_ans = call_gemini_raw(
        "You are U WILL CLASSES AI Assistant. You have access to the master timetable for 11 branches and 41 faculties. Answer user timetable queries accurately and concisely.",
        f"Master Schedule:\n" + "\n".join(summary_lines[:250]) + f"\n\nUser Question: {user_question}"
    )

    if gemini_ans:
        return gemini_ans

    return (
        "I couldn't locate a specific faculty or batch in your query. "
        "Try asking: \n"
        "- *'Show me Vicky Sir schedule on Monday'*\n"
        "- *'Show me Aasif Sir schedule for Wednesday'*\n"
        "- *'Timetable for VB 12TH GSEB (FLEXI)'*\n"
        "- *'Show me Weekly Tests on Monday'*"
    )

def explain_infeasibility(error_details: str) -> str:
    system_prompt = """You are an expert Operations Research & Timetable Infeasibility Diagnostician for U WILL CLASSES.
When a schedule configuration is mathematically unsolvable (UNSAT), analyze the exact conflict report provided and give:
1. Root Cause Summary: Explain in plain English which faculty, branch, or time window is overloaded.
2. 2 to 3 Actionable Fixes: Practical remedies for the institute coordinator (e.g. increase evening availability by 30 mins, swap to a 2-day block, or reassign a subject to another teacher).
Keep the tone helpful and professional.
"""
    ans = call_gemini_raw(system_prompt, f"Analyze this timetable conflict report and explain fixes:\n\n{error_details}")
    if ans:
        return ans

    return (
        "### Infeasibility Diagnostic Report\n\n"
        "**Root Cause**: The constraint solver encountered a mathematical conflict where total required lecture hours "
        "plus transit travel buffers exceeded the operating window.\n\n"
        "**Actionable Fixes**:\n"
        "1. Check if the faculty is assigned to multiple distant branches (e.g. VB and PNG) in the same morning/evening window.\n"
        "2. Adjust the daily required duration in Google Sheets (e.g., from 90 mins to 60 mins).\n"
        "3. Reassign one of the batch requirements to another faculty."
    )
