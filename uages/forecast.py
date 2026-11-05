"""7 gunluk saatlik uretim tahmini (coklu model + karma + ensemble bandi) ve bolge hava durumu.

Kalibre tahmin = model(liste MWp) x k x saat_sekli[yerel saat] x kt_faktoru[berraklik sinifi]; gece = gece net tuketim.
calibration.mode (config.json):
  "mevcut" -> katsayilar analysis.build_history icinde Open-Meteo gecmis tahmin (best_match) modeliyle fit edilir,
              tum ufuklara ayni katsayi uygulanir.
  "ufuk"   -> her ufuk gunu (D+1..D+7) icin ayri k / sekil / kt (optimize.refresh -> outputs/kalibrasyon_ufuk.json),
              ayni hava karmasinin o ufuktaki arsiv tahminleriyle fit edilir. Dosya yoksa ya da 10 gunden eskiyse
              otomatik olarak "mevcut"a duser.
Bant: ECMWF ensemble uyelerinin GHI oranlari (q_lo, q_hi) bolge bazinda karma modele uygulanir.
(Bolgeler arasi tam korelasyon varsayimi -> bant muhafazakar genistir.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import calibrate as cal
from . import weather
from .config import PATHS, region_pv, rnd
from .pvmodel import aggregate_fleet, run_pv


def build_forecast(cfg: dict, calib: dict, regions: pd.DataFrame, verbose: bool = True) -> dict:
    tz = cfg["local_tz"]
    wx = weather.forecast_weather(regions, cfg, verbose=verbose)
    models = list(cfg["forecast"]["model_weights"].keys())
    fcal, night = calib["fc"], calib["night"]
    k = fcal["k"]  # mevcut yontemin k'si (ufuk modunda yalnizca bilgi amacli)

    per_model = {}
    reg_blend = {}
    for m in models + ["blend"]:
        res = {}
        for _, r in regions.iterrows():
            rid = int(r["region"])
            if rid in wx.get(m, {}):
                res[rid] = run_pv(wx[m][rid], r["lat"], r["lon"], r["mwp"], region_pv(cfg, rid))
        if res:
            per_model[m] = aggregate_fleet(res, regions)
            if m == "blend":
                reg_blend = res

    idx = per_model["blend"].index
    loc = idx.tz_localize("UTC").tz_convert(tz).tz_localize(None)
    wreg = regions.set_index("region")["weight"]
    elev = sum(reg_blend[r]["elev"].reindex(idx).to_numpy() * wreg[r] for r in reg_blend) / sum(wreg[r] for r in reg_blend)
    g0h = sum(reg_blend[r]["g0h"].reindex(idx).to_numpy() * wreg[r] for r in reg_blend) / sum(wreg[r] for r in reg_blend)
    ghi_fleet = per_model["blend"]["ghi"].reindex(idx).to_numpy()
    kt = np.clip(ghi_fleet / np.where(g0h > 50, g0h, np.nan), 0, 1.2)
    # Saatlik toplam kalibrasyon carpani (k x saat sekli x kt) -> filo, model, bant ve bolge hesaplarinda ayni
    kfac, mode = calibration_factor(cfg, fcal, loc, kt)

    def calibrate(p):
        v = p.reindex(idx).to_numpy() * kfac
        return np.where(elev < -3, night, v)

    out = pd.DataFrame({"time_utc": idx, "time_local": loc})
    for m in models:
        if m in per_model:
            out[f"{m}_mw"] = calibrate(per_model[m]["p_ac"])
    out["tahmin_p50_mw"] = calibrate(per_model["blend"]["p_ac"])
    out["model_liste_mw"] = per_model["blend"]["p_ac"].reindex(idx).to_numpy()

    # Ensemble bandi (bolge bazli)
    lo = pd.Series(0.0, index=idx)
    hi = pd.Series(0.0, index=idx)
    for rid, rdf in reg_blend.items():
        p = rdf["p_ac"].reindex(idx)
        er = wx["ens_ratio"].get(rid)
        cap = float(regions.loc[regions.region == rid, "mwp"].iloc[0]) / cfg["pv"]["dc_ac_ratio"]
        if er is None:
            ql = qh = pd.Series(1.0, index=idx)
        else:
            er = er.reindex(idx)
            ql, qh = er["q_lo"].fillna(1.0), er["q_hi"].fillna(1.0)
        lo = lo + (p * ql).clip(upper=cap).fillna(0)
        hi = hi + (p * qh).clip(upper=cap).fillna(0)
    out["tahmin_p10_mw"] = np.where(elev < -3, night, lo.to_numpy() * kfac)
    out["tahmin_p90_mw"] = np.where(elev < -3, night, hi.to_numpy() * kfac)
    mcols = [f"{m}_mw" for m in models if f"{m}_mw" in out]
    out["model_min_mw"] = out[mcols].min(axis=1)
    out["model_max_mw"] = out[mcols].max(axis=1)
    out["gunes_yuksekligi"] = elev
    out["kt"] = kt

    # Filo hava durumu (MWp agirlikli) + bolge hava
    w = regions.set_index("region")["weight"]
    for v in ["ghi", "temp", "cloud", "wind"]:
        acc = sum(wx["blend"][rid][v].reindex(idx).fillna(0) * w[rid] for rid in wx["blend"] if v in wx["blend"][rid])
        out[v] = acc.to_numpy()
    reg_rows = []
    for rid, df in wx["blend"].items():
        d = df.reindex(idx)
        reg_rows.append(pd.DataFrame({
            "time_utc": idx, "time_local": loc, "region": rid,
            "ghi": d["ghi"].to_numpy(), "temp": d["temp"].to_numpy(), "cloud": d["cloud"].to_numpy() if "cloud" in d else np.nan,
            "wind": d["wind"].to_numpy(),
            "uretim_mw": np.where(reg_blend[rid]["elev"].reindex(idx) < -3, 0,
                                   reg_blend[rid]["p_ac"].reindex(idx).to_numpy() * kfac),
        }))
    reg_df = pd.concat(reg_rows, ignore_index=True)

    now_utc = pd.Timestamp.now("UTC").tz_localize(None).floor("h")
    out["gecmis"] = out["time_utc"] < now_utc
    today = pd.Timestamp.now(tz).tz_localize(None).normalize()
    days = pd.date_range(today, periods=cfg["forecast"]["days"], freq="D")
    dsel = out[out["time_local"].dt.normalize().isin(days)]
    daily = dsel.groupby(dsel["time_local"].dt.normalize()).agg(
        saat=("tahmin_p50_mw", lambda s: int(s.notna().sum())),
        p50_mwh=("tahmin_p50_mw", lambda s: s.clip(lower=0).sum()),
        p10_mwh=("tahmin_p10_mw", lambda s: s.clip(lower=0).sum()),
        p90_mwh=("tahmin_p90_mw", lambda s: s.clip(lower=0).sum()),
        pik_mw=("tahmin_p50_mw", "max"), ghi_kwhm2=("ghi", lambda s: s.sum() / 1000),
        sicaklik_max=("temp", "max"), sicaklik_min=("temp", "min"), bulut_ort=("cloud", "mean"),
        ruzgar_max=("wind", "max"))
    daily = daily[daily["saat"] >= 20]
    daily["SY_kwh_kwp_liste"] = daily["p50_mwh"] / float(regions["mwp"].sum())
    out["kalibrasyon_carpani"] = kfac
    return {"hourly": out, "regions": reg_df, "daily": daily.reset_index().rename(columns={"time_local": "date"}),
            "issued_utc": str(now_utc), "k": k, "kalibrasyon_modu": mode}


def calibration_factor(cfg: dict, fcal: dict, loc: pd.DatetimeIndex, kt: np.ndarray) -> tuple[np.ndarray, str]:
    """Saatlik k x saat_sekli x kt_faktoru ve kullanilan mod ("mevcut" | "ufuk").
    ufuk: hedef yerel gun - bugun (Kyiv) = ufuk gunu; gecmis saatler ve bugun D+1, 7'den uzak olanlar D+7 katsayisini alir.
    Bir ufkun katsayisi yoksa (ör. veri eksik) en yakin daha kisa ufuk kullanilir."""
    b = cal.kt_bin(kt)
    if cfg["calibration"].get("mode", "mevcut") == "ufuk":
        from .optimize import load_ufuk
        u = load_ufuk(cfg)
        if u is None:
            print("  UYARI: kalibrasyon_ufuk.json yok ya da eski; mevcut yontemle devam ediliyor")
        else:
            K, S, F = np.full(8, np.nan), np.ones((8, 24)), np.ones((8, len(u["kt_bins"]) - 1))
            SW = np.full(8, np.nan)
            for L in range(1, 8):
                c = u["ufuklar"].get(str(L))
                if c is None:  # eksik ufuk -> bir onceki
                    K[L], S[L], F[L], SW[L] = K[L - 1], S[L - 1], F[L - 1], SW[L - 1]
                else:
                    K[L], S[L], F[L] = c["k"], c["shape"], c["kt_factor"]
                    SW[L] = c.get("mevsim_sw", np.nan)
            if np.isfinite(K[1:]).all():
                today = pd.Timestamp.now(cfg["local_tz"]).tz_localize(None).normalize()
                lead = np.clip((pd.DatetimeIndex(loc).normalize() - today).days.to_numpy(), 1, 7)
                v = K[lead] * S[lead, loc.hour] * F[lead, b]
                # Mevsimsel k: k penceresi ile hedef gun arasindaki mevsimsel degisim (ör. Ekim -> Kasim dususu)
                if cfg["calibration"].get("season_correction") and u.get("mevsim_coef") and np.isfinite(SW[1:]).all():
                    from .optimize import season_factor
                    return v * season_factor(np.asarray(u["mevsim_coef"]), loc) / SW[lead], "ufuk+mevsim"
                return v, "ufuk"
            print("  UYARI: kalibrasyon_ufuk.json'da D+1 yok; mevcut yontemle devam ediliyor")
    fac = np.asarray(fcal["shape"])[loc.hour] * np.asarray(fcal["kt_factor"])[b]
    return fcal["k"] * fac, "mevcut"


def attach_actuals(fc: dict, gpee: pd.DataFrame) -> None:
    """Tahmin penceresindeki gecmis saatlere GPEE gerceklesen/tahmin ekler (dogrulama grafigi icin)."""
    g = gpee.set_index("time_utc")[["actual_mw", "forecast_mw"]].rename(
        columns={"actual_mw": "gerceklesen_mw", "forecast_mw": "gpee_tahmin_mw"})
    h = fc["hourly"].set_index("time_utc").join(g, how="left")
    fc["hourly"] = h.reset_index()


def save_forecast(fc: dict, csv_kw: dict) -> None:
    out = PATHS["out"]
    fc["hourly"].pipe(rnd, 2).to_csv(out / "tahmin_7gun_saatlik.csv", index=False, **csv_kw)
    fc["regions"].pipe(rnd, 2).to_csv(out / "tahmin_7gun_bolge_saatlik.csv", index=False, **csv_kw)
    fc["daily"].pipe(rnd, 3).to_csv(out / "tahmin_7gun_gunluk.csv", index=False, **csv_kw)
    # Arsiv: her verilen tahmin saklanir -> ileride gercek D+1..D+7 isabeti olculebilir
    arc = out / "arsiv"
    arc.mkdir(exist_ok=True)
    stamp = pd.Timestamp(fc["issued_utc"]).strftime("%Y%m%d_%H")
    cols = ["time_utc", "time_local", "tahmin_p50_mw", "tahmin_p10_mw", "tahmin_p90_mw", "model_liste_mw", "ghi", "temp", "cloud"]
    fc["hourly"][[c for c in cols if c in fc["hourly"]]].pipe(rnd, 1).to_csv(arc / f"tahmin_{stamp}UTC.csv", index=False, **csv_kw)
