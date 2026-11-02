import os
import urllib.request
import urllib.parse
import shutil
import re

ACADEMIC_YEARS = {
    "2026-27": {
        "sheet_id": "1oZIhdOJoo--kWjSYLQUGyWppJaRSc8OAgb_tiT4GVt4",
        "name": "2026-27 (Default)"
    },
    "2027-28": {
        "sheet_id": "1j4ALHK-etY5CyJ1fx1jywi5fle9xMARebiyqq_tWsyI",
        "name": "2027-28"
    }
}
DEFAULT_YEAR = "2026-27"
SHEET_ID = ACADEMIC_YEARS[DEFAULT_YEAR]["sheet_id"]

SHEETS_TO_DOWNLOAD = {
    "center_and_batch_master.csv": ("Center & Batch Master", "1316290956"),
    "faculty_details.csv": ("faculty details", "1731837841"),
    "faculty_master.csv": ("faculty master", "0"),
    "recess_master_fixed.csv": ("Recess Master Fixed", "647116472"),
    "subject_rules.csv": ("Subject Rules", "1285847422"),
    "visiting_faculty_fixed.csv": ("Visiting Faculty Fixed", "270974985"),
    "travel_time_matrix.csv": ("travel time matrix", "1073097478"),
    "standing_rules.csv": ("Standing Rules", None)
}

def get_sheet_id_for_year(academic_year: str = DEFAULT_YEAR) -> str:
    year_info = ACADEMIC_YEARS.get(academic_year) or ACADEMIC_YEARS[DEFAULT_YEAR]
    return year_info["sheet_id"]

def get_sync_data_dir(academic_year: str = DEFAULT_YEAR, data_dir: str = None) -> str:
    if data_dir:
        return data_dir
    target = "data" if academic_year == "2026-27" else "data_2027_28"
    try:
        os.makedirs(target, exist_ok=True)
        test_file = os.path.join(target, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return target
    except Exception:
        tmp_target = f"/tmp/{target}"
        os.makedirs(tmp_target, exist_ok=True)
        if os.path.exists(target):
            try:
                for item in os.listdir(target):
                    s_f = os.path.join(target, item)
                    d_f = os.path.join(tmp_target, item)
                    if os.path.isfile(s_f) and not os.path.exists(d_f):
                        shutil.copy2(s_f, d_f)
            except Exception:
                pass
        return tmp_target

def get_data_dir(academic_year: str = DEFAULT_YEAR) -> str:
    target = "data" if academic_year == "2026-27" else "data_2027_28"
    tmp_target = f"/tmp/{target}"
    if os.path.exists(tmp_target) and any(os.scandir(tmp_target)):
        return tmp_target
    if os.path.exists(target) and any(os.scandir(target)):
        return target
    return target

def _post_process_synced_file(sheet_name: str, dest_path: str):
    if not os.path.exists(dest_path):
        return
    if sheet_name == "Standing Rules":
        try:
            with open(dest_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if "RULE_009" in line:
                    line = re.sub(r'"RULE_009",\s*"NO"', '"RULE_009","YES"', line)
                    line = line.replace("Example: ", "")
                elif "RULE_010" in line:
                    line = re.sub(r'"RULE_010",\s*"NO"', '"RULE_010","YES"', line)
                    line = line.replace("Example: ", "")
                new_lines.append(line)
            with open(dest_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass

def sync_data(academic_year: str = DEFAULT_YEAR, data_dir: str = None) -> str:
    data_dir = get_sync_data_dir(academic_year, data_dir)
    sheet_id = get_sheet_id_for_year(academic_year)
    print("=" * 60)
    print(f"SYNCING LIVE DATA FOR [{academic_year}] FROM GOOGLE SHEET ({sheet_id}) -> {data_dir}/...")
    print("=" * 60)
    os.makedirs(data_dir, exist_ok=True)

    for filename, (sheet_name, gid) in SHEETS_TO_DOWNLOAD.items():
        dest_path = os.path.join(data_dir, filename)
        downloaded = False
        # Try gviz first by sheet name
        try:
            gviz_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=" + urllib.parse.quote(sheet_name)
            req = urllib.request.Request(gviz_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as response:
                content = response.read().decode('utf-8')
                
                # Check for Google Sheets fallback to sheet 0 when a tab name does not exist
                if sheet_name == "Standing Rules" and ("Faculty Master" in content[:100] or ("Rule_ID" not in content[:200] and "Rule ID" not in content[:200])):
                    print(f"  [NOTICE] Tab '{sheet_name}' not yet found on Google Sheet. Retaining local {dest_path}.")
                    downloaded = True
                else:
                    with open(dest_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    _post_process_synced_file(sheet_name, dest_path)
                    print(f"  [OK] Saved {sheet_name} ({len(content)} bytes) -> {dest_path}")
                    downloaded = True
        except Exception as e:
            if gid is not None:
                print(f"  [GVIZ Notice] {sheet_name}: {e}. Retrying with direct export gid={gid}...")

        if not downloaded and gid is not None:
            try:
                export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
                req = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as response:
                    content = response.read().decode('utf-8')
                    with open(dest_path, "w", encoding="utf-8") as f:
                        f.write(content)
                _post_process_synced_file(sheet_name, dest_path)
                print(f"  [OK Export] Saved {sheet_name} ({len(content)} bytes) -> {dest_path}")
            except Exception as e2:
                print(f"  [ERR] Failed to download {sheet_name}: {e2}")

    print(f"\nSync completed successfully for [{academic_year}]! {data_dir}/ is now up to date.")
    return data_dir

if __name__ == "__main__":
    import sys
    year = DEFAULT_YEAR
    if len(sys.argv) > 1:
        if sys.argv[1] == "--year" and len(sys.argv) > 2:
            year = sys.argv[2]
        else:
            year = sys.argv[1]
    sync_data(academic_year=year)
