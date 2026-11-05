@echo off
REM Hizli: sadece 7 gunluk hava tahmini + dashboard (kalibrasyon son tam calismadan)
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
if not exist logs mkdir logs
set "PYTHONIOENCODING=utf-8"
"%PY%" -m uages forecast >> logs\guncelle.log 2>&1
start "" "outputs\dashboard.html"
