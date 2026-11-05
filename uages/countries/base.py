"""Ulke adaptoru arayuzu: ulkeye ozgu her sey (hedef serisi, kiyas tahmini, bolgeler, harita) buradan gecer.

Ortak hesap cekirdegi (solar, pvmodel, weather, calibrate, optimize, forecast, longterm) ulke bilmez; yalnizca
asagidaki sozlesmeyi kullanir.

Hedef tablosu sozlesmesi (load_target):
  time_utc, time_local (tz-naive, UTC aralik basi / yerel), actual_mw, forecast_mw (kiyas: TSO/GPEE D+1),
  flag_curtail_day, flag_curtail_hour, flag_night_anomaly, use_for_training (bool), source (str)
Bolge tablosu sozlesmesi (load_regions): region (int), lat, lon, mw, mwp, weight (+ ulkeye ozel ek sutunlar)
Santral tablosu (load_plants): plant, phase, oblast, region, mw, mwp, lat, lon (+ ek sutunlar)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

# Natural Earth 1:50m ulke sinirlari (world-atlas TopoJSON). Kimlikler ISO 3166-1 sayisal (UA 804, HU 348, PL 616 ...).
OUTLINE_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json"


def world_atlas_outline(ids: set[str], cache_fp: Path, ek_kutu: tuple | None = None, ad: str = "") -> dict | None:
    """{'fill': dolgu halkalari, 'border': dis sinir cizgileri}, koordinatlar [lon, lat]. Onbellekte varsa oradan.
    ek_kutu (lon0, lat0, lon1, lat1): baska ulkeye ait olup tamamen bu kutuya dusen poligonlar da eklenir
    (UA: Kirim, uluslararasi taninan sinirlar). Ortak yaylar dolguda kalir ama cizilmez. Ag yoksa None."""
    from .. import net
    if cache_fp.exists():
        return json.loads(cache_fp.read_text(encoding="utf-8"))
    try:
        topo = requests.get(OUTLINE_URL, timeout=60, **net.kw()).json()
    except Exception as e:  # noqa: BLE001
        print(f"  {ad} siniri alinamadi: {e}")
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
        return all(ek_kutu[0] <= p[0] <= ek_kutu[2] and ek_kutu[1] <= p[1] <= ek_kutu[3] for p in pts)

    polys = []
    for g in topo["objects"]["countries"]["geometries"]:
        gp = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]] if g["type"] == "Polygon" else []
        if str(g.get("id")) in ids:
            polys += gp
        elif ek_kutu:
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
    cache_fp.write_text(json.dumps(out), encoding="utf-8")
    return out


class CountryAdapter:
    code: str = ""
    name: str = ""
    benchmark_label: str = "TSO resmi (D+1)"            # optimizasyon / son 7 gun tablolarindaki yontem adi
    benchmark_label_long: str = "TSO resmi tahmini (D+1)"  # gecmis dogrulama tablosundaki yontem adi
    # Dashboard sablonu Ukrayna metinleriyle yazildi; diger ulkeler (eski, yeni) metin ciftleriyle uyarlar (sirayla uygulanir)
    panel_metin: list[tuple[str, str]] = []

    # --- hedef serisi
    def init_store(self, cfg: dict, overwrite: bool = False) -> pd.DataFrame:
        raise NotImplementedError

    def update_store(self, cfg: dict, verbose: bool = False) -> pd.DataFrame:
        raise NotImplementedError

    def load_target(self, cfg: dict) -> pd.DataFrame:
        raise NotImplementedError

    # --- kapasite / konum
    def load_regions(self, cfg: dict) -> pd.DataFrame:
        raise NotImplementedError

    def load_plants(self, cfg: dict) -> pd.DataFrame:
        raise NotImplementedError

    # --- ulkeye ozel kurallar
    def monthly_k_mirror(self) -> dict[int, int]:
        """Gozlenmemis aylar icin k kaynagi {hedef ay: kaynak ay}. Bos = ayna yok (medyan kullanilir)."""
        return {}

    def map_outline(self) -> dict | None:
        """Dashboard harita siniri {'fill': [...], 'border': [...]} ([lon, lat]); yoksa None."""
        return None
