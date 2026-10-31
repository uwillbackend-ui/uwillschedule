import sys, os
sys.path.insert(0, os.path.abspath("."))
import openpyxl
from collections import defaultdict
from src.models import ScheduledSlot
from src.data_loader import DataLoader, parse_time_to_minutes
from src.formatter import TimetableFormatter
from src.pdf_generator import TimetablePDFGenerator
from src.excel_exporter import ExcelExporter

def update_and_export(excel_file: str = "output/excel/Weekly_Schedule_Input_Topics.xlsx", output_dir_base: str = "output"):
    print("=" * 65)
    print("STUDENT & FACULTY PDF EXPORTER (TOPIC SYNC)")
    print("=" * 65)

    if not os.path.exists(excel_file):
        print(f"Error: {excel_file} not found! Please run generate_timetable.py first.")
        return

    loader = DataLoader("data")
    loader.load_all()

    wb = openpyxl.load_workbook(excel_file)
    ws = wb.active

    slots = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]: continue
        c, b, d, st_str, et_str, dur, subj, fac, ch, top = row[:10]
        st = parse_time_to_minutes(str(st_str))
        et = parse_time_to_minutes(str(et_str))

        slots.append(ScheduledSlot(
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
        ))

    print(f"Loaded {len(slots)} lectures with chapters and topics.")

    sample_dates = {
        "MONDAY": "05/10/2026",
        "TUESDAY": "06/10/2026",
        "WEDNESDAY": "07/10/2026",
        "THURSDAY": "08/10/2026",
        "FRIDAY": "09/10/2026",
        "SATURDAY": "10/10/2026"
    }

    formatter = TimetableFormatter(start_date_str="05/10/2026")
    pdf_gen = TimetablePDFGenerator(output_dir=f"{output_dir_base}/pdf")
    fac_pdf_gen = TimetablePDFGenerator(output_dir=f"{output_dir_base}/faculty_pdf")
    excel_exp = ExcelExporter(output_dir=f"{output_dir_base}/excel")

    # 1. Update Batch PDFs & Excel Map
    batch_slots = defaultdict(list)
    for s in slots:
        batch_slots[(s.center, s.batch_name)].append(s)

    batches_grid_map = {}
    b_count = 0
    for (center, batch), b_slots in batch_slots.items():
        b_info = loader.batches.get((center, batch))
        recess = (b_info.recess_start_min, b_info.recess_end_min) if b_info and b_info.recess_start_min else None
        grid_data = formatter.format_vertical_matrix(b_slots, recess_info=recess)
        pdf_gen.generate_batch_pdf(center, batch, grid_data, week_dates=sample_dates)
        excel_exp.export_vertical_matrix(center, batch, grid_data, week_dates=sample_dates)
        batches_grid_map[f"{center} - {batch}"] = grid_data
        b_count += 1

    # 2. Update Faculty PDFs & Excel Map
    fac_slots = defaultdict(list)
    for s in slots:
        fac = s.faculty.strip().upper()
        if fac and not fac.startswith("TBD_") and fac not in ["TEST", "WEEKLY TEST", "EXAM"]:
            fac_slots[fac].append(s)

    faculties_grid_map = {}
    f_count = 0
    for fac_name, f_slots in fac_slots.items():
        grid_data = formatter.format_faculty_vertical_matrix(f_slots)
        clean_name = fac_name.replace(" ", "_").replace("/", "_")
        fac_pdf_gen.generate_faculty_pdf(
            faculty_name=fac_name,
            grid_data=grid_data,
            week_dates=sample_dates,
            file_name=f"{clean_name}_Weekly_Schedule.pdf"
        )
        faculties_grid_map[fac_name] = grid_data
        f_count += 1

    # 3. Export Master Multi-Tab Excel Files
    b_master_path = excel_exp.export_all_batches_workbook(
        batches_grid_map, week_dates=sample_dates, file_name="All_Batches_Weekly_Schedule.xlsx"
    )
    f_master_path = excel_exp.export_all_faculties_workbook(
        faculties_grid_map, week_dates=sample_dates, file_name="All_Faculties_Weekly_Schedule.xlsx"
    )

    print(f"Updated {b_count} Batch PDFs in 'output/pdf/'")
    print(f"Updated {f_count} Faculty Personal PDFs in 'output/faculty_pdf/'")
    print(f"Generated Master All-Batches Excel (36 tabs): {b_master_path}")
    print(f"Generated Master All-Faculties Excel (41 tabs): {f_master_path}")

if __name__ == "__main__":
    update_and_export()
