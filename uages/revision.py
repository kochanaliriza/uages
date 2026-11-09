"""Tahmin revizyonu: ayni hedef gun icin onceki calismanin tahmini ile bugunku tahmin karsilastirmasi.

Her `forecast` calismasi outputs/arsiv/tahmin_YYYYMMDD_HHUTC.csv olarak saklanir (forecast.save_forecast).
Bu modul, yeni tahmin arsive yazilmadan ONCE arsivdeki calismalardan iki referans secer:
  - "dun"    : yaklasik 24 saat onceki calisma (yayin zamani simdi-24 sa'ye en yakin olan; en az 12 sa once)
  - "onceki" : bir onceki calisma (ayni gun icinde birden cok calistirma varsa son degisimi gosterir)
ve ayrica gecmis/bugun icin "gun oncesi" serisini kurar: her yerel gun icin o gun baslamadan once verilmis
son tahmin (gercekten elde olan D+1 tahmini; gerceklesenle kiyas icin).

Ciktilar:
  tahmin_revizyon_gunluk.csv : tarih, guncel ve referans P50 (MWh), fark (MWh, %), GHI ve bulut degisimi
  tahmin_revizyon_saatlik.csv: time_utc, time_local, dun_p50_mw, onceki_p50_mw, gun_oncesi_p50_mw
Arsiv bossa (ilk calisma) referans sutunlari bos kalir; hata vermez.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PATHS, rnd

RX = re.compile(r"tahmin_(\d{8})_(\d{2})UTC\.csv$")
MIN_SAAT = 20  # gunluk toplam icin en az bu kadar dolu saat (forecast.daily ile ayni kural)


def arsiv_dir() -> Path:
    return PATHS["out"] / "arsiv"


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


def _read(fp: Path, kw: dict) -> pd.DataFrame:
    df = pd.read_csv(fp, sep=kw["sep"], decimal=kw["decimal"], encoding=kw["encoding"])
    df["time_utc"] = pd.to_datetime(df["time_utc"])
    df["time_local"] = pd.to_datetime(df["time_local"])
    return df


def pick_refs(runs: pd.DataFrame, issued: pd.Timestamp) -> dict:
    """{'dun': satir|None, 'onceki': satir|None}; bugunku calisma (ayni saat damgasi) haric."""
    r = runs[runs["issued_utc"] < issued]
    out = {"dun": None, "onceki": None}
    if r.empty:
        return out
    out["onceki"] = r.iloc[-1]
    d = r[r["issued_utc"] <= issued - pd.Timedelta(hours=12)]
    if not d.empty:
        target = issued - pd.Timedelta(hours=24)
        out["dun"] = d.loc[(d["issued_utc"] - target).abs().idxmin()]
    return out


def _daily(df: pd.DataFrame, col: str = "tahmin_p50_mw") -> pd.DataFrame:
    g = df.groupby(df["time_local"].dt.normalize())
    d = pd.DataFrame({
        "saat": g[col].apply(lambda s: int(s.notna().sum())),
        "p50_mwh": g[col].apply(lambda s: s.clip(lower=0).sum()),
        "ghi_kwhm2": g["ghi"].apply(lambda s: s.sum() / 1000) if "ghi" in df else np.nan,
        "bulut_ort": g["cloud"].mean() if "cloud" in df else np.nan,
    })
    d.index.name = "date"
    return d[d["saat"] >= MIN_SAAT]


def build(fc: dict, cfg: dict, kw: dict) -> dict:
    """fc: forecast.build_forecast ciktisi (henuz arsive yazilmamis)."""
    tz = cfg["local_tz"]
    issued = pd.Timestamp(fc["issued_utc"]).floor("h")
    runs = list_runs()
    refs = pick_refs(runs, issued)
    h = fc["hourly"]
    cur = h[["time_utc", "time_local", "tahmin_p50_mw"] + [c for c in ("ghi", "cloud") if c in h]].copy()
    cur["time_utc"] = pd.to_datetime(cur["time_utc"])
    cur["time_local"] = pd.to_datetime(cur["time_local"])
    hourly = cur[["time_utc", "time_local"]].copy()

    frames = {}
    for key in ("dun", "onceki"):
        r = refs[key]
        if r is None:
            hourly[f"{key}_p50_mw"] = np.nan
            continue
        try:
            frames[key] = _read(r["path"], kw)
        except Exception as e:  # noqa: BLE001
            print(f"  UYARI: arsiv okunamadi ({r['path'].name}): {e}")
            hourly[f"{key}_p50_mw"] = np.nan
            continue
        hourly[f"{key}_p50_mw"] = cur["time_utc"].map(frames[key].set_index("time_utc")["tahmin_p50_mw"]).to_numpy()

    # Gun oncesi seri: her yerel gun D (bugun dahil) icin D'nin 00:00'indan (yerel) once verilmis son calisma
    hourly["gun_oncesi_p50_mw"] = np.nan
    today = pd.Timestamp.now(tz).tz_localize(None).normalize()
    cache: dict = {}
    for day in sorted(cur["time_local"].dt.normalize().unique()):
        day = pd.Timestamp(day)
        if day > today or runs.empty:
            continue
        start_utc = day.tz_localize(tz, ambiguous=False, nonexistent="shift_forward").tz_convert("UTC").tz_localize(None)
        cand = runs[(runs["issued_utc"] < start_utc) & (runs["issued_utc"] >= start_utc - pd.Timedelta(days=2))]
        if cand.empty:
            continue
        fp = cand.iloc[-1]["path"]
        if fp not in cache:
            try:
                cache[fp] = _read(fp, kw).set_index("time_utc")["tahmin_p50_mw"]
            except Exception:  # noqa: BLE001
                cache[fp] = None
        if cache[fp] is None:
            continue
        m = (cur["time_local"].dt.normalize() == day).to_numpy()
        hourly.loc[m, "gun_oncesi_p50_mw"] = cur.loc[m, "time_utc"].map(cache[fp]).to_numpy()

    # Gunluk revizyon: tahmin penceresindeki gunler (bugun + D+1..)
    days = pd.date_range(today, periods=cfg["forecast"]["days"], freq="D")
    dc = _daily(cur)
    daily = pd.DataFrame(index=pd.DatetimeIndex(days, name="date"))
    daily["guncel_p50_mwh"] = dc["p50_mwh"]
    daily["guncel_ghi_kwhm2"] = dc["ghi_kwhm2"]
    daily["guncel_bulut_ort"] = dc["bulut_ort"]
    for key in ("dun", "onceki"):
        if key in frames:
            dr = _daily(frames[key])
            daily[f"{key}_p50_mwh"] = dr["p50_mwh"]
            daily[f"{key}_fark_mwh"] = daily["guncel_p50_mwh"] - daily[f"{key}_p50_mwh"]
            daily[f"{key}_fark_pct"] = 100 * daily[f"{key}_fark_mwh"] / daily[f"{key}_p50_mwh"].where(daily[f"{key}_p50_mwh"] > 0)
            daily[f"{key}_ghi_fark_kwhm2"] = daily["guncel_ghi_kwhm2"] - dr["ghi_kwhm2"]
            daily[f"{key}_bulut_fark"] = daily["guncel_bulut_ort"] - dr["bulut_ort"]
        else:
            for s in ("p50_mwh", "fark_mwh", "fark_pct", "ghi_fark_kwhm2", "bulut_fark"):
                daily[f"{key}_{s}"] = np.nan
        daily[f"{key}_yayin_utc"] = str(refs[key]["issued_utc"]) if refs[key] is not None else ""
    daily = daily[daily["guncel_p50_mwh"].notna()]
    daily["guncel_yayin_utc"] = str(issued)
    return {"hourly": hourly, "daily": daily.reset_index(),
            "refs": {k: (str(v["issued_utc"]) if v is not None else None) for k, v in refs.items()}}


def save(rev: dict, kw: dict) -> None:
    out = PATHS["out"]
    rev["hourly"].pipe(rnd, 2).to_csv(out / "tahmin_revizyon_saatlik.csv", index=False, **kw)
    rev["daily"].pipe(rnd, 3).to_csv(out / "tahmin_revizyon_gunluk.csv", index=False, **kw)
