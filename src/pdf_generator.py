import os
from typing import Dict, List, Optional
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from src.data_loader import DAYS_OF_WEEK

class TimetablePDFGenerator:
    def __init__(self, output_dir: str = "output/pdf"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._init_custom_styles()

    def _init_custom_styles(self):
        self.title_style = ParagraphStyle(
            'DocTitle',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=16,
            leading=20,
            alignment=1, # Center
            textColor=colors.HexColor("#0F172A")
        )
        self.subtitle_style = ParagraphStyle(
            'DocSubtitle',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            alignment=1, # Center
            textColor=colors.HexColor("#64748B")
        )
        self.header_left_style = ParagraphStyle(
            'HLeft',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=14,
            alignment=0, # Left-aligned beside logo
            textColor=colors.HexColor("#0F172A")
        )
        self.header_right_style = ParagraphStyle(
            'HRight',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=13,
            alignment=2, # Right-aligned
            textColor=colors.HexColor("#0F172A")
        )
        self.header_cell_style = ParagraphStyle(
            'HeaderCell',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8.5,
            leading=11,
            alignment=1, # Center
            textColor=colors.white
        )
        self.time_cell_style = ParagraphStyle(
            'TimeCell',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=7.5,
            leading=10,
            alignment=1,
            textColor=colors.HexColor("#334155")
        )
        self.lecture_batch_style = ParagraphStyle(
            'LecBatch',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10.5,
            alignment=1,
            textColor=colors.HexColor("#0F172A")
        )
        self.lecture_fac_style = ParagraphStyle(
            'LecFac',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5,
            leading=9.5,
            alignment=1,
            textColor=colors.HexColor("#0F172A")
        )
        self.empty_cell_style = ParagraphStyle(
            'EmptyCell',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            alignment=1,
            textColor=colors.HexColor("#CBD5E1")
        )
        self.recess_style = ParagraphStyle(
            'RecessStyle',
            parent=self.styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8.5,
            leading=11,
            alignment=1,
            textColor=colors.HexColor("#92400E")
        )
        self.test_cell_style = ParagraphStyle(
            'TestCellStyle',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=8,
            leading=10.5,
            alignment=1,
            textColor=colors.HexColor("#92400E")
        )
        self.footer_style = ParagraphStyle(
            'FooterStyle',
            parent=self.styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5,
            leading=10,
            alignment=1,
            textColor=colors.HexColor("#64748B")
        )

    def generate_batch_pdf(
        self,
        center: str,
        batch: str,
        grid_data: Dict,
        week_dates: Optional[Dict[str, str]] = None,
        file_name: Optional[str] = None
    ) -> str:
        """
        Generates a clean, modern, professional PDF for a single batch.
        """
        if not file_name:
            clean_b = batch.replace(" ", "_").replace("/", "_")
            file_name = f"{center}_{clean_b}_Weekly_Schedule.pdf"

        file_path = os.path.join(self.output_dir, file_name)
        doc = SimpleDocTemplate(
            file_path,
            pagesize=landscape(A4),
            leftMargin=20,
            rightMargin=20,
            topMargin=18,
            bottomMargin=18
        )

        elements = []

        # Locate logo
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "uwill_logo.png"))
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath("assets/uwill_logo.png")

        clean_center = center.strip()
        clean_batch = batch.strip()

        if os.path.exists(logo_path):
            logo_img = Image(logo_path, width=110, height=55)
            title_html = (
                '<font size=16 color="#0F172A"><b>WEEKLY LECTURE TIMETABLE</b></font><br/>'
                '<font size=8.5 color="#64748B">Academic Session 2026–27 &nbsp;•&nbsp; Monday to Saturday</font>'
            )
            right_html = (
                f'<font size=9 color="#64748B"><b>BRANCH:</b></font> <font size=11 color="#27348B"><b>{clean_center}</b></font><br/>'
                f'<font size=9 color="#64748B"><b>BATCH:</b></font> <font size=11 color="#EE2A35"><b>{clean_batch}</b></font><br/>'
                f'<font size=8 color="#64748B">05/10/2026 to 10/10/2026</font>'
            )
            p_title = Paragraph(title_html, self.header_left_style)
            p_right = Paragraph(right_html, self.header_right_style)

            # Printable width: 802pt (120 + 380 + 302 = 802)
            header_table = Table([[logo_img, p_title, p_right]], colWidths=[120, 380, 302])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
                ('LINEBELOW', (0, 0), (-1, -1), 2.5, colors.HexColor("#EE2A35")),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(header_table)
        else:
            sub_text = f"<b>BRANCH:</b> {clean_center} &nbsp;|&nbsp; <b>BATCH:</b> {clean_batch} &nbsp;|&nbsp; <b>WEEK:</b> 05/10/2026 to 10/10/2026"
            elements.append(Paragraph("WEEKLY LECTURE TIMETABLE", self.title_style))
            elements.append(Spacer(1, 4))
            elements.append(Paragraph(sub_text, self.subtitle_style))

        elements.append(Spacer(1, 8))

        # Build Table Header with Ice-Blue Dates
        header_row = [Paragraph("TIME SLOT", self.header_cell_style)]
        for d in grid_data["days"]:
            date_str = week_dates.get(d, "") if week_dates else ""
            label = f'<font size=7 color="#93C5FD">{date_str}</font><br/><font size=9.5 color="#FFFFFF"><b>{d}</b></font>' if date_str else f'<b>{d}</b>'
            header_row.append(Paragraph(label, self.header_cell_style))

        table_data = [header_row]

        # Table Rows
        for r in grid_data["rows"]:
            time_p = Paragraph(r["time_label"], self.time_cell_style)
            row_cells = [time_p]

            if r.get("is_recess"):
                for _ in grid_data["days"]:
                    row_cells.append(Paragraph("★ &nbsp;RECESS / BREAK &nbsp;★", self.recess_style))
            else:
                for d in grid_data["days"]:
                    cell_info = r["day_cells"].get(d, {})
                    if cell_info.get("type") == "test" or cell_info.get("subject") == "WEEKLY TEST":
                        time_str = cell_info.get("time_range", "")
                        dur_line = f"<font color='#92400E' size=7.5><b>{time_str} (60 mins)</b></font><br/>" if time_str else "<font color='#92400E' size=7.5><b>1 Hour Exam</b></font><br/>"
                        cell_p = Paragraph(
                            "<b><font color='#B45309' size=8.5>★ WEEKLY TEST ★</font></b><br/>"
                            f"{dur_line}"
                            "<font color='#78350F' size=6.5>1 Hour Exam • Weekly Syllabus</font>",
                            self.test_cell_style
                        )
                        row_cells.append(cell_p)
                    elif cell_info.get("type") == "lecture":
                        fac = cell_info.get("faculty", "")
                        sub = cell_info.get("subject", "")
                        ch = cell_info.get("chapter", "")
                        top = cell_info.get("topic", "")
                        t_range = cell_info.get("time_range", "")

                        details = f"<br/><font color='#475569' size=6.5>{ch} • {top}</font>" if (ch or top) else ""
                        time_line = f"<br/><font color='#2563EB' size=7><b>{t_range}</b></font>" if t_range and (r["end_min"] - r["start_min"] != cell_info.get("duration_min")) else ""
                        cell_p = Paragraph(
                            f"<b><font color='#27348B' size=8>{fac}</font></b><br/>"
                            f"<font color='#EE2A35' size=7.5><b>{sub}</b></font>"
                            f"{time_line}"
                            f"{details}",
                            self.lecture_batch_style
                        )
                        row_cells.append(cell_p)
                    else:
                        row_cells.append(Paragraph("—", self.empty_cell_style))

            table_data.append(row_cells)

        num_cols = len(grid_data["days"]) + 1
        col_widths = [85] + [115] * (num_cols - 1)

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#27348B")),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor("#F8FAFC")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor("#27348B")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])

        for row_idx, r in enumerate(grid_data["rows"], start=1):
            if r.get("is_recess"):
                t_style.add('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor("#FEF3C7"))
                t_style.add('SPAN', (1, row_idx), (-1, row_idx))
            else:
                for c_idx, d in enumerate(grid_data["days"], start=1):
                    cell_info = r["day_cells"].get(d, {})
                    if cell_info.get("type") == "test":
                        t_style.add('BACKGROUND', (c_idx, row_idx), (c_idx, row_idx), colors.HexColor("#FEF3C7"))
                    if cell_info.get("is_span_start") and cell_info.get("span_count", 1) > 1:
                        span_cnt = cell_info["span_count"]
                        t_style.add('SPAN', (c_idx, row_idx), (c_idx, row_idx + span_cnt - 1))

        t.setStyle(t_style)
        elements.append(t)

        # Footer
        elements.append(Spacer(1, 8))
        footer_p = Paragraph(
            "● Note: Students are requested to bring textbooks & notebooks as per syllabus chapters listed above. | U WILL CLASSES",
            self.footer_style
        )
        elements.append(footer_p)

        doc.build(elements)
        return file_path

    def generate_faculty_pdf(
        self,
        faculty_name: str,
        grid_data: Dict,
        week_dates: Optional[Dict[str, str]] = None,
        file_name: Optional[str] = None
    ) -> str:
        """
        Generates a clean personal timetable PDF for an individual faculty member.
        """
        os.makedirs(f"{self.output_dir}/faculty", exist_ok=True)
        if not file_name:
            clean_name = faculty_name.replace(" ", "_").replace("/", "_")
            file_name = f"faculty/{clean_name}_Weekly_Schedule.pdf"

        file_path = os.path.join(self.output_dir, file_name)
        doc = SimpleDocTemplate(
            file_path,
            pagesize=landscape(A4),
            leftMargin=20,
            rightMargin=20,
            topMargin=18,
            bottomMargin=18
        )

        elements = []

        # Locate logo
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "uwill_logo.png"))
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath("assets/uwill_logo.png")

        clean_fac = faculty_name.strip()

        if os.path.exists(logo_path):
            logo_img = Image(logo_path, width=110, height=55)
            title_html = (
                '<font size=16 color="#0F172A"><b>FACULTY MASTER SCHEDULE</b></font><br/>'
                '<font size=8.5 color="#64748B">Academic Session 2026–27 &nbsp;•&nbsp; Monday to Saturday</font>'
            )
            right_html = (
                f'<font size=9 color="#64748B"><b>FACULTY:</b></font> <font size=12 color="#27348B"><b>{clean_fac}</b></font><br/>'
                f'<font size=8 color="#64748B">05/10/2026 to 10/10/2026</font>'
            )
            p_title = Paragraph(title_html, self.header_left_style)
            p_right = Paragraph(right_html, self.header_right_style)

            # Printable width: 802pt (120 + 380 + 302 = 802)
            header_table = Table([[logo_img, p_title, p_right]], colWidths=[120, 380, 302])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
                ('LINEBELOW', (0, 0), (-1, -1), 2.5, colors.HexColor("#EE2A35")),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(header_table)
        else:
            sub_text = f"<b>FACULTY:</b> {clean_fac} &nbsp;|&nbsp; <b>WEEK:</b> 05/10/2026 to 10/10/2026"
            elements.append(Paragraph("FACULTY MASTER SCHEDULE", self.title_style))
            elements.append(Spacer(1, 4))
            elements.append(Paragraph(sub_text, self.subtitle_style))

        elements.append(Spacer(1, 8))

        # Build Table Header with Ice-Blue Dates
        header_row = [Paragraph("TIME SLOT", self.header_cell_style)]
        for d in grid_data["days"]:
            date_str = week_dates.get(d, "") if week_dates else ""
            label = f'<font size=7 color="#93C5FD">{date_str}</font><br/><font size=9.5 color="#FFFFFF"><b>{d}</b></font>' if date_str else f'<b>{d}</b>'
            header_row.append(Paragraph(label, self.header_cell_style))

        table_data = [header_row]

        # Table Rows
        for r in grid_data["rows"]:
            time_p = Paragraph(r["time_label"], self.time_cell_style)
            row_cells = [time_p]

            if r.get("is_recess") or r.get("is_lunch_break"):
                for _ in grid_data["days"]:
                    row_cells.append(Paragraph("★ &nbsp;LUNCH BREAK &nbsp;★", self.recess_style))
            else:
                for d in grid_data["days"]:
                    cell_info = r["day_cells"].get(d, {})
                    if cell_info.get("type") == "lecture":
                        time_range = cell_info.get("time_range", "")
                        dur = cell_info.get("duration", "")
                        center_batch = cell_info.get("center_batch", cell_info.get("faculty", ""))
                        sub = cell_info.get("subject", "")
                        ch = cell_info.get("chapter", "")
                        top = cell_info.get("topic", "")

                        content_lines = []
                        if time_range:
                            content_lines.append(f"<font color='#EE2A35' size=7.5><b>{time_range}</b></font> <font size=6.5 color='#64748B'>{dur}</font>")
                        content_lines.append(f"<b><font color='#27348B' size=8>{center_batch}</font></b>")
                        content_lines.append(f"<font color='#0F172A' size=7.5><b>{sub}</b></font>")
                        if ch or top:
                            content_lines.append(f"<font color='#475569' size=6.5>{ch} • {top}</font>")

                        cell_p = Paragraph("<br/>".join(content_lines), self.lecture_fac_style)
                        row_cells.append(cell_p)
                    else:
                        row_cells.append(Paragraph("—", self.empty_cell_style))

            table_data.append(row_cells)

        num_cols = len(grid_data["days"]) + 1
        col_widths = [85] + [115] * (num_cols - 1)

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t_style = TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#27348B")),
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor("#F8FAFC")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor("#27348B")),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])

        for r_idx, r in enumerate(grid_data["rows"], start=1):
            if r.get("is_recess") or r.get("is_lunch_break"):
                t_style.add('BACKGROUND', (0, r_idx), (0, r_idx), colors.HexColor("#FDE68A"))
                t_style.add('BACKGROUND', (1, r_idx), (-1, r_idx), colors.HexColor("#FEF3C7"))
                t_style.add('SPAN', (1, r_idx), (-1, r_idx))
        t.setStyle(t_style)
        elements.append(t)

        # Footer
        elements.append(Spacer(1, 8))
        footer_p = Paragraph(
            "● Note: Please arrive 10 minutes prior to lecture start. Ensure inter-branch travel buffers are maintained. | U WILL CLASSES",
            self.footer_style
        )
        elements.append(footer_p)

        doc.build(elements)
        return file_path
