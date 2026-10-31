import csv
from collections import defaultdict

eve_hours = defaultdict(float)
mrg_hours = defaultdict(float)

with open("data/faculty_master.csv") as f:
    for r in csv.DictReader(f):
        fac = r["Faculty Name"].strip().upper()
        c = r["Assigned Centers"].strip()
        b = r["Assigned Batch"].strip()
        h_str = r["Max Weekly Hours"].strip()
        if not (fac and h_str): continue
        h = float(h_str)
        if c in ["SUB", "OP", "NZM", "VB", "PNG"] and "MRG" not in b:
            eve_hours[fac] += h
        else:
            mrg_hours[fac] += h

print("=== FACULTY AUDIT: WORKLOAD VS THEORETICAL MAX CAPACITY ===")
print("Max evening window = 4.5h x 6 days = 27h (or 5.0h x 6 = 30h at SUB)")
print("Max morning window = 5.0h x 6 days = 30h\n")

for fac in sorted(set(list(eve_hours.keys()) + list(mrg_hours.keys()))):
    eh = eve_hours[fac]
    mh = mrg_hours[fac]
    flags = []
    if eh > 27.0:
        flags.append(f"OVERLOAD EVENING: {eh:.1f}h > 27h")
    if mh > 30.0:
        flags.append(f"OVERLOAD MORNING: {mh:.1f}h > 30h")
    if flags:
        print(f"⚠️ {fac:20s}: " + ", ".join(flags))
