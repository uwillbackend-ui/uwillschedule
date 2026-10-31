@echo off
title Sync From Google Sheets
echo ========================================================
echo   SYNCING DATA LIVE FROM GOOGLE SHEETS
echo ========================================================
echo.
python sync_from_google_sheets.py %*
echo.
pause
