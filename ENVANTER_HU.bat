@echo off
REM Macaristan ENTSO-E gunes verisi envanteri (yalnizca okur, rapor: countries\HU\envanter_raporu.md)
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
"%PY%" tools\entsoe_envanter.py --ulke HU
if exist "countries\HU\envanter_raporu.md" start "" notepad "countries\HU\envanter_raporu.md"
pause
