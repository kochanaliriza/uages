@echo off
chcp 65001 >nul
title Macaristan GES Tahmin
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
set "ULKE_DIR=countries\HU"
if not exist "%ULKE_DIR%\logs" mkdir "%ULKE_DIR%\logs"
echo.
echo  MACARISTAN GES TAHMIN - ENTSO-E gerceklesen + MAVIR tahmini + Open-Meteo hava
echo  (Ilk calismada ENTSO-E gecmisi ve hava verisi indirilir: 5-15 dakika)
echo.
"%PY%" -m uages all --ulke HU
if errorlevel 1 (
  echo.
  echo  HATA olustu. Ayrinti: %ULKE_DIR%\logs\son_hata.txt
  pause
  exit /b 1
)
echo.
echo  Tamam. Panel: %ULKE_DIR%\outputs\dashboard.html
start "" "%ULKE_DIR%\outputs\dashboard.html"
timeout /t 15
