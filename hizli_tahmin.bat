@echo off
REM Hizli: sadece 7 gunluk hava tahmini + dashboard (kalibrasyon son tam calismadan)
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "ULKE_DIR=countries\UA"
if not exist "%ULKE_DIR%\logs" mkdir "%ULKE_DIR%\logs"
set "PYTHONIOENCODING=utf-8"
"%PY%" -m uages forecast >> "%ULKE_DIR%\logs\guncelle.log" 2>&1
start "" "%ULKE_DIR%\outputs\dashboard.html"
