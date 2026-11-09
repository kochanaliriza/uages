@echo off
REM Bir kez: eski klasor yapisini (data/, outputs/, logs/) countries\UA ve ortak cache\ altina tasir.
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
"%PY%" tools\migrate_to_countries.py
pause
