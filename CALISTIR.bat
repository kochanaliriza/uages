@echo off
chcp 65001 >nul
title Ukrayna GES Tahmin
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
set "ULKE_DIR=countries\UA"
if not exist "%ULKE_DIR%\logs" mkdir "%ULKE_DIR%\logs"
echo.
echo  UKRAYNA GES TAHMIN - veriler cekiliyor ve hesaplaniyor
echo  GPEE gerceklesen + Open-Meteo hava tahmini + PVGIS / ERA5
echo  (Ilk calismada gecmis veriler indirildigi icin 3-5 dakika surebilir, sonra ~1 dakika)
echo.
"%PY%" -c "import pandas, requests, openpyxl, tzdata, truststore" 2>nul || (
  echo  Eksik Python paketleri kuruluyor...
  "%PY%" -m pip install -q -r requirements.txt || "%PY%" -m pip install -q --use-feature=truststore -r requirements.txt
)
"%PY%" -m uages all
if errorlevel 1 (
  echo.
  echo  HATA olustu. Ayrinti: %ULKE_DIR%\logs\son_hata.txt
  pause
  exit /b 1
)
echo.
echo  Tamam. Panel tarayicida aciliyor: %ULKE_DIR%\outputs\dashboard.html
echo  CSV dosyalari: %ULKE_DIR%\outputs klasoru
start "" "%ULKE_DIR%\outputs\dashboard.html"
timeout /t 15
