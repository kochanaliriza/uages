"""Gun ici / gun oncesi tahmin karsilastirmasi ve tarih secici verisi.

Ornek: 9'unda calistirildi -> 10'u icin tahmin (ufuk 1). 10'unda calistirildi -> 10'u icin gun ici tahmin (ufuk 0).
Panel, ayni hedef gun icin bu iki tahmin arasindaki farki gosterir (istenirse D-2..D-7 ile de).

Her `forecast` calismasi outputs/arsiv/tahmin_YYYYMMDD_HHUTC.csv olarak saklanir (forecast.save_forecast);
`forecast.archive_days` (varsayilan 30) gunden eski arsiv dosyalari silinir (prune).

Ufuk tanimi (yerel takvim gunu): hedef gun D icin ufuk L tahmini = yerel gun D-L'de verilmis SON calismanin D icin degerleri.
  ufuk 0 = gun ici (D gunu icinde verilmis son tahmin; bugun icin bu calismanin kendisi)
  ufuk 1 = gun oncesi (D-1'de verilmis son tahmin), ... ufuk 7
Ciktilar:
  tahmin_gun_gecmisi.csv       : son archive_days gun + tahmin penceresi, saatlik: hedef gerceklesen, kiyas (resmi) tahmin,
                                 ufuk0_mw .. ufuk7_mw
  tahmin_gun_gecmisi_gunluk.csv: her gun icin ufuk0..7 gunluk P50 (MWh), gerceklesen ve kiyas toplami (en az 20 saat),
                                 gun ici - ufuk L farki (MWh, %), ufuklarin yayin zamanlari (UTC)
Arsiv bossa yalnizca bugunku calismanin sutunlari dolar; hata vermez.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PATHS, rnd

RX = re.compile(r"tahmin_(\d{8})_(\d{2})UTC\.csv$")
MIN_SAAT = 20      # gunluk toplam icin en az bu kadar dolu saat (forecast.daily ile ayni kural)
MAX_UFUK = 7


def arsiv_dir() -> Path:
    return PATHS["out"] / "arsiv"


def archive_days(cfg: dict) -> int:
    return int(cfg["forecast"].get("archive_days", 30))


def list_runs(arc: Path | None = None) -> pd.DataFrame:
    """Arsivdeki calismalar: [issued_utc, path], eskiden yeniye."""
    arc = arc or arsiv_dir()
    rows = []
    if arc.exists():
        for fp in arc.glob("tahmin_*UTC.csv"):
            m = RX.search(fp.name)
            if m:
                rows.append((pd.Timestamp(f"{m.group(1)} {m.group(2)}:00"), fp))
    return pd.DataFrame(rows, columns=["issued_utc", "path"]).sort_values("issued_utc").reset_index(drop=True)


def prune(cfg: dict, verbose: bool = True) -> int:
    """archive_days'ten eski arsiv dosyalarini siler. Silinen dosya sayisi."""
    runs = list_runs()
    if runs.empty:
        return 0
    limit = pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(days=archive_days(cfg))
    old = runs[runs["issued_utc"] < limit]
    for fp in old["path"]:
        try:
            fp.unlink()
        except OSError:
            pass
    if verbose and len(old):
        print(f"    arsiv: {archive_days(cfg)} gunden eski {len(old)} tahmin dosyasi silindi")
    return len(old)


def _p50(fp: Path, kw: dict) -> pd.Series | None:
    try:
        df = pd.read_csv(fp, sep=kw["sep"], decimal=kw["decimal"], encoding=kw["encoding"],
                         usecols=["time_utc", "tahmin_p50_mw"])
    except Exception as e:  # noqa: BLE001
        print(f"  UYARI: arsiv okunamadi ({fp.name}): {e}")
        return None
    return pd.Series(df["tahmin_p50_mw"].to_numpy(), index=pd.to_datetime(df["time_utc"]))


def _local_start_utc(day: pd.Timestamp, tz: str) -> pd.Timestamp:
    return day.tz_localize(tz, ambiguous=False, nonexistent="shift_forward").tz_convert("UTC").tz_localize(None)


def build(fc: dict, cfg: dict, kw: dict, target: pd.DataFrame | None = None) -> dict:
    """fc: forecast.build_forecast ciktisi (henuz arsive yazilmamis). target: adaptor.load_target (opsiyonel)."""
    tz = cfg["local_tz"]
    issued = pd.Timestamp(fc["issued_utc"]).floor("h")
    today = pd.Timestamp.now(tz).tz_localize(None).normalize()
    first = today - pd.Timedelta(days=archive_days(cfg))
    cur = fc["hourly"]
    last = pd.to_datetime(cur["time_local"]).max().normalize()
    # UTC saatlik sira (DST gunleri yerel 23/25 saat olur)
    utc = pd.date_range(_local_start_utc(first, tz), _local_start_utc(last + pd.Timedelta(days=1), tz) - pd.Timedelta(hours=1), freq="h")
    out = pd.DataFrame({"time_utc": utc, "time_local": utc.tz_localize("UTC").tz_convert(tz).tz_localize(None)})
    if target is not None and len(target):
        t = target.set_index("time_utc")
        out["gerceklesen_mw"] = out["time_utc"].map(t["actual_mw"]).to_numpy()
        out["kiyas_tahmin_mw"] = out["time_utc"].map(t["forecast_mw"]).to_numpy()
    else:
        out["gerceklesen_mw"] = np.nan
        out["kiyas_tahmin_mw"] = np.nan

    # Adaylar: arsiv + bugunku calisma (henuz arsivde degil; ayni saat damgali arsiv dosyasinin yerine gecer)
    runs = list_runs()
    runs = runs[runs["issued_utc"] != issued]
    cand = pd.concat([runs, pd.DataFrame({"issued_utc": [issued], "path": [None]})], ignore_index=True).sort_values("issued_utc")
    cand["issued_utc"] = pd.to_datetime(cand["issued_utc"])
    cand["gun"] = cand["issued_utc"].dt.tz_localize("UTC").dt.tz_convert(tz).dt.tz_localize(None).dt.normalize()
    son = cand.groupby("gun").tail(1).set_index("gun")  # her yerel gunun son calismasi
    cur_s = pd.Series(pd.to_numeric(cur["tahmin_p50_mw"]).to_numpy(), index=pd.to_datetime(cur["time_utc"]))
    memo: dict = {}

    def series(row) -> pd.Series | None:
        if row["path"] is None:
            return cur_s
        if row["path"] not in memo:
            memo[row["path"]] = _p50(row["path"], kw)
        return memo[row["path"]]

    day = out["time_local"].dt.normalize()
    yayin = {}
    for L in range(0, MAX_UFUK + 1):
        col = np.full(len(out), np.nan)
        for d in day.unique():
            d = pd.Timestamp(d)
            iday = d - pd.Timedelta(days=L)
            if iday not in son.index:
                continue
            s = series(son.loc[iday])
            if s is None:
                continue
            m = (day == d).to_numpy()
            col[m] = out.loc[m, "time_utc"].map(s).to_numpy()
            if np.isfinite(col[m]).any():
                yayin[(d, L)] = str(son.loc[iday, "issued_utc"])
        out[f"ufuk{L}_mw"] = col

    # Gunluk ozet
    g = out.groupby(day)

    def tot(c):
        return g[c].apply(lambda s: s.clip(lower=0).sum() if s.notna().sum() >= MIN_SAAT else np.nan)

    daily = pd.DataFrame(index=pd.DatetimeIndex(sorted(day.unique()), name="date"))
    daily["gerceklesen_mwh"] = tot("gerceklesen_mw")
    daily["kiyas_tahmin_mwh"] = tot("kiyas_tahmin_mw")
    for L in range(0, MAX_UFUK + 1):
        daily[f"ufuk{L}_mwh"] = tot(f"ufuk{L}_mw")
    for L in range(1, MAX_UFUK + 1):
        f = daily["ufuk0_mwh"] - daily[f"ufuk{L}_mwh"]
        daily[f"fark{L}_mwh"] = f
        daily[f"fark{L}_pct"] = 100 * f / daily[f"ufuk{L}_mwh"].where(daily[f"ufuk{L}_mwh"] > 0)
    for L in range(0, MAX_UFUK + 1):
        daily[f"ufuk{L}_yayin_utc"] = [yayin.get((d, L), "") for d in daily.index]
    daily = daily.reset_index()
    return {"history": out, "daily": daily, "guncel_yayin_utc": str(issued)}


def save(rev: dict, kw: dict) -> None:
    out = PATHS["out"]
    rev["history"].pipe(rnd, 1).to_csv(out / "tahmin_gun_gecmisi.csv", index=False, **kw)
    rev["daily"].pipe(rnd, 2).to_csv(out / "tahmin_gun_gecmisi_gunluk.csv", index=False, **kw)
    for eski in ("tahmin_revizyon_saatlik.csv", "tahmin_revizyon_gunluk.csv"):  # onceki surumun dosyalari
        (out / eski).unlink(missing_ok=True)
