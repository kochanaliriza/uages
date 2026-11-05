"""Ukrayna adaptoru: GPEE hedef serisi, 8 hava bolgesi (v2 xlsx), santral listesi, Ukrayna harita siniri.

Bu modul refactor oncesi `uages/inputs.py` (bolge/santral yukleyicileri), `uages/gpee.py` (-> ua_gpee.py) ve
`uages/dashboard.py` icindeki harita siniri kodunun birebir tasinmis halidir; hesaplar degismedi.
"""
from __future__ import annotations

import pandas as pd

from ..config import PATHS, inp
from . import ua_gpee
from .base import CountryAdapter, world_atlas_outline

# Natural Earth'un varsayilan gorunumu Kirim'i Rusya geometrisine koyar; panel uluslararasi taninan
# sinirlari gosterir, bu yuzden Kirim poligonu (asagidaki kutuya tamamen dusen poligon) Ukrayna'ya eklenir.
CRIMEA_BOX = (32.3, 44.2, 36.8, 46.4)  # lon0, lat0, lon1, lat1


def outline_path():
    return PATHS["cache"] / "ukraine_outline_v2.json"


class UkraineAdapter(CountryAdapter):
    code = "UA"
    name = "Ukrayna"
    benchmark_label = "GPEE resmi (D+1)"
    benchmark_label_long = "GPEE resmi tahmini (D+1)"

    # --- hedef serisi (GPEE)
    def init_store(self, cfg: dict, overwrite: bool = False) -> pd.DataFrame:
        return ua_gpee.init_gpee_store(cfg, overwrite)

    def update_store(self, cfg: dict, verbose: bool = False) -> pd.DataFrame:
        return ua_gpee.update_store(cfg, verbose=verbose)

    def load_target(self, cfg: dict) -> pd.DataFrame:
        return ua_gpee.load_gpee(cfg)

    # --- bolgeler ve santraller
    def load_regions(self, cfg: dict) -> pd.DataFrame:
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

    def load_plants(self, cfg: dict) -> pd.DataFrame:
        df = pd.read_excel(inp(cfg, "regions_xlsx"), sheet_name="Plant_Assignment")
        keep = ["Project Name", "Phase Name", "Capacity (MW)", "Capacity_Rating", "Capacity_MWp_est",
                "Latitude", "Longitude", "Placeholder_Flag", "State_Province_Clean", "Owner",
                "Frontline_Flag", "Status_2026", "Forecast_Status_v2", "PV_Region"]
        df = df[[c for c in keep if c in df.columns]].copy()
        df = df.rename(columns={"Project Name": "plant", "Phase Name": "phase", "Capacity (MW)": "mw",
                                "Capacity_MWp_est": "mwp", "State_Province_Clean": "oblast",
                                "PV_Region": "region", "Latitude": "lat", "Longitude": "lon"})
        return df

    # --- ulkeye ozel kurallar
    def monthly_k_mirror(self) -> dict[int, int]:
        # Gozlenmemis Eki-Ara aylari icin gunes geometrisi simetrisi: Eki<-Mar, Kas<-Sub, Ara<-Oca
        return {10: 3, 11: 2, 12: 1}

    def map_outline(self) -> dict | None:
        """Ukrayna + Kirim (uluslararasi taninan sinirlar); Perekop ortak yayi dolguda kalir ama cizilmez."""
        return world_atlas_outline({"804"}, outline_path(), CRIMEA_BOX, "Ukrayna")
