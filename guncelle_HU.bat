@echo off
REM Macaristan sessiz tam guncelleme (zamanlanmis gorev icin). Gunluk: countries\HU\logs\guncelle.log
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "ULKE_DIR=countries\HU"
if not exist "%ULKE_DIR%\logs" mkdir "%ULKE_DIR%\logs"
set "PYTHONIOENCODING=utf-8"
echo ==== %date% %time% ==== >> "%ULKE_DIR%\logs\guncelle.log"
"%PY%" -m uages all --ulke HU >> "%ULKE_DIR%\logs\guncelle.log" 2>&1
