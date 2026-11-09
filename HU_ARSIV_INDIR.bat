@echo off
REM Bir kez: Macaristan icin Open-Meteo arsiv tahminleri (D+1..D+7, 2024->) + uydu isinimi. 8 nokta, ~408 parca,
REM ~7.900 istek esdegeri (gunluk ucretsiz limit ~10.000). Limit dolarsa durur; ertesi gun ayni dosyayla kaldigi yerden devam eder.
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\ekrem\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONIOENCODING=utf-8"
"%PY%" tools\fetch_optim_data.py --ulke HU
echo.
echo  Bittiyse optimizasyon raporu icin:  "%PY%" -m uages optimize --ulke HU
pause
