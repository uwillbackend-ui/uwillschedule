#!/bin/bash
cd "$(dirname "$0")"
echo "========================================================"
echo "  COACHING INSTITUTE TIMETABLE GENERATOR"
echo "========================================================"
echo ""
PYTHON_CMD="python3"
if [ -f "./.venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
fi
$PYTHON_CMD generate_timetable.py "$@"
echo ""
echo "========================================================"
echo "Done!"
echo "1. Student PDFs: output/pdf/"
echo "2. Faculty PDFs: output/faculty_pdf/"
echo "3. Topic Editor: output/excel/Weekly_Schedule_Input_Topics.xlsx"
echo "========================================================"
open output/pdf
