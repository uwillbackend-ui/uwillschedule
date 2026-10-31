import os
import json
import urllib.request
import urllib.error
import openpyxl
from typing import Dict, List, Optional

OUTPUT_SHEETS_BY_YEAR = {
    "2026-27": {
        "batch_id": "1d3P2qL7rZFl5Pkt8aDpr7_d5U2mok8lpLgELWrjh6CE",
        "faculty_id": "1ILnDlPNjN5WaVZZ2T5LnDJx2TFALZtxbeay-bA4CLpo",
        "batch_file": "All_Batches_Weekly_Schedule_2026_27.xlsx",
        "faculty_file": "All_Faculties_Weekly_Schedule_2026_27.xlsx",
        "default_batch_file": "All_Batches_Weekly_Schedule.xlsx",
        "default_faculty_file": "All_Faculties_Weekly_Schedule.xlsx"
    },
    "2027-28": {
        "batch_id": "15wqwcsSk-ZC7xveuVNhIBGExBswvkpum9LW0Ig2L4Jk",
        "faculty_id": "1f8-H_Y_8HFE_b8BRpx65BwW3LLaduoYRAuyDN7hDOCI",
        "batch_file": "All_Batches_Weekly_Schedule_2027_28.xlsx",
        "faculty_file": "All_Faculties_Weekly_Schedule_2027_28.xlsx",
        "default_batch_file": "All_Batches_Weekly_Schedule.xlsx",
        "default_faculty_file": "All_Faculties_Weekly_Schedule.xlsx"
    }
}
DEFAULT_YEAR = "2026-27"
BATCH_SHEET_ID = OUTPUT_SHEETS_BY_YEAR[DEFAULT_YEAR]["batch_id"]
FACULTY_SHEET_ID = OUTPUT_SHEETS_BY_YEAR[DEFAULT_YEAR]["faculty_id"]

def to_hex(color, default='#FFFFFF') -> str:
    if not color:
        return default
    rgb = getattr(color, 'rgb', None)
    if rgb and isinstance(rgb, str):
        if len(rgb) == 8:
            rgb = rgb[2:]
        return f'#{rgb}'
    return default

def resolve_excel_path(filename: str, output_base: Optional[str] = None) -> str:
    candidates = []
    if output_base:
        candidates.append(os.path.join(output_base, "excel", filename))
        candidates.append(os.path.join(output_base, filename))
    candidates.extend([
        os.path.join("output", "excel", filename),
        os.path.join("output", filename),
        os.path.join(os.path.dirname(__file__), "..", "output", "excel", filename),
        os.path.join(os.path.dirname(__file__), "..", "output", filename),
        os.path.join("/tmp", "excel", filename),
        os.path.join("/tmp", filename)
    ])
    for c in candidates:
        if os.path.exists(c) and os.path.getsize(c) > 0:
            return c
    return candidates[0]

def serialize_workbook(excel_path: str) -> List[dict]:
    if not os.path.exists(excel_path):
        return []
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    res = []
    for name in wb.sheetnames:
        ws = wb[name]
        max_r, max_c = ws.max_row, ws.max_column
        values, bgs, fgs, weights, sizes, aligns = [], [], [], [], [], []
        for r in range(1, max_r + 1):
            r_val, r_bg, r_fg, r_wt, r_sz, r_al = [], [], [], [], [], []
            for c in range(1, max_c + 1):
                cell = ws.cell(r, c)
                val = str(cell.value) if cell.value is not None else ''
                r_val.append(val)
                r_bg.append(to_hex(cell.fill.start_color if cell.fill else None, '#FFFFFF'))
                r_fg.append(to_hex(cell.font.color if cell.font else None, '#000000'))
                r_wt.append('bold' if cell.font and cell.font.bold else 'normal')
                r_sz.append(int(cell.font.size) if cell.font and cell.font.size else 10)
                al = cell.alignment.horizontal if cell.alignment and cell.alignment.horizontal else 'center'
                r_al.append(al)
            values.append(r_val)
            bgs.append(r_bg)
            fgs.append(r_fg)
            weights.append(r_wt)
            sizes.append(r_sz)
            aligns.append(r_al)

        merges = [str(m) for m in ws.merged_cells.ranges]
        res.append({
            'name': name,
            'max_r': max_r,
            'max_c': max_c,
            'values': values,
            'backgrounds': bgs,
            'fontColors': fgs,
            'fontWeights': weights,
            'fontSizes': sizes,
            'alignments': aligns,
            'merges': merges
        })
    return res

def get_batches_payload(output_base: Optional[str] = None, year: str = DEFAULT_YEAR) -> dict:
    cfg = OUTPUT_SHEETS_BY_YEAR.get(year) or OUTPUT_SHEETS_BY_YEAR[DEFAULT_YEAR]
    batch_file_name = cfg["batch_file"]
    batch_file = resolve_excel_path(batch_file_name, output_base)
    if not os.path.exists(batch_file):
        batch_file = resolve_excel_path(cfg["default_batch_file"], output_base)
    batches_data = serialize_workbook(batch_file)
    return {
        "status": "success",
        "type": "batches",
        "year": year,
        "spreadsheet_id": cfg["batch_id"],
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{cfg['batch_id']}/edit",
        "total_batches": len(batches_data),
        "batches": batches_data
    }

def get_faculties_payload(output_base: Optional[str] = None, year: str = DEFAULT_YEAR) -> dict:
    cfg = OUTPUT_SHEETS_BY_YEAR.get(year) or OUTPUT_SHEETS_BY_YEAR[DEFAULT_YEAR]
    fac_file_name = cfg["faculty_file"]
    faculty_file = resolve_excel_path(fac_file_name, output_base)
    if not os.path.exists(faculty_file):
        faculty_file = resolve_excel_path(cfg["default_faculty_file"], output_base)
    faculties_data = serialize_workbook(faculty_file)
    return {
        "status": "success",
        "type": "faculties",
        "year": year,
        "spreadsheet_id": cfg["faculty_id"],
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{cfg['faculty_id']}/edit",
        "total_faculties": len(faculties_data),
        "faculties": faculties_data
    }

def build_google_sheets_payload(output_base: Optional[str] = None, year: str = DEFAULT_YEAR) -> dict:
    cfg = OUTPUT_SHEETS_BY_YEAR.get(year) or OUTPUT_SHEETS_BY_YEAR[DEFAULT_YEAR]
    batches_payload = get_batches_payload(output_base, year)
    faculties_payload = get_faculties_payload(output_base, year)
    return {
        "status": "success",
        "year": year,
        "batch_spreadsheet_id": cfg["batch_id"],
        "faculty_spreadsheet_id": cfg["faculty_id"],
        "batch_sheet_url": f"https://docs.google.com/spreadsheets/d/{cfg['batch_id']}/edit",
        "faculty_sheet_url": f"https://docs.google.com/spreadsheets/d/{cfg['faculty_id']}/edit",
        "total_batches": batches_payload["total_batches"],
        "total_faculties": faculties_payload["total_faculties"],
        "batches": batches_payload["batches"],
        "faculties": faculties_payload["faculties"]
    }

WEBHOOK_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "sheets_webhooks.json")

def load_saved_webhooks() -> dict:
    try:
        cfg = os.path.abspath(WEBHOOK_CONFIG_FILE)
        if os.path.exists(cfg):
            with open(cfg, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_webhooks(batch_url: Optional[str] = None, faculty_url: Optional[str] = None, combined_url: Optional[str] = None):
    try:
        cfg = os.path.abspath(WEBHOOK_CONFIG_FILE)
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        data = load_saved_webhooks()
        if batch_url:
            data["batch_webhook_url"] = batch_url
        if faculty_url:
            data["faculty_webhook_url"] = faculty_url
        if combined_url:
            data["combined_webhook_url"] = combined_url
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def push_to_url(url: str, payload: Optional[dict] = None) -> dict:
    if not url:
        return {"success": False, "error": "Empty URL"}
    url = url.strip()
    try:
        req_data = json.dumps(payload or {}).encode("utf-8") if payload else None
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(
            url,
            data=req_data,
            headers=headers,
            method="POST" if req_data else "GET"
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            return {"success": True, "response": resp_body[:200]}
    except Exception as e:
        # Fallback to GET ping
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
            with urllib.request.urlopen(req, timeout=45) as resp:
                resp_body = resp.read().decode("utf-8", errors="ignore")
                return {"success": True, "response": resp_body[:200]}
        except Exception as e2:
            return {"success": False, "error": str(e)}

def push_to_google_apps_script(webhook_url: Optional[str] = None,
                                batch_webhook_url: Optional[str] = None,
                                faculty_webhook_url: Optional[str] = None,
                                output_base: Optional[str] = None,
                                year: str = DEFAULT_YEAR) -> dict:
    saved = load_saved_webhooks()
    b_url = batch_webhook_url or os.environ.get("BATCH_SHEETS_WEBHOOK_URL") or saved.get("batch_webhook_url")
    f_url = faculty_webhook_url or os.environ.get("FACULTY_SHEETS_WEBHOOK_URL") or saved.get("faculty_webhook_url")
    comb_url = webhook_url or os.environ.get("GOOGLE_APPS_SCRIPT_WEBHOOK_URL") or saved.get("combined_webhook_url")

    if batch_webhook_url or faculty_webhook_url or webhook_url:
        save_webhooks(b_url, f_url, comb_url)

    results = {}
    pushed_any = False

    if b_url:
        results["batches"] = push_to_url(b_url, get_batches_payload(output_base, year=year))
        pushed_any = True
    if f_url:
        results["faculties"] = push_to_url(f_url, get_faculties_payload(output_base, year=year))
        pushed_any = True
    if comb_url and not b_url and not f_url:
        results["combined"] = push_to_url(comb_url, build_google_sheets_payload(output_base, year=year))
        pushed_any = True

    if not pushed_any:
        return {
            "success": False,
            "message": "Google Sheets Web App URLs are not yet configured on the server. Please provide the Web App URLs to Antigravity in chat."
        }

    all_success = all(r.get("success", False) for r in results.values())
    return {
        "success": all_success,
        "message": f"Pushed to Google Sheets ({year}) successfully! All Batch tabs & Faculty tabs updated." if all_success else f"Some updates for {year} could not be delivered.",
        "details": results
    }

def auto_push_all(output_base: Optional[str] = None, year: str = DEFAULT_YEAR) -> dict:
    return push_to_google_apps_script(output_base=output_base, year=year)
