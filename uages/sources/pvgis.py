"""PVGIS (JRC) kaynaklari: TMY ve SARAH3 saatlik seriler (duzlem ici bilesenler).

- TMY: tipik meteorolojik yil, G(h)/Gb(n)/Gd(h)/T2m/WS10m -> tam model zinciri.
- seriescalc: components=1 ile Gb(i)/Gd(i)/Gr(i) (egimli duzlem) + T2m/WS10m -> run_pv_from_poa.
PVGIS aspect: 0=guney, -90=dogu. Bizim azimut 180=guney -> aspect = azimut - 180.
Zaman etiketleri (HH:10 vb.) saat basina yuvarlanir ve aralik basi kabul edilir; aylik toplamlar icin etkisi ihmal edilebilir.
"""
from __future__ import annotations

import hashlib
import os
import json
import time

import pandas as pd
import requests

from ..config import PATHS

API = "https://re.jrc.ec.europa.eu/api/v5_3"
def cache_dir():
    """Ortak PVGIS onbellegi (tum ulkeler): <kok>/cache/pvgis."""
    return PATHS["wcache"] / "pvgis"


def _get(endpoint: str, params: dict) -> dict:
    CACHE = cache_dir()
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5((endpoint + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    fp = CACHE / f"{key}.json"
    if fp.exists():
        return json.loads(fp.read_text(encoding="utf-8"))
    err = None
    for i in range(4):
        try:
            r = requests.get(f"{API}/{endpoint}", params=params | {"outputformat": "json"}, timeout=180)
            if r.status_code == 429:
                time.sleep(15 * (i + 1))
                continue
            r.raise_for_status()
            data = r.json()
            fp.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"PVGIS hatasi {endpoint}: {err}")


def _parse_time(s: pd.Series) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(s, format="%Y%m%d:%H%M")).floor("h")


def tmy(lat, lon) -> pd.DataFrame:
    """Index: 2001 yilina yeniden etiketlenmis tipik yil (UTC aralik basi). Sutunlar ghi,dni,dhi,temp,wind."""
    d = _get("tmy", {"lat": round(lat, 4), "lon": round(lon, 4)})
    df = pd.DataFrame(d["outputs"]["tmy_hourly"])
    t = _parse_time(df["time(UTC)"])
    t2001 = pd.DatetimeIndex([x.replace(year=2001) for x in t], name="time_utc")
    out = pd.DataFrame({"ghi": df["G(h)"].to_numpy(float), "dni": df["Gb(n)"].to_numpy(float),
                        "dhi": df["Gd(h)"].to_numpy(float), "temp": df["T2m"].to_numpy(float),
                        "wind": df["WS10m"].to_numpy(float)}, index=t2001)
    return out[~out.index.duplicated()].sort_index()


def series_poa(lat, lon, y0: int, y1: int, tilt: float, azimuth: float) -> pd.DataFrame:
    """SARAH3 saatlik duzlem ici bilesenler. Sutunlar poa_beam, poa_diff, poa_gnd, temp, wind, p_pvgis_w_per_kwp."""
    d = _get("seriescalc", {"lat": round(lat, 4), "lon": round(lon, 4), "startyear": y0, "endyear": y1,
                            "pvcalculation": 1, "peakpower": 1, "loss": 14, "angle": tilt,
                            "aspect": azimuth - 180, "components": 1})
    df = pd.DataFrame(d["outputs"]["hourly"])
    t = _parse_time(df["time"])
    out = pd.DataFrame({"poa_beam": df["Gb(i)"].to_numpy(float), "poa_diff": df["Gd(i)"].to_numpy(float),
                        "poa_gnd": df["Gr(i)"].to_numpy(float), "temp": df["T2m"].to_numpy(float),
                        "wind": df["WS10m"].to_numpy(float), "p_pvgis": df["P"].to_numpy(float)},
                       index=pd.DatetimeIndex(t, name="time_utc"))
    return out[~out.index.duplicated()].sort_index()
