@echo off
REM Son 50 gun: D-1 / gun ici tahmin sapmasi ve fiyat (SMF) korelasyonu. Fiyat dosyasi: countries\UA\data\input\smf.xlsx
REM Farkli gun sayisi icin: FIYAT_KORELASYON.bat 45
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
"%PY%" -m uages fiyat %1
if exist "countries\UA\outputs\fiyat_korelasyon_raporu.md" start "" notepad "countries\UA\outputs\fiyat_korelasyon_raporu.md"
pause
