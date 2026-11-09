"""Kaynaklari bolge bazinda toplar ve 'karma' (agirlikli) hava serisi uretir.

Karma kurali: her saat ve her degisken icin, o saatte verisi olan kaynaklarin agirliklari
yeniden normalize edilerek agirlikli ortalama alinir. Boylece son gunlerde ERA5 gecikmesi
(~5 gun) varsa karma otomatik olarak arsiv best-match'e duser.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import normalize_weights
from .sources import openmeteo as om

BLEND_VARS = ["ghi", "dni", "dhi", "temp", "wind", "cloud", "snow"]


def blend(frames: dict, weights: dict) -> pd.DataFrame:
    w = normalize_weights({k: v for k, v in weights.items() if k in frames})
    if not w:
        raise ValueError("Karma icin agirlikli kaynak yok")
    idx = None
    for k in w:
        idx = frames[k].index if idx is None else idx.union(frames[k].index)
    out = {}
    for v in BLEND_VARS:
        num = pd.Series(0.0, index=idx)
        den = pd.Series(0.0, index=idx)
        for k, wk in w.items():
            if v not in frames[k]:
                continue
            s = frames[k][v].reindex(idx)
            ok = s.notna()
            num = num + s.fillna(0.0) * wk
            den = den + ok.astype(float) * wk
        if (den > 0).any():
            out[v] = num / den.replace(0.0, np.nan)
    df = pd.DataFrame(out, index=idx)
    df.index.name = "time_utc"
    return df


def history_weather(regions: pd.DataFrame, start, end, cfg: dict, verbose=True) -> dict:
    """{kaynak: {bolge: df}} + 'blend'. Kaynaklar: era5, om_archive, om_historical_forecast."""
    res = {"era5": {}, "om_archive": {}, "om_historical_forecast": {}}
    for _, r in regions.iterrows():
        rid = int(r["region"])
        if verbose:
            print(f"  Bolge {rid}: ERA5 / arsiv / gecmis tahmin")
        res["era5"][rid] = om.archive(r["lat"], r["lon"], start, end, model="era5")
        res["om_archive"][rid] = om.archive(r["lat"], r["lon"], start, end, model=None)
        try:
            res["om_historical_forecast"][rid] = om.historical_forecast(r["lat"], r["lon"], start, end)
        except Exception as e:  # noqa: BLE001
            print(f"   gecmis tahmin alinamadi: {e}")
    wts = cfg["history"]["weather_weights"]
    res["blend"] = {rid: blend({k: res[k][rid] for k in wts if rid in res.get(k, {})}, wts)
                    for rid in res["era5"]}
    return res


def forecast_weather(regions: pd.DataFrame, cfg: dict, verbose=True) -> dict:
    """{model: {bolge: df}} + 'blend' + 'ens_ratio' (bolge: DataFrame q_lo,q_hi GHI oranlari)."""
    fc = cfg["forecast"]
    models = list(fc["model_weights"].keys())
    res = {m: {} for m in models}
    ens = {}
    for _, r in regions.iterrows():
        rid = int(r["region"])
        if verbose:
            print(f"  Bolge {rid}: {', '.join(models)} + ensemble")
        got = om.forecast(r["lat"], r["lon"], models, days=fc["days"], past_days=fc["past_days"])
        for m, df in got.items():
            res[m][rid] = df
        try:
            e = om.ensemble_ghi(r["lat"], r["lon"], fc["ensemble_model"], days=fc["days"])
            mean = e.mean(axis=1)
            lo, hi = fc["band_quantiles"]
            ratio = e.div(mean.where(mean > 20), axis=0)
            ens[rid] = pd.DataFrame({"q_lo": ratio.quantile(lo, axis=1), "q_hi": ratio.quantile(hi, axis=1)})
        except Exception as e:  # noqa: BLE001
            print(f"   ensemble alinamadi: {e}")
    wts = fc["model_weights"]
    res["blend"] = {}
    for _, r in regions.iterrows():
        rid = int(r["region"])
        frames = {m: res[m][rid] for m in models if rid in res[m]}
        if frames:
            res["blend"][rid] = blend(frames, wts)
    res["ens_ratio"] = ens
    return res
