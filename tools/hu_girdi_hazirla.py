r"""GEM Global Solar Power Tracker'dan bir ulkenin santral listesi ve hava bolgeleri (kapasite agirlikli k-ortalama).

  python tools/hu_girdi_hazirla.py --gem "Global-Solar-Power-Tracker-February-2026.xlsx"            # HU, 8 bolge
  python tools/hu_girdi_hazirla.py --gem ... --ulke HU --bolge 15                                   # karsilastirma icin

Cikti (countries/<KOD>/data/input/):
  <KOD>_PV_SANTRALLER.csv : plant, phase, county, region, mw, rating, mwp, lat, lon, start_year, location_accuracy, gem_phase_id
  <KOD>_PV_BOLGELER.csv   : region, lat, lon, mw, mwp, phases, weight, counties   (lat/lon = bolgenin kapasite agirlik merkezi)
Varsayimlar: yalnizca 'operating'; MWp = MWp/dc ise oldugu gibi, MWac ve bilinmeyen x dc_ac (varsayilan 1,2, config pv.dc_ac_ratio
ile ayni). Bolgeler batidan doguya numaralanir. k-ortalama deterministiktir (sabit tohum), koordinatlar km'ye olceklenir.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd

from uages.config import ROOT

ULKE_ADI = {"HU": "Hungary", "PL": "Poland", "SK": "Slovakia", "RO": "Romania", "MD": "Moldova", "UA": "Ukraine"}


def kmeans_agirlikli(X: np.ndarray, w: np.ndarray, k: int, tohum: int = 7, iter_: int = 200, deneme: int = 20) -> np.ndarray:
    """Agirlikli Lloyd + k-means++ baslangici; en dusuk agirlikli kare hatali cozum. Donus: etiketler."""
    rng = np.random.default_rng(tohum)
    en_iyi, en_iyi_sse = None, np.inf
    for _ in range(deneme):
        c = [X[rng.choice(len(X), p=w / w.sum())]]
        for _ in range(1, k):
            d2 = np.min(((X[:, None, :] - np.array(c)[None]) ** 2).sum(-1), axis=1) * w
            c.append(X[rng.choice(len(X), p=d2 / d2.sum())])
        c = np.array(c)
        for _ in range(iter_):
            lab = np.argmin(((X[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
            yeni = np.array([np.average(X[lab == j], axis=0, weights=w[lab == j]) if (lab == j).any() else c[j] for j in range(k)])
            if np.allclose(yeni, c):
                break
            c = yeni
        sse = float((((X - c[lab]) ** 2).sum(1) * w).sum())
        if sse < en_iyi_sse:
            en_iyi, en_iyi_sse = lab, sse
    return en_iyi


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gem", required=True, help="GEM Global Solar Power Tracker xlsx")
    ap.add_argument("--ulke", default="HU")
    ap.add_argument("--bolge", type=int, default=8)
    ap.add_argument("--dc-ac", type=float, default=1.2)
    a = ap.parse_args()
    u = pd.read_excel(a.gem, sheet_name="Utility-Scale (1 MW+)")
    p = u[(u["Country/Area"] == ULKE_ADI[a.ulke]) & (u["Status"] == "operating")].copy()
    p = p.dropna(subset=["Latitude", "Longitude", "Capacity (MW)"])
    if p.empty:
        sys.exit(f"HATA: {ULKE_ADI[a.ulke]} icin calisan santral yok")
    rating = p["Capacity Rating"].fillna("unknown").astype(str)
    p["mwp"] = np.where(rating.str.contains("dc", case=False), p["Capacity (MW)"], p["Capacity (MW)"] * a.dc_ac)
    lat0 = np.deg2rad(p["Latitude"].mean())
    X = np.column_stack([p["Longitude"] * 111.32 * np.cos(lat0), p["Latitude"] * 110.57])
    lab = kmeans_agirlikli(X, p["mwp"].to_numpy(float), a.bolge)
    # batidan doguya numara
    lon_m = pd.Series(p["Longitude"].to_numpy()).groupby(lab).apply(lambda s: s.mean())
    sira = {old: new + 1 for new, old in enumerate(lon_m.sort_values().index)}
    p["region"] = [sira[x] for x in lab]
    out = pd.DataFrame({
        "plant": p["Project Name"], "phase": p["Phase Name"], "county": p.get("Local area (taluk, county)"),
        "region": p["region"], "mw": p["Capacity (MW)"], "rating": rating, "mwp": p["mwp"].round(3),
        "lat": p["Latitude"], "lon": p["Longitude"], "start_year": p["Start year"],
        "location_accuracy": p["Location accuracy"], "gem_phase_id": p["GEM phase ID"],
    }).sort_values(["region", "plant"]).reset_index(drop=True)

    def merkez(g):
        w = g["mwp"]
        top = g.groupby("county")["mwp"].sum().sort_values(ascending=False)
        return pd.Series({"lat": round(float(np.average(g["lat"], weights=w)), 4), "lon": round(float(np.average(g["lon"], weights=w)), 4),
                          "mw": round(float(g["mw"].sum()), 1), "mwp": round(float(w.sum()), 1), "phases": int(len(g)),
                          "counties": ", ".join(f"{c} %{v / w.sum() * 100:.0f}" for c, v in top.head(3).items())})
    reg = out.groupby("region").apply(merkez).reset_index()
    reg["weight"] = (reg["mwp"] / reg["mwp"].sum()).round(6)
    reg = reg[["region", "lat", "lon", "mw", "mwp", "phases", "weight", "counties"]]
    d = ROOT / "countries" / a.ulke / "data" / "input"
    d.mkdir(parents=True, exist_ok=True)
    out.to_csv(d / f"{a.ulke}_PV_SANTRALLER.csv", index=False, encoding="utf-8")
    ek = "" if a.bolge == 8 else f"_{a.bolge}"
    reg.to_csv(d / f"{a.ulke}_PV_BOLGELER{ek}.csv", index=False, encoding="utf-8")
    print(f"{ULKE_ADI[a.ulke]}: {len(out)} santral, {out['mw'].sum():,.0f} MW ({out['mwp'].sum():,.0f} MWp tahmini), {a.bolge} bolge")
    print(reg.to_string(index=False))
    print(f"yazildi: {d}")


if __name__ == "__main__":
    main()
