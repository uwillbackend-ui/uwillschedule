# AI Coaching Institute Timetable Scheduling System

An intelligent, constraint-based weekly scheduling system powered by **Google OR-Tools CP-SAT** and **ReportLab**. Designed specifically for multi-branch coaching institutes with tight faculty availability, travel times between centers, and school recess requirements.

---

## Key Features

1. **Deterministic Constraint Solver (Google OR-Tools CP-SAT)**:
   - **Zero Overlaps**: 100% mathematical guarantee that no faculty is double-booked across any branch.
   - **Block 1 & Block 2 Consistency**: Enforces **Monday, Tuesday, and Wednesday schedules to be identical**, and **Thursday, Friday, and Saturday schedules to be identical** wherever possible!
   - **Travel Time Buffers**: Strictly enforces inter-branch travel times when a faculty moves between centers on the same day.
   - **Fixed School Recess**: Strictly reserves batch recess windows (e.g. 9:30 AM – 10:00 AM at Jai Ambe).
   - **Visiting Faculty Anchors**: Pins immovable school visiting lectures (e.g. Preeti Madam, Meet Sir, Rakhi Madam).
   - **Lecture Duration Flexibility**: Dynamically adjusts up to 20% of lectures in any batch by $\pm 10$ minutes (e.g., 50 min, 55 min, 60 min, 65 min, 70 min) to achieve optimal packing.

2. **Dual PDF Deliverables**:
   - **Batch Schedules (`output/pdf/`)**: 36 student-ready timetable PDFs (one per batch of every branch).
   - **Faculty Personal Schedules (`output/faculty_pdf/`)**: 41 personalized timetable PDFs (one for each teacher showing their cross-branch weekly routine).

3. **Vertical Timetable Matrix Format**:
   - Matches the standard student-facing and teacher layout:
     - **Columns**: Dates & Days of the Week (`MONDAY`, `TUESDAY`, `WEDNESDAY`, `THURSDAY`, `FRIDAY`, `SATURDAY`).
     - **Rows**: Time Slots (`8:00 AM TO 9:00 AM`, `9:00 AM TO 10:00 AM`, etc.).
     - **Cells**:
       - Faculty Name (or Branch & Batch for faculty view)
       - Subject Name
       - Chapter (e.g. `CH-1`)
       - Topic (e.g. `MEAN`)

4. **Weekly Chapter & Topic Workflow**:
   - The schedule guy opens `output/excel/Weekly_Schedule_Input_Topics.xlsx`.
   - Types or pastes the chapters and topics for each scheduled lecture.
   - Runs `python update_topics_and_export_pdfs.py` to regenerate both student and faculty PDFs instantly.

---

## Project Structure

```
zealous-bardeen/
├── data/                                 # Raw input data exported from Google Sheets
│   ├── center_and_batch_master.csv
│   ├── faculty_details.csv
│   ├── faculty_master.csv
│   ├── recess_master_fixed.csv
│   ├── subject_rules.csv
│   ├── visiting_faculty_fixed.csv
│   └── travel_time_matrix.csv
├── src/
│   ├── models.py                         # Data models
│   ├── data_loader.py                    # Multi-sheet CSV parser & alias resolver
│   ├── formatter.py                      # Vertical timetable matrix formatter
│   ├── pdf_generator.py                  # ReportLab PDF styling engine
│   └── excel_exporter.py                 # Excel exporter for topic entry and matrices
├── output/
│   ├── pdf/                              # Student-ready weekly timetable PDFs
│   └── excel/                            # Editable topic sheet & Excel matrices
├── scripts/
│   ├── diagnose.py                       # Constraint & capacity diagnostic tool
│   ├── audit_capacities.py               # Faculty workload vs daily capacity auditor
│   └── inspect_data.py                   # Data inspection tool
├── generate_timetable.py                 # Main scheduler runner
├── update_topics_and_export_pdfs.py      # 1-click topic sync and PDF regenerator
└── README.md
```

---

---

## Web Application (Method 2) — Turnkey Dashboard for Schedule Coordinator

For everyday operation, the schedule coordinator doesn't need to run terminal commands or manually edit Excel files. They can use the **AI Timetable Web Command Center**:

### 1. Launching the Web App:
- **On Mac**: Double-click `Start_Web_App_Mac.command` (or run `python web_app.py`).
- **On Windows**: Double-click `Start_Web_App_Windows.bat` (or run `python web_app.py`).
- The browser will automatically open to `http://localhost:8080`.

### 2. Giving Access to the Schedule Guy on His Laptop:
- **Option A (Shared Local / Office Wi-Fi)**:
  - Vicky Sir runs the web app on his laptop.
  - The schedule coordinator simply opens `http://<Vicky-Sir-IP>:8080` in Chrome on his laptop. Zero setup required on the coordinator's machine!
- **Option B (Copy Folder to Coordinator's Laptop)**:
  - Copy this project folder to the coordinator's Windows laptop.
  - Double-click `Start_Web_App_Windows.bat`.
- **Option C (Free Cloud Hosting - URL Access)**:
  - Run `ngrok http 8080` or host on Streamlit Community Cloud for a permanent web link accessible anywhere.

### 3. Web Features:
- **Batch Timetables Tab**: View any branch and batch timetable in vertical matrix format with recess indicators.
- **Faculty Personal Schedules Tab**: View any faculty member's personal timetable with exact lecture times, duration labels, and branch transit buffers.
- **Weekly Chapter & Topic Editor Tab**: Directly enter or edit Chapter and Topic for all 642 lectures in the browser table.
- **1-Click "Save & Bake into PDFs"**: Saves all chapters/topics and instantly updates all Batch & Faculty PDFs.
- **1-Click ZIP Downloads**:
  - `Download Batch PDFs (ZIP)`: Bundles all 36 student batch timetable PDFs into one zip file.
  - `Download Faculty PDFs (ZIP)`: Bundles all 41 teacher personal schedule PDFs into one zip file.
- **Live "Sync Sheet"**: Fetches fresh data from Google Sheets when mid-year changes happen.
- **"Generate Schedule"**: Re-runs the global CP-SAT optimization engine anytime constraints change.

---

## Alternative: Command Line & Excel Workflow

---

## Troubleshooting & Mid-Year Updates (For Vicky Sir)

If timings or faculty availability change mid-year:
1. Update the corresponding rows in the Google Sheet (or CSV files in `data/`).
2. Run the audit tool to verify there are no mathematical overloads:
   ```bash
   python scripts/audit_capacities.py
   ```
3. Run `python generate_timetable.py` to regenerate the full timetable.
