@echo off
title Coaching Institute Timetable Generator
echo ========================================================
echo   COACHING INSTITUTE TIMETABLE GENERATOR
echo ========================================================
echo.
echo Running AI Timetable Solver...
python generate_timetable.py %*
echo.
echo ========================================================
echo Done! 
echo 1. Student PDFs generated in: output\pdf\
echo 2. Faculty PDFs generated in: output\faculty_pdf\
echo 3. To enter topics, open: output\excel\Weekly_Schedule_Input_Topics.xlsx
echo ========================================================
pause
