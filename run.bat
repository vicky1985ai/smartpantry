@echo off
title SmartPantry - Home Grocery & Price Intelligence
color 0A

echo ===================================================
echo     SmartPantry - Home Grocery Management App
echo ===================================================
echo.
echo Starting Python FastAPI backend on port 8000...
echo.

start "" "http://localhost:8000"
python server.py

pause
