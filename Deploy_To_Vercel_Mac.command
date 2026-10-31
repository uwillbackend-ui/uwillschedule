#!/bin/bash
cd "$(dirname "$0")"
echo "========================================================"
echo "  UWILL - DEPLOY LATEST TIMETABLE TO VERCEL"
echo "========================================================"
echo "Publishing latest batches and faculty schedules..."
echo "Live URL: https://uwillschedule.vercel.app"
echo ""
npx vercel --prod --yes --name uwillschedule
echo ""
echo "========================================================"
echo "SUCCESS! Web App updated at: https://uwillschedule.vercel.app"
echo "========================================================"
read -p "Press Enter to exit..."
