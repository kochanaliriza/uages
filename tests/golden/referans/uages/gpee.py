"""GPEE (Garantili Alici) gunluk GES serisi: gerceklesen + GPEE tahmini.

Uc: POST https://www.gpee.com.ua/main/loadCharts  (date=dd.mm.yyyy, zona=1, gen=1)
Yanit: 50 elemanli dizi. [0..24] gerceklesen, [25..49] tahmin (25. slot DST'de 25 saatlik gun icin).
Saat k (1..n), yerel (Kyiv) (k-1):00-k:00 araligidir -> depoda aralik basi etiketi kullanilir.
Bulut ortamindan 403 doner; kullanicinin bilgisayarindan calisir.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from .inputs import load_gpee, save_gpee

URL = "https://www.gpee.com.ua/main/loadCharts"
HEADERS = {"User-Agent": "Mozilla/5.0 (UA-GES-Tahmin)", "X-Requested-With": "XMLHttpRequest",
           "Referer": "https://www.gpee.com.ua/"}


def local_hours(d: date, tz: str) -> pd.DatetimeIndex:
    start = pd.Timestamp(d).tz_localize(tz)
    end = pd.Timestamp(d + timedelta(days=1)).tz_localize(tz)
    # UTC uzerinden uret -> DST gunlerinde 23/25 saat dogru cikar
    return pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left").tz_convert(tz)


def fetch_day(d: date, tz: str = "Europe/Kyiv", session=None) -> pd.DataFrame:
    s = session or requests
    r = s.post(URL, data={"date": d.strftime("%d.%m.%Y"), "zona": "1", "gen": "1"}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    arr = json.loads(r.text.strip())
    arr = [np.nan if v is None else float(v) for v in arr]
    hrs = local_hours(d, tz)
    n = len(hrs)
    if len(arr) < 25 + n:
        # Gun henuz yayimlanmamis (bos dizi) ya da eksik
        arr = arr + [np.nan] * (25 + n - len(arr))
    act = np.array(arr[0:n], dtype=float)
    fc = np.array(arr[25:25 + n], dtype=float)
    # Yayimlanmamis gerceklesen: tamami 0 ya da bos gelir
    if np.all(np.isnan(act)) or np.nanmax(np.abs(act)) < 1e-9:
        act[:] = np.nan
    if np.all(np.isnan(fc)):
        raise ValueError("gun henuz yayimlanmamis (bos yanit)")
    return pd.DataFrame({
        "time_utc": hrs.tz_convert("UTC").tz_localize(None),
        "time_local": hrs.tz_localize(None),
        "actual_mw": act, "forecast_mw": fc,
        "flag_curtail_day": False, "flag_curtail_hour": False, "flag_night_anomaly": False,
        "use_for_training": True, "source": "gpee_api",
    })


def update_store(cfg: dict, until: date | None = None, refetch_days: int = 3, verbose: bool = True) -> pd.DataFrame:
    """Depodaki son gunden (refetch_days geriye giderek) 'until' gunune kadar ceker.
    until varsayilan = yarin (GPEE ertesi gun tahminini de yayimlar)."""
    tz = cfg["local_tz"]
    store = load_gpee(cfg)
    today = pd.Timestamp.now(tz=tz).date()
    until = until or (today + timedelta(days=1))
    last_actual = store.loc[store["actual_mw"].notna(), "time_local"].max()
    start = (last_actual.date() - timedelta(days=refetch_days)) if pd.notna(last_actual) else date(today.year, 1, 1)
    frames, d = [], start
    with requests.Session() as sess:
        while d <= until:
            try:
                frames.append(fetch_day(d, tz, sess))
                if verbose:
                    print(f"  GPEE {d} ok")
            except ValueError:
                print(f"  GPEE {d}: henuz yayimlanmamis")
            except Exception as e:  # noqa: BLE001
                print(f"  GPEE {d} HATA: {e}")
            d += timedelta(days=1)
            time.sleep(0.4)
    if not frames:
        return store
    new = pd.concat(frames, ignore_index=True)
    # xlsx v2'de elle duzeltilmis satirlari (source=xlsx_v2) yeni API verisi gerceklesen NaN ise ezmesin
    merged = store.set_index("time_utc")
    new = new.set_index("time_utc")
    for t, row in new.iterrows():
        if t in merged.index:
            old = merged.loc[t]
            if pd.isna(row["actual_mw"]) and pd.notna(old["actual_mw"]):
                row = row.copy()
                row["actual_mw"] = old["actual_mw"]
            if old.get("source") == "xlsx_v2":
                # v2 duzeltmeleri ve bayraklari korunur; sadece bos alanlar doldurulur
                for c in ["actual_mw", "forecast_mw"]:
                    if pd.isna(old[c]) and pd.notna(row[c]):
                        merged.loc[t, c] = row[c]
                continue
        merged.loc[t] = row
    out = merged.reset_index().sort_values("time_utc")
    save_gpee(out)
    return out
