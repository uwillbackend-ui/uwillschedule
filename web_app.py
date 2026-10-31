import http.server
import socketserver
import json
import os
import sys
import zipfile
import io
import urllib.parse

sys.path.insert(0, os.path.abspath("."))

from src.data_loader import DataLoader, parse_time_to_minutes, minutes_to_str, DAYS_OF_WEEK
from src.formatter import TimetableFormatter
from src.pdf_generator import TimetablePDFGenerator
from src.excel_exporter import ExcelExporter
import generate_timetable
import update_topics_and_export_pdfs
import sync_from_google_sheets
import openpyxl
import shutil

PORT = 8080

def get_excel_path(academic_year: str = "2026-27"):
    year_suffix = "_2027_28" if academic_year == "2027-28" else "_2026_27"
    candidates = [
        f"/tmp/excel/Weekly_Schedule_Input_Topics{year_suffix}.xlsx",
        f"/tmp/Weekly_Schedule_Input_Topics{year_suffix}.xlsx",
        f"output/excel/Weekly_Schedule_Input_Topics{year_suffix}.xlsx",
    ]
    if academic_year == "2026-27":
        candidates.extend([
            "/tmp/excel/Weekly_Schedule_Input_Topics.xlsx",
            "/tmp/Weekly_Schedule_Input_Topics.xlsx",
            "output/excel/Weekly_Schedule_Input_Topics.xlsx"
        ])
    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 0:
            return c
    return candidates[2]

def get_output_base():
    if os.environ.get("VERCEL") or not os.access("output", os.W_OK):
        return "/tmp"
    return "output"

def get_html_page():
    index_path = os.path.join(os.path.dirname(__file__), "public", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>U WILL CLASSES - Timetable Command Center</h1>"

HTML_PAGE = get_html_page()

class SchedulerRequestHandler(http.server.SimpleHTTPRequestHandler):
    def _resolve_path(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "path" in qs:
            return qs["path"][0]
        fwd = self.headers.get("x-forwarded-uri")
        if fwd:
            return urllib.parse.urlparse(fwd).path
        return parsed.path

    def _get_query_param(self, param_name):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if param_name in qs:
            return qs[param_name][0]
        if "path" in qs:
            sub_parsed = urllib.parse.urlparse(qs["path"][0])
            sub_qs = urllib.parse.parse_qs(sub_parsed.query)
            if param_name in sub_qs:
                return sub_qs[param_name][0]
        fwd = self.headers.get("x-forwarded-uri")
        if fwd:
            fwd_parsed = urllib.parse.urlparse(fwd)
            fwd_qs = urllib.parse.parse_qs(fwd_parsed.query)
            if param_name in fwd_qs:
                return fwd_qs[param_name][0]
        return ""

    def do_HEAD(self):
        path = self._resolve_path()
        self.send_response(200)
        if path == "/api/data":
            self.send_header("Content-Type", "application/json; charset=utf-8")
        else:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        path = self._resolve_path()

        if path in ["/", "/index.html", "/api/index"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(get_html_page().encode("utf-8"))
            return

        elif path == "/api/data":
            self.handle_get_data()
            return

        elif path == "/api/download/batch-pdf":
            b_name = self._get_query_param("name")
            self.handle_download_single_batch_pdf(b_name)
            return

        elif path == "/api/download/faculty-pdf":
            f_name = self._get_query_param("name")
            self.handle_download_single_faculty_pdf(f_name)
            return

        elif path == "/api/download/batch-pdfs":
            self.handle_download_zip("pdf", "Student_Batch_Timetables_PDFs.zip")
            return

        elif path == "/api/download/faculty-pdfs":
            self.handle_download_zip("faculty_pdf", "Faculty_Personal_Schedules_PDFs.zip")
            return

        elif path == "/api/download/all-batches-excel":
            self.handle_download_all_batches_excel()
            return

        elif path == "/api/download/all-faculties-excel":
            self.handle_download_all_faculties_excel()
            return

        elif path == "/api/library/current":
            try:
                year = self._get_query_param("year") or "2026-27"
                excel_path = get_excel_path(academic_year=year)
                if not os.path.exists(excel_path):
                    self.send_json_response(404, {"success": False, "message": f"No schedule generated yet for {year}."})
                    return
                wb = openpyxl.load_workbook(excel_path, data_only=True)
                ws = wb.active
                topics = []
                batches_set = set()
                faculties_set = set()
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if not row or not row[0]: continue
                    c, b, d, st_str, et_str, dur, subj, fac, ch, top = row[:10]
                    batches_set.add(f"{c} - {b}")
                    if fac:
                        faculties_set.add(str(fac).strip())
                    topics.append({
                        "center": str(c),
                        "batch": str(b),
                        "day": str(d),
                        "time": f"{st_str} - {et_str}",
                        "start_time": str(st_str),
                        "end_time": str(et_str),
                        "duration": dur,
                        "subject": str(subj),
                        "faculty": str(fac),
                        "chapter": str(ch or ""),
                        "topic": str(top or "")
                    })
                from datetime import datetime
                now_dt = datetime.now()
                self.send_json_response(200, {
                    "success": True,
                    "title": f"Schedule ({year}) - {now_dt.strftime('%d/%m/%Y, %I:%M %p')}",
                    "academicYear": year,
                    "createdAt": now_dt.isoformat(),
                    "folder": "past",
                    "finalisedDate": None,
                    "summary": {
                        "totalBatches": len(batches_set),
                        "totalFaculties": len(faculties_set),
                        "totalSlots": len(topics)
                    },
                    "topics": topics
                })
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/export/batches_data":
            try:
                year = self._get_query_param("year") or "2026-27"
                from src import google_sheets_exporter
                payload = google_sheets_exporter.get_batches_payload(output_base=get_output_base(), year=year)
                self.send_json_response(200, payload)
            except Exception as e:
                self.send_json_response(500, {"status": "error", "message": str(e)})
            return

        elif path == "/api/export/faculties_data":
            try:
                year = self._get_query_param("year") or "2026-27"
                from src import google_sheets_exporter
                payload = google_sheets_exporter.get_faculties_payload(output_base=get_output_base(), year=year)
                self.send_json_response(200, payload)
            except Exception as e:
                self.send_json_response(500, {"status": "error", "message": str(e)})
            return

        elif path == "/api/export/google_sheets_data":
            try:
                year = self._get_query_param("year") or "2026-27"
                from src import google_sheets_exporter
                payload = google_sheets_exporter.build_google_sheets_payload(output_base=get_output_base(), year=year)
                self.send_json_response(200, payload)
            except Exception as e:
                self.send_json_response(500, {"status": "error", "message": str(e)})
            return

        elif path in ["/google_apps_script.js", "/batch_google_apps_script.js", "/faculty_google_apps_script.js"]:
            f_name = path.lstrip("/")
            if os.path.exists(f_name):
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                with open(f_name, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error(404, "Script not found")
                return

        elif path == "/api/download/excel":
            year = self._get_query_param("year") or "2026-27"
            excel_path = get_excel_path(academic_year=year)
            if os.path.exists(excel_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", f"attachment; filename=Weekly_Schedule_Input_Topics_{year.replace('-', '_')}.xlsx")
                with open(excel_path, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error(404, "Excel file not found")
                return

        elif path in ["/uwill_logo.png", "/public/uwill_logo.png", "/assets/uwill_logo.png"] or path.endswith(".png"):
            clean_path = path.lstrip("/")
            candidate_paths = [
                clean_path,
                os.path.join("public", os.path.basename(clean_path)),
                os.path.join("assets", os.path.basename(clean_path))
            ]
            found_img = None
            for cp in candidate_paths:
                if os.path.exists(cp) and os.path.isfile(cp):
                    found_img = cp
                    break
            if found_img:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=86400")
                with open(found_img, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error(404, "Image not found")
                return

        elif path.startswith("/output/") or path.endswith(".pdf"):
            clean_path = path.lstrip("/")
            out_base = get_output_base()
            file_path = os.path.join(out_base, clean_path.replace("output/", ""))
            if not os.path.exists(file_path):
                file_path = clean_path
            if os.path.exists(file_path) and os.path.isfile(file_path):
                self.send_response(200)
                if file_path.endswith(".pdf"):
                    self.send_header("Content-Type", "application/pdf")
                elif file_path.endswith(".xlsx"):
                    self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_error(404, "File not found")
                return

        self.send_error(404, "Page not found")

    def do_POST(self):
        path = self._resolve_path()

        if path == "/api/sync":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
                data = json.loads(body) if body else {}
                year = data.get("year") or self._get_query_param("year") or "2026-27"
                
                # Fast sync of all CSVs and Standing Rules from Google Sheets (takes ~3s)
                data_dir = sync_from_google_sheets.sync_data(academic_year=year)
                
                # If explicit solve was requested and not running on serverless Vercel
                if (data.get("generate") or data.get("solve")) and not os.environ.get("VERCEL"):
                    generate_timetable.run_schedule_generation(sync_first=False, academic_year=year)
                    try:
                        from src import google_sheets_exporter
                        google_sheets_exporter.auto_push_all(output_base=get_output_base(), year=year)
                    except Exception:
                        pass
                    msg = f"Synced latest requirements from Google Sheets and regenerated schedule for {year}!"
                else:
                    msg = f"Synced all master requirements and Standing Rules live from Google Sheets for {year} successfully!"

                self.send_json_response(200, {"success": True, "message": msg, "data_dir": data_dir})
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/generate":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
                data = json.loads(body) if body else {}
                year = data.get("year") or self._get_query_param("year") or "2026-27"
                generate_timetable.run_schedule_generation(sync_first=True, academic_year=year)
                try:
                    from src import google_sheets_exporter
                    google_sheets_exporter.auto_push_all(output_base=get_output_base(), year=year)
                except Exception:
                    pass
                self.send_json_response(200, {"success": True, "message": f"Timetable for {year} generated successfully with 0 overlaps, exact travel buffers & block consistency!"})
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/topics":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body)
                if isinstance(data, dict) and "topics" in data:
                    topics_list = data["topics"]
                    year = data.get("year") or self._get_query_param("year") or "2026-27"
                else:
                    topics_list = data
                    year = self._get_query_param("year") or "2026-27"
                self.save_updated_topics(topics_list, academic_year=year)
                self.send_json_response(200, {"success": True, "message": f"Topics for {year} saved and PDFs regenerated!"})
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/chat":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body) if body else {}
                user_msg = data.get("message", "")
                from src import ai_assistant
                reply_obj = ai_assistant.ask_assistant(user_msg)
                if isinstance(reply_obj, dict):
                    self.send_json_response(200, {
                        "success": True,
                        "reply": reply_obj.get("reply"),
                        "reschedule_data": reply_obj.get("reschedule_data")
                    })
                else:
                    self.send_json_response(200, {"success": True, "reply": reply_obj})
            except Exception as e:
                self.send_json_response(500, {"success": False, "reply": f"Error: {str(e)}"})
            return

        elif path == "/api/reschedule/propose":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body) if body else {}
                instruction = data.get("instruction", "")
                from src import rescheduler, ai_assistant
                slots = ai_assistant.load_timetable_slots()
                prop = rescheduler.parse_reschedule_intent(instruction, slots)
                sim = rescheduler.validate_and_simulate_change(prop, slots)
                md = rescheduler.format_reschedule_markdown(sim)
                self.send_json_response(200, {
                    "success": True,
                    "data": sim,
                    "markdown": md
                })
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/reschedule/apply":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body) if body else {}
                token = data.get("token", "")
                from src import rescheduler
                res = rescheduler.apply_and_lock_schedule(token)
                if res.get("success"):
                    try:
                        from src import google_sheets_exporter
                        google_sheets_exporter.auto_push_all(output_base=get_output_base())
                    except Exception:
                        pass
                self.send_json_response(200, res)
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/export/push_to_sheets":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
                data = json.loads(body) if body else {}
                webhook_url = data.get("webhook_url")
                batch_webhook_url = data.get("batch_webhook_url")
                faculty_webhook_url = data.get("faculty_webhook_url")
                year = data.get("year") or self._get_query_param("year") or "2026-27"
                from src import google_sheets_exporter
                result = google_sheets_exporter.push_to_google_apps_script(
                    webhook_url=webhook_url,
                    batch_webhook_url=batch_webhook_url,
                    faculty_webhook_url=faculty_webhook_url,
                    output_base=get_output_base(),
                    year=year
                )
                self.send_json_response(200, result)
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/reschedule/discard":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body) if body else {}
                token = data.get("token", "")
                from src import rescheduler
                if token in rescheduler.PENDING_PROPOSALS:
                    del rescheduler.PENDING_PROPOSALS[token]
                self.send_json_response(200, {"success": True, "message": "Proposal discarded."})
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/library/load":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body) if body else {}
                topics_list = data.get("topics", [])
                if not topics_list:
                    self.send_json_response(400, {"success": False, "message": "No topics or slots data provided in payload."})
                    return

                year = data.get("academicYear") or data.get("academic_year") or self._get_query_param("year") or "2026-27"
                excel_path = get_excel_path(academic_year=year)
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Weekly_Schedule"
                headers = [
                    "Center", "Batch", "Day", "Start Time", "End Time",
                    "Duration", "Subject", "Faculty", "Chapter", "Topic"
                ]
                ws.append(headers)

                for item in topics_list:
                    time_str = item.get("time", "")
                    st_str = item.get("start_time", "")
                    et_str = item.get("end_time", "")
                    if not st_str or not et_str:
                        if " - " in time_str:
                            parts = time_str.split(" - ")
                            st_str = parts[0].strip()
                            et_str = parts[1].strip()

                    dur = item.get("duration", 60)
                    if not dur and st_str and et_str:
                        try:
                            dur = parse_time_to_minutes(et_str) - parse_time_to_minutes(st_str)
                        except:
                            dur = 60

                    ws.append([
                        item.get("center", ""),
                        item.get("batch", ""),
                        item.get("day", ""),
                        st_str,
                        et_str,
                        dur,
                        item.get("subject", ""),
                        item.get("faculty", ""),
                        item.get("chapter", ""),
                        item.get("topic", "")
                    ])

                wb.save(excel_path)

                from src.models import ScheduledSlot
                slots = []
                topics = []
                for item in topics_list:
                    c = str(item.get("center", ""))
                    b = str(item.get("batch", ""))
                    d = str(item.get("day", ""))
                    time_str = item.get("time", "")
                    st_str = item.get("start_time", "")
                    et_str = item.get("end_time", "")
                    if not st_str or not et_str:
                        if " - " in time_str:
                            parts = time_str.split(" - ")
                            st_str = parts[0].strip()
                            et_str = parts[1].strip()

                    dur = item.get("duration", 60)
                    if not dur and st_str and et_str:
                        try:
                            dur = parse_time_to_minutes(et_str) - parse_time_to_minutes(st_str)
                        except:
                            dur = 60

                    subj = str(item.get("subject", ""))
                    fac = str(item.get("faculty", ""))
                    ch = str(item.get("chapter", ""))
                    top = str(item.get("topic", ""))

                    st = parse_time_to_minutes(str(st_str)) if st_str else 0
                    et = parse_time_to_minutes(str(et_str)) if et_str else 0
                    slots.append(ScheduledSlot(
                        batch_key=f"{c}_{b}",
                        center=c,
                        batch_name=b,
                        day=d,
                        start_min=st,
                        end_min=et,
                        subject=subj,
                        faculty=fac,
                        chapter=ch,
                        topic=top
                    ))
                    topics.append({
                        "center": c,
                        "batch": b,
                        "day": d,
                        "time": f"{st_str} - {et_str}",
                        "start_time": st_str,
                        "end_time": et_str,
                        "duration": dur,
                        "subject": subj,
                        "faculty": fac,
                        "chapter": ch,
                        "topic": top
                    })

                data_dir = sync_from_google_sheets.get_data_dir(academic_year=year)
                loader = DataLoader(data_dir)
                loader.load_all()
                default_start = "05/10/2026" if year == "2026-27" else "04/10/2027"
                start_date = data.get("effective_from") or default_start
                formatter = TimetableFormatter(start_date_str=start_date)

                batches_map = {}
                batch_slots = {}
                for s in slots:
                    batch_slots.setdefault((s.center, s.batch_name), []).append(s)

                for (center, batch), b_slots in batch_slots.items():
                    b_info = loader.batches.get((center, batch))
                    recess = (b_info.recess_start_min, b_info.recess_end_min) if b_info and b_info.recess_start_min else None
                    key = f"{center} - {batch}"
                    batches_map[key] = formatter.format_vertical_matrix(b_slots, recess_info=recess)

                faculties_map = {}
                fac_slots = {}
                for s in slots:
                    fac_clean = s.faculty.strip().upper()
                    if not fac_clean or fac_clean.startswith("TBD_") or fac_clean in ["TEST", "WEEKLY TEST", "EXAM"]:
                        continue
                    fac_names = [f.strip() for f in fac_clean.split("/")] if "/" in fac_clean else [fac_clean]
                    for fn in fac_names:
                        if fn == "ASIF SIR": fn = "AASIF SIR"
                        fac_slots.setdefault(fn, []).append(s)

                for fac_name, f_slots in fac_slots.items():
                    faculties_map[fac_name] = formatter.format_faculty_vertical_matrix(f_slots)

                self.send_json_response(200, {
                    "success": True,
                    "academic_year": year,
                    "message": f"Schedule ({year}) loaded successfully into active viewer!",
                    "batches": batches_map,
                    "faculties": faculties_map,
                    "topics": topics
                })
            except Exception as e:
                self.send_json_response(500, {"success": False, "message": str(e)})
            return

        elif path == "/api/diagnose":
            try:
                from src import ai_assistant
                # Run capacity check
                lines = []
                import csv
                from collections import defaultdict
                eve_h = defaultdict(float)
                mrg_h = defaultdict(float)
                fm_path = os.path.join("data", "faculty_master.csv")
                if os.path.exists(fm_path):
                    with open(fm_path, "r", encoding="utf-8") as f:
                        for r in csv.DictReader(f):
                            fac = (r.get("Faculty Name") or "").strip().upper()
                            c = (r.get("Assigned Centers") or "").strip()
                            b = (r.get("Assigned Batch") or "").strip()
                            h_str = (r.get("Max Weekly Hours") or "").strip()
                            if not (fac and h_str): continue
                            try:
                                h = float(h_str)
                            except:
                                continue
                            if c in ["SUB", "OP", "NZM", "VB", "PNG"] and "MRG" not in b:
                                eve_h[fac] += h
                            else:
                                mrg_h[fac] += h
                    for fac in sorted(set(list(eve_h.keys()) + list(mrg_h.keys()))):
                        eh = eve_h[fac]
                        mh = mrg_h[fac]
                        if eh > 27.0:
                            lines.append(f"OVERLOAD EVENING: {fac} has {eh:.1f}h weekly requirements exceeding 27h window")
                        if mh > 30.0:
                            lines.append(f"OVERLOAD MORNING: {fac} has {mh:.1f}h weekly requirements exceeding 30h window")

                report_text = "\n".join(lines) if lines else "All faculty weekly hours and operating windows are well within mathematical capacity bounds."
                explanation = ai_assistant.explain_infeasibility(report_text)
                self.send_json_response(200, {"success": True, "report": report_text, "explanation": explanation})
            except Exception as e:
                self.send_json_response(500, {"success": False, "explanation": str(e)})
            return

        self.send_error(404, "Endpoint not found")

    def handle_get_data(self):
        year = self._get_query_param("year") or "2026-27"
        excel_path = get_excel_path(academic_year=year)
        if not os.path.exists(excel_path):
            self.send_json_response(200, {"batches": {}, "faculties": {}, "topics": [], "academic_year": year})
            return

        data_dir = sync_from_google_sheets.get_data_dir(academic_year=year)
        loader = DataLoader(data_dir)
        loader.load_all()

        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active

        slots = []
        topics = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]: continue
            c, b, d, st_str, et_str, dur, subj, fac, ch, top = row[:10]
            st = parse_time_to_minutes(str(st_str))
            et = parse_time_to_minutes(str(et_str))

            from src.models import ScheduledSlot
            slot = ScheduledSlot(
                batch_key=f"{c}_{b}",
                center=str(c),
                batch_name=str(b),
                day=str(d),
                start_min=st,
                end_min=et,
                subject=str(subj),
                faculty=str(fac),
                chapter=str(ch or ""),
                topic=str(top or "")
            )
            slots.append(slot)
            topics.append({
                "center": str(c),
                "batch": str(b),
                "day": str(d),
                "time": f"{st_str} - {et_str}",
                "subject": str(subj),
                "faculty": str(fac),
                "chapter": str(ch or ""),
                "topic": str(top or "")
            })

        default_start = "05/10/2026" if year == "2026-27" else "04/10/2027"
        formatter = TimetableFormatter(start_date_str=default_start)

        # Format Batches
        batches_map = {}
        batch_slots = {}
        for s in slots:
            batch_slots.setdefault((s.center, s.batch_name), []).append(s)

        for (center, batch), b_slots in batch_slots.items():
            b_info = loader.batches.get((center, batch))
            recess = (b_info.recess_start_min, b_info.recess_end_min) if b_info and b_info.recess_start_min else None
            key = f"{center} - {batch}"
            batches_map[key] = formatter.format_vertical_matrix(b_slots, recess_info=recess)

        # Format Faculties
        faculties_map = {}
        fac_slots = {}
        for s in slots:
            fac = s.faculty.strip().upper()
            if not fac or fac.startswith("TBD_") or fac in ["TEST", "WEEKLY TEST", "EXAM"]:
                continue
            fac_names = [f.strip() for f in fac.split("/")] if "/" in fac else [fac]
            for fn in fac_names:
                if fn == "ASIF SIR": fn = "AASIF SIR"
                fac_slots.setdefault(fn, []).append(s)

        for fac_name, f_slots in fac_slots.items():
            faculties_map[fac_name] = formatter.format_faculty_vertical_matrix(f_slots)

        self.send_json_response(200, {
            "batches": batches_map,
            "faculties": faculties_map,
            "topics": topics,
            "academic_year": year
        })

    def save_updated_topics(self, updated_topics, academic_year="2026-27"):
        excel_path = get_excel_path(academic_year=academic_year)
        wb = openpyxl.load_workbook(excel_path)
        ws = wb.active

        for idx, item in enumerate(updated_topics, start=2):
            ws.cell(row=idx, column=9, value=item.get("chapter", ""))
            ws.cell(row=idx, column=10, value=item.get("topic", ""))

        wb.save(excel_path)
        out_base = get_output_base()
        update_topics_and_export_pdfs.update_and_export(excel_path, output_dir_base=out_base)

    def handle_download_single_batch_pdf(self, batch_key):
        if not batch_key:
            self.send_error(400, "Missing batch name parameter")
            return

        year = self._get_query_param("year") or "2026-27"
        parts = batch_key.split(" - ", 1)
        if len(parts) == 2:
            center, batch = parts[0].strip(), parts[1].strip()
            clean_b = batch.replace(" ", "_").replace("/", "_")
            target = f"{center}_{clean_b}_Weekly_Schedule.pdf"
        else:
            target = batch_key.replace(" ", "_").replace("/", "_") + "_Weekly_Schedule.pdf"

        out_base = get_output_base()
        candidate_paths = [
            os.path.join(out_base, "pdf", year, target),
            os.path.join("output/pdf", year, target),
            os.path.join(out_base, "pdf", target),
            os.path.join("output/pdf", target)
        ]
        found_path = None
        for p in candidate_paths:
            if os.path.exists(p):
                found_path = p
                break

        if not found_path:
            for folder in [os.path.join(out_base, "pdf", year), os.path.join("output/pdf", year), os.path.join(out_base, "pdf"), "output/pdf"]:
                if os.path.exists(folder):
                    for f in os.listdir(folder):
                        if f.lower() == target.lower():
                            found_path = os.path.join(folder, f)
                            break
                if found_path:
                    break

        if found_path and os.path.exists(found_path):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(found_path)}"')
            with open(found_path, "rb") as f:
                content = f.read()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, f"Batch PDF not found for '{batch_key}'")

    def handle_download_single_faculty_pdf(self, fac_name):
        if not fac_name:
            self.send_error(400, "Missing faculty name parameter")
            return

        year = self._get_query_param("year") or "2026-27"
        clean_name = fac_name.strip().upper().replace(" ", "_").replace("/", "_")
        target = f"{clean_name}_Weekly_Schedule.pdf"

        out_base = get_output_base()
        candidate_paths = [
            os.path.join(out_base, "faculty_pdf", year, target),
            os.path.join("output/faculty_pdf", year, target),
            os.path.join(out_base, "faculty_pdf", target),
            os.path.join("output/faculty_pdf", target)
        ]
        found_path = None
        for p in candidate_paths:
            if os.path.exists(p):
                found_path = p
                break

        if not found_path:
            for folder in [os.path.join(out_base, "faculty_pdf", year), os.path.join("output/faculty_pdf", year), os.path.join(out_base, "faculty_pdf"), "output/faculty_pdf"]:
                if os.path.exists(folder):
                    for f in os.listdir(folder):
                        if f.lower() == target.lower():
                            found_path = os.path.join(folder, f)
                            break
                if found_path:
                    break

        if found_path and os.path.exists(found_path):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(found_path)}"')
            with open(found_path, "rb") as f:
                content = f.read()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, f"Faculty PDF not found for '{fac_name}'")

    def handle_download_all_batches_excel(self):
        year = self._get_query_param("year") or "2026-27"
        year_suffix = "_2027_28" if year == "2027-28" else "_2026_27"
        filename = f"All_Batches_Weekly_Schedule{year_suffix}.xlsx"
        default_file = "All_Batches_Weekly_Schedule.xlsx"
        out_base = get_output_base()
        candidate_paths = [
            os.path.join(out_base, "excel", filename),
            os.path.join("output/excel", filename),
            os.path.join(out_base, "excel", default_file),
            os.path.join("output/excel", default_file)
        ]
        found_path = None
        for p in candidate_paths:
            if os.path.exists(p):
                found_path = p
                break

        if not found_path:
            try:
                update_topics_and_export_pdfs.update_and_export(get_excel_path(academic_year=year), output_dir_base=out_base)
                gen_path = os.path.join(out_base, "excel", default_file)
                if os.path.exists(gen_path):
                    found_path = gen_path
            except Exception as e:
                print("Error generating all batches excel:", e)

        if found_path and os.path.exists(found_path):
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            with open(found_path, "rb") as f:
                content = f.read()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "All Batches Excel file not found")

    def handle_download_all_faculties_excel(self):
        year = self._get_query_param("year") or "2026-27"
        year_suffix = "_2027_28" if year == "2027-28" else "_2026_27"
        filename = f"All_Faculties_Weekly_Schedule{year_suffix}.xlsx"
        default_file = "All_Faculties_Weekly_Schedule.xlsx"
        out_base = get_output_base()
        candidate_paths = [
            os.path.join(out_base, "excel", filename),
            os.path.join("output/excel", filename),
            os.path.join(out_base, "excel", default_file),
            os.path.join("output/excel", default_file)
        ]
        found_path = None
        for p in candidate_paths:
            if os.path.exists(p):
                found_path = p
                break

        if not found_path:
            try:
                update_topics_and_export_pdfs.update_and_export(get_excel_path(academic_year=year), output_dir_base=out_base)
                gen_path = os.path.join(out_base, "excel", default_file)
                if os.path.exists(gen_path):
                    found_path = gen_path
            except Exception as e:
                print("Error generating all faculties excel:", e)

        if found_path and os.path.exists(found_path):
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            with open(found_path, "rb") as f:
                content = f.read()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "All Faculties Excel file not found")

    def handle_download_zip(self, sub_dir, zip_filename):
        year = self._get_query_param("year") or "2026-27"
        year_suffix = f"_{year.replace('-', '_')}"
        out_zip_name = zip_filename.replace(".zip", f"{year_suffix}.zip")

        out_base = get_output_base()
        candidate_folders = [
            os.path.join(out_base, sub_dir, year),
            os.path.join("output", sub_dir, year),
            os.path.join(out_base, sub_dir),
            os.path.join("output", sub_dir)
        ]
        folder_path = None
        for cf in candidate_folders:
            if os.path.exists(cf) and os.listdir(cf):
                folder_path = cf
                break

        if not folder_path or not os.path.exists(folder_path):
            self.send_error(404, "PDF Folder not found")
            return

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file in os.listdir(folder_path):
                if file.endswith(".pdf"):
                    full_path = os.path.join(folder_path, file)
                    if os.path.isfile(full_path):
                        zip_file.write(full_path, file)

        zip_buffer.seek(0)
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f"attachment; filename={out_zip_name}")
        self.send_header("Content-Length", str(len(zip_buffer.getvalue())))
        self.end_headers()
        self.wfile.write(zip_buffer.getvalue())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def send_json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

def start_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", PORT))
    socketserver.TCPServer.allow_reuse_address = True
    handler = SchedulerRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"==================================================")
        print(f"WEB APP RUNNING AT: http://localhost:{port}")
        print(f"Open this URL in Google Chrome or any browser!")
        print(f"==================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    start_server()
