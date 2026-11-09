"""Optimizasyon egitim tablosu: hedef serisi (UA: GPEE) saatlik x ufuk (D+1..D+7) x NWP modeli.

Her model ve ufuk icin Previous Runs havasi bolge bazinda PV zincirinden gecirilir ve filo toplami alinir.
Ayrica gunluk kalibrasyonla ayni bicimde "mevcut yontem" icin hava karmasi (weather.blend, config agirliklari)
uzerinden bir seri uretilir. Tablo uzun bicimdedir: satir = (saat, ufuk).

Sutunlar: time_utc, time_local, lead, p_<model>, ghi_<model>, p_legacy, ghi_legacy, g0h, elev,
          actual_mw, forecast_mw (resmi kiyas D+1; UA: GPEE), egitim maskesi bayraklari.
Tum guc degerleri liste MWp evreninde (kalibresiz) MW'tir.
"""
from __future__ import annotations

import pandas as pd

from . import weather
from .analysis import _fleet_extraterrestrial
from .config import PATHS, opt, region_pv
from .countries import get_adapter
from .pvmodel import aggregate_fleet, run_pv
from .sources import openmeteo as om

LEADS = range(1, 8)


def pr_start(cfg: dict) -> pd.Timestamp:
    """Previous Runs baslangici (config.optimize.prev_runs_start). UA: 2024-01-01 (ICON/GFS 2024-01-19, ECMWF 2024-03-06)."""
    return pd.Timestamp(opt(cfg, "prev_runs_start"))


def sat_start(cfg: dict) -> pd.Timestamp:
    """Uydu serisi baslangici (config.optimize.satellite_start). UA: 2020-07-01 (GPEE gerceklesen 2020-07 ortasindan)."""
    return pd.Timestamp(opt(cfg, "satellite_start"))


def table_path():
    return PATHS["cache"] / "egitim_ufuk.pkl"
WX = ["ghi", "dni", "dhi", "temp", "wind"]


def chunks(start: pd.Timestamp, end: pd.Timestamp, freq: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[(bas, bit)] takvim parcalari (QS = ceyrek, YS = yil), en yeni once.
    Gecmis parcalarin sinirlari `end`'den bagimsizdir -> onbellek anahtarlari gunden gune degismez;
    yalnizca son (devam eden) parca her gun yeniden cekilir."""
    edges = list(pd.date_range(start, end, freq=freq)) + [end + pd.Timedelta(days=1)]
    if edges[0] > start:
        edges.insert(0, start)
    out = [(a, b - pd.Timedelta(days=1)) for a, b in zip(edges[:-1], edges[1:]) if a < b]
    return out[::-1]


def yesterday() -> pd.Timestamp:
    return pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)


def lead_weather(r, model: str, end: pd.Timestamp, start: pd.Timestamp | None = None,
                 pr0: pd.Timestamp | None = None) -> pd.DataFrame:
    """Bir bolge ve model icin tum ufuklarin uzun tablosu. start=None -> pr0'dan (Previous Runs baslangici) ceyrek
    parcalarla (onbellek araci tools/fetch_optim_data.py ile ayni sinirlar); start verilirse tek istek (gunluk yenileme)."""
    spans = chunks(pr0, end, "QS") if start is None else [(start, end)]
    parts = [om.previous_runs(r["lat"], r["lon"], s, e, model) for s, e in spans]
    return pd.concat(parts, ignore_index=True).drop_duplicates(["time_utc", "lead"]).sort_values(["lead", "time_utc"])


def build(cfg: dict, end: pd.Timestamp | None = None, verbose: bool = True,
          start: pd.Timestamp | None = None, save: bool = True) -> pd.DataFrame:
    """start=None: tam tablo (Previous Runs baslangicindan), <ulke>/data/cache/egitim_ufuk.pkl'ye yazilir.
    start verilirse yalnizca o donem (gunluk kalibrasyon yenilemesi icin, ~16 istek esdegeri x 32)."""
    end = end or yesterday()
    ad = get_adapter(cfg)
    regions = ad.load_regions(cfg)
    pr0, sat0 = pr_start(cfg), sat_start(cfg)
    models = list(cfg["forecast"]["model_weights"])
    wx = {m: {} for m in models}
    for _, r in regions.iterrows():
        if verbose:
            print(f"  Bolge {int(r['region'])}: Previous Runs {', '.join(models)}", flush=True)
        for m in models:
            wx[m][int(r["region"])] = lead_weather(r, m, end, start, pr0)

    rows = []
    for L in LEADS:
        cols = {}
        frames_by_region = {}
        for m in models:
            res = {}
            for _, r in regions.iterrows():
                rid = int(r["region"])
                w = wx[m][rid]
                w = w[w["lead"] == L].set_index("time_utc")[WX]
                frames_by_region.setdefault(rid, {})[m] = w
                res[rid] = run_pv(w, r["lat"], r["lon"], r["mwp"], region_pv(cfg, rid))
            f = aggregate_fleet(res, regions)
            cols[f"p_{m}"], cols[f"ghi_{m}"] = f["p_ac"], f["ghi"]
        # Mevcut yontem: hava degiskenleri config agirliklariyla karistirilir, sonra PV (forecast.py ile ayni)
        res = {}
        for _, r in regions.iterrows():
            rid = int(r["region"])
            bw = weather.blend(frames_by_region[rid], cfg["forecast"]["model_weights"])
            res[rid] = run_pv(bw[WX], r["lat"], r["lon"], r["mwp"], region_pv(cfg, rid))
        f = aggregate_fleet(res, regions)
        cols["p_legacy"], cols["ghi_legacy"] = f["p_ac"], f["ghi"]
        d = pd.DataFrame(cols)
        d.index.name = "time_utc"
        rows.append(d.reset_index().assign(lead=L))
        if verbose:
            print(f"  Ufuk D+{L}: {len(d)} saat", flush=True)
    t = pd.concat(rows, ignore_index=True)

    # Gerceklesen hava modeli: uydu (SARAH3) isinimi + best_match D+1 sicaklik/ruzgar (Tcell'e etkisi kucuk).
    # Model tabanli kisit bayragi ve gerceklesen hava karsilastirmasi (optimizasyon adim a) icin.
    tw_model = "best_match" if "best_match" in models else models[0]
    res = {}
    for _, r in regions.iterrows():
        rid = int(r["region"])
        spans = chunks(sat0, end, "YS") if start is None else [(start, end)]
        sat = pd.concat([om.satellite(r["lat"], r["lon"], s, e) for s, e in spans])
        sat = sat[~sat.index.duplicated()].sort_index()
        tw = wx[tw_model][rid]
        tw = tw[tw["lead"] == 1].set_index("time_utc")[["temp", "wind"]]
        w = sat[["ghi", "dni", "dhi"]].join(tw, how="inner")
        res[rid] = run_pv(w, r["lat"], r["lon"], r["mwp"], region_pv(cfg, rid))
    fs = aggregate_fleet(res, regions)
    t["p_sat"] = t["time_utc"].map(fs["p_ac"])
    t["ghi_sat"] = t["time_utc"].map(fs["ghi"])

    idx = pd.DatetimeIndex(sorted(t["time_utc"].unique()))
    g0, el = _fleet_extraterrestrial(idx, regions)
    t["g0h"] = t["time_utc"].map(g0)
    t["elev"] = t["time_utc"].map(el)
    t["time_local"] = (pd.DatetimeIndex(t["time_utc"]).tz_localize("UTC").tz_convert(cfg["local_tz"]).tz_localize(None))

    g = ad.load_target(cfg).set_index("time_utc")
    keep = ["actual_mw", "forecast_mw", "flag_curtail_day", "flag_curtail_hour", "use_for_training"]
    t = t.join(g[keep], on="time_utc")
    for c in ["flag_curtail_day", "flag_curtail_hour"]:
        t[c] = t[c].fillna(False).astype(bool)
    t["use_for_training"] = t["use_for_training"].fillna(True).astype(bool)
    t = t[t["time_utc"] >= (pr0 if start is None else start)].sort_values(["lead", "time_utc"]).reset_index(drop=True)
    if save and start is None:
        t.to_pickle(table_path())
    return t


def load(cfg: dict, rebuild: bool = False, verbose: bool = True) -> pd.DataFrame:
    """Tablo bugun uretildiyse onu dondurur, yoksa (ya da rebuild) yeniden kurar."""
    fp = table_path()
    if fp.exists() and not rebuild:
        if pd.Timestamp(fp.stat().st_mtime, unit="s").normalize() >= pd.Timestamp.now().normalize():
            return pd.read_pickle(fp)
    return build(cfg, verbose=verbose)
