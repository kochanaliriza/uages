"""Hava -> PV guc zinciri. Bolge (agirlik merkezi) bazinda calisir, filo = bolgeler toplami.

Zincir: GHI/DNI/DHI -> Hay-Davies POA -> IAM -> Faiman hucre sicakligi -> DC (gamma, kayiplar) -> AC (evirici verimi, AC kirpma)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .solar import interval_solar_position, poa_hay_davies, DEG

WX_COLS = ["ghi", "dni", "dhi", "temp", "wind"]


def _albedo(wx: pd.DataFrame, pv: dict) -> np.ndarray:
    base = np.full(len(wx), pv["albedo"], dtype=float)
    if "snow" in wx:
        snow = wx["snow"].to_numpy(dtype=float)
        base = np.where(np.nan_to_num(snow) > 0.01, pv["albedo_snow"], base)
    return base


def _dc_ac(poa_eff, poa_global, temp, wind, mwp, pv):
    tcell = temp + poa_global / (pv["faiman_u0"] + pv["faiman_u1"] * np.maximum(wind, 0.0))
    pdc = mwp * poa_eff / 1000.0 * (1.0 + pv["gamma_pdc"] * (tcell - 25.0)) * (1.0 - pv["dc_losses"])
    pac_cap = mwp / pv["dc_ac_ratio"]
    pac = np.clip(pdc * pv["inverter_eff"], 0.0, pac_cap)
    return tcell, pdc, pac


def run_pv(wx: pd.DataFrame, lat: float, lon: float, mwp: float, pv: dict) -> pd.DataFrame:
    """wx: UTC aralik-basi index; ghi,dni,dhi (W/m2), temp (C), wind (m/s), ops. snow (m). Donus MW."""
    sp = interval_solar_position(wx.index, lat, lon)
    poa = poa_hay_davies(wx["ghi"], wx["dni"], wx["dhi"], sp, pv["tilt_deg"], pv["azimuth_deg"],
                         _albedo(wx, pv), pv["iam_b0"])
    temp = wx["temp"].to_numpy(dtype=float)
    wind = wx["wind"].to_numpy(dtype=float)
    tcell, pdc, pac = _dc_ac(poa["poa_eff"].to_numpy(), poa["poa_global"].to_numpy(), temp, wind, mwp, pv)
    out = pd.DataFrame({
        "ghi": wx["ghi"].to_numpy(dtype=float),
        "poa": poa["poa_global"].to_numpy(),
        "tcell": tcell,
        "p_dc": pdc,
        "p_ac": pac,
        "elev": 90.0 - sp["zenith"].to_numpy(),
        "g0h": (sp["e0n"] * sp["cosz"].clip(lower=0)).to_numpy(),
    }, index=wx.index)
    return out


def run_pv_from_poa(poa_beam, poa_diff, poa_gnd, temp, wind, index, lat, lon, mwp, pv) -> pd.DataFrame:
    """PVGIS seriescalc gibi duzlem ici bilesenleri hazir veren kaynaklar icin."""
    sp = interval_solar_position(index, lat, lon)
    zen = sp["zenith"].to_numpy() * DEG
    saz = sp["azimuth"].to_numpy() * DEG
    beta = pv["tilt_deg"] * DEG
    cos_aoi = np.cos(zen) * np.cos(beta) + np.sin(zen) * np.sin(beta) * np.cos(saz - pv["azimuth_deg"] * DEG)
    ca = np.clip(cos_aoi, 0.05, 1.0)
    iam = np.where(cos_aoi > 0, np.clip(1.0 - pv["iam_b0"] * (1.0 / ca - 1.0), 0.0, 1.0), 1.0)
    beam = np.asarray(poa_beam, dtype=float)
    poa_g = beam + np.asarray(poa_diff, dtype=float) + np.asarray(poa_gnd, dtype=float)
    poa_eff = beam * iam + np.asarray(poa_diff, dtype=float) + np.asarray(poa_gnd, dtype=float)
    tcell, pdc, pac = _dc_ac(poa_eff, poa_g, np.asarray(temp, float), np.asarray(wind, float), mwp, pv)
    return pd.DataFrame({"poa": poa_g, "tcell": tcell, "p_dc": pdc, "p_ac": pac,
                         "elev": 90.0 - sp["zenith"].to_numpy()}, index=index)


def run_fleet(weather_by_region: dict, regions: pd.DataFrame, cfg: dict, region_pv_fn) -> dict:
    """weather_by_region: {region_id: wx DataFrame}. Donus: {'regions': {rid: df}, 'fleet': df}.
    Filo ghi/poa/temp: MWp agirlikli ortalama; p_ac: toplam."""
    res = {}
    for _, r in regions.iterrows():
        rid = int(r["region"])
        wx = weather_by_region.get(rid)
        if wx is None or wx.empty:
            continue
        res[rid] = run_pv(wx, r["lat"], r["lon"], r["mwp"], region_pv_fn(cfg, rid))
    fleet = aggregate_fleet(res, regions)
    return {"regions": res, "fleet": fleet}


def aggregate_fleet(res: dict, regions: pd.DataFrame) -> pd.DataFrame:
    if not res:
        return pd.DataFrame()
    w = regions.set_index("region")["mwp"]
    idx = None
    for df in res.values():
        idx = df.index if idx is None else idx.union(df.index)
    p = pd.Series(0.0, index=idx)
    wsum = pd.Series(0.0, index=idx)
    acc = {c: pd.Series(0.0, index=idx) for c in ["ghi", "poa", "tcell"]}
    for rid, df in res.items():
        d = df.reindex(idx)
        p = p + d["p_ac"]  # bir bolge eksikse filo toplami NaN olur (bilincli)
        ok = d["p_ac"].notna().astype(float) * w[rid]
        wsum = wsum + ok
        for c in acc:
            if c in d:
                acc[c] = acc[c] + d[c].fillna(0) * ok
    out = pd.DataFrame({"p_ac": p})
    for c in acc:
        out[c] = acc[c] / wsum.replace(0, np.nan)
    out["mwp_covered"] = wsum
    return out
