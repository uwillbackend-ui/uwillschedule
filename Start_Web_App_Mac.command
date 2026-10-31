#!/bin/bash
cd "$(dirname "$0")"
echo "========================================================"
echo "  COACHING INSTITUTE AI SCHEDULER - WEB DASHBOARD"
echo "========================================================"
echo ""
echo "Starting local web server on port 8080..."
echo "Opening your web browser..."

PYTHON_CMD="python3"
if [ -f "./.venv/bin/python" ]; then
    PYTHON_CMD="./.venv/bin/python"
fi

# Open browser after a slight 1s pause
(sleep 1 && open "http://localhost:8080") &

$PYTHON_CMD web_app.py
