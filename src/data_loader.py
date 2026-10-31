import csv
import json
import os
import re
from typing import Dict, List, Tuple, Optional
from src.models import BatchInfo, FacultyRestrictions, SubjectRequirement, FixedLecture

DAYS_OF_WEEK = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

def parse_time_to_minutes(t_str: Optional[str]) -> Optional[int]:
    if not t_str or not t_str.strip():
        return None
    s = t_str.strip().upper().replace(".", ":")
    is_pm = "PM" in s
    is_am = "AM" in s
    clean = s.replace("AM", "").replace("PM", "").strip()
    parts = clean.split(":")
    if not parts or not parts[0].isdigit():
        return None
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if is_pm and h < 12:
        h += 12
    if is_am and h == 12:
        h = 0
    return h * 60 + m

def minutes_to_str(m: Optional[int]) -> str:
    if m is None:
        return ""
    h = m // 60
    mins = m % 60
    suffix = "AM" if h < 12 else "PM"
    h_disp = h if h <= 12 else h - 12
    if h_disp == 0:
        h_disp = 12
    return f"{h_disp}:{mins:02d} {suffix}"

def norm_subj(s: str) -> str:
    s = s.strip().upper()
    if s == "STATS":
        return "STATISTICS"
    if s in ["BST", "B.ST", "B.STUDIES"]:
        return "BUSINESS STUDIES"
    return s

def norm_batch(b: str) -> str:
    return b.strip().upper()

def norm_day(d: str) -> str:
    d = d.strip().upper()
    for day in DAYS_OF_WEEK:
        if day in d:
            return day
    return d

class DataLoader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.batches: Dict[Tuple[str, str], BatchInfo] = {}
        self.faculties: Dict[str, FacultyRestrictions] = {}
        self.subject_requirements: List[SubjectRequirement] = []
        self.fixed_lectures: List[FixedLecture] = []
        self.travel_matrix: Dict[Tuple[str, str], int] = {}

    def load_all(self):
        self._load_centers_and_batches()
        self._load_recess()
        self._load_faculty_details()
        self._load_faculty_master_and_subjects()
        self._load_visiting_faculty()
        self._load_travel_matrix()

        # Deduplicate requirements that are already 100% scheduled as fixed lectures
        fixed_counts = {}
        for fl in self.fixed_lectures:
            k = (fl.center, fl.batch, fl.subject, fl.faculty)
            fixed_counts[k] = fixed_counts.get(k, 0) + 1

        filtered_reqs = []
        for req in self.subject_requirements:
            k = (req.center, req.batch, req.subject, req.faculty)
            fc = fixed_counts.get(k, 0)
            if fc >= req.weekly_days:
                continue
            elif fc > 0:
                req.weekly_days -= fc
                req.weekly_hours = max(0.0, req.weekly_hours - (fc * req.daily_duration_min / 60.0))
                filtered_reqs.append(req)
            else:
                filtered_reqs.append(req)
        self.subject_requirements = filtered_reqs

    def _load_centers_and_batches(self):
        path = f"{self.data_dir}/center_and_batch_master.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = row["Center Name"].strip().upper()
                raw_b = row["Batch Name"].strip().upper()
                if not c or not raw_b:
                    continue
                es = parse_time_to_minutes(row["Earliest Start"])
                le = parse_time_to_minutes(row["Latest End"])
                raw_days = row["Operating Days"].split(",")
                days = [norm_day(d) for d in raw_days if norm_day(d) in DAYS_OF_WEEK]
                smode = row.get("Start Time Mode", "Flexible").strip()
                emode = row.get("End Time Mode", "Flexible").strip()

                # If BRIGHT 11TH CBSE, duplicate for B and C sections
                batch_names = [raw_b]
                if c == "BRIGHT" and raw_b == "11TH CBSE":
                    batch_names = ["11TH CBSE - B", "11TH CBSE - C"]

                for b in batch_names:
                    key = (c, b)
                    if key not in self.batches:
                        self.batches[key] = BatchInfo(
                            center=c,
                            name=b,
                            earliest_start_min=es,
                            latest_end_min=le,
                            operating_days=list(days),
                            start_mode=smode,
                            end_mode=emode,
                            day_earliest_start={d: es for d in days},
                            day_latest_end={d: le for d in days}
                        )
                    else:
                        b_obj = self.batches[key]
                        for d in days:
                            if d not in b_obj.operating_days:
                                b_obj.operating_days.append(d)
                            b_obj.day_earliest_start[d] = es
                            b_obj.day_latest_end[d] = le
                        b_obj.earliest_start_min = min(b_obj.day_earliest_start.values())
                        b_obj.latest_end_min = max(b_obj.day_latest_end.values())

        # Fallback for batches present in subject_rules.csv or visiting_faculty_fixed.csv
        # that are not explicitly defined in center_and_batch_master.csv
        sr_path = f"{self.data_dir}/subject_rules.csv"
        if os.path.exists(sr_path):
            with open(sr_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    c = row.get("Center Name", "").strip().upper()
                    raw_b = row.get("Batch Name", "").strip().upper()
                    if not c or not raw_b:
                        continue
                    key = (c, raw_b)
                    if key not in self.batches:
                        base_b = raw_b.replace("(FLEXI)", "").strip()
                        base_key = (c, base_b)
                        if base_key in self.batches:
                            base = self.batches[base_key]
                            self.batches[key] = BatchInfo(
                                center=c,
                                name=raw_b,
                                earliest_start_min=base.earliest_start_min,
                                latest_end_min=base.latest_end_min,
                                operating_days=list(base.operating_days),
                                start_mode=base.start_mode,
                                end_mode=base.end_mode,
                                day_earliest_start=dict(base.day_earliest_start),
                                day_latest_end=dict(base.day_latest_end)
                            )

    def _load_recess(self):
        path = f"{self.data_dir}/recess_master_fixed.csv"
        if not os.path.exists(path):
            return

        solved_path = f"{self.data_dir}/solved_recess.json"
        solved_recesses = {}
        if os.path.exists(solved_path):
            try:
                with open(solved_path, "r", encoding="utf-8") as sf:
                    solved_recesses = json.load(sf)
            except Exception:
                pass

        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = row.get("Center Name", "").strip().upper()
                b = row.get("Batch Name", "").strip().upper()
                st_str = row.get("Start Time", "").strip()
                et_str = row.get("End Time", "").strip()
                if not c or not b or not st_str or not et_str:
                    continue
                st = parse_time_to_minutes(st_str)
                et = parse_time_to_minutes(et_str)
                time_str = row.get("TIME", "").strip()
                dur_match = re.search(r'\d+', time_str)
                dur = int(dur_match.group()) if dur_match else (et - st)
                mode_str = row.get("FIXED/FLEXIBLE", "Fixed").strip().upper()
                mode = "Flexible" if "FLEX" in mode_str else "Fixed"

                for (bc, bb), b_info in self.batches.items():
                    if bc == c:
                        if bb == b or (c == "BRIGHT" and "11TH CBSE" in bb):
                            b_info.recess_earliest_start_min = st
                            b_info.recess_latest_end_min = et
                            b_info.recess_mode = mode

                            if mode == "Fixed":
                                b_info.recess_start_min = st
                                b_info.recess_end_min = et
                                b_info.recess_duration_min = et - st
                            else:
                                b_info.recess_duration_min = dur
                                key_str = f"{bc}_{bb}"
                                if key_str in solved_recesses:
                                    b_info.recess_start_min = solved_recesses[key_str]["start_min"]
                                    b_info.recess_end_min = solved_recesses[key_str]["end_min"]
                                else:
                                    # Fallback default: set recess within [st, et]
                                    b_info.recess_start_min = st
                                    b_info.recess_end_min = st + dur

    def _load_faculty_details(self):
        path = f"{self.data_dir}/faculty_details.csv"
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if len(rows) < 3:
            return

        for row in rows[2:]:
            if not row or not row[0]:
                continue
            fac = row[0].strip().upper()
            if not fac:
                continue
            restr = self.faculties.get(fac) or FacultyRestrictions(name=fac)
            for d_idx, day in enumerate(DAYS_OF_WEEK):
                base_col = 1 + d_idx * 4
                if base_col + 3 < len(row):
                    mrg_from = parse_time_to_minutes(row[base_col])
                    mrg_to = parse_time_to_minutes(row[base_col + 1])
                    eve_from = parse_time_to_minutes(row[base_col + 2])
                    eve_to = parse_time_to_minutes(row[base_col + 3])
                else:
                    mrg_from = mrg_to = eve_from = eve_to = None
                restr.day_limits[day] = {
                    "mrg_from": mrg_from,
                    "mrg_to": mrg_to,
                    "eve_from": eve_from,
                    "eve_to": eve_to
                }
            self.faculties[fac] = restr
            if fac == "ASIF SIR":
                self.faculties["AASIF SIR"] = restr
            elif fac == "AASIF SIR":
                self.faculties["ASIF SIR"] = restr

    def _load_faculty_master_and_subjects(self):
        fm_map = {}
        fm_lecture_info = {}
        fm_path = f"{self.data_dir}/faculty_master.csv"
        with open(fm_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = row["Assigned Centers"].strip().upper()
                raw_b = row["Assigned Batch"].strip().upper()
                b = norm_batch(raw_b)
                raw_s = row["Core Subjects"].strip().upper()
                fac = row["Faculty Name"].strip().upper()
                avail_from = parse_time_to_minutes(row.get("Available From"))
                avail_to = parse_time_to_minutes(row.get("Available To"))

                max_hrs_str = row.get("Max Weekly Hours", "").strip()
                no_of_lecs_str = row.get("No. of Lectures", "").strip()

                if fac and fac not in self.faculties:
                    self.faculties[fac] = FacultyRestrictions(name=fac)
                
                if fac and avail_to:
                    self.faculties[fac].available_to_min = avail_to
                if fac and avail_from:
                    self.faculties[fac].available_from_min = avail_from

                # Parse Max Weekly Hours and No. of Lectures
                lec_info = None
                if max_hrs_str and no_of_lecs_str:
                    try:
                        m_hrs = float(max_hrs_str)
                        if abs(m_hrs - 3.45) < 0.001:
                            m_hrs = 3.75
                        n_lecs = int(float(no_of_lecs_str))
                        if n_lecs > 0:
                            calc_daily_min = int(round((m_hrs / n_lecs) * 60))
                            lec_info = {
                                "faculty": fac,
                                "weekly_hours": m_hrs,
                                "weekly_days": n_lecs,
                                "daily_duration_min": calc_daily_min
                            }
                    except ValueError:
                        pass

                is_extra = "EXTRA" in raw_s
                subjs = [norm_subj(s.replace("- EXTRA", "").strip()) for s in raw_s.split("&")]
                for s in subjs:
                    if is_extra and (c, b, s) in fm_map:
                        continue
                    fm_map[(c, b, s)] = fac
                    fm_map[(c, raw_b, s)] = fac
                    if c == "BRIGHT" and "11TH CBSE" in b:
                        fm_map[(c, "11TH CBSE - B", s)] = fac
                        fm_map[(c, "11TH CBSE - C", s)] = fac

                if lec_info:
                    if len(subjs) == 1:
                        s = subjs[0]
                        if not is_extra or (c, b, s) not in fm_lecture_info:
                            fm_lecture_info[(c, b, s, fac)] = lec_info
                            fm_lecture_info[(c, raw_b, s, fac)] = lec_info
                            fm_lecture_info[(c, b, s)] = lec_info
                            fm_lecture_info[(c, raw_b, s)] = lec_info
                            if c == "BRIGHT" and "11TH CBSE" in b:
                                fm_lecture_info[(c, "11TH CBSE - B", s)] = lec_info
                                fm_lecture_info[(c, "11TH CBSE - C", s)] = lec_info
                    else:
                        comb_s = norm_subj(raw_s.replace("- EXTRA", "").strip())
                        fm_lecture_info[(c, b, comb_s)] = lec_info
                        fm_lecture_info[(c, raw_b, comb_s)] = lec_info

        sr_path = f"{self.data_dir}/subject_rules.csv"
        req_count = 0
        seen_png_12th_gseb = 0
        seen_png_11th_eco = 0
        png_is_evening = False

        with open(sr_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = row["Center Name"].strip().upper()
                raw_b = row["Batch Name"].strip().upper()
                s = norm_subj(row["Subject"])
                test_col = row.get("Weekly Tests Required", "").strip().upper()
                if not c or not raw_b or not s:
                    continue

                # Disambiguate BRIGHT sections B and C
                if c == "BRIGHT" and "11TH CBSE" in raw_b:
                    if "BATCH - B" in test_col:
                        raw_b = "11TH CBSE - B"
                    elif "BATCH - C" in test_col:
                        raw_b = "11TH CBSE - C"

                # Disambiguate PNG Morning vs Evening
                if c == "PNG" and "GSEB" in raw_b:
                    if "EVE" in raw_b:
                        png_is_evening = True
                    elif "MRG" in raw_b:
                        png_is_evening = False
                    elif png_is_evening:
                        raw_b = "11TH GSEB - EVE" if "11" in raw_b else "12TH GSEB - EVE"
                    else:
                        raw_b = "11TH GSEB - MRG" if "11" in raw_b else "12TH GSEB - MRG"

                b = norm_batch(raw_b)

                d_hrs = float(row.get("Daily Hours Required", "1") or "1")
                w_hrs = float(row.get("Weekly Hours Required", "3") or "3")
                w_days_str = row.get("Weekly Days Required", "3").strip()
                try:
                    w_days = int(float(w_days_str))
                except:
                    w_days = int(round(w_hrs / d_hrs)) if d_hrs > 0 else 3

                shared = row.get("Subject shared by", "").strip().upper()
                faculty = shared if shared else None

                if not faculty:
                    faculty = fm_map.get((c, b, s)) or fm_map.get((c, raw_b, s))

                if not faculty:
                    # Prefer faculty whose specified weekly_days matches w_days
                    for k, info in fm_lecture_info.items():
                        if len(k) == 4:
                            fc, fb, fs, f_name = k
                            if fc == c and fs == s and (fb in b or b in fb):
                                if info.get("weekly_days") == w_days:
                                    faculty = f_name
                                    break

                if not faculty:
                    for (fc, fb, fs), f_name in fm_map.items():
                        if fc == c and (fb in b or b in fb):
                            if s == fs or s in fs or fs in s:
                                faculty = f_name
                                s = fs
                                break

                if not faculty and any(sub in s for sub in ["ENGLISH", "GUJARATI", "COMPUTER", "HINDI", "YOGA", "IP/PE"]):
                    continue

                if not faculty and s in ["ME", "IED", "MACRO ECONOMICS"]:
                    faculty = fm_map.get((c, b, "ECONOMICS")) or fm_map.get((c, raw_b, "ECONOMICS"))

                if not faculty:
                    faculty = f"TBD_{s}"

                req_count += 1

                # Check if faculty master specifies No. of Lectures and Max Weekly Hours
                lec_info = (fm_lecture_info.get((c, b, s, faculty)) or
                            fm_lecture_info.get((c, raw_b, s, faculty)) or
                            fm_lecture_info.get((c, b, s)) or
                            fm_lecture_info.get((c, raw_b, s)))

                is_multi_row_split = (c == "VB" and "12TH GSEB" in raw_b and "FLEXI" in raw_b and s in ["ACCOUNTS", "STATISTICS"])

                if lec_info and not is_multi_row_split:
                    daily_min = lec_info["daily_duration_min"]
                    w_days = lec_info["weekly_days"]
                    w_hrs = lec_info["weekly_hours"]
                else:
                    daily_min = int(round(d_hrs * 60))

                req = SubjectRequirement(
                    req_id=f"req_{req_count}",
                    center=c,
                    batch=raw_b,
                    subject=s,
                    faculty=faculty,
                    daily_duration_min=daily_min,
                    weekly_hours=w_hrs,
                    weekly_days=w_days,
                    allow_duration_flex=True
                )
                self.subject_requirements.append(req)

    def _load_visiting_faculty(self):
        path = f"{self.data_dir}/visiting_faculty_fixed.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                c = row["Center Name"].strip().upper()
                raw_b = row["Batch Name"].strip().upper()
                day = norm_day(row["Day"])
                st = parse_time_to_minutes(row["Start Time"])
                et = parse_time_to_minutes(row["End Time"])
                s = row["Subject"].strip().upper()
                fac = row["Faculty Name"].strip().upper()
                extra_col = row.get("", "").strip().upper()

                if c == "BRIGHT" and "11TH CBSE" in raw_b:
                    if "BATCH - B" in extra_col:
                        raw_b = "11TH CBSE - B"
                    elif "BATCH - C" in extra_col:
                        raw_b = "11TH CBSE - C"

                if c and raw_b and day in DAYS_OF_WEEK and st and et:
                    self.fixed_lectures.append(FixedLecture(
                        center=c,
                        batch=raw_b,
                        day=day,
                        start_min=st,
                        end_min=et,
                        subject=s,
                        faculty=fac
                    ))

    def _load_travel_matrix(self):
        path = f"{self.data_dir}/travel_time_matrix.csv"
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fc = row.get("From Center", "").strip().upper()
                tc = row.get("To Center", "").strip().upper()
                tt_str = row.get("Travel Time (in minutes)", "").strip()
                if fc and tc and tt_str:
                    try:
                        self.travel_matrix[(fc, tc)] = int(tt_str)
                    except:
                        pass
