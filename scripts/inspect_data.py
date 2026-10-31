import csv
import json

def parse_time_to_minutes(t_str):
    if not t_str or not t_str.strip():
        return None
    t_str = t_str.strip().upper().replace(".", ":")
    # Handle cases like "7:30 AM", "6:00 PM", "7:45 AM"
    # Sometimes written as "7.30 AM" or "7:30AM"
    is_pm = "PM" in t_str
    is_am = "AM" in t_str
    clean = t_str.replace("AM", "").replace("PM", "").strip()
    parts = clean.split(":")
    if len(parts) == 1:
        h = int(parts[0])
        m = 0
    else:
        h = int(parts[0])
        m = int(parts[1])
    if is_pm and h < 12:
        h += 12
    if is_am and h == 12:
        h = 0
    return h * 60 + m

def minutes_to_str(m):
    if m is None:
        return ""
    h = m // 60
    mins = m % 60
    suffix = "AM" if h < 12 else "PM"
    h_disp = h if h <= 12 else h - 12
    if h_disp == 0:
        h_disp = 12
    return f"{h_disp}:{mins:02d} {suffix}"

print("=== CHECKING CENTER AND BATCH MASTER ===")
with open("data/center_and_batch_master.csv") as f:
    r = csv.DictReader(f)
    for row in r:
        c = row["Center Name"].strip()
        b = row["Batch Name"].strip()
        es = parse_time_to_minutes(row["Earliest Start"])
        le = parse_time_to_minutes(row["Latest End"])
        days = [d.strip() for d in row["Operating Days"].split(",") if d.strip()]
        smode = row.get("Start Time Mode", "").strip()
        emode = row.get("End Time Mode", "").strip()
        print(f"[{c} - {b}] {minutes_to_str(es)} ({es}m) -> {minutes_to_str(le)} ({le}m) | Days: {len(days)} | Mode: {smode}/{emode}")

print("\n=== CHECKING RECESS MASTER FIXED ===")
with open("data/recess_master_fixed.csv") as f:
    r = csv.DictReader(f)
    for row in r:
        c = row["Center Name"].strip()
        b = row["Batch Name"].strip()
        st = parse_time_to_minutes(row["Start Time"])
        et = parse_time_to_minutes(row["End Time"])
        print(f"[{c} - {b}] Recess: {minutes_to_str(st)} ({st}m) -> {minutes_to_str(et)} ({et}m) [{et-st} mins]")

print("\n=== CHECKING VISITING FACULTY FIXED ===")
with open("data/visiting_faculty_fixed.csv") as f:
    r = csv.DictReader(f)
    vf_list = list(r)
    print(f"Total Visiting Faculty slots: {len(vf_list)}")
    for row in vf_list[:5]:
        c = row["Center Name"].strip()
        b = row["Batch Name"].strip()
        day = row["Day"].strip()
        st = parse_time_to_minutes(row["Start Time"])
        et = parse_time_to_minutes(row["End Time"])
        sub = row["Subject"].strip()
        fac = row["Faculty Name"].strip()
        print(f"[{c} - {b} - {day}] {minutes_to_str(st)} -> {minutes_to_str(et)}: {sub} by {fac}")

print("\n=== CHECKING TRAVEL TIME MATRIX ===")
with open("data/travel_time_matrix.csv") as f:
    r = csv.DictReader(f)
    travel = {}
    for row in r:
        f_c = row.get("From Center", "").strip()
        t_c = row.get("To Center", "").strip()
        tt = row.get("Travel Time (in minutes)", "").strip()
        if f_c and t_c and tt:
            travel[(f_c, t_c)] = int(tt)
    print(f"Total travel entries: {len(travel)}")
