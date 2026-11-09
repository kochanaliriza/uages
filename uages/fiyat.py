"""Tahmin sapmasi / revizyonu ile fiyat (SMF) iliskisi, son N gun (varsayilan 50).

  python -m uages fiyat            # son config.fiyat.gun (50) gun
  python -m uages fiyat 45         # son 45 gun

Geriye donuk iki tahmin uretilir (Open-Meteo Previous Runs, ayni hava karmasi + ufka gore kalibrasyon):
  - D-1 tahmini   : hedef gunden bir gun once yapilan kosu (lead 1), D+1 kalibrasyonuyla
  - gun ici tahmin: hedef gunun kendi kosusu (lead 0); canli sistem bugunku gun icin D+1 katsayilarini kullandigi icin
                    ayni kalibrasyon yolu, kalibrasyon gunu T = D - lag ile uygulanir (sizinti yok)
Bunlar hedef gerceklesen ve resmi (kiyas) D+1 tahminiyle birlestirilir, sapmalar cikarilir:
  sapma_d1 = gerceklesen - D-1,  sapma_gun_ici = gerceklesen - gun ici,  sapma_kiyas = gerceklesen - resmi,
  revizyon = gun ici - D-1
ve fiyat serisiyle (config.fiyat.dosya; saatlik, yerel saat) korelasyonu hesaplanir: saatlik (gunduz saatleri) ve gunluk,
Pearson + Spearman, ham fiyat ve "fiyat anomalisi" (fiyat - donemdeki ayni saatin ortalamasi; gunluk profil etkisini ayirir).
Ciktilar (outputs/): fiyat_analiz_saatlik.csv, fiyat_analiz_gunluk.csv, fiyat_korelasyon_ozet.csv, fiyat_korelasyon_raporu.md
Fiyat dosyasi yoksa sapma tablolari yine yazilir.

Fiyat dosyasi bicimi (csv/xlsx, ilk sayfa): ya tek bir tarih-saat sutunu, ya tarih + saat sutunu (0-23 ya da 1-24; 1-24 ise
saat k = (k-1):00-k:00 kabul edilir) ve bir fiyat sutunu (adinda smf/fiyat/price/цін/цен gecen; yoksa son sayisal sutun).
Saatler yerel saattir; config.fiyat.saat_etiketi = "bitis" ise tarih-saat sutunu aralik sonudur (1 saat geri alinir).
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from . import dataset
from .config import PATHS, csv_kw, rnd
from .countries import get_adapter
from .optimize import Prep, metrics, mevsim_json, season_factor

PAD_DAYS = 75  # kalibrasyon pencereleri (k 21 gun, sekil 45 gun) + gecikme icin analiz doneminden once alinan veri
PRICE_RX = re.compile(r"smf|fiyat|price|ціна|цін|цена|цен|imb|небаланс|dengesiz", re.I)


def fiyat_cfg(cfg: dict) -> dict:
    return {"gun": 50, "dosya": "data/input/smf.xlsx", "saat_etiketi": "baslangic", **cfg.get("fiyat", {})}


# ---------------------------------------------------------------- fiyat dosyasi
def _bul(fp_cfg: str):
    p = PATHS["country"] / fp_cfg
    if p.exists():
        return p
    for ext in (".xlsx", ".xls", ".csv"):  # ayni ad, farkli uzanti
        q = p.with_suffix(ext)
        if q.exists():
            return q
    return None


def load_price(cfg: dict) -> pd.DataFrame | None:
    """[time_utc, smf] ya da None (dosya yok)."""
    fc = fiyat_cfg(cfg)
    fp = _bul(fc["dosya"])
    if fp is None:
        return None
    if fp.suffix.lower() == ".csv":
        df = pd.read_csv(fp, sep=None, engine="python", encoding="utf-8-sig")
    else:
        df = pd.read_excel(fp)
    df = df.dropna(how="all").copy()
    df.columns = [str(c).strip() for c in df.columns]

    # fiyat sutunu
    num = [c for c in df.columns if pd.to_numeric(df[c].astype(str).str.replace(",", ".").str.replace(" ", ""), errors="coerce").notna().mean() > 0.8]
    named = [c for c in df.columns if PRICE_RX.search(c)]
    pcol = next((c for c in named if c in num), None)

    # zaman: tek tarih-saat sutunu mu, tarih + saat mi?
    tcol = hcol = None
    for c in df.columns:
        if c == pcol:
            continue
        t = pd.to_datetime(df[c], errors="coerce", dayfirst=True)
        if t.notna().mean() > 0.8:
            if (t.dt.hour != 0).any():
                tcol = c
                break
            if tcol is None:
                tcol = c  # yalniz tarih; saat sutunu aranir
    if tcol is None:
        raise ValueError(f"{fp.name}: tarih sutunu bulunamadi (sutunlar: {list(df.columns)})")
    t = pd.to_datetime(df[tcol], errors="coerce", dayfirst=True)
    if not (t.dt.hour != 0).any():
        for c in df.columns:
            if c in (tcol, pcol):
                continue
            h = pd.to_numeric(df[c].astype(str).str.extract(r"^\s*(\d{1,2})")[0], errors="coerce")
            if h.notna().mean() > 0.8 and h.min() >= 0 and h.max() <= 24 and h.nunique() >= 20:
                hcol = c
                break
        if hcol is None:
            raise ValueError(f"{fp.name}: saat bilgisi bulunamadi (tarih sutunu '{tcol}' saat icermiyor, saat sutunu yok)")
        h = pd.to_numeric(df[hcol].astype(str).str.extract(r"^\s*(\d{1,2})")[0], errors="coerce")
        if h.max() == 24 or h.min() == 1:
            h = h - 1  # 1-24: saat k = (k-1):00-k:00
        t = t.dt.normalize() + pd.to_timedelta(h, unit="h")
    elif fc["saat_etiketi"] == "bitis":
        t = t - pd.Timedelta(hours=1)
    if pcol is None:
        cand = [c for c in num if c not in (tcol, hcol)]
        if not cand:
            raise ValueError(f"{fp.name}: fiyat sutunu bulunamadi")
        pcol = cand[-1]
    v = pd.to_numeric(df[pcol].astype(str).str.replace(" ", "").str.replace(",", "."), errors="coerce")
    out = pd.DataFrame({"time_local": t, "smf": v}).dropna()
    out = out.groupby("time_local", as_index=False)["smf"].mean()  # DST cift saat / tekrarlar
    utc = out["time_local"].dt.tz_localize(cfg["local_tz"], ambiguous=False, nonexistent="shift_forward").dt.tz_convert("UTC")
    out["time_utc"] = utc.dt.tz_localize(None)
    print(f"    fiyat: {fp.name}, sutun '{pcol}', {len(out)} saat, {out['time_local'].min()} -> {out['time_local'].max()}")
    return out[["time_utc", "smf"]]


# ---------------------------------------------------------------- geriye donuk tahminler
def retro(cfg: dict, days: int, verbose: bool = False) -> pd.DataFrame:
    end = dataset.yesterday()
    t = dataset.build(cfg, end=end, start=end - pd.Timedelta(days=days + PAD_DAYS), save=False, verbose=verbose, leads=(0, 1))
    d = Prep(t, cfg)
    S = None
    if cfg["calibration"].get("season_correction") and mevsim_json().exists():
        S = season_factor(np.asarray(json.loads(mevsim_json().read_text(encoding="utf-8"))["coef"]), d.dates())
    path = d.path_of(d.cube_for(1, *d.series(1)), d.cfg_h, season=S)  # canli: bugun ve yarin D+1 katsayilari
    out = d.t.loc[d.LT[1], ["time_utc", "time_local", "actual_mw", "forecast_mw", "elev", "flag_curtail_hour", "flag_curtail_day"]].copy()
    out["d1_tahmin_mw"] = d.pred_for(1, path, *d.series(1))
    r0 = d.LT[0]
    p0 = pd.Series(d.pred_for(0, path, *d.series(0)), index=d.t.loc[r0, "time_utc"].to_numpy())
    out["gun_ici_tahmin_mw"] = out["time_utc"].map(p0).to_numpy()
    out["kisit"] = out["flag_curtail_hour"] | out["flag_curtail_day"] | pd.Series(d.flags[d.LT[1]], index=out.index)
    first = d.last_day - pd.Timedelta(days=days - 1)
    out = out[out["time_local"].dt.normalize() >= first].reset_index(drop=True)
    return out.rename(columns={"actual_mw": "gerceklesen_mw", "forecast_mw": "kiyas_tahmin_mw"}).drop(
        columns=["flag_curtail_hour", "flag_curtail_day"])


# ---------------------------------------------------------------- korelasyon
def _corr(x: pd.Series, y: pd.Series) -> dict:
    m = x.notna() & y.notna()
    n = int(m.sum())
    if n < 10 or x[m].std() == 0 or y[m].std() == 0:
        return {"n": n, "pearson": np.nan, "spearman": np.nan, "anlamli_95": False}
    p = float(np.corrcoef(x[m], y[m])[0, 1])
    s = float(np.corrcoef(x[m].rank(), y[m].rank())[0, 1])
    # |r| > 1.96/sqrt(n): bagimsiz gozlem varsayimiyla kaba %95 esigi (saatler otokorelasyonlu -> iyimser)
    return {"n": n, "pearson": p, "spearman": s, "anlamli_95": bool(abs(p) > 1.96 / np.sqrt(n))}


SAPMALAR = {"sapma_d1_mw": "Gerçekleşen − D-1 tahminimiz", "sapma_gun_ici_mw": "Gerçekleşen − gün içi tahminimiz",
            "sapma_kiyas_mw": "Gerçekleşen − resmi D+1 tahmini", "revizyon_mw": "Gün içi − D-1 tahminimiz (revizyon)"}


def analyse(h: pd.DataFrame, price: pd.DataFrame | None) -> dict:
    h = h.copy()
    h["sapma_d1_mw"] = h["gerceklesen_mw"] - h["d1_tahmin_mw"]
    h["sapma_gun_ici_mw"] = h["gerceklesen_mw"] - h["gun_ici_tahmin_mw"]
    h["sapma_kiyas_mw"] = h["gerceklesen_mw"] - h["kiyas_tahmin_mw"]
    h["revizyon_mw"] = h["gun_ici_tahmin_mw"] - h["d1_tahmin_mw"]
    if price is not None:
        h["smf"] = h["time_utc"].map(price.set_index("time_utc")["smf"])
        h["smf_anomali"] = h["smf"] - h.groupby(h["time_local"].dt.hour)["smf"].transform("mean")
    gunduz = h[h["elev"] > 0]
    g = gunduz.groupby(gunduz["time_local"].dt.normalize())
    daily = pd.DataFrame({c.replace("_mw", "_mwh"): g[c].sum(min_count=1) for c in
                          ["gerceklesen_mw", "d1_tahmin_mw", "gun_ici_tahmin_mw", "kiyas_tahmin_mw", *SAPMALAR]})
    if price is not None:
        gd = h.groupby(h["time_local"].dt.normalize())
        daily["smf_gunduz_ort"] = g["smf"].mean()
        daily["smf_gun_ort"] = gd["smf"].mean()
        daily["smf_anomali_gunduz_ort"] = g["smf_anomali"].mean()
    daily.index.name = "date"

    rows = []
    if price is not None:
        for c, lab in SAPMALAR.items():
            for pc in ("smf", "smf_anomali"):
                rows.append({"seviye": "saatlik (gündüz)", "degisken": lab, "fiyat": pc, **_corr(gunduz[c], gunduz[pc])})
            dc = c.replace("_mw", "_mwh")
            for pc in ("smf_gunduz_ort", "smf_anomali_gunduz_ort"):
                rows.append({"seviye": "günlük", "degisken": lab, "fiyat": pc, **_corr(daily[dc], daily[pc])})
    ozet = pd.DataFrame(rows)

    # Isaret / dilim tablosu: sapma ve revizyon dilimlerinde ortalama fiyat
    dil = []
    if price is not None:
        for c, lab in SAPMALAR.items():
            x = gunduz[[c, "smf", "smf_anomali"]].dropna()
            if len(x) < 25:
                continue
            q = pd.qcut(x[c], 5, duplicates="drop")
            for k, grp in x.groupby(q, observed=True):
                dil.append({"degisken": lab, "dilim_mw": f"{k.left:.0f} … {k.right:.0f}", "n": len(grp),
                            "ort_sapma_mw": grp[c].mean(), "ort_smf": grp["smf"].mean(), "ort_smf_anomali": grp["smf_anomali"].mean()})
    # Isabet (gunduz, kisitsiz): D-1, gun ici, resmi
    m = ((gunduz["gerceklesen_mw"].notna()) & ~gunduz["kisit"].astype(bool)).to_numpy()
    A = gunduz["gerceklesen_mw"].to_numpy(float)
    isabet = []
    common = m & np.isfinite(gunduz[["d1_tahmin_mw", "gun_ici_tahmin_mw", "kiyas_tahmin_mw"]].to_numpy(float)).all(axis=1)
    for c, lab in [("d1_tahmin_mw", "D-1 tahminimiz"), ("gun_ici_tahmin_mw", "Gün içi tahminimiz"), ("kiyas_tahmin_mw", "Resmi D+1 tahmini")]:
        isabet.append({"tahmin": lab, **metrics(gunduz[c].to_numpy(float), A, common)})
    return {"hourly": h, "daily": daily.reset_index(), "ozet": ozet, "dilim": pd.DataFrame(dil), "isabet": pd.DataFrame(isabet)}


def _md_table(df: pd.DataFrame, nd: int = 2) -> str:
    if df is None or df.empty:
        return "_(veri yok)_\n"
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].map(lambda v: "" if pd.isna(v) else f"{v:.{nd}f}")
    head = "| " + " | ".join(map(str, d.columns)) + " |\n|" + "---|" * len(d.columns) + "\n"
    return head + "".join("| " + " | ".join(map(str, r)) + " |\n" for r in d.itertuples(index=False))


def run(cfg: dict, days: int | None = None, verbose: bool = False) -> dict:
    kw = csv_kw(cfg)
    days = int(days or fiyat_cfg(cfg)["gun"])
    ad = get_adapter(cfg)
    print(f"    geriye donuk D-1 ve gun ici tahmin (son {days} gun; Previous Runs lead 0 + 1)")
    h = retro(cfg, days, verbose)
    price = None
    try:
        price = load_price(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"    UYARI: fiyat dosyasi okunamadi: {e}")
    if price is None:
        print(f"    UYARI: fiyat dosyasi yok ({PATHS['country'] / fiyat_cfg(cfg)['dosya']}); yalnizca sapmalar yazilir")
    r = analyse(h, price)
    out = PATHS["out"]
    r["hourly"].pipe(rnd, 2).to_csv(out / "fiyat_analiz_saatlik.csv", index=False, **kw)
    r["daily"].pipe(rnd, 2).to_csv(out / "fiyat_analiz_gunluk.csv", index=False, **kw)
    r["ozet"].pipe(rnd, 3).to_csv(out / "fiyat_korelasyon_ozet.csv", index=False, **kw)
    d0, d1 = r["daily"]["date"].min(), r["daily"]["date"].max()
    md = [f"# Tahmin sapması / revizyonu ve fiyat ilişkisi\n",
          f"Dönem: {d0:%Y-%m-%d} … {d1:%Y-%m-%d} ({len(r['daily'])} gün) · gündüz saatleri (güneş yüksekliği > 0) · "
          f"resmi tahmin: {ad.benchmark_label}\n",
          "Gün içi tahmin = hedef günün kendi model koşusu (Open-Meteo Previous Runs, lead 0); D-1 = bir gün önceki koşu. "
          "İkisi de bugünkü ufka göre kalibrasyon kurallarıyla, yayın anında mevcut gerçekleşenle (gecikmeli) üretildi.\n",
          "\n## İsabet (gündüz, kısıtsız; nMAE paydası ort. gündüz gerçekleşen)\n", _md_table(r["isabet"], 2)]
    if price is not None:
        md += ["\n## Korelasyon\n",
               "`smf_anomali` = fiyat − dönemdeki aynı saatin ortalaması (günlük fiyat profilini ayırır). "
               "`anlamli_95`: |r| > 1,96/√n (saatler otokorelasyonlu olduğundan iyimser bir eşik).\n\n", _md_table(r["ozet"], 3),
               "\n## Sapma dilimlerine göre ortalama fiyat (saatlik, gündüz)\n", _md_table(r["dilim"], 1)]
    else:
        md += [f"\n**Fiyat dosyası bulunamadı.** `{fiyat_cfg(cfg)['dosya']}` (ülke klasörüne göre) olarak koyup tekrar çalıştırın.\n"]
    (out / "fiyat_korelasyon_raporu.md").write_text("".join(md), encoding="utf-8")
    return r
