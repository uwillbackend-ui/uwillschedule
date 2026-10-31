import os
import re
from typing import Dict, List, Optional, Set
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from src.models import ScheduledSlot
from src.data_loader import DAYS_OF_WEEK, minutes_to_str

def sanitize_sheet_title(name: str, existing_names: Set[str]) -> str:
    """
    Sanitizes sheet name for Excel compatibility:
    - Max 31 chars
    - Disallowed chars: \\ / ? * [ ] :
    - Unique within workbook
    """
    clean = re.sub(r'[\\/*?\[\]:]', '-', str(name)).strip()
    if not clean:
        clean = "Schedule"
    clean = clean[:31]
    base = clean
    counter = 1
    while clean.upper() in [n.upper() for n in existing_names]:
        suffix = f"_{counter}"
        clean = f"{base[:31 - len(suffix)]}{suffix}"
        counter += 1
    existing_names.add(clean)
    return clean

def write_batch_sheet(ws, center: str, batch: str, grid_data: Dict, week_dates: Optional[Dict[str, str]] = None):
    c_blue = "27348B"
    c_red = "EE2A35"
    c_border = "CBD5E1"
    c_slate_dark = "1E293B"
    c_recess_bg = "FEF3C7"
    c_recess_txt = "B45309"

    border = Border(left=Side(style='thin', color=c_border),
                    right=Side(style='thin', color=c_border),
                    top=Side(style='thin', color=c_border),
                    bottom=Side(style='thin', color=c_border))

    # Row 1: Brand title
    ws.merge_cells("A1:G1")
    r1 = ws["A1"]
    r1.value = "U WILL CLASSES | EDUCATION REDEFINED"
    r1.font = Font(name="Segoe UI", size=14, bold=True, color=c_blue)
    r1.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    # Row 2: Subtitle
    ws.merge_cells("A2:G2")
    r2 = ws["A2"]
    r2.value = f"WEEKLY BATCH TIMETABLE  •  BRANCH: {center}  •  BATCH: {batch}  •  WEEK: 05/10/2026 to 10/10/2026"
    r2.font = Font(name="Segoe UI", size=10, bold=True, color=c_red)
    r2.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 20

    # Row 3: Spacer
    ws.row_dimensions[3].height = 6

    # Row 4: Column Headers
    days_list = grid_data.get("days", ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"])
    headers = ["TIME SLOT"] + days_list
    ws.row_dimensions[4].height = 28

    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col_idx)
        if col_idx == 1:
            cell.value = h
        else:
            day_name = h
            date_str = week_dates.get(day_name, "") if week_dates else ""
            cell.value = f"{day_name}\n({date_str})" if date_str else day_name

        cell.font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=c_blue, end_color=c_blue, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    # Row 5 onwards: Data Rows
    curr_row = 5
    for r in grid_data.get("rows", []):
        ws.row_dimensions[curr_row].height = 46 if not r.get("is_recess") else 24

        time_c = ws.cell(row=curr_row, column=1, value=r["time_label"])
        time_c.font = Font(name="Segoe UI", size=9, bold=True, color=c_slate_dark)
        time_c.alignment = Alignment(horizontal="center", vertical="center")
        time_c.border = border
        time_c.fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        if r.get("is_recess"):
            ws.merge_cells(start_row=curr_row, start_column=2, end_row=curr_row, end_column=len(headers))
            rec_c = ws.cell(row=curr_row, column=2, value="★ RECESS / BREAK ★")
            rec_c.font = Font(name="Segoe UI", size=10, bold=True, color=c_recess_txt)
            rec_c.fill = PatternFill(start_color=c_recess_bg, end_color=c_recess_bg, fill_type="solid")
            rec_c.alignment = Alignment(horizontal="center", vertical="center")
            for c_i in range(1, len(headers) + 1):
                ws.cell(row=curr_row, column=c_i).border = border
        else:
            for col_idx, d in enumerate(days_list, start=2):
                cell_info = r.get("day_cells", {}).get(d, {})
                c = ws.cell(row=curr_row, column=col_idx)
                c.border = border
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

                if cell_info.get("is_span_start") and cell_info.get("span_count", 1) > 1:
                    span_cnt = cell_info["span_count"]
                    ws.merge_cells(start_row=curr_row, start_column=col_idx, end_row=curr_row + span_cnt - 1, end_column=col_idx)

                if cell_info.get("is_span_continuation"):
                    continue

                if cell_info.get("type") == "test" or cell_info.get("subject") == "WEEKLY TEST":
                    time_str = cell_info.get("time_range", "")
                    dur_line = f"{time_str} (60 mins)" if time_str else "1 Hour Exam (60 mins)"
                    c.value = f"★ WEEKLY TEST ★\n{dur_line}\nWeekly Syllabus"
                    c.font = Font(name="Segoe UI", size=9, bold=True, color="92400E")
                    c.fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
                elif cell_info.get("type") == "lecture":
                    fac = cell_info.get("faculty", "")
                    sub = cell_info.get("subject", "")
                    ch = cell_info.get("chapter", "")
                    top = cell_info.get("topic", "")
                    t_range = cell_info.get("time_range", "")

                    details = f"{ch} • {top}" if (ch or top) else ""
                    sub_line = f"{sub} ({t_range})" if t_range and (r["end_min"] - r["start_min"] != cell_info.get("duration_min")) else sub
                    lines = [l for l in [fac, sub_line, details] if l]
                    c.value = "\n".join(lines)
                    c.font = Font(name="Segoe UI", size=9, color=c_slate_dark)
                    c.fill = PatternFill(start_color="F0F4F8", end_color="F0F4F8", fill_type="solid")
                else:
                    c.value = "---"
                    c.font = Font(name="Segoe UI", size=9, color="94A3B8")

        curr_row += 1

    # Footer Row
    curr_row += 1
    ws.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=len(headers))
    foot_c = ws.cell(row=curr_row, column=1, value="Note: Students are requested to bring textbooks & notebooks as per the chapter topics listed above.")
    foot_c.font = Font(name="Segoe UI", size=8, italic=True, color="64748B")
    foot_c.alignment = Alignment(horizontal="left", vertical="center")

    # Column Widths
    ws.column_dimensions["A"].width = 20
    for col_letter in ["B", "C", "D", "E", "F", "G"]:
        ws.column_dimensions[col_letter].width = 22

def write_faculty_sheet(ws, faculty_name: str, grid_data: Dict, week_dates: Optional[Dict[str, str]] = None):
    c_blue = "27348B"
    c_red = "EE2A35"
    c_border = "CBD5E1"
    c_slate_dark = "1E293B"
    c_recess_bg = "FEF3C7"
    c_recess_txt = "B45309"

    border = Border(left=Side(style='thin', color=c_border),
                    right=Side(style='thin', color=c_border),
                    top=Side(style='thin', color=c_border),
                    bottom=Side(style='thin', color=c_border))

    # Row 1: Brand title
    ws.merge_cells("A1:G1")
    r1 = ws["A1"]
    r1.value = "U WILL CLASSES | EDUCATION REDEFINED"
    r1.font = Font(name="Segoe UI", size=14, bold=True, color=c_blue)
    r1.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 24

    # Row 2: Subtitle
    ws.merge_cells("A2:G2")
    r2 = ws["A2"]
    r2.value = f"FACULTY PERSONAL WEEKLY SCHEDULE  •  FACULTY: {faculty_name}  •  WEEK: 05/10/2026 to 10/10/2026  •  SESSION: 2026-27"
    r2.font = Font(name="Segoe UI", size=10, bold=True, color=c_red)
    r2.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 20

    # Row 3: Spacer
    ws.row_dimensions[3].height = 6

    # Row 4: Column Headers
    days_list = grid_data.get("days", ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"])
    headers = ["TIME SLOT"] + days_list
    ws.row_dimensions[4].height = 28

    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=4, column=col_idx)
        if col_idx == 1:
            cell.value = h
        else:
            day_name = h
            date_str = week_dates.get(day_name, "") if week_dates else ""
            cell.value = f"{day_name}\n({date_str})" if date_str else day_name

        cell.font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=c_blue, end_color=c_blue, fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    # Row 5 onwards: Data Rows
    curr_row = 5
    for r in grid_data.get("rows", []):
        if r.get("is_recess") or r.get("is_lunch_break"):
            ws.row_dimensions[curr_row].height = 24

            slot_c = ws.cell(row=curr_row, column=1, value="LUNCH BREAK")
            slot_c.font = Font(name="Segoe UI", size=9, bold=True, color=c_recess_txt)
            slot_c.alignment = Alignment(horizontal="center", vertical="center")
            slot_c.border = border
            slot_c.fill = PatternFill(start_color="FDE68A", end_color="FDE68A", fill_type="solid")

            ws.merge_cells(start_row=curr_row, start_column=2, end_row=curr_row, end_column=len(headers))
            rec_c = ws.cell(row=curr_row, column=2, value="★ LUNCH BREAK ★")
            rec_c.font = Font(name="Segoe UI", size=10, bold=True, color=c_recess_txt)
            rec_c.fill = PatternFill(start_color=c_recess_bg, end_color=c_recess_bg, fill_type="solid")
            rec_c.alignment = Alignment(horizontal="center", vertical="center")
            for c_i in range(1, len(headers) + 1):
                ws.cell(row=curr_row, column=c_i).border = border
        else:
            ws.row_dimensions[curr_row].height = 54

            slot_c = ws.cell(row=curr_row, column=1, value=r["time_label"])
            slot_c.font = Font(name="Segoe UI", size=9, bold=True, color=c_slate_dark)
            slot_c.alignment = Alignment(horizontal="center", vertical="center")
            slot_c.border = border
            slot_c.fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

            for col_idx, d in enumerate(days_list, start=2):
                cell_info = r.get("day_cells", {}).get(d, {})
                c = ws.cell(row=curr_row, column=col_idx)
                c.border = border
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

                if cell_info.get("type") == "lecture":
                    time_range = cell_info.get("time_range", "")
                    dur = cell_info.get("duration", "")
                    center_batch = cell_info.get("center_batch", "")
                    sub = cell_info.get("subject", "")
                    ch = cell_info.get("chapter", "")
                    top = cell_info.get("topic", "")

                    if dur:
                        dur_clean = dur if (dur.startswith("(") and dur.endswith(")")) else f"({dur})"
                        time_line = f"{time_range} {dur_clean}" if time_range else dur_clean
                    else:
                        time_line = time_range
                    details = f"{ch} • {top}" if (ch or top) else ""
                    lines = [l for l in [time_line, center_batch, sub, details] if l]
                    c.value = "\n".join(lines)
                    c.font = Font(name="Segoe UI", size=9, color=c_slate_dark)
                    c.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
                else:
                    c.value = "---"
                    c.font = Font(name="Segoe UI", size=9, color="94A3B8")

        curr_row += 1

    # Footer Row
    curr_row += 1
    ws.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=len(headers))
    foot_c = ws.cell(row=curr_row, column=1, value="Note: Please arrive 10 minutes prior to lecture start. Ensure inter-branch travel buffers are maintained.")
    foot_c.font = Font(name="Segoe UI", size=8, italic=True, color="64748B")
    foot_c.alignment = Alignment(horizontal="left", vertical="center")

    # Column Widths
    ws.column_dimensions["A"].width = 22
    for col_letter in ["B", "C", "D", "E", "F", "G"]:
        ws.column_dimensions[col_letter].width = 24


class ExcelExporter:
    def __init__(self, output_dir: str = "output/excel"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def export_topic_editor_sheet(self, slots: List[ScheduledSlot], file_name: str = "Weekly_Schedule_Input_Topics.xlsx") -> str:
        """
        Creates an editable table where the schedule coordinator can enter Chapter & Topic.
        """
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lecture_Topics_Editor"

        headers = ["Center", "Batch", "Day", "Start Time", "End Time", "Duration (mins)", "Subject", "Faculty", "Chapter", "Topic"]
        ws.append(headers)

        header_fill = PatternFill(start_color="27348B", end_color="27348B", fill_type="solid")
        header_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
        border = Border(left=Side(style='thin', color='CBD5E1'),
                        right=Side(style='thin', color='CBD5E1'),
                        top=Side(style='thin', color='CBD5E1'),
                        bottom=Side(style='thin', color='CBD5E1'))

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        day_order = {d: i for i, d in enumerate(DAYS_OF_WEEK)}
        sorted_slots = sorted(slots, key=lambda s: (day_order.get(s.day, 99), s.center, s.batch_name, s.start_min))

        for row_idx, s in enumerate(sorted_slots, start=2):
            ws.append([
                s.center,
                s.batch_name,
                s.day,
                minutes_to_str(s.start_min),
                minutes_to_str(s.end_min),
                s.duration_min,
                s.subject,
                s.faculty,
                s.chapter or "CH-1",
                s.topic or "TOPIC-1"
            ])
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=row_idx, column=col_idx)
                c.border = border
                c.alignment = Alignment(horizontal="left" if col_idx in [1, 2, 7, 8, 9, 10] else "center", vertical="center")
                if col_idx in [9, 10]:
                    c.fill = PatternFill(start_color="FEFCBF", end_color="FEFCBF", fill_type="solid")

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        file_path = os.path.join(self.output_dir, file_name)
        wb.save(file_path)
        return file_path

    def export_vertical_matrix(self, center: str, batch: str, grid_data: Dict, week_dates: Optional[Dict[str, str]] = None) -> str:
        """
        Creates a vertical timetable matrix Excel sheet for a single batch.
        """
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sanitize_sheet_title(f"{center}_{batch}", set())
        write_batch_sheet(ws, center, batch, grid_data, week_dates)

        clean_b = batch.replace(" ", "_").replace("/", "_")
        file_path = os.path.join(self.output_dir, f"{center}_{clean_b}_Matrix.xlsx")
        wb.save(file_path)
        return file_path

    def export_all_batches_workbook(
        self,
        batches_grid_map: Dict[str, Dict],
        week_dates: Optional[Dict[str, str]] = None,
        file_name: str = "All_Batches_Weekly_Schedule.xlsx"
    ) -> str:
        """
        Exports ALL batches into a single workbook where each batch has its own tab.
        """
        wb = openpyxl.Workbook()
        default_sheet = wb.active
        existing_names: Set[str] = set()

        sorted_keys = sorted(batches_grid_map.keys())
        first = True
        for key in sorted_keys:
            grid_data = batches_grid_map[key]
            parts = key.split(" - ", 1)
            center = parts[0] if len(parts) > 1 else key
            batch = parts[1] if len(parts) > 1 else ""

            sheet_title = sanitize_sheet_title(key, existing_names)
            if first:
                ws = default_sheet
                ws.title = sheet_title
                first = False
            else:
                ws = wb.create_sheet(title=sheet_title)

            write_batch_sheet(ws, center, batch, grid_data, week_dates)

        file_path = os.path.join(self.output_dir, file_name)
        wb.save(file_path)
        return file_path

    def export_all_faculties_workbook(
        self,
        faculties_grid_map: Dict[str, Dict],
        week_dates: Optional[Dict[str, str]] = None,
        file_name: str = "All_Faculties_Weekly_Schedule.xlsx"
    ) -> str:
        """
        Exports ALL faculty schedules into a single workbook where each faculty has their own tab.
        """
        wb = openpyxl.Workbook()
        default_sheet = wb.active
        existing_names: Set[str] = set()

        sorted_keys = sorted(faculties_grid_map.keys())
        first = True
        for fac_name in sorted_keys:
            grid_data = faculties_grid_map[fac_name]
            sheet_title = sanitize_sheet_title(fac_name, existing_names)
            if first:
                ws = default_sheet
                ws.title = sheet_title
                first = False
            else:
                ws = wb.create_sheet(title=sheet_title)

            write_faculty_sheet(ws, fac_name, grid_data, week_dates)

        file_path = os.path.join(self.output_dir, file_name)
        wb.save(file_path)
        return file_path
