@echo off
title Coaching Institute PDF Exporter
echo ========================================================
echo   SYNC TOPICS AND REGENERATE STUDENT & FACULTY PDFS
echo ========================================================
echo.
echo Reading updated topics from output\excel\Weekly_Schedule_Input_Topics.xlsx...
python update_topics_and_export_pdfs.py
echo.
echo ========================================================
echo Done! All Student and Faculty PDFs have been updated.
echo Check the 'output\pdf' and 'output\faculty_pdf' folders.
echo ========================================================
pause
