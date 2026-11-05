"""outputs/ klasorundeki CSV'lerden tek dosyalik dashboard.html uretir (veri gomulu).

Sablon: uages/dashboard_template.html  ->  '/*__DATA__*/null' yer tutucusu JSON ile degistirilir.
Dashboard sadece bu klasordeki ciktilara bagimlidir; hesap motoruna dokunmaz (moduler).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from .config import PATHS
from .countries import get_adapter

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
def _read(name: str, kw: dict) -> pd.DataFrame | None:
    fp = PATHS["out"] / name
    if not fp.exists():
        return None
    return pd.read_csv(fp, sep=kw["sep"], decimal=kw["decimal"], encoding=kw["encoding"])


def _records(df: pd.DataFrame | None, cols: list[str] | None = None, nd: int = 2) -> dict | None:
    """Sutun-yonelimli kompakt JSON: {col: [..]}."""
    if df is None:
        return None
    if cols:
        df = df[[c for c in cols if c in df.columns]]
    out = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            out[c] = [None if (v is None or (isinstance(v, float) and math.isnan(v))) else round(float(v), nd)
                      for v in s.to_numpy()]
        elif pd.api.types.is_bool_dtype(s):
            out[c] = [bool(v) for v in s.to_numpy()]
        else:
            out[c] = [None if pd.isna(v) else str(v) for v in s.to_numpy()]
    return out


def build(cfg: dict) -> Path:
    from .cli import csv_kw, _load_state
    kw = csv_kw(cfg)
    st = _load_state()
    ad = get_adapter(cfg)
    regions = ad.load_regions(cfg)
    fc_h = _read("tahmin_7gun_saatlik.csv", kw)
    fc_r = _read("tahmin_7gun_bolge_saatlik.csv", kw)
    fc_d = _read("tahmin_7gun_gunluk.csv", kw)
    hd = _read("gecmis_gunluk.csv", kw)
    hm = _read("gecmis_aylik.csv", kw)
    wc = _read("hava_sinifi_performans.csv", kw)
    tb = _read("sicaklik_performans.csv", kw)
    val = _read("tahmin_dogrulama.csv", kw)
    rm = _read("bolge_aylik_model.csv", kw)
    mk = _read("kalibrasyon_aylik_k.csv", kw)
    ltc = _read("uzun_vade_klimatoloji_aylik.csv", kw)
    ltf = _read("uzun_vade_gelecek_aylar.csv", kw)
    pl = _read("santral_aylik_model.csv", kw)
    s7 = _read("son7gun_isabet.csv", kw)

    reg_sy = None
    if rm is not None:
        reg_sy = rm.groupby("region").agg(model_liste_mwh=("model_liste_mwh", "sum"),
                                          model_kalibre_mwh=("model_kalibre_mwh", "sum")).reset_index()
    regs = regions.merge(reg_sy, on="region", how="left") if reg_sy is not None else regions
    if "model_liste_mwh" in regs:
        regs["sy_liste"] = regs["model_liste_mwh"] / regs["mwp"]

    data = {
        "meta": {
            "project": cfg.get("project_name"),
            "generated_utc": str(pd.Timestamp.now("UTC").floor("min")),
            "forecast_issued_utc": st.get("forecast_issued_utc"),
            "history_run_utc": st.get("history_run_utc"),
            "summary": st.get("summary", {}),
            "calib": st.get("calib", {}),
            "weights": cfg["forecast"]["model_weights"],
            "lt_weights": st.get("longterm_weights", cfg["longterm"]["source_weights"]),
            "csv": {"sep": kw["sep"], "decimal": kw["decimal"]},
            "tz": cfg["local_tz"],
            "calib_mode": st.get("forecast_calib_mode", cfg["calibration"].get("mode", "mevcut")),
        },
        "son7": _records(s7, nd=2),
        "regions": _records(regs, nd=4),
        "fc_hourly": _records(fc_h),
        "fc_regions": _records(fc_r),
        "fc_daily": _records(fc_d),
        "hist_daily": _records(hd, nd=3),
        "hist_monthly": _records(hm, nd=4),
        "weather_class": _records(wc, nd=4),
        "temp_bins": _records(tb, nd=4),
        "validation": _records(val, nd=3),
        "monthly_k": _records(mk, nd=4),
        "lt_clim": _records(ltc, nd=3),
        "lt_future": _records(ltf, nd=3),
        "plants": _records(pl, nd=2),
        "ukraine": ad.map_outline(),  # sablon anahtari (harita siniri), ulkeden bagimsiz ad korunuyor
    }
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    js = js.replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", js)
    # Yerel dosya: tam belge (standart mod). Artifact yayini icin govde-only surum ayrica yazilir.
    full = "<!doctype html>\n<html lang=\"tr\">\n<head>\n" + html + "\n</html>\n"
    fp = PATHS["out"] / "dashboard.html"
    fp.write_text(full, encoding="utf-8")
    (PATHS["out"] / "dashboard_artifact.html").write_text(html, encoding="utf-8")
    return fp
