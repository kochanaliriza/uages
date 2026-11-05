"""Ukrayna adaptoru: GPEE hedef serisi, 8 hava bolgesi (v2 xlsx), santral listesi, Ukrayna harita siniri.

Bu modul refactor oncesi `uages/inputs.py` (bolge/santral yukleyicileri), `uages/gpee.py` (-> ua_gpee.py) ve
`uages/dashboard.py` icindeki harita siniri kodunun birebir tasinmis halidir; hesaplar degismedi.
"""
from __future__ import annotations

import json

import pandas as pd
import requests

from .. import net
from ..config import PATHS, inp
from . import ua_gpee
from .base import CountryAdapter

# Natural Earth 1:50m ulke sinirlari (world-atlas TopoJSON); Ukrayna id=804. Bir kez indirilir.
# Natural Earth'un varsayilan gorunumu Kirim'i Rusya geometrisine koyar; panel uluslararasi taninan
# sinirlari gosterir, bu yuzden Kirim poligonu (asagidaki kutuya tamamen dusen poligon) Ukrayna'ya eklenir.
OUTLINE_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json"
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
        """{'fill': dolgu halkalari, 'border': dis sinir cizgileri}, koordinatlar [lon, lat].
        Ukrayna + Kirim arasindaki ortak yay (Perekop) dolguda kalir ama cizilmez.
        Ag yoksa ve onbellek bossa None (harita sinirsiz cizilir)."""
        fp = outline_path()
        if fp.exists():
            return json.loads(fp.read_text(encoding="utf-8"))
        try:
            topo = requests.get(OUTLINE_URL, timeout=60, **net.kw()).json()
        except Exception as e:  # noqa: BLE001
            print(f"  Ukrayna siniri alinamadi: {e}")
            return None
        (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
        arcs = []
        for arc in topo["arcs"]:  # delta kodlu, kuantize koordinatlar
            x = y = 0
            pts = []
            for dx, dy in arc:
                x, y = x + dx, y + dy
                pts.append([round(x * sx + tx, 3), round(y * sy + ty, 3)])
            arcs.append(pts)
        seg = lambda i: arcs[i] if i >= 0 else arcs[~i][::-1]  # noqa: E731

        def in_box(poly):
            pts = [p for i in poly[0] for p in seg(i)]
            return all(CRIMEA_BOX[0] <= p[0] <= CRIMEA_BOX[2] and CRIMEA_BOX[1] <= p[1] <= CRIMEA_BOX[3] for p in pts)

        polys = []
        for g in topo["objects"]["countries"]["geometries"]:
            gp = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]] if g["type"] == "Polygon" else []
            if str(g.get("id")) == "804":
                polys += gp
            else:
                polys += [p for p in gp if in_box(p)]
        fill, use = [], {}
        for poly in polys:
            for ring in poly:
                pts = []
                for i in ring:
                    s = seg(i)
                    pts.extend(s[1:] if pts else s)
                    use[i if i >= 0 else ~i] = use.get(i if i >= 0 else ~i, 0) + 1
                fill.append(pts)
        out = {"fill": fill, "border": [arcs[i] for i, n in use.items() if n == 1]}
        fp.write_text(json.dumps(out), encoding="utf-8")
        return out
