"""Uzun vadeli (gelecek aylar) uretim beklentisi: ERA5 klimatolojisi + PVGIS SARAH3 serisi + PVGIS TMY karmasi.

Her kaynak ayni PV zincirinden gecer (PVGIS serisi duzlem ici bilesenlerden). Sonuc:
 - aylik beklenen uretim (liste MWp ve kalibre), P50/P90 (yillar arasi dagilim)
 - gelecek N ay icin saatlik 'tipik' profil (ay x yerel saat ortalamasi, karma aylik toplama olceklenmis)
 - opsiyonel: ECMWF SEAS5 mevsimsel GHI anomalisi ile gostergesel duzeltme
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import PATHS, normalize_weights, region_pv, rnd
from .pvmodel import run_pv, run_pv_from_poa
from .sources import openmeteo as om
from .sources import pvgis


def _monthly_by_year(p: pd.Series, tz: str) -> pd.DataFrame:
    loc = p.index.tz_localize("UTC").tz_convert(tz).tz_localize(None)
    df = pd.DataFrame({"yil": loc.year, "ay": loc.month, "mwh": p.to_numpy()})
    return df.groupby(["yil", "ay"])["mwh"].sum(min_count=24 * 20).unstack("ay")


def _diurnal(p: pd.Series, tz: str) -> pd.DataFrame:
    loc = p.index.tz_localize("UTC").tz_convert(tz).tz_localize(None)
    df = pd.DataFrame({"ay": loc.month, "saat": loc.hour, "mw": p.to_numpy()})
    return df.groupby(["ay", "saat"])["mw"].mean().unstack("saat")


def build_longterm(cfg: dict, regions: pd.DataFrame, k_ref: float, mk: pd.DataFrame | None = None,
                   verbose: bool = True, period: tuple | None = None) -> dict:
    tz = cfg["local_tz"]
    lt = cfg["longterm"]
    y0, y1 = lt["era5_years"]
    p0, p1 = lt["pvgis_years"]
    fleet = {"era5_clim": None, "pvgis_series": None, "pvgis_tmy": None}
    era5_ghi_month = pd.Series(0.0, index=range(1, 13))
    seas_ratio_num = None
    w = regions.set_index("region")["weight"]
    for _, r in regions.iterrows():
        rid = int(r["region"])
        pv = region_pv(cfg, rid)
        if verbose:
            print(f"  Bolge {rid}: ERA5 {y0}-{y1}, PVGIS {p0}-{p1}, TMY")
        e5 = om.archive(r["lat"], r["lon"], f"{y0}-01-01", f"{y1}-12-31", model="era5")
        pe = run_pv(e5, r["lat"], r["lon"], r["mwp"], pv)["p_ac"]
        fleet["era5_clim"] = pe if fleet["era5_clim"] is None else fleet["era5_clim"].add(pe, fill_value=0)
        gm = e5["ghi"].groupby(e5.index.month).mean()
        era5_ghi_month = era5_ghi_month + gm.reindex(range(1, 13)).fillna(0) * w[rid]
        try:
            ps = pvgis.series_poa(r["lat"], r["lon"], p0, p1, pv["tilt_deg"], pv["azimuth_deg"])
            pp = run_pv_from_poa(ps["poa_beam"], ps["poa_diff"], ps["poa_gnd"], ps["temp"], ps["wind"],
                                 ps.index, r["lat"], r["lon"], r["mwp"], pv)["p_ac"]
            fleet["pvgis_series"] = pp if fleet["pvgis_series"] is None else fleet["pvgis_series"].add(pp, fill_value=0)
        except Exception as ex:  # noqa: BLE001
            print(f"   PVGIS seri alinamadi: {ex}")
        try:
            tm = pvgis.tmy(r["lat"], r["lon"])
            pt = run_pv(tm, r["lat"], r["lon"], r["mwp"], pv)["p_ac"]
            fleet["pvgis_tmy"] = pt if fleet["pvgis_tmy"] is None else fleet["pvgis_tmy"].add(pt, fill_value=0)
        except Exception as ex:  # noqa: BLE001
            print(f"   PVGIS TMY alinamadi: {ex}")
        if lt.get("use_seasonal"):
            s = om.seasonal_monthly_ghi(r["lat"], r["lon"])
            if s is not None:
                clim = e5["ghi"].groupby(e5.index.month).mean()
                ratio = s["ghi_mean_wm2"] / s.index.month.map(clim).to_numpy()
                seas_ratio_num = ratio * w[rid] if seas_ratio_num is None else seas_ratio_num.add(ratio * w[rid], fill_value=0)

    # Aylik tablolar
    tab = {}
    years = {}
    for src, p in fleet.items():
        if p is None:
            continue
        if src == "pvgis_tmy":
            m = _monthly_by_year(p, tz)
            tab[src] = m.mean(axis=0)
        else:
            m = _monthly_by_year(p, tz).dropna(how="all")
            years[src] = m
            tab[src] = m.mean(axis=0)
    clim = pd.DataFrame(tab)
    clim.index.name = "ay"
    wts = normalize_weights({k: v for k, v in lt["source_weights"].items() if k in clim})
    clim["karma_liste_mwh"] = sum(clim[k] * v for k, v in wts.items())
    pooled = pd.concat(list(years.values())) if years else None
    if pooled is not None:
        rel = pooled.div(pooled.mean(axis=0), axis=1)
        clim["p90_carpan"] = rel.quantile(0.10).reindex(clim.index)
        clim["p10_carpan"] = rel.quantile(0.90).reindex(clim.index)
        clim["yil_sayisi"] = pooled.notna().sum().reindex(clim.index)
    kmon = mk.set_index("ay")["k_kullanilan"] if mk is not None else pd.Series(k_ref, index=range(1, 13))
    clim["k_ay"] = clim["ay"].map(kmon) if "ay" in clim else clim.index.map(kmon)
    clim["karma_kalibre_sabitk_mwh"] = clim["karma_liste_mwh"] * k_ref
    clim["karma_kalibre_p50_mwh"] = clim["karma_liste_mwh"] * clim["k_ay"]
    clim["karma_kalibre_p90_mwh"] = clim["karma_kalibre_p50_mwh"] * clim["p90_carpan"]
    clim["karma_kalibre_p10_mwh"] = clim["karma_kalibre_p50_mwh"] * clim["p10_carpan"]
    mwp = float(regions["mwp"].sum())
    clim["SY_liste_kwh_kwp"] = clim["karma_liste_mwh"] / mwp
    clim = clim.reset_index()

    # Gelecek N ay
    if period is None:
        now = pd.Timestamp.now(tz).tz_localize(None)
        first = (now + pd.offsets.MonthBegin(1)).normalize()
        months = pd.date_range(first, periods=lt["horizon_months"], freq="MS")
    else:
        months = pd.date_range(period[0].to_period("M").to_timestamp(), period[1], freq="MS")
    fut = pd.DataFrame({"ay_basi": months, "ay": months.month})
    fut = fut.merge(clim, on="ay", how="left")
    fut["gun"] = months.days_in_month
    if seas_ratio_num is not None:
        sr = seas_ratio_num.copy()
        sr.index = pd.DatetimeIndex(sr.index).to_period("M").to_timestamp()
        fut["seas5_ghi_orani"] = fut["ay_basi"].map(sr)
        fut["seas5_gostergesel_mwh"] = fut["karma_kalibre_p50_mwh"] * fut["seas5_ghi_orani"]

    # Saatlik tipik profil: ERA5 gun-ici sekli, karma aylik toplama olceklenir
    diur = _diurnal(fleet["era5_clim"], tz)
    rows = []
    for _, fr in fut.iterrows():
        days = pd.date_range(fr["ay_basi"], periods=int(fr["gun"]), freq="D")
        prof = diur.loc[int(fr["ay"])]
        scale = fr["karma_liste_mwh"] / (prof.sum() * len(days)) if prof.sum() > 0 else 0
        for d in days:
            for h in range(24):
                v = prof.iloc[h] * scale
                rows.append((d + pd.Timedelta(hours=h), v, v * fr["k_ay"]))
    hourly = pd.DataFrame(rows, columns=["time_local", "beklenen_liste_mw", "beklenen_kalibre_mw"])
    if period is not None:
        hourly = hourly[(hourly["time_local"] >= period[0]) & (hourly["time_local"] < period[1] + pd.Timedelta(days=1))]
    return {"climatology": clim, "future": fut, "hourly": hourly, "weights": wts,
            "years": {k: v.reset_index() for k, v in years.items()}}


def save_longterm(lt: dict, csv_kw: dict) -> None:
    out = PATHS["out"]
    lt["climatology"].pipe(rnd, 3).to_csv(out / "uzun_vade_klimatoloji_aylik.csv", index=False, **csv_kw)
    lt["future"].pipe(rnd, 3).to_csv(out / "uzun_vade_gelecek_aylar.csv", index=False, **csv_kw)
    lt["hourly"].pipe(rnd, 2).to_csv(out / "uzun_vade_tipik_saatlik.csv", index=False, **csv_kw)
