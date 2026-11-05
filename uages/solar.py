"""Gunes geometrisi (NOAA), dunya disi isinim, egimli yuzey isinimi (Hay-Davies).

Zaman kurali (tum paket): saatlik seriler UTC *aralik basi* etiketiyle tutulur.
Deger, [t, t+1h) araliginin ortalamasidir. Gunes konumu aralik ortasinda (t+30 dk)
hesaplanir. Dashboard bu formulleri tekrar hesaplamaz; yalnizca outputs/ altindaki sonuclari gosterir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEG = np.pi / 180.0
SOLAR_CONST = 1367.0


def solar_position(times_utc: pd.DatetimeIndex, lat: float, lon: float) -> pd.DataFrame:
    """NOAA algoritmasi. times_utc: tz-naive UTC ya da tz-aware. Donus: zenith, azimuth (derece, kuzeyden saat yonu)."""
    t = pd.DatetimeIndex(times_utc)
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    jd = t.to_julian_date().to_numpy()
    jc = (jd - 2451545.0) / 36525.0
    l0 = np.mod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360.0)
    m = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    e = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    mr = m * DEG
    c = (np.sin(mr) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + np.sin(2 * mr) * (0.019993 - 0.000101 * jc) + np.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * np.sin(omega * DEG)
    mean_obliq = 23.0 + (26.0 + (21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))) / 60.0) / 60.0
    obliq = mean_obliq + 0.00256 * np.cos(omega * DEG)
    decl = np.arcsin(np.sin(obliq * DEG) * np.sin(app_long * DEG))
    y = np.tan(obliq * DEG / 2.0) ** 2
    l0r = l0 * DEG
    eot = 4.0 / DEG * (y * np.sin(2 * l0r) - 2 * e * np.sin(mr) + 4 * e * y * np.sin(mr) * np.cos(2 * l0r)
                       - 0.5 * y * y * np.sin(4 * l0r) - 1.25 * e * e * np.sin(2 * mr))
    minutes = t.hour.to_numpy() * 60.0 + t.minute.to_numpy() + t.second.to_numpy() / 60.0
    tst = np.mod(minutes + eot + 4.0 * lon, 1440.0)
    ha = tst / 4.0 - 180.0
    latr = lat * DEG
    cosz = np.sin(latr) * np.sin(decl) + np.cos(latr) * np.cos(decl) * np.cos(ha * DEG)
    cosz = np.clip(cosz, -1.0, 1.0)
    zen = np.arccos(cosz)
    sinz = np.maximum(np.sin(zen), 1e-6)
    cos_az = np.clip((np.sin(latr) * cosz - np.sin(decl)) / (np.cos(latr) * sinz), -1.0, 1.0)
    az = np.arccos(cos_az) / DEG
    az = np.where(ha > 0, np.mod(az + 180.0, 360.0), np.mod(540.0 - az, 360.0))
    doy = t.dayofyear.to_numpy()
    e0n = SOLAR_CONST * (1.0 + 0.033 * np.cos(2 * np.pi * doy / 365.0))
    return pd.DataFrame({"zenith": zen / DEG, "azimuth": az, "cosz": cosz, "e0n": e0n}, index=times_utc)


def interval_solar_position(start_times_utc: pd.DatetimeIndex, lat: float, lon: float) -> pd.DataFrame:
    """Aralik basi etiketli saatler icin aralik ortasindaki gunes konumu (index yine aralik basi)."""
    mid = pd.DatetimeIndex(start_times_utc) + pd.Timedelta(minutes=30)
    sp = solar_position(mid, lat, lon)
    sp.index = start_times_utc
    return sp


def extraterrestrial_horizontal(start_times_utc: pd.DatetimeIndex, lat: float, lon: float) -> pd.Series:
    sp = interval_solar_position(start_times_utc, lat, lon)
    return (sp["e0n"] * sp["cosz"].clip(lower=0)).rename("g0h")


def poa_hay_davies(ghi, dni, dhi, sp: pd.DataFrame, tilt: float, az_panel: float, albedo, iam_b0: float = 0.05):
    """Egimli duzlem isinimi. Donus: DataFrame(poa_global, poa_eff, poa_beam, poa_diff, poa_gnd, cos_aoi)."""
    ghi = np.asarray(ghi, dtype=float)
    dni = np.asarray(dni, dtype=float)
    dhi = np.asarray(dhi, dtype=float)
    cosz = sp["cosz"].to_numpy()
    zen = sp["zenith"].to_numpy() * DEG
    saz = sp["azimuth"].to_numpy() * DEG
    beta = tilt * DEG
    cos_aoi = np.cos(zen) * np.cos(beta) + np.sin(zen) * np.sin(beta) * np.cos(saz - az_panel * DEG)
    sun_up = cosz > 0.0
    # Gunes aralik ortasinda ufkun altindaysa (sabah/aksam ilk-son saat) tum isinim difuz kabul edilir
    dni_eff = np.where(sun_up, dni, 0.0)
    dhi_eff = np.where(sun_up, dhi, np.maximum(ghi, 0.0))
    beam = dni_eff * np.maximum(cos_aoi, 0.0)
    ai = np.clip(dni_eff / sp["e0n"].to_numpy(), 0.0, 1.0)
    rb = np.maximum(cos_aoi, 0.0) / np.maximum(cosz, 0.087)
    diff = dhi_eff * (ai * rb + (1.0 - ai) * (1.0 + np.cos(beta)) / 2.0)
    gnd = np.maximum(ghi, 0.0) * np.asarray(albedo, dtype=float) * (1.0 - np.cos(beta)) / 2.0
    poa = beam + diff + gnd
    # ASHRAE IAM, sadece direkt bilesene
    ca = np.clip(cos_aoi, 0.05, 1.0)
    iam = np.clip(1.0 - iam_b0 * (1.0 / ca - 1.0), 0.0, 1.0)
    iam = np.where(cos_aoi > 0, iam, 0.0)
    poa_eff = beam * iam + diff + gnd
    # NaN girdiler NaN kalir (eksik hava verisi 0 uretim gibi gorunmesin)
    return pd.DataFrame({
        "poa_global": poa, "poa_eff": poa_eff, "poa_beam": beam,
        "poa_diff": diff, "poa_gnd": gnd, "cos_aoi": cos_aoi,
    }, index=sp.index)
