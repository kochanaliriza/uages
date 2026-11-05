@echo off
REM Tam guncelleme: GPEE + gecmis analiz/kalibrasyon + 7 gun tahmin + uzun vade + dashboard
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
if not exist logs mkdir logs
set "PYTHONIOENCODING=utf-8"
echo ==== %date% %time% ==== >> logs\guncelle.log
"%PY%" -m uages all >> logs\guncelle.log 2>&1
