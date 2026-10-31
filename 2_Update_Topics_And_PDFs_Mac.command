#!/bin/bash
cd "$(dirname "$0")"
echo "========================================================"
echo "  SYNC TOPICS AND REGENERATE STUDENT & FACULTY PDFS"
echo "========================================================"
echo ""
PYTHON_CMD="python3"
if [ -f "./.venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
fi
$PYTHON_CMD update_topics_and_export_pdfs.py
echo ""
echo "========================================================"
echo "Done! All Student and Faculty PDFs have been updated."
echo "========================================================"
open output/pdf
