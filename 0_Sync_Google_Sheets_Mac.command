#!/bin/bash
cd "$(dirname "$0")"
echo "========================================================"
echo "  SYNCING DATA LIVE FROM GOOGLE SHEETS"
echo "========================================================"
echo ""
PYTHON_CMD="python3"
if [ -f "./.venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
fi
$PYTHON_CMD sync_from_google_sheets.py "$@"
echo ""
chmod +x "$0"
