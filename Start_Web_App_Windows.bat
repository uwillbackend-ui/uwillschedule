@echo off
title Coaching Institute AI Scheduler - Web Dashboard
echo ========================================================
echo   COACHING INSTITUTE AI SCHEDULER - WEB DASHBOARD
echo ========================================================
echo.
echo Starting local web server on port 8080...
echo Opening your browser at http://localhost:8080...
echo.

start http://localhost:8080
python web_app.py
pause
