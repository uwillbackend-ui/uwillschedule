@echo off
title UWILL - Deploy Timetable to Vercel
echo ========================================================
echo   UWILL - DEPLOY LATEST TIMETABLE TO VERCEL
echo ========================================================
echo Publishing latest schedules to: https://uwillschedule.vercel.app
echo.
call npx vercel --prod --yes --name uwillschedule
echo.
echo ========================================================
echo SUCCESS! Web App updated at: https://uwillschedule.vercel.app
echo ========================================================
pause
