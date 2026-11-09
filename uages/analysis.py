"""Gerceklesen performans analizi: GPEE saatlik vs hava tabanli model.

Ciktilar (outputs/):
  gecmis_saatlik.csv, gecmis_gunluk.csv, gecmis_aylik.csv, hava_sinifi_performans.csv,
  sicaklik_performans.csv, bolge_aylik_model.csv, santral_aylik_model.csv, tahmin_dogrulama.csv
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import calibrate as cal
from . import weather
from .config import PATHS, region_pv, rnd
from .countries import get_adapter
from .pvmodel import run_fleet
from .solar import interval_solar_position


def _fleet_table(res: dict, regions: pd.DataFrame, prefix: str) -> pd.DataFrame:
    f = res["fleet"]
    return pd.DataFrame({f"{prefix}_mw": f["p_ac"], f"{prefix}_ghi": f["ghi"],
                         f"{prefix}_poa": f["poa"], f"{prefix}_tcell": f["tcell"]})


def _weighted(wx_by_region: dict, regions: pd.DataFrame, col: str) -> pd.Series:
    w = regions.set_index("region")["weight"]
    s, ws = None, None
    for rid, df in wx_by_region.items():
        if col not in df:
            continue
        v = df[col]
        ok = v.notna().astype(float) * w[rid]
        s = v.fillna(0) * w[rid] if s is None else s.add(v.fillna(0) * w[rid], fill_value=0)
        ws = ok if ws is None else ws.add(ok, fill_value=0)
    return s / ws.replace(0, np.nan) if s is not None else pd.Series(dtype=float)


def _fleet_extraterrestrial(idx: pd.DatetimeIndex, regions: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    g0, el = 0.0, 0.0
    for _, r in regions.iterrows():
        sp = interval_solar_position(idx, r["lat"], r["lon"])
        g0 = g0 + (sp["e0n"] * sp["cosz"].clip(lower=0)) * r["weight"]
        el = el + (90 - sp["zenith"]) * r["weight"]
    return pd.Series(np.asarray(g0), index=idx), pd.Series(np.asarray(el), index=idx)


def metrics(pred: pd.Series, act: pd.Series, mask: pd.Series, norm: float) -> dict:
    ok = mask & pred.notna() & act.notna()
    e = (pred - act)[ok]
    if len(e) == 0:
        return {}
    return {"n_saat": int(ok.sum()), "MAE_MW": float(e.abs().mean()), "RMSE_MW": float(np.sqrt((e ** 2).mean())),
            "Bias_MW": float(e.mean()), "nMAE_pct": float(e.abs().mean() / norm * 100),
            "nRMSE_pct": float(np.sqrt((e ** 2).mean()) / norm * 100)}


def build_history(cfg: dict, verbose: bool = True) -> dict:
    tz = cfg["local_tz"]
    ad = get_adapter(cfg)
    regions = ad.load_regions(cfg)
    g = ad.load_target(cfg)
    start = pd.Timestamp(cfg["history"]["start"])
    # Depo daha eski yillari da icerebilir (tools/backfill_gpee.py); analiz donemi config'ten gelir
    g = g[g["time_local"] >= start].reset_index(drop=True)
    # Bitis: deponun son gunu, ama en gec dun (UTC). Depo yarinin resmi tahminini de tasiyabilir (HU: MAVIR D+1/D+2);
    # Open-Meteo arsivi gelecek tarihi reddeder (400). UA'da GPEE gec yayimladigi icin bu sinir hic devreye girmez.
    dun = pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    end = min(g["time_utc"].max().normalize(), dun)
    wx = weather.history_weather(regions, start, end, cfg, verbose=verbose)

    runs = {}
    for src in ["blend", "era5", "om_archive", "om_historical_forecast"]:
        if wx.get(src):
            runs[src] = run_fleet(wx[src], regions, cfg, region_pv)

    df = g.set_index("time_utc").sort_index()
    df = df[~df.index.duplicated()]
    idx = df.index
    df["model_mw"] = runs["blend"]["fleet"]["p_ac"].reindex(idx)
    for src, lab in [("era5", "model_era5_mw"), ("om_archive", "model_arsiv_mw"),
                     ("om_historical_forecast", "model_gunoncesi_mw")]:
        if src in runs:
            df[lab] = runs[src]["fleet"]["p_ac"].reindex(idx)
    fb = runs["blend"]["fleet"].reindex(idx)
    df["ghi"], df["poa"], df["tcell"] = fb["ghi"], fb["poa"], fb["tcell"]
    df["temp"] = _weighted(wx["blend"], regions, "temp").reindex(idx)
    df["cloud"] = _weighted(wx["blend"], regions, "cloud").reindex(idx)
    df["wind"] = _weighted(wx["blend"], regions, "wind").reindex(idx)
    df["snow"] = _weighted(wx["blend"], regions, "snow").reindex(idx)
    g0, el = _fleet_extraterrestrial(idx, regions)
    df["g0h"], df["elev"] = g0, el
    df["kt_h"] = (df["ghi"] / df["g0h"].where(df["g0h"] > 50)).clip(0, 1.2)
    df = df.reset_index()

    # Zaman hizalama kontrolu
    lag = cal.best_lag(df.set_index("time_utc")["actual_mw"], df.set_index("time_utc")["model_mw"])

    # Kalibrasyon (reanaliz modeli): once kaba k, sonra model tabanli kisit bayragi, sonra yeniden k
    k1 = cal.rolling_k(df, cfg)
    df["flag_curtail_model"] = cal.flag_curtailment(df, k1["k_roll"].ffill().bfill(), cfg)
    k = cal.rolling_k(df, cfg)
    all_days = pd.date_range(df["time_local"].min().normalize(), df["time_local"].max().normalize(), freq="D")
    k_roll = k["k_roll"].reindex(all_days).ffill().bfill()
    df["k"] = df["time_local"].dt.normalize().map(k_roll).astype(float)
    k_now = float(k_roll.dropna().iloc[-1])
    m = cal.training_mask(df, cfg)
    recent = m & (df["time_local"] > df["time_local"].max() - pd.Timedelta(days=90))
    k_ref = float(df.loc[recent, "actual_mw"].sum() / df.loc[recent, "model_mw"].sum())
    mk = cal.monthly_k(df, cfg)
    night = cal.night_baseline(df)
    mwp_list = float(regions["mwp"].sum())
    mwp_eff = mwp_list * k_ref
    df["model_kalibre_mw"] = np.where(df["elev"] < -3, night, df["model_mw"] * df["k"])

    # Tahmin kalibrasyonu: tahmin-hava modeli (Open-Meteo gecmis tahmin) uzerinde, yuruyen pencere
    fc_cal, wf_start = {}, None
    if "model_gunoncesi_mw" in df:
        df["model_fc_mw"] = df["model_gunoncesi_mw"]
        if "om_historical_forecast" in wx and wx["om_historical_forecast"]:
            ghi_fc = _weighted(wx["om_historical_forecast"], regions, "ghi").reindex(pd.DatetimeIndex(df["time_utc"]))
            df["kt_fc"] = (ghi_fc.to_numpy() / df["g0h"].where(df["g0h"] > 50).to_numpy()).clip(0, 1.2)
        wf_start = str((df["time_local"].min() + pd.Timedelta(days=cfg["calibration"]["shape_window_days"])).date())
        df["model_gunoncesi_kalibre_mw"] = cal.walk_forward(df, cfg, wf_start, "model_fc_mw", night).to_numpy()
        last_actual = df.loc[df["actual_mw"].notna(), "time_local"].max().normalize()
        fc_cal = cal.fit(df, cfg, last_actual, "model_fc_mw", lag_days=0)

    # --- Dogrulama metrikleri (gunduz, kisitsiz saatler)
    day_mask = (df["elev"] > 0) & ~df["flag_curtail_model"] & ~df["flag_curtail_hour"].astype(bool)
    if wf_start:
        day_mask &= df["time_local"] >= pd.Timestamp(wf_start)
    norm = float(df.loc[day_mask, "actual_mw"].mean())
    val = []
    for lab, col in [(ad.benchmark_label_long, "forecast_mw"),
                     ("Model · tahmin havası (Open-Meteo geçmiş tahmin) + yürüyen kalibrasyon, 2 gün gecikmeli", "model_gunoncesi_kalibre_mw"),
                     ("Model · gerçekleşen hava (ERA5/arşiv karması), yalnız kayan k (saat/bulut düzeltmesiz)", "model_kalibre_mw")]:
        if col in df:
            mt = metrics(df[col], df["actual_mw"], day_mask, norm)
            if mt:
                val.append({"yontem": lab, **mt})
    val = pd.DataFrame(val)

    # --- Gunluk
    df["date"] = df["time_local"].dt.normalize()
    agg = df.groupby("date").agg(
        saat=("actual_mw", "size"),
        gerceklesen_mwh=("actual_mw", lambda s: s.sum(min_count=18)),
        gpee_tahmin_mwh=("forecast_mw", "sum"),
        model_liste_mwh=("model_mw", "sum"),
        model_kalibre_mwh=("model_kalibre_mw", "sum"),
        gunoncesi_model_mwh=("model_gunoncesi_kalibre_mw", "sum"),
        H_ghi_kwhm2=("ghi", lambda s: s.sum() / 1000),
        H_poa_kwhm2=("poa", lambda s: s.sum() / 1000),
        H0_kwhm2=("g0h", lambda s: s.sum() / 1000),
        sicaklik_ort=("temp", "mean"), sicaklik_max=("temp", "max"),
        bulut_ort_pct=("cloud", "mean"), kar_m=("snow", "max"),
        pik_gerceklesen_mw=("actual_mw", "max"),
        kisit_saat_gpee=("flag_curtail_hour", "sum"), kisit_saat_model=("flag_curtail_model", "sum"),
        kisit_gun_gpee=("flag_curtail_day", "max"),
    )
    agg["kt"] = agg["H_ghi_kwhm2"] / agg["H0_kwhm2"]
    wc = cfg["weather_classes"]
    agg["hava_sinifi"] = np.select([agg["kt"] >= wc["clear_kt"], agg["kt"] < wc["cloudy_kt"]],
                                   ["Acik", "Kapali"], "Parcali")
    agg["SY_gercek_liste"] = agg["gerceklesen_mwh"] / mwp_list          # kWh/kWp (liste MWp)
    agg["SY_gercek_etkin"] = agg["gerceklesen_mwh"] / mwp_eff           # kWh/kWp (etkin MWp)
    agg["SY_model_liste"] = agg["model_liste_mwh"] / mwp_list
    agg["PR_liste"] = agg["gerceklesen_mwh"] / (agg["H_poa_kwhm2"] * mwp_list)
    agg["PR_etkin"] = agg["gerceklesen_mwh"] / (agg["H_poa_kwhm2"] * mwp_eff)
    agg["PR_model"] = agg["model_liste_mwh"] / (agg["H_poa_kwhm2"] * mwp_list)
    agg["PI"] = agg["gerceklesen_mwh"] / agg["model_liste_mwh"]
    agg["PI_norm"] = agg["PI"] / k_ref
    agg["kar_suphesi"] = (agg["kar_m"] > 0.02) & (agg["PI_norm"] < 0.7)
    agg["gpee_tahmin_hata_pct"] = (agg["gpee_tahmin_mwh"] / agg["gerceklesen_mwh"] - 1) * 100
    agg["gunoncesi_hata_pct"] = (agg["gunoncesi_model_mwh"] / agg["gerceklesen_mwh"] - 1) * 100
    daily = agg.reset_index()

    # --- Aylik (tam gunler)
    dd = daily[daily["saat"] >= 23].copy()
    dd["ay"] = dd["date"].dt.to_period("M").dt.to_timestamp()
    mon = dd.groupby("ay").agg(gun=("date", "size"), gerceklesen_mwh=("gerceklesen_mwh", "sum"),
                               gpee_tahmin_mwh=("gpee_tahmin_mwh", "sum"), model_liste_mwh=("model_liste_mwh", "sum"),
                               H_ghi_kwhm2=("H_ghi_kwhm2", "sum"), H_poa_kwhm2=("H_poa_kwhm2", "sum"),
                               H0_kwhm2=("H0_kwhm2", "sum"), sicaklik_ort=("sicaklik_ort", "mean"),
                               acik_gun=("hava_sinifi", lambda s: (s == "Acik").sum()),
                               kapali_gun=("hava_sinifi", lambda s: (s == "Kapali").sum()),
                               kisit_gun=("kisit_gun_gpee", "sum"), pik_mw=("pik_gerceklesen_mw", "max"))
    mon["kt"] = mon["H_ghi_kwhm2"] / mon["H0_kwhm2"]
    mon["SY_gercek_liste"] = mon["gerceklesen_mwh"] / mwp_list
    mon["SY_gercek_etkin"] = mon["gerceklesen_mwh"] / mwp_eff
    mon["SY_model_liste"] = mon["model_liste_mwh"] / mwp_list
    mon["PR_liste"] = mon["gerceklesen_mwh"] / (mon["H_poa_kwhm2"] * mwp_list)
    mon["PR_etkin"] = mon["gerceklesen_mwh"] / (mon["H_poa_kwhm2"] * mwp_eff)
    mon["PR_model"] = mon["model_liste_mwh"] / (mon["H_poa_kwhm2"] * mwp_list)
    mon["k_ay"] = mon["gerceklesen_mwh"] / mon["model_liste_mwh"]
    mon["PI_norm"] = mon["k_ay"] / k_ref
    mon["gpee_tahmin_sapma_pct"] = (mon["gpee_tahmin_mwh"] / mon["gerceklesen_mwh"] - 1) * 100
    monthly = mon.reset_index()

    # --- Hava sinifina gore performans (kisitsiz tam gunler)
    ok = dd[(dd["kisit_saat_gpee"] == 0) & (dd["kisit_saat_model"] == 0) & dd["gerceklesen_mwh"].notna()]
    wcls = ok.groupby("hava_sinifi").agg(gun=("date", "size"), kt_ort=("kt", "mean"),
                                         SY_gercek_liste=("SY_gercek_liste", "mean"),
                                         SY_model_liste=("SY_model_liste", "mean"),
                                         PR_etkin=("PR_etkin", "median"), PI_norm=("PI_norm", "median"),
                                         gpee_mutlak_hata_pct=("gpee_tahmin_hata_pct", lambda s: s.abs().median()),
                                         gunoncesi_mutlak_hata_pct=("gunoncesi_hata_pct", lambda s: s.abs().median()))
    wcls = wcls.reindex(["Acik", "Parcali", "Kapali"]).reset_index()

    # --- Sicaklik etkisi (acik gunler)
    clear = ok[ok["hava_sinifi"] == "Acik"].copy()
    bins = [-30, 0, 10, 20, 25, 30, 35, 50]
    clear["sicaklik_araligi"] = pd.cut(clear["sicaklik_max"], bins).astype(str)
    tbin = clear.groupby("sicaklik_araligi", sort=False).agg(gun=("date", "size"),
                                                             PR_etkin=("PR_etkin", "median"),
                                                             PR_model=("PR_model", "median"),
                                                             PI_norm=("PI_norm", "median")).reset_index()

    # --- Bolge ve santral bazli model uretimi (kalibre, dagitilmis)
    rows = []
    for rid, rdf in runs["blend"]["regions"].items():
        s = rdf["p_ac"].copy()
        loc = s.index.tz_localize("UTC").tz_convert(tz).tz_localize(None)
        kk = pd.Series(loc.normalize(), index=s.index).map(k_roll).astype(float).to_numpy()
        mm = pd.DataFrame({"ay": loc.to_period("M").to_timestamp(), "liste": s.to_numpy(), "kal": s.to_numpy() * kk})
        mm = mm[mm["ay"] <= daily["date"].max()]
        a = mm.groupby("ay").agg(model_liste_mwh=("liste", "sum"), model_kalibre_mwh=("kal", "sum")).reset_index()
        a["region"] = rid
        rows.append(a)
    reg_m = pd.concat(rows).merge(regions[["region", "mwp", "mw", "lat", "lon"]], on="region")
    reg_m["SY_model_kwh_kwp"] = reg_m["model_liste_mwh"] / reg_m["mwp"]
    plants = ad.load_plants(cfg)
    pm = plants.merge(regions[["region", "mwp"]].rename(columns={"mwp": "region_mwp"}), on="region", how="left")
    pm["pay"] = pm["mwp"] / pm["region_mwp"]
    piv = reg_m.pivot_table(index="region", columns="ay", values="model_kalibre_mwh")
    plant_rows = pm[[c for c in ["plant", "phase", "oblast", "region", "mw", "mwp", "Placeholder_Flag", "Frontline_Flag", "pay"]
                      if c in pm]].copy()
    for col in piv.columns:
        plant_rows[col.strftime("%Y-%m") + "_MWh"] = pm["region"].map(piv[col]) * pm["pay"]
    ycols = [c for c in plant_rows.columns if c.endswith("_MWh")]
    plant_rows["toplam_MWh"] = plant_rows[ycols].sum(axis=1)
    plant_rows["SY_kwh_kwp_kalibre"] = plant_rows["toplam_MWh"] / plant_rows["mwp"]

    summary = {
        "mwp_liste": mwp_list, "mw_liste": float(regions["mw"].sum()), "k_ref": k_ref, "k_now": k_now,
        "mwp_etkin": mwp_eff, "gece_net_mw": night, "zaman_kaymasi_korelasyon": lag,
        "tahmin_kalibrasyonu": fc_cal, "yuruyen_dogrulama_baslangic": wf_start, "donem": [str(df["time_local"].min()), str(df["time_local"].max())],
        "son_gerceklesen": str(df.loc[df["actual_mw"].notna(), "time_local"].max()),
        "maks_gerceklesen_mw": float(df["actual_mw"].max()),
    }
    return {"hourly": df, "daily": daily, "monthly": monthly, "weather_class": wcls, "temp_bins": tbin,
            "region_monthly": reg_m, "plants": plant_rows, "validation": val, "k": k, "summary": summary,
            "regions": regions, "monthly_k": mk,
            "calib": {"fc": fc_cal, "night": night, "k_ref": k_ref, "k_now": k_now, "mwp_list": mwp_list}}


def save_history(h: dict, csv_kw: dict) -> None:
    out = PATHS["out"]
    cols = ["time_local", "time_utc", "actual_mw", "forecast_mw", "model_mw", "model_kalibre_mw",
            "model_gunoncesi_kalibre_mw", "model_era5_mw", "model_arsiv_mw", "ghi", "poa", "temp", "cloud", "wind",
            "kt_h", "elev", "k", "flag_curtail_hour", "flag_curtail_model"]
    h["hourly"][[c for c in cols if c in h["hourly"]]].pipe(rnd, 3).to_csv(out / "gecmis_saatlik.csv", index=False, **csv_kw)
    h["daily"].pipe(rnd, 4).to_csv(out / "gecmis_gunluk.csv", index=False, **csv_kw)
    h["monthly"].pipe(rnd, 4).to_csv(out / "gecmis_aylik.csv", index=False, **csv_kw)
    h["weather_class"].pipe(rnd, 4).to_csv(out / "hava_sinifi_performans.csv", index=False, **csv_kw)
    h["temp_bins"].pipe(rnd, 4).to_csv(out / "sicaklik_performans.csv", index=False, **csv_kw)
    h["region_monthly"].pipe(rnd, 3).to_csv(out / "bolge_aylik_model.csv", index=False, **csv_kw)
    h["plants"].pipe(rnd, 2).to_csv(out / "santral_aylik_model.csv", index=False, **csv_kw)
    h["validation"].pipe(rnd, 3).to_csv(out / "tahmin_dogrulama.csv", index=False, **csv_kw)
    h["monthly_k"].pipe(rnd, 4).to_csv(out / "kalibrasyon_aylik_k.csv", index=False, **csv_kw)
