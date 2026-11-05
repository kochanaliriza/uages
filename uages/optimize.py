"""Kalibrasyon optimizasyonu (ufka gore) ve on/sonra raporu.

  python -m uages optimize

Adimlar (bkz. .claude/skills/pv-forecast/references/calibration-validation.md):
  a) gerceklesen hava kaynagi: uydu (SARAH3) mi, ERA5/arsiv karmasi mi -> yalnizca rapor
  c) ufka gore model agirliklari: negatif olmayan en kucuk kareler, esit agirliga dogru buzulmus
  d) ufka gore k / saat sekli / kt: her ufuk kendi tahmin serisiyle kalibre edilir
  b) kalibrasyon ayarlari (k penceresi, sekil penceresi, buzme, zaman azalimi): yuruyen dogrulamayla izgara arama
  e) ufuk x kt sinifina gore konformal P10/P90 bandi
Donemler: secim = PR_START .. TEST_START-1 (ayar ve agirlik secimi), test = TEST_START .. son gerceklesen
(secimde hic kullanilmaz). Son 7 gun ayrica raporlanir (kullanici icin en onemli gosterge).
Hicbir sey otomatik devreye girmez: outputs/kalibrasyon_aday.json + outputs/optimizasyon_raporu.csv yazilir.

Kalibrasyon cekirdegi calibrate.fit/apply ile ayni matematiktir, ama gunluk [gun, saat, kt sinifi] kup
toplamlari uzerinden vektorel calisir (izgara x ufuk x ~1000 gun icin gerekli). Esdegerlik testi:
tools/check_vector_calib.py.
"""
from __future__ import annotations

import json
from itertools import combinations, product

import numpy as np
import pandas as pd

from . import calibrate as cal
from . import dataset
from .config import PATHS

NB = len(cal.KT_BINS) - 1
TEST_START = pd.Timestamp("2026-05-01")
LAG = 2           # yayin gunu ile son mevcut GPEE gerceklesen gunu arasi (gun); GPEE ~1-2 gun gec yayimlar
SEL_LEADS = (1, 2, 3)  # ayar secim olcutu: D+1..D+3 ortalama nMAE (alim-satim icin en degerli ufuklar)
WEIGHT_SHRINK = 0.2    # agirliklar esit agirliga bu oranda cekilir (asiri uyuma karsi)
GRID = {"window_days": [7, 14, 21, 30, 45], "shape_window_days": [30, 45, 60, 90],
        "shape_shrink_n": [10, 20, 40], "half_life": [None, 60, 30, 14]}
OUT_JSON = PATHS["out"] / "kalibrasyon_aday.json"
OUT_CSV = PATHS["out"] / "optimizasyon_raporu.csv"


# ---------------------------------------------------------------- vektorel kalibrasyon cekirdegi
def kt_of(ghi, g0h) -> np.ndarray:
    g0h = np.asarray(g0h, dtype=float)
    return np.clip(np.asarray(ghi, dtype=float) / np.where(g0h > 50, g0h, np.nan), 0, 1.2)


def cube(di, h, b, A, P, m, N) -> tuple:
    """Egitim maskesindeki saatlerin gunluk [gun, yerel saat, kt sinifi] toplamlari: (gerceklesen, model, adet)."""
    shp = (N, 24, NB)
    Ad, Pd, Cd = np.zeros(shp), np.zeros(shp), np.zeros(shp)
    ix = (di[m], h[m], b[m])
    np.add.at(Ad, ix, A[m])
    np.add.at(Pd, ix, P[m])
    np.add.at(Cd, ix, 1.0)
    return Ad, Pd, Cd


def wsum(x: np.ndarray, W: int, lam: float) -> np.ndarray:
    """S[T] = sum_{j<W} lam^j * x[T-j]  (T dahil geriye W gunluk, ustel azalimli pencere toplami)."""
    S = np.zeros_like(x)
    n = len(x)
    for j in range(min(W, n)):
        S[j:] += lam ** j * x[: n - j]
    return S


def _shrunk(a, m, n, shrink, clip) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        f = 1.0 + (a / m - 1.0) * (n / (n + shrink))
    f = np.clip(f, *clip)
    return np.where(np.isfinite(f) & (n > 0), f, 1.0)


def fit_season(dates: pd.DatetimeIndex, a: np.ndarray, p: np.ndarray, harmonics: int = 3) -> np.ndarray:
    """k'nin mevsimsel egrisi: haftalik log(sum A / sum P) = yil sabiti + sum_h a_h cos + b_h sin (2 pi h doy / 365,25).
    Yil sabitleri seviye farklarini (kapasite, kapsam) emer; donen yalnizca harmonik katsayilaridir. Agirlik: sqrt(P)."""
    w = pd.DataFrame({"a": a, "p": p}, index=dates).resample("W").sum()
    w = w[(w["p"] > 0) & (w["a"] > 0)]
    y = np.log(w["a"] / w["p"]).to_numpy()
    yr = w.index.year.to_numpy()
    Xy = np.column_stack([(yr == v).astype(float) for v in sorted(set(yr))])
    Xh = _harm(w.index.dayofyear.to_numpy(), harmonics)
    wt = np.sqrt(w["p"].to_numpy())
    beta = np.linalg.lstsq(np.column_stack([Xy, Xh]) * wt[:, None], y * wt, rcond=None)[0]
    return beta[Xy.shape[1]:]


def _harm(doy, H) -> np.ndarray:
    x = 2 * np.pi * np.asarray(doy, dtype=float) / 365.25
    return np.column_stack([f(h * x) for h in range(1, H + 1) for f in (np.cos, np.sin)])


def season_factor(coef: np.ndarray, dates) -> np.ndarray:
    """Gun bazinda mevsimsel k carpani (seviyesi keyfi; yalnizca oranlari anlamlidir)."""
    return np.exp(_harm(pd.DatetimeIndex(dates).dayofyear.to_numpy(), len(coef) // 2) @ coef)


def fit_path(cb, W_k, W_s, shrink_s, half_life, shape_clip, memo=None, season=None) -> dict:
    """Her gun T icin (T dahil) kalibrasyon: k[N], shape[N,24], ktf[N,NB]. half_life=None -> azalim yok
    (calibrate.fit ile ayni). memo: (W_s, half_life) pencere toplamlarini izgarada yeniden kullanmak icin.
    season[N]: verilirse hedef gun D icin k, s(D) / s_pencere(T) ile olceklenir (predict); s_pencere, k penceresindeki
    gunlerin model enerjisiyle agirlikli mevsimsel ortalamasidir."""
    Ad, Pd, Cd = cb
    lam = 1.0 if not half_life else 0.5 ** (1.0 / half_life)
    a1, p1, n1 = Ad.sum((1, 2)), Pd.sum((1, 2)), Cd.sum((1, 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        k = wsum(a1, W_k, lam) / wsum(p1, W_k, lam)
        sw = wsum(season * p1, W_k, lam) / wsum(p1, W_k, lam) if season is not None else None
    ok = (wsum(n1, W_k, 1.0) >= 50) & np.isfinite(k) & (k > 0)
    k = np.where(ok, k, np.nan)
    key = (W_s, half_life)
    if memo is not None and key in memo:
        Sa, Sp, Sn = memo[key]
    else:
        Sa, Sp, Sn = wsum(Ad, W_s, lam), wsum(Pd, W_s, lam), wsum(Cd, W_s, lam)
        if memo is not None:
            memo[key] = (Sa, Sp, Sn)
    shape = _shrunk(Sa.sum(2), k[:, None] * Sp.sum(2), Sn.sum(2), shrink_s, shape_clip)
    base = k[:, None] * (shape[:, :, None] * Sp).sum(1)
    ktf = _shrunk(Sa.sum(1), base, Sn.sum(1), 30, (0.6, 1.3))
    out = {"k": k, "shape": shape, "ktf": ktf}
    if season is not None:
        out["season"], out["sw"] = season, sw
    return out


def predict(path, di, h, b, P, elev, lead, lag, night) -> np.ndarray:
    """Hedef gun D icin kalibrasyon gunu T = D - lead - lag (yayin aninda mevcut son gerceklesen)."""
    T = di - lead - lag
    Tc = np.clip(T, 0, len(path["k"]) - 1)
    v = P * path["k"][Tc] * path["shape"][Tc, h] * path["ktf"][Tc, b]
    if "season" in path:
        v = v * path["season"][np.clip(di, 0, len(path["season"]) - 1)] / path["sw"][Tc]
    v = np.where(T >= 0, v, np.nan)
    return np.where(elev < -3, np.where(T >= 0, night[Tc], np.nan), v)


def night_path(di, A, elev, N, days=30) -> np.ndarray:
    """Gece net tuketimi: gunes -5 derecenin altindaki saatlerin gunluk medyani, son `days` gunun medyani."""
    s = pd.Series(np.where(elev < -5, A, np.nan)).groupby(di).median().reindex(range(N))
    return s.rolling(days, min_periods=3).median().ffill().fillna(0.0).to_numpy()


# ---------------------------------------------------------------- agirliklar
def nnls_small(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Negatif olmayan en kucuk kareler; az sayida model icin tum alt kumeleri deneyerek tam cozum."""
    best, M = (np.inf, (), None), X.shape[1]
    for r in range(1, M + 1):
        for S in combinations(range(M), r):
            beta = np.linalg.lstsq(X[:, S], y, rcond=None)[0]
            if (beta < 0).any():
                continue
            sse = float(((X[:, S] @ beta - y) ** 2).sum())
            if sse < best[0]:
                best = (sse, S, beta)
    w = np.zeros(M)
    w[list(best[1])] = best[2]
    return w


def fit_weights(t: pd.DataFrame, models: list[str], rows: np.ndarray) -> dict:
    """Bir ufuk icin model agirliklari. Kapasite kaymasi (zamanla degisen k) agirliklari bozmasin diye hedef,
    21 gunluk merkezi oranla (gerceklesen / modellerin esit ortalamasi) normalize edilir."""
    avail = [m for m in models if t.loc[rows, f"p_{m}"].notna().mean() > 0.9]
    r = rows & t[[f"p_{m}" for m in avail]].notna().all(axis=1).to_numpy() & (t["elev"].to_numpy() > 5)
    X = t.loc[r, [f"p_{m}" for m in avail]].to_numpy()
    A = t.loc[r, "actual_mw"].to_numpy()
    day = t.loc[r, "time_local"].dt.normalize()
    d = pd.DataFrame({"a": A, "p": X.mean(1), "day": day.to_numpy()}).groupby("day").sum()
    d = d.asfreq("D").fillna(0)
    kc = d["a"].rolling(21, center=True, min_periods=7).sum() / d["p"].rolling(21, center=True, min_periods=7).sum()
    y = A / day.map(kc).to_numpy()
    ok = np.isfinite(y)
    w = nnls_small(X[ok], y[ok])
    w = w / w.sum() if w.sum() > 0 else np.full(len(avail), 1 / len(avail))
    w = (1 - WEIGHT_SHRINK) * w + WEIGHT_SHRINK / len(avail)
    out = {m: 0.0 for m in models}
    out.update({m: float(v) for m, v in zip(avail, w)})
    return out


# ---------------------------------------------------------------- yardimcilar
def metrics(pred, A, m) -> dict:
    ok = m & np.isfinite(pred) & np.isfinite(A)
    if ok.sum() == 0:
        return {"n_saat": 0}
    e = pred[ok] - A[ok]
    n = A[ok].mean()
    return {"n_saat": int(ok.sum()), "nMAE_pct": float(np.abs(e).mean() / n * 100),
            "nRMSE_pct": float(np.sqrt((e ** 2).mean()) / n * 100), "bias_pct": float(e.mean() / n * 100)}


def curtail_flag(t1: pd.DataFrame, cfg: dict) -> pd.Series:
    """Model tabanli kisit suphesi (calibrate.flag_curtailment ile ayni kural), uydu modeline gore."""
    r = cfg["calibration"]["curtail_ratio"]
    m = (t1["p_sat"] > 50) & t1["actual_mw"].notna() & ~t1["flag_curtail_hour"] & ~t1["flag_curtail_day"]
    day = t1["time_local"].dt.normalize()
    d = pd.DataFrame({"a": t1["actual_mw"].where(m, 0), "p": t1["p_sat"].where(m, 0), "day": day}).groupby("day").sum()
    d = d.asfreq("D").fillna(0)
    k = (d["a"].rolling(21, min_periods=7).sum() / d["p"].rolling(21, min_periods=7).sum()).ffill().bfill()
    exp = t1["p_sat"] * day.map(k).to_numpy()
    clear = kt_of(t1["ghi_sat"], t1["g0h"]) > 0.6
    low = (t1["actual_mw"] < r * exp) & (t1["actual_mw"] < r * t1["forecast_mw"]) & (exp > 300)
    return pd.Series(clear & low.fillna(False).to_numpy(), index=t1["time_utc"].to_numpy())


def actual_weather_report(t1: pd.DataFrame) -> list[dict]:
    """Adim a: gerceklesen hava kaynagi. 2026'da ERA5/arsiv karmasi modeli (outputs/gecmis_saatlik.csv) ile
    uydu modelini, gerceklesenle saatlik korelasyon ve gunluk k oynakligi (CV) uzerinden kiyaslar."""
    fp = PATHS["out"] / "gecmis_saatlik.csv"
    if not fp.exists():
        return []
    h = pd.read_csv(fp, sep=";", decimal=",", encoding="utf-8-sig", parse_dates=["time_utc"])
    j = h[["time_utc", "model_mw", "flag_curtail_model"]].merge(t1[["time_utc", "p_sat", "actual_mw", "elev"]], on="time_utc")
    j = j[(j["elev"] > 5) & j["actual_mw"].notna() & j["p_sat"].notna() & j["model_mw"].notna()
          & ~j["flag_curtail_model"].astype(str).str.lower().eq("true")]
    out = []
    for col, lab in [("model_mw", "ERA5/arşiv karması (mevcut)"), ("p_sat", "Uydu SARAH3")]:
        dk = j.groupby(j["time_utc"].dt.normalize()).apply(lambda g: g["actual_mw"].sum() / g[col].sum() if len(g) >= 6 else np.nan)
        out.append({"kaynak": lab, "n_saat": len(j), "korelasyon": float(np.corrcoef(j["actual_mw"], j[col])[0, 1]),
                    "gunluk_k_cv_pct": float(dk.std() / dk.mean() * 100)})
    return out


# ---------------------------------------------------------------- ortak hazirlik
class Prep:
    """Egitim tablosunu (dataset.build) kalibrasyon ve degerlendirme icin hazirlar: kisit bayragi, gun indeksi,
    maskeler, gece degeri. Hem tam optimizasyon (run) hem gunluk yenileme (refresh) bunu kullanir."""

    def __init__(self, t: pd.DataFrame, cfg: dict):
        self.cfg, self.c = cfg, cfg["calibration"]
        self.models = list(cfg["forecast"]["model_weights"])
        t1 = t[t["lead"] == 1].reset_index(drop=True)
        self.t1 = t1
        flag = curtail_flag(t1, cfg)
        t = t.assign(flag_curtail_model=t["time_utc"].map(flag).fillna(False).astype(bool))
        self.d0 = t["time_local"].min().normalize()
        self.last_day = t.loc[t["actual_mw"].notna(), "time_local"].max().normalize()
        self.N = (self.last_day - self.d0).days + 1
        t = t[t["time_local"].dt.normalize() <= self.last_day].reset_index(drop=True)
        t["di"] = (t["time_local"].dt.normalize() - self.d0).dt.days
        t["h"] = t["time_local"].dt.hour
        self.t = t
        self.flags = (t["flag_curtail_hour"] | t["flag_curtail_day"] | t["flag_curtail_model"]).to_numpy()
        self.day = t["time_local"].dt.normalize()
        self.evalm = ((t["elev"] > 0) & t["actual_mw"].notna()).to_numpy() & ~self.flags  # gunduz, kisitsiz
        self.evalall = ((t["elev"] > 0) & t["actual_mw"].notna()).to_numpy()               # gunduz, tum saatler
        self.trainbase = (t["actual_mw"].notna() & t["use_for_training"]).to_numpy() & ~self.flags
        self.A = t["actual_mw"].to_numpy(dtype=float)
        self.elev = t["elev"].to_numpy(dtype=float)
        self.leads = sorted(int(x) for x in t["lead"].unique())
        self.LT = {L: (t["lead"] == L).to_numpy() for L in self.leads}
        t1n = t[self.LT[1]]
        self.night = night_path(t1n["di"].to_numpy(), t1n["actual_mw"].to_numpy(dtype=float), t1n["elev"].to_numpy(), self.N)
        self.allp = np.ones(len(t), bool)
        c = self.c
        self.cfg_h = dict(window_days=c["window_days"], shape_window_days=c["shape_window_days"],
                          shape_shrink_n=c["shape_shrink_n"], half_life=None)

    def series(self, L, w=None):
        """Ufuk L satirlari icin (P, kt sinifi); w=None -> hava karmasi (forecast.py'deki 'blend' ile ayni)."""
        t, r = self.t, self.LT[L]
        if w is None:
            P, ghi = t.loc[r, "p_legacy"].to_numpy(float), t.loc[r, "ghi_legacy"].to_numpy(float)
        else:
            P = sum(t.loc[r, f"p_{m}"].fillna(0).to_numpy(float) * v for m, v in w.items() if v > 0)
            ghi = sum(t.loc[r, f"ghi_{m}"].fillna(0).to_numpy(float) * v for m, v in w.items() if v > 0)
            P = np.where(t.loc[r, [f"p_{m}" for m, v in w.items() if v > 0]].notna().all(axis=1), P, np.nan)
        return P, cal.kt_bin(kt_of(ghi, t.loc[r, "g0h"]))

    def cube_for(self, L, P, b, period=None):
        r = self.LT[L]
        period = self.allp if period is None else period
        m = self.trainbase[r] & (P > self.c["min_model_mw"]) & period[r]
        return cube(self.t.loc[r, "di"].to_numpy(), self.t.loc[r, "h"].to_numpy(), b, self.A[r], np.nan_to_num(P), m, self.N)

    def pred_for(self, L, path, P, b):
        r = self.LT[L]
        return predict(path, self.t.loc[r, "di"].to_numpy(), self.t.loc[r, "h"].to_numpy(), b, P, self.elev[r], L, LAG, self.night)

    def path_of(self, cb, hp, memo=None, season=None):
        return fit_path(cb, hp["window_days"], hp["shape_window_days"], hp["shape_shrink_n"], hp["half_life"],
                        self.c["shape_clip"], memo, season)

    def dates(self) -> pd.DatetimeIndex:
        return pd.date_range(self.d0, periods=self.N, freq="D")

    def season_for(self, L=1, P=None, b=None, period=None, source="tahmin", harmonics=3):
        """Gun bazinda mevsimsel k egrisi [N] ve katsayilari. source='tahmin': ufuk L'nin kendi serisi (NWP'nin
        mevsimsel yanliligini da icerir); 'uydu': uydu tabanli gerceklesen model (yalnizca filonun mevsimselligi)."""
        if source == "uydu":
            L, r = 1, self.LT[1]
            P, b = self.t.loc[r, "p_sat"].to_numpy(float), np.zeros(r.sum(), int)
        Ad, Pd, _ = self.cube_for(L, P, b, period)
        coef = fit_season(self.dates(), Ad.sum((1, 2)), Pd.sum((1, 2)), harmonics)
        return season_factor(coef, self.dates()), coef

    def legacy_preds(self) -> dict:
        """Mevcut yontem: best_match D+1 serisiyle fit (gecmis tahmin vekili), hava karmasina tum ufuklarda uygulanir."""
        bm = {m: float(m == "best_match") for m in self.models} if "best_match" in self.models else None
        P1, b1 = self.series(1, bm)
        path = self.path_of(self.cube_for(1, P1, b1), self.cfg_h)
        return {L: self.pred_for(L, path, *self.series(L)) for L in self.leads}

    def ufuk_paths(self) -> dict:
        """Sade varyant: her ufuk kendi hava karmasi serisiyle, config ayarlariyla kalibre edilir."""
        return {L: self.path_of(self.cube_for(L, *self.series(L)), self.cfg_h) for L in self.leads}


def pooled_season(d: "Prep", period) -> np.ndarray:
    """Tum ufuklarin mevsimsel egri katsayilarinin ortalamasi (tek ufkun gurultusune karsi)."""
    return np.mean([d.season_for(L, *d.series(L), period=period)[1] for L in d.leads], axis=0)


# ---------------------------------------------------------------- gunluk yenileme (uretim)
UFUK_JSON = PATHS["out"] / "kalibrasyon_ufuk.json"
MEVSIM_JSON = PATHS["out"] / "mevsim_k.json"  # python -m uages optimize yazar; ayda bir yenilemek yeterli
SON7_CSV = PATHS["out"] / "son7gun_isabet.csv"
RECENT_DAYS = 75  # en uzun ufuk (7) + gecikme (2) + sekil penceresi (45) + 7 gunluk degerlendirme + pay


def refresh(cfg: dict, verbose: bool = False) -> dict:
    """Son ~75 gunun Previous Runs + uydu verisiyle (12 saat onbellek) ufka gore kalibrasyonu yeniden fit eder ve
    son 7 gun isabetini (GPEE / mevcut / ufka gore) hesaplar. calibration.mode ne olursa olsun calisir;
    forecast.py yalnizca mode == "ufuk" iken kalibrasyon_ufuk.json'u kullanir."""
    end = dataset.yesterday()
    t = dataset.build(cfg, end=end, start=end - pd.Timedelta(days=RECENT_DAYS), save=False, verbose=verbose)
    d = Prep(t, cfg)
    paths = d.ufuk_paths()
    # Mevsimsel egri (varsa): her ufuk icin k penceresinin mevsimsel ortalamasi (sw) saklanir; tahmin hedef gun icin
    # k x s(D) / sw uygular. calibration.season_correction kapaliyken de hesaplanir (son 7 gun kiyasi icin).
    coef = json.loads(MEVSIM_JSON.read_text(encoding="utf-8"))["coef"] if MEVSIM_JSON.exists() else None
    S = season_factor(np.asarray(coef), d.dates()) if coef is not None else None
    spaths = {L: d.path_of(d.cube_for(L, *d.series(L)), d.cfg_h, season=S) for L in d.leads} if S is not None else {}
    out = {"olusturma_utc": str(pd.Timestamp.now("UTC").floor("s")), "fit_son_gun": str(d.last_day.date()),
           "ayarlar": d.cfg_h, "kt_bins": cal.KT_BINS, "mevsim_coef": coef, "ufuklar": {}}
    for L, pth in paths.items():
        if not np.isfinite(pth["k"][-1]):
            continue
        out["ufuklar"][str(L)] = {"k": float(pth["k"][-1]), "shape": [float(x) for x in pth["shape"][-1]],
                                  "kt_factor": [float(x) for x in pth["ktf"][-1]]}
        if L in spaths:
            out["ufuklar"][str(L)]["mevsim_sw"] = float(spaths[L]["sw"][-1])
    UFUK_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    leg = d.legacy_preds()
    last7 = (d.day > d.last_day - pd.Timedelta(days=7)).to_numpy()
    gp = d.t["forecast_mw"].to_numpy(dtype=float)
    rows = []
    for L in d.leads:
        r = d.LT[L]
        meths = {"Mevcut yöntem": leg[L], "Ufka göre kalibrasyon": d.pred_for(L, paths[L], *d.series(L))}
        if L in spaths:
            meths["Ufka göre + mevsim"] = d.pred_for(L, spaths[L], *d.series(L))
        if L == 1:
            meths = {"GPEE resmi (D+1)": gp[r], **meths}
        common = np.logical_and.reduce([np.isfinite(v) for v in meths.values()])
        for k, v in meths.items():
            rows.append({"ufuk": L, "yontem": k, "baslangic": str((d.last_day - pd.Timedelta(days=6)).date()),
                         "bitis": str(d.last_day.date()), **metrics(v, d.A[r], (d.evalm & last7)[r] & common)})
    son7 = pd.DataFrame(rows)
    son7.to_csv(SON7_CSV, index=False, sep=";", decimal=",", encoding="utf-8-sig")
    return {"kalibrasyon": out, "son7": son7}


def load_ufuk(cfg: dict, max_age_days: int = 10) -> dict | None:
    """Uretimde kullanilacak ufka gore kalibrasyon; yoksa, bozuksa ya da fit_son_gun cok eskiyse None."""
    try:
        cal_ = json.loads(UFUK_JSON.read_text(encoding="utf-8"))
        age = (pd.Timestamp.now(cfg["local_tz"]).tz_localize(None).normalize() - pd.Timestamp(cal_["fit_son_gun"])).days
        if age > max_age_days or not cal_.get("ufuklar"):
            return None
        return cal_
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- tam optimizasyon
def run(cfg: dict, rebuild: bool = False, verbose: bool = True) -> dict:
    t = dataset.load(cfg, rebuild=rebuild, verbose=verbose)
    d = Prep(t, cfg)
    models, leads, LT, A = d.models, d.leads, d.LT, d.A
    sel = (d.day < TEST_START).to_numpy()
    test = (d.day >= TEST_START).to_numpy()
    last7 = (d.day > d.last_day - pd.Timedelta(days=7)).to_numpy()
    evalm, evalall = d.evalm, d.evalall
    series, cube_for, pred_for, path_of, cfg_h = d.series, d.cube_for, d.pred_for, d.path_of, d.cfg_h
    t, d0, last_day, night, allp = d.t, d.d0, d.last_day, d.night, d.allp

    preds = {"Mevcut yöntem": d.legacy_preds()}
    if verbose:
        print("  [1] mevcut yontem hazir", flush=True)

    # 2) Ufka gore kalibrasyon, config agirliklari ve ayarlari (sade varyant)
    UP = d.ufuk_paths()
    preds["Ufka göre kalibrasyon"] = {L: pred_for(L, UP[L], *series(L)) for L in leads}
    # 2b) + mevsimsel k duzeltmesi: tum ufuklarin ortak egrisi (yalnizca secim doneminden fit, test sizintisiz).
    # Ufuk basina ayri egri ve uydu modelinden egri de denendi (2026-11-01): ortak egri ayni kazanci daha az riskle verdi.
    S_pool = season_factor(pooled_season(d, sel), d.dates())
    preds["Ufka göre + mevsim"] = {L: pred_for(L, path_of(cube_for(L, *series(L)), cfg_h, season=S_pool), *series(L)) for L in leads}
    MEVSIM_JSON.write_text(json.dumps({
        "olusturma_utc": str(pd.Timestamp.now("UTC").floor("s")), "veri": [str(d0.date()), str(last_day.date())],
        "kaynak": "ufka gore hava karmasi serileri (D+1..D+7), havuzlanmis; yil sabitli harmonik regresyon",
        "coef": [float(x) for x in pooled_season(d, allp)]}, ensure_ascii=False, indent=1), encoding="utf-8")

    # 3) + ufka gore agirliklar (secim doneminde fit)
    W = {L: fit_weights(t[LT[L]].reset_index(drop=True), models, sel[LT[L]]) for L in leads}
    SER = {L: series(L, W[L]) for L in leads}
    CB = {L: cube_for(L, *SER[L], allp) for L in leads}
    preds["+ ufka göre ağırlıklar"] = {L: pred_for(L, path_of(CB[L], cfg_h), *SER[L]) for L in leads}
    if verbose:
        print("  [2-3] ufka gore kalibrasyon ve agirliklar hazir", flush=True)

    # 4) + ayar secimi: secim doneminde D+1..D+3 ortalama nMAE
    memo = {L: {} for L in SEL_LEADS}
    scores = []
    for combo in product(*GRID.values()):
        hp = dict(zip(GRID, combo))
        s = []
        for L in SEL_LEADS:
            p = pred_for(L, path_of(CB[L], hp, memo[L]), *SER[L])
            s.append(metrics(p, A[LT[L]], (evalm & sel)[LT[L]]).get("nMAE_pct", np.inf))
        scores.append({**hp, "skor": float(np.mean(s))})
    scores = pd.DataFrame(scores).sort_values("skor")
    best = scores.iloc[0].to_dict()
    hp_best = {k: (None if pd.isna(best[k]) else int(best[k])) for k in GRID}
    PATH = {L: path_of(CB[L], hp_best) for L in leads}
    preds["Optimize (aday)"] = {L: pred_for(L, PATH[L], *SER[L]) for L in leads}
    if verbose:
        print(f"  [4] en iyi ayarlar {hp_best} (secim skoru %{best['skor']:.2f})", flush=True)

    # 5) Konformal bant: secim donemi oranlarinin (gerceklesen/tahmin) yuzdelikleri, ufuk x kt sinifi
    band, cover = {}, {}
    for L in leads:
        r = LT[L]
        p, b = preds["Optimize (aday)"][L], SER[L][1]
        m = (evalm & sel)[r] & (p > 50)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = A[r] / p
        qlo = [float(np.nanquantile(ratio[m & (b == k)], 0.1)) if (m & (b == k)).sum() >= 100 else float(np.nanquantile(ratio[m], 0.1)) for k in range(NB)]
        qhi = [float(np.nanquantile(ratio[m & (b == k)], 0.9)) if (m & (b == k)).sum() >= 100 else float(np.nanquantile(ratio[m], 0.9)) for k in range(NB)]
        band[L] = {"q_lo": qlo, "q_hi": qhi}
        mt = (evalm & test)[r] & (p > 50)
        lo, hi = p * np.array(qlo)[b], p * np.array(qhi)[b]
        cover[L] = float(((A[r] >= lo) & (A[r] <= hi))[mt].mean() * 100) if mt.any() else np.nan

    # Rapor
    rows = []
    gp = t["forecast_mw"].to_numpy(dtype=float)
    for L in leads:
        r = LT[L]
        meths = dict((k, v[L]) for k, v in preds.items())
        if L == 1:
            meths = {"GPEE resmi (D+1)": gp[r], **meths}
        common = np.logical_and.reduce([np.isfinite(v) for v in meths.values()])
        for per, pm in [("secim", (evalm & sel)[r]), ("test", (evalm & test)[r]), ("test_tum_saatler", (evalall & test)[r]),
                        ("son_7_gun", (evalm & last7)[r])]:
            for k, v in meths.items():
                rows.append({"ufuk": L, "donem": per, "yontem": k, **metrics(v, A[r], pm & common),
                             **({"bant_kapsama_pct": cover[L]} if (k == "Optimize (aday)" and per == "test") else {})})
        for mo, g in pd.Series(np.arange(r.sum())).groupby(t.loc[r, "time_local"].dt.to_period("M").astype(str).to_numpy()):
            if pd.Period(mo) < TEST_START.to_period("M"):
                continue
            mm = np.zeros(r.sum(), bool)
            mm[g.to_numpy()] = True
            for k in meths:
                rows.append({"ufuk": L, "donem": f"ay_{mo}", "yontem": k, **metrics(meths[k], A[r], (evalm[r] & mm) & common)})
    rep = pd.DataFrame(rows)

    # Devreye alinabilecek aday: agirliklar tum veriyle yeniden fit, kalibrasyon son gerceklesen gune gore
    W_all = {L: fit_weights(t[LT[L]].reset_index(drop=True), models, np.ones(LT[L].sum(), bool)) for L in leads}
    cand = {"olusturma_utc": str(pd.Timestamp.now("UTC").floor("s")), "secim_donemi": [str(d0.date()), str((TEST_START - pd.Timedelta(days=1)).date())],
            "test_donemi": [str(TEST_START.date()), str(last_day.date())], "fit_son_gun": str(last_day.date()),
            "ayarlar": hp_best, "kt_bins": cal.KT_BINS, "gece_mw": float(night[-1]), "ufuklar": {}}
    for L in leads:
        P, b = series(L, W_all[L])
        pth = path_of(cube_for(L, P, b, allp), hp_best)
        cand["ufuklar"][str(L)] = {"agirliklar": W_all[L], "secim_agirliklari": W[L], "k": float(pth["k"][-1]),
                                    "shape": [float(x) for x in pth["shape"][-1]], "kt_factor": [float(x) for x in pth["ktf"][-1]],
                                    "bant": band[L]}
    OUT_JSON.write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")
    rep.to_csv(OUT_CSV, index=False, sep=";", decimal=",", encoding="utf-8-sig")
    scores.head(30).to_csv(PATHS["out"] / "optimizasyon_izgara.csv", index=False, sep=";", decimal=",", encoding="utf-8-sig")
    return {"rapor": rep, "aday": cand, "izgara": scores, "gerceklesen_hava": actual_weather_report(d.t1),
            "kisit_saat": int(d.flags[LT[1]].sum())}
