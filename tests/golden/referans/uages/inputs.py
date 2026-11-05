"""Girdi dosyalari: bolgeler, santral listesi, GPEE saatlik deposu."""
from __future__ import annotations

import pandas as pd

from .config import PATHS, inp

GPEE_STORE = PATHS["store"] / "gpee_hourly.csv"


def load_regions(cfg: dict) -> pd.DataFrame:
    df = pd.read_excel(inp(cfg, "regions_xlsx"), sheet_name="8_Regions")
    out = pd.DataFrame({
        "region": df["PV_Region"].astype(int),
        "lat": df["Weather_Latitude"].astype(float),
        "lon": df["Weather_Longitude"].astype(float),
        "mw": df["Capacity_MW"].astype(float),
        "mwp": df["Capacity_MWp_est"].astype(float),
        "phases": df["Plant_Phases"].astype(int),
        "placeholder_pct": df["Placeholder_Share_pct"].astype(float),
        "frontline_mw": df["Frontline_MW"].astype(float),
    }).sort_values("region").reset_index(drop=True)
    out["weight"] = out["mwp"] / out["mwp"].sum()
    return out


def load_plants(cfg: dict) -> pd.DataFrame:
    df = pd.read_excel(inp(cfg, "regions_xlsx"), sheet_name="Plant_Assignment")
    keep = ["Project Name", "Phase Name", "Capacity (MW)", "Capacity_Rating", "Capacity_MWp_est",
            "Latitude", "Longitude", "Placeholder_Flag", "State_Province_Clean", "Owner",
            "Frontline_Flag", "Status_2026", "Forecast_Status_v2", "PV_Region"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df = df.rename(columns={"Project Name": "plant", "Phase Name": "phase", "Capacity (MW)": "mw",
                            "Capacity_MWp_est": "mwp", "State_Province_Clean": "oblast",
                            "PV_Region": "region", "Latitude": "lat", "Longitude": "lon"})
    return df


def _flags_from_xlsx(g: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "time_utc": pd.to_datetime(g["Datetime_UTC"]),
        "time_local": pd.to_datetime(g["Datetime"]),
        "actual_mw": pd.to_numeric(g["GPEE_Actual_MW"], errors="coerce"),
        "forecast_mw": pd.to_numeric(g["GPEE_Forecast_MW"], errors="coerce"),
        "flag_curtail_day": g["flag_curtail_day"].fillna(False).astype(bool),
        "flag_curtail_hour": g["flag_curtail_hour"].fillna(False).astype(bool),
        "flag_night_anomaly": g["flag_night_regime_anomaly"].fillna(False).astype(bool),
        "use_for_training": g["Use_For_Training"].fillna(True).astype(bool),
        "source": "xlsx_v2",
    })


def init_gpee_store(cfg: dict, overwrite: bool = False) -> pd.DataFrame:
    """v2 xlsx'ten saatlik depoyu olusturur (bir kez). Sonraki gunler gpee.update_store ile eklenir."""
    if GPEE_STORE.exists() and not overwrite:
        return load_gpee(cfg)
    g = pd.read_excel(inp(cfg, "gpee_xlsx"), sheet_name="GPEE")
    df = _flags_from_xlsx(g).dropna(subset=["time_utc"]).sort_values("time_utc")
    df = df.drop_duplicates("time_utc", keep="last")
    save_gpee(df)
    return df


def save_gpee(df: pd.DataFrame) -> None:
    df = df.sort_values("time_utc").drop_duplicates("time_utc", keep="last")
    df.to_csv(GPEE_STORE, index=False, date_format="%Y-%m-%d %H:%M:%S")


def load_gpee(cfg: dict) -> pd.DataFrame:
    if not GPEE_STORE.exists():
        return init_gpee_store(cfg)
    df = pd.read_csv(GPEE_STORE, parse_dates=["time_utc", "time_local"])
    for c in ["flag_curtail_day", "flag_curtail_hour", "flag_night_anomaly", "use_for_training"]:
        df[c] = df[c].astype(str).str.lower().isin(["true", "1"])
    return df.sort_values("time_utc").reset_index(drop=True)
