"""Ilk kurulum: tum hava/isinim onbellegini doldurur (gelistirme amacli; normal kullanimda cli yeterli)."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
from uages.config import load_config
from uages.inputs import load_regions, init_gpee_store
from uages.sources import openmeteo as om, pvgis
from uages import weather, gpee

cfg = load_config()
print("tz test:", pd.Timestamp("2026-03-29 12:00").tz_localize("Europe/Kyiv"))
reg = load_regions(cfg)
init_gpee_store(cfg)
print("GPEE guncelle"); gpee.update_store(cfg)
end = (pd.Timestamp.now("UTC") - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
t0 = time.time()
print("Gecmis hava"); weather.history_weather(reg, cfg["history"]["start"], end, cfg)
print("Tahmin"); weather.forecast_weather(reg, cfg)
y0, y1 = cfg["longterm"]["era5_years"]; p0, p1 = cfg["longterm"]["pvgis_years"]
for _, r in reg.iterrows():
    print("Uzun vade bolge", int(r.region))
    om.archive(r.lat, r.lon, f"{y0}-01-01", f"{y1}-12-31", model="era5")
    pvgis.tmy(r.lat, r.lon)
    pvgis.series_poa(r.lat, r.lon, p0, p1, cfg["pv"]["tilt_deg"], cfg["pv"]["azimuth_deg"])
    om.seasonal_monthly_ghi(r.lat, r.lon)
print("bitti", round(time.time() - t0), "sn")
