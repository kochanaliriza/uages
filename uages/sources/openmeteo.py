"""Open-Meteo kaynaklari: ERA5 arsivi, arsiv (best match), gecmis tahmin, 7-16 gun tahmin, ensemble, mevsimsel.

Open-Meteo saatlik isinim degerleri *onceki saatin ortalamasi*dir (etiket = aralik sonu).
Burada tum seriler 1 saat geri kaydirilip UTC aralik-basi etiketine cevrilir.
Ruzgar m/s istenir (varsayilan km/h'dir!).
"""
from __future__ import annotations

import hashlib
import os
import json
import time

import pandas as pd
import requests

from .. import ssl_ipucu
from ..config import PATHS

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HISTFC = "https://historical-forecast-api.open-meteo.com/v1/forecast"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
SEASONAL = "https://seasonal-api.open-meteo.com/v1/seasonal"

VARS = {
    "shortwave_radiation": "ghi",
    "direct_normal_irradiance": "dni",
    "diffuse_radiation": "dhi",
    "temperature_2m": "temp",
    "wind_speed_10m": "wind",
    "cloud_cover": "cloud",
    "snow_depth": "snow",
}
HOURLY = ",".join(VARS)
def cache_dir():
    """Ortak hava onbellegi (tum ulkeler): <kok>/cache/openmeteo."""
    return PATHS["wcache"] / "openmeteo"


class DailyLimit(RuntimeError):
    """Open-Meteo gunluk istek limiti doldu. Onbellek korunur; ayni komut ertesi gun kaldigi yerden devam eder."""


def _get(url: str, params: dict, cache_hours: float | None = None, retries: int = 4) -> dict:
    """GET + disk onbellegi. cache_hours=None -> kalici (arsiv), sayi -> o kadar saat gecerli.
    429'da limit turune gore bekler (dakikalik 65 sn, saatlik 15 dk); gunluk limitte DailyLimit firlatir."""
    CACHE = cache_dir()
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    fp = CACHE / f"{key}.json"
    if fp.exists():
        age_h = (time.time() - fp.stat().st_mtime) / 3600
        if cache_hours is None or age_h < cache_hours or os.environ.get("UAGES_OFFLINE") == "1":
            return json.loads(fp.read_text(encoding="utf-8"))
    err = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=120)
            if r.status_code == 429:
                reason = r.text
                if "Daily" in reason:
                    raise DailyLimit(reason)
                time.sleep(900 if "Hourly" in reason else 65 if "Minutely" in reason else 20 * (i + 1))
                continue
            r.raise_for_status()
            data = r.json()
            fp.write_text(json.dumps(data), encoding="utf-8")
            return data
        except DailyLimit:
            raise
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"Open-Meteo hatasi {url}: {err}{ssl_ipucu(err)}")


def _to_frame(hourly: dict, suffix: str = "") -> pd.DataFrame:
    t = pd.to_datetime(hourly["time"]) - pd.Timedelta(hours=1)  # aralik sonu -> aralik basi
    cols = {}
    for om, short in VARS.items():
        key = om + suffix
        if key in hourly:
            cols[short] = pd.to_numeric(pd.Series(hourly[key]), errors="coerce").to_numpy()
    df = pd.DataFrame(cols, index=pd.DatetimeIndex(t, name="time_utc"))
    return df


def _base(lat, lon):
    return {"latitude": round(float(lat), 4), "longitude": round(float(lon), 4), "timezone": "UTC",
            "wind_speed_unit": "ms"}


def _complete_days(end: pd.Timestamp) -> str:
    return pd.Timestamp(end).strftime("%Y-%m-%d")


def archive(lat, lon, start, end, model: str | None = "era5") -> pd.DataFrame:
    """ERA5 (model='era5') ya da best-match arsiv (model=None). Bitis gunu +1 alinir (kaydirma icin)."""
    p = _base(lat, lon) | {"start_date": str(start)[:10],
                           "end_date": (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                           "hourly": HOURLY}
    if model:
        p["models"] = model
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    recent = pd.Timestamp(p["end_date"]) >= today - pd.Timedelta(days=10)
    data = _get(ARCHIVE, p, cache_hours=12 if recent else None)
    df = _to_frame(data["hourly"])
    return df.loc[pd.Timestamp(start): pd.Timestamp(end) + pd.Timedelta(hours=23)]


def historical_forecast(lat, lon, start, end, model: str = "best_match") -> pd.DataFrame:
    p = _base(lat, lon) | {"start_date": str(start)[:10],
                           "end_date": (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                           "hourly": HOURLY}
    if model and model != "best_match":
        p["models"] = model
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    recent = pd.Timestamp(p["end_date"]) >= today - pd.Timedelta(days=10)
    data = _get(HISTFC, p, cache_hours=12 if recent else None)
    df = _to_frame(data["hourly"])
    return df.loc[pd.Timestamp(start): pd.Timestamp(end) + pd.Timedelta(hours=23)]


def forecast(lat, lon, models: list[str], days: int = 7, past_days: int = 3, cache_hours: float = 1.0) -> dict:
    """{model: DataFrame}. Coklu model tek istekte; sutunlar '<var>_<model>' gelir."""
    p = _base(lat, lon) | {"hourly": HOURLY, "forecast_days": min(days + 1, 16), "past_days": past_days,
                           "models": ",".join(models)}
    data = _get(FORECAST, p, cache_hours=cache_hours)
    h = data["hourly"]
    out = {}
    for m in models:
        suffix = f"_{m}" if len(models) > 1 else ""
        df = _to_frame(h, suffix)
        if "ghi" in df and df["ghi"].notna().any():
            out[m] = df
    return out


PREVRUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"
SATELLITE = "https://satellite-api.open-meteo.com/v1/archive"
LEAD_VARS = {"shortwave_radiation": "ghi", "direct_normal_irradiance": "dni", "diffuse_radiation": "dhi",
             "temperature_2m": "temp"}


def previous_runs(lat, lon, start, end, model: str, leads=range(1, 8)) -> pd.DataFrame:
    """Ufka gore arsivlenmis tahmin (Previous Runs API). `<var>_previous_dayN` = N gun onceki model kosusunun
    o saat icin verdigi deger. Donus: uzun tablo [time_utc, lead, ghi, dni, dhi, temp, wind].
    Ruzgar yalnizca lead 1'den alinir ve tum ufuklara kopyalanir (Faiman'a etkisi kucuk, istek maliyetini dusurur).
    Kapsam: ICON ve GFS 2024-01-19, ECMWF IFS025 2024-03-06'dan itibaren; ICON'da previous_day7 yok (NaN)."""
    names = [f"{v}_previous_day{n}" for n in leads for v in LEAD_VARS] + ["wind_speed_10m_previous_day1"]
    p = _base(lat, lon) | {"start_date": str(start)[:10],
                           "end_date": (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                           "hourly": ",".join(names)}
    if model != "best_match":
        p["models"] = model
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    data = _get(PREVRUNS, p, cache_hours=12 if pd.Timestamp(p["end_date"]) >= today - pd.Timedelta(days=10) else None)
    h = data["hourly"]
    t = pd.DatetimeIndex(pd.to_datetime(h["time"]) - pd.Timedelta(hours=1), name="time_utc")  # aralik sonu -> basi
    wind = pd.to_numeric(pd.Series(h.get("wind_speed_10m_previous_day1")), errors="coerce").to_numpy()
    frames = []
    for n in leads:
        cols = {short: pd.to_numeric(pd.Series(h.get(f"{v}_previous_day{n}")), errors="coerce").to_numpy()
                for v, short in LEAD_VARS.items()}
        frames.append(pd.DataFrame(cols, index=t).assign(wind=wind, lead=n))
    df = pd.concat(frames).reset_index()
    keep = (df["time_utc"] >= pd.Timestamp(start)) & (df["time_utc"] <= pd.Timestamp(end) + pd.Timedelta(hours=23))
    return df[keep].reset_index(drop=True)


def satellite(lat, lon, start, end, model: str = "eumetsat_sarah3") -> pd.DataFrame:
    """Uydu tabanli gerceklesen isinim (GHI/DNI/DHI), ~1-2 gun gecikmeli. Model acikca verilmeli
    (verilmezse karisim gelir). Zaman konvansiyonu diger Open-Meteo urunleri gibi kabul edilir (-1 saat);
    ilk kullanimda calibrate.best_lag ile dogrulanmali."""
    p = _base(lat, lon) | {"start_date": str(start)[:10], "end_date": str(end)[:10], "models": model,
                           "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation"}
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    data = _get(SATELLITE, p, cache_hours=12 if pd.Timestamp(end) >= today - pd.Timedelta(days=10) else None)
    return _to_frame(data["hourly"])


def ensemble_ghi(lat, lon, model: str = "ecmwf_ifs025", days: int = 7, cache_hours: float = 1.0) -> pd.DataFrame:
    """Ensemble uyeleri GHI (W/m2), sutun = uye."""
    p = _base(lat, lon) | {"hourly": "shortwave_radiation", "forecast_days": min(days + 1, 15), "models": model}
    data = _get(ENSEMBLE, p, cache_hours=cache_hours)
    h = data["hourly"]
    t = pd.to_datetime(h["time"]) - pd.Timedelta(hours=1)
    mem = {k: h[k] for k in h if k.startswith("shortwave_radiation")}
    return pd.DataFrame(mem, index=pd.DatetimeIndex(t, name="time_utc")).apply(pd.to_numeric, errors="coerce")


def seasonal_monthly_ghi(lat, lon, cache_hours: float = 24.0) -> pd.DataFrame | None:
    """ECMWF SEAS5 (Open-Meteo seasonal) gunluk kisa dalga toplamlarindan aylik ortalama GHI (W/m2), uye medyani.
    Yanlilik duzeltmesiz; sadece gostergesel kullanilir. Hata olursa None."""
    try:
        p = {"latitude": round(float(lat), 4), "longitude": round(float(lon), 4),
             "daily": "shortwave_radiation_sum", "forecast_days": 183, "timezone": "UTC"}
        data = _get(SEASONAL, p, cache_hours=cache_hours)
        d = data.get("daily", {})
        t = pd.to_datetime(d["time"])
        mem = {k: d[k] for k in d if k.startswith("shortwave_radiation_sum")}
        df = pd.DataFrame(mem, index=t).apply(pd.to_numeric, errors="coerce")  # MJ/m2/gun
        med = df.median(axis=1) * 1e6 / 86400.0  # gunluk ortalama W/m2
        mon = med.resample("MS").agg(["mean", "count"])
        mon = mon[mon["count"] >= 20]
        return mon.rename(columns={"mean": "ghi_mean_wm2"})
    except Exception as e:  # noqa: BLE001
        print(f"  Mevsimsel tahmin alinamadi: {e}")
        return None
