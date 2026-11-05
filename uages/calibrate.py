"""Model -> GPEE serisi kalibrasyonu ("MOS-lite").

Neden gerekli: GPEE serisi sadece yesil tarife dengeleme grubunu kapsar ve grubun MW'i yayimlanmiyor.
Model, santral listesindeki (tahmin evreni) tum MWp ile calisir. k = gerceklesen / model orani;
kapasite kapsami, erisilebilirlik, kirlenme, kar, kisit ve liste hatalarini birlikte toplar.

Tahmin kalibrasyonu uc katmanlidir (hepsi yuruyen pencerede, veri sizintisi olmadan):
  1) k      : son `window_days` gunun toplam orani (gerceklesen D+1/D+2 yayimlandigi icin 2 gun gecikmeli)
  2) sekil  : yerel saat bazli kalan oran (orijinal/dogu-bati/izleyici karisimi, oglen kisiti, kirpma)
  3) kt     : saatlik berraklik indeksi sinifina gore kalan oran (bulutlu saatlerde model iyimserligi)
Hepsi n'e gore 1'e buzulur ve kirpilir. Katsayilar model_durumu.json -> calib'e yazilir; dashboard bunlari yalnizca gosterir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KT_BINS = [0.0, 0.2, 0.35, 0.5, 0.6, 0.7, 0.8, 2.0]


def kt_bin(kt) -> np.ndarray:
    kt = np.nan_to_num(np.asarray(kt, dtype=float), nan=0.0)
    return np.clip(np.digitize(kt, KT_BINS) - 1, 0, len(KT_BINS) - 2)


def training_mask(df: pd.DataFrame, cfg: dict, model_col: str = "model_mw") -> pd.Series:
    c = cfg["calibration"]
    m = (df[model_col] > c["min_model_mw"]) & df["actual_mw"].notna()
    for f in ["flag_curtail_hour", "flag_curtail_day", "flag_curtail_model"]:
        if f in df:
            m &= ~df[f].fillna(False).astype(bool)
    if "use_for_training" in df:
        m &= df["use_for_training"].fillna(True).astype(bool)
    return m


def best_lag(actual: pd.Series, model: pd.Series, lags=range(-2, 3)) -> dict:
    """Zaman hizalama kontrolu: modeli kaydirip korelasyona bakar (0 bekleniyor)."""
    out = {}
    for L in lags:
        s = model.shift(L)
        ok = actual.notna() & s.notna() & (s > 0)
        out[L] = float(np.corrcoef(actual[ok], s[ok])[0, 1]) if ok.sum() > 100 else np.nan
    return out


def rolling_k(df: pd.DataFrame, cfg: dict, model_col: str = "model_mw", window_days: int | None = None) -> pd.DataFrame:
    """Gunluk k ve kayan pencere k (index: yerel tarih)."""
    w = window_days or cfg["calibration"]["window_days"]
    m = training_mask(df, cfg, model_col)
    sub = df.loc[m]
    d = sub.groupby(sub["time_local"].dt.normalize()).agg(a=("actual_mw", "sum"), m=(model_col, "sum")).asfreq("D")
    mp = max(5, w // 3)
    roll = d["a"].rolling(w, min_periods=mp).sum() / d["m"].rolling(w, min_periods=mp).sum()
    return pd.DataFrame({"k_day": d["a"] / d["m"], "k_roll": roll, "a_mwh": d["a"], "m_mwh": d["m"]})


def _shrunk_ratio(a: pd.Series, m: pd.Series, n: pd.Series, shrink_n: float, clip) -> pd.Series:
    raw = a / m
    f = 1.0 + (raw - 1.0) * (n / (n + shrink_n))
    return f.clip(*clip)


def fit(df: pd.DataFrame, cfg: dict, end_date: pd.Timestamp, model_col: str = "model_fc_mw", lag_days: int = 2) -> dict:
    """end_date (yerel gun) icin kalibrasyon: sadece end_date - lag_days ve oncesi veriyi kullanir."""
    c = cfg["calibration"]
    m = training_mask(df, cfg, model_col)
    day = df["time_local"].dt.normalize()
    last = end_date - pd.Timedelta(days=lag_days)
    w1 = m & (day <= last) & (day > last - pd.Timedelta(days=c["window_days"]))
    if w1.sum() < 50:
        return {}
    k = float(df.loc[w1, "actual_mw"].sum() / df.loc[w1, model_col].sum())
    w2 = m & (day <= last) & (day > last - pd.Timedelta(days=c["shape_window_days"]))
    sub = df.loc[w2]
    g = sub.groupby(sub["time_local"].dt.hour).agg(a=("actual_mw", "sum"), m=(model_col, "sum"), n=("actual_mw", "size"))
    shape = _shrunk_ratio(g["a"], k * g["m"], g["n"], c["shape_shrink_n"], c["shape_clip"]).reindex(range(24)).fillna(1.0)
    base = k * sub[model_col] * sub["time_local"].dt.hour.map(shape).to_numpy()
    b = kt_bin(sub["kt_fc"] if "kt_fc" in sub else sub["kt_h"])
    g2 = pd.DataFrame({"a": sub["actual_mw"].to_numpy(), "m": base.to_numpy(), "b": b}).groupby("b").agg(
        a=("a", "sum"), m=("m", "sum"), n=("a", "size"))
    ktf = _shrunk_ratio(g2["a"], g2["m"], g2["n"], 30, (0.6, 1.3)).reindex(range(len(KT_BINS) - 1)).fillna(1.0)
    return {"k": k, "shape": [float(x) for x in shape.to_numpy()], "kt_bins": KT_BINS,
            "kt_factor": [float(x) for x in ktf.to_numpy()], "fit_end": str(last.date())}


def apply(model_mw, local_hour, kt, elev, cal: dict, night: float) -> np.ndarray:
    model_mw = np.asarray(model_mw, dtype=float)
    sh = np.asarray(cal["shape"])[np.asarray(local_hour, dtype=int)]
    kf = np.asarray(cal["kt_factor"])[kt_bin(kt)]
    v = model_mw * cal["k"] * sh * kf
    return np.where(np.asarray(elev) < -3, night, v)


def walk_forward(df: pd.DataFrame, cfg: dict, start: str, model_col: str = "model_fc_mw", night: float = 0.0) -> pd.Series:
    """Her gun icin o gune kadar (2 gun gecikmeli) veriyle kalibre edip tahmin uretir. Donus: saatlik seri."""
    pred = pd.Series(np.nan, index=df.index)
    day = df["time_local"].dt.normalize()
    kt = df["kt_fc"] if "kt_fc" in df else df["kt_h"]
    for D in sorted(day[day >= pd.Timestamp(start)].unique()):
        cal = fit(df, cfg, pd.Timestamp(D), model_col)
        if not cal:
            continue
        te = day == D
        pred[te] = apply(df.loc[te, model_col], df.loc[te, "time_local"].dt.hour, kt[te], df.loc[te, "elev"], cal, night)
    return pred


def night_baseline(df: pd.DataFrame, days: int = 30) -> float:
    """Gece net tuketim (MW, negatif): gunes -5 derecenin altindaki saatlerin medyani."""
    sub = df[(df["elev"] < -5) & df["actual_mw"].notna()]
    sub = sub[sub["time_local"] > sub["time_local"].max() - pd.Timedelta(days=days)]
    v = sub["actual_mw"].median()
    return float(v) if pd.notna(v) else 0.0


CURTAIL_CLEAR_KT = 0.6   # acik hava esigi (saatlik berraklik indeksi)
CURTAIL_MIN_MW = 300.0   # beklenen uretim alt siniri (MW)


def curtail_low(actual, expected, forecast, ratio: float):
    """Kisit suphesi cekirdegi (gecmis analiz ve optimizasyonda ortak): gerceklesen hem beklenenin hem resmi kiyas
    tahmininin `ratio` katinin altinda ve beklenen > CURTAIL_MIN_MW. NaN karsilastirmalari False'tur."""
    return (actual < ratio * expected) & (actual < ratio * forecast) & (expected > CURTAIL_MIN_MW)


def flag_curtailment(df: pd.DataFrame, k: pd.Series, cfg: dict) -> pd.Series:
    """Model tabanli kisit suphesi: acik havada (kt_h>0.6) gerceklesen hem kalibre modelin hem resmi kiyas
    tahmininin (UA: GPEE) 'curtail_ratio' katinin altinda ve beklenen > 300 MW (bkz. curtail_low)."""
    r = cfg["calibration"]["curtail_ratio"]
    kk = df["time_local"].dt.normalize().map(k).astype(float)
    exp = df["model_mw"] * kk
    clear = df["kt_h"] > CURTAIL_CLEAR_KT
    low = curtail_low(df["actual_mw"], exp, df["forecast_mw"], r)
    return (clear & low).fillna(False)


def monthly_k(df: pd.DataFrame, cfg: dict, model_col: str = "model_mw") -> pd.DataFrame:
    """Aylik k (reanaliz modeline gore). Veri olmayan aylar ulke adaptorunun ayna kuraliyla doldurulur
    (UA: gunes geometrisi simetrisi Eki<-Mar, Kas<-Sub, Ara<-Oca), kalan bosluklar medyanla."""
    m = training_mask(df, cfg, model_col)
    sub = df.loc[m]
    g = sub.groupby(sub["time_local"].dt.month).agg(a=("actual_mw", "sum"), m=(model_col, "sum"),
                                                     gun=("time_local", lambda s: s.dt.normalize().nunique()))
    g["k"] = g["a"] / g["m"]
    out = pd.DataFrame(index=range(1, 13))
    out["k_gozlenen"] = g["k"].where(g["gun"] >= 15)
    from .countries import get_adapter
    mirror = get_adapter(cfg).monthly_k_mirror()
    out["k_kullanilan"] = out["k_gozlenen"]
    out["kaynak"] = np.where(out["k_gozlenen"].notna(), "2026 gozlenen", "")
    for mo, src in mirror.items():
        if pd.isna(out.loc[mo, "k_kullanilan"]) and pd.notna(out.loc[src, "k_gozlenen"]):
            out.loc[mo, "k_kullanilan"] = out.loc[src, "k_gozlenen"]
            out.loc[mo, "kaynak"] = f"simetri ({src}. ay)"
    out["k_kullanilan"] = out["k_kullanilan"].fillna(out["k_gozlenen"].median())
    out.index.name = "ay"
    return out.reset_index()
