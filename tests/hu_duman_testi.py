"""Macaristan uctan uca duman testi: sahte ENTSO-E + Open-Meteo + PVGIS sunuculariyla (ag gerekmez).

  python tests/hu_duman_testi.py

Projenin gecici bir kopyasinda (tests/_hu_duman/) saati 2026-11-05 10:00 UTC'ye sabitleyip
`all --ulke HU` ve `optimize --ulke HU` calistirir; ciktilari ve zaman kuralini kontrol eder. Gercek veriye dokunmaz.
Sahte veri fiziksel olarak tutarlidir: gunes geometrisi x gun/bolge bulutlulugu; ufuk arttikca tahmin gurultusu artar.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
WORK = Path(__file__).resolve().parent / "_hu_duman"
FROZEN = pd.Timestamp("2026-11-05 10:00")


def kur() -> Path:
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.copytree(REPO / "uages", WORK / "uages", ignore=shutil.ignore_patterns("__pycache__"))
    (WORK / "countries" / "HU" / "data").mkdir(parents=True)
    shutil.copytree(REPO / "countries" / "HU" / "data" / "input", WORK / "countries" / "HU" / "data" / "input")
    c = json.loads((REPO / "countries" / "HU" / "config.json").read_text(encoding="utf-8"))
    c["longterm"]["era5_years"], c["longterm"]["pvgis_years"] = [2024, 2025], [2022, 2023]  # test hizi
    c["entsoe"]["baslangic"] = "2023-09-01"
    (WORK / "countries" / "HU" / "config.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    (WORK / "entsoe_token.txt").write_text("SAHTE-TOKEN-0000-0000-000000000000\n", encoding="utf-8")
    return WORK


def main() -> None:
    root = kur()
    sys.path.insert(0, str(root))
    os.chdir(root)
    os.environ.pop("UAGES_OFFLINE", None)
    import requests

    def _now(tz=None):
        return FROZEN.tz_localize("UTC").tz_convert(tz) if tz else FROZEN
    pd.Timestamp.now = staticmethod(_now)

    from uages.solar import solar_position
    reg = pd.read_csv(root / "countries/HU/data/input/HU_PV_BOLGELER.csv")

    def T(t: pd.DatetimeIndex, lat: float, lon: float) -> np.ndarray:
        """Bulut gecirgenligi: gun + bolge + saat bazli deterministik, 0,15..1."""
        d = (t.normalize() - pd.Timestamp("2015-01-01")).days.to_numpy()
        h = t.hour.to_numpy() // 4
        x = np.sin(d * 12.9898 + h * 4.1 + lat * 78.233 + lon * 3.7) * 43758.5453
        return 0.15 + 0.85 * (x - np.floor(x))

    def ghi(t_mid: pd.DatetimeIndex, lat, lon, t_lab=None):
        sp = solar_position(t_mid, lat, lon)
        cs = 1050 * np.clip(np.sin(np.radians(90 - sp["zenith"].to_numpy())), 0, None) ** 1.15
        return cs * T(t_lab if t_lab is not None else t_mid, lat, lon), sp

    # ---------------- ENTSO-E
    NS = "urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0"

    def entsoe(params):
        a, b = pd.Timestamp(params["periodStart"]), pd.Timestamp(params["periodEnd"])
        b = min(b, FROZEN.normalize() + pd.Timedelta(days=2))
        if a >= b:
            return b"<Acknowledgement_MarketDocument><Reason><code>999</code><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>"
        idx = pd.date_range(a, b, freq="15min", inclusive="left")
        p = np.zeros(len(idx))
        for _, r in reg.iterrows():
            g, _ = ghi(idx + pd.Timedelta(minutes=7.5), r.lat, r.lon, idx)
            p += r.mwp * 0.78 * g / 1000
        if params["documentType"] == "A69":
            z = np.sin(np.arange(len(idx)) * 0.37) * 0.08
            p = p * (1.0 + z)
        else:  # gerceklesen: gelecek yok
            p = np.where(idx < FROZEN.floor("h"), p, np.nan)
        pts = "".join(f"<Point><position>{i + 1}</position><quantity>{v:.2f}</quantity></Point>" for i, v in enumerate(p) if np.isfinite(v))
        if not pts:
            return b"<Acknowledgement_MarketDocument><Reason><code>999</code><text>No matching data found</text></Reason></Acknowledgement_MarketDocument>"
        return (f'<GL_MarketDocument xmlns="{NS}"><TimeSeries><curveType>A01</curveType><Period><timeInterval>'
                f'<start>{a:%Y-%m-%dT%H:%MZ}</start><end>{b:%Y-%m-%dT%H:%MZ}</end></timeInterval><resolution>PT15M</resolution>'
                f"{pts}</Period></TimeSeries></GL_MarketDocument>").encode()

    # ---------------- Open-Meteo
    def om_saatler(params):
        if "start_date" in params:
            a = pd.Timestamp(params["start_date"])
            b = min(pd.Timestamp(params["end_date"]) + pd.Timedelta(days=1), FROZEN.normalize() + pd.Timedelta(days=1))
        else:
            a = FROZEN.normalize() - pd.Timedelta(days=int(params.get("past_days", 0)))
            b = FROZEN.normalize() + pd.Timedelta(days=int(params.get("forecast_days", 7)))
        return pd.date_range(a + pd.Timedelta(hours=1), b, freq="h")  # aralik sonu etiketleri

    def degiskenler(t_end, lat, lon, gurultu=0.0, tohum=0.0):
        lab = t_end - pd.Timedelta(hours=1)
        g, sp = ghi(t_end - pd.Timedelta(minutes=30), lat, lon, lab)
        if gurultu:
            g = g * np.clip(1 + gurultu * np.sin(np.arange(len(g)) * 0.21 + tohum), 0.2, 2)
        cz = np.clip(np.cos(np.radians(sp["zenith"].to_numpy())), 0.08, None)
        dhi = np.minimum(g, 0.25 * g + 60 * (g > 0))
        dni = np.clip((g - dhi) / cz, 0, 1000)
        return {"shortwave_radiation": g, "direct_normal_irradiance": dni, "diffuse_radiation": dhi,
                "temperature_2m": 12 + 8 * np.sin(np.arange(len(g)) * 2 * np.pi / 24), "wind_speed_10m": np.full(len(g), 3.0),
                "cloud_cover": (1 - T(lab, lat, lon)) * 100, "snow_depth": np.zeros(len(g))}

    def openmeteo(url, params):
        lat, lon = float(params["latitude"]), float(params["longitude"])
        if "seasonal" in url:
            return {"daily": {"time": []}}
        t = om_saatler(params)
        times = [x.strftime("%Y-%m-%dT%H:%M") for x in t]
        h = {"time": times}
        if "ensemble" in url:
            for m in range(10):
                h[f"shortwave_radiation_member{m:02d}" if m else "shortwave_radiation"] = degiskenler(t, lat, lon, 0.15, m)["shortwave_radiation"].round(1).tolist()
            return {"hourly": h}
        istenen = params["hourly"].split(",")
        if "previous-runs" in url:
            for n in istenen:
                v, lead = n.rsplit("_previous_day", 1)
                h[n] = np.round(degiskenler(t, lat, lon, 0.05 * int(lead), int(lead))[v], 2).tolist()
            return {"hourly": h}
        models = params.get("models", "").split(",") if "api.open-meteo.com/v1/forecast" in url and "," in params.get("models", "") else [""]
        for i, m in enumerate(models):
            d = degiskenler(t, lat, lon, 0.04 * (i + 1), i)
            for v in istenen:
                if v in d:
                    h[v + (f"_{m}" if m else "")] = np.round(d[v], 2).tolist()
        return {"hourly": h}

    # ---------------- PVGIS
    def pvgis(url, params):
        lat, lon = float(params["lat"]), float(params["lon"])
        if url.endswith("tmy"):
            t = pd.date_range("2019-01-01", periods=8760, freq="h")
            d = degiskenler(t + pd.Timedelta(hours=1), lat, lon)
            rows = [{"time(UTC)": x.strftime("%Y%m%d:%H%M"), "G(h)": g, "Gb(n)": b, "Gd(h)": f, "T2m": 12.0, "WS10m": 3.0}
                    for x, g, b, f in zip(t, d["shortwave_radiation"], d["direct_normal_irradiance"], d["diffuse_radiation"])]
            return {"outputs": {"tmy_hourly": rows}}
        t = pd.date_range(f"{params['startyear']}-01-01", f"{params['endyear']}-12-31 23:00", freq="h")
        d = degiskenler(t + pd.Timedelta(hours=1), lat, lon)
        g = d["shortwave_radiation"] * 1.1
        rows = [{"time": (x + pd.Timedelta(minutes=10)).strftime("%Y%m%d:%H%M"), "Gb(i)": 0.7 * v, "Gd(i)": 0.28 * v, "Gr(i)": 0.02 * v,
                 "T2m": 12.0, "WS10m": 3.0, "P": 0.8 * v} for x, v in zip(t, g)]
        return {"outputs": {"hourly": rows}}

    istekler = {"entsoe": 0, "openmeteo": 0, "pvgis": 0}

    class R:
        def __init__(self, body, js=None, kod=200):
            self.status_code, self._js = kod, js
            self.content = body if body is not None else json.dumps(js).encode()
            self.text = self.content.decode("utf-8", "replace")

        def json(self):
            return self._js if self._js is not None else json.loads(self.content)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code} Client Error: Bad Request (sahte sunucu)")

    def fake_get(url, params=None, timeout=None, **k):
        if "entsoe" in url:
            istekler["entsoe"] += 1
            return R(entsoe(params))
        if "open-meteo" in url:
            istekler["openmeteo"] += 1
            # gercek servis gibi: arsiv uclari gelecek bitis tarihini reddeder
            if ("archive" in url or "historical-forecast" in url) and "end_date" in (params or {}):
                if pd.Timestamp(params["end_date"]) > FROZEN.normalize():
                    istekler["reddedilen"] = istekler.get("reddedilen", 0) + 1
                    return R(None, {"error": True, "reason": "end_date out of range"}, kod=400)
            return R(None, openmeteo(url, params))
        if "jrc.ec.europa" in url:
            istekler["pvgis"] += 1
            return R(None, pvgis(url, params))
        raise RuntimeError(f"beklenmeyen istek: {url}")

    requests.get = fake_get
    t0 = time.time()
    from uages import cli
    cli.main(["all", "--ulke", "HU"])
    cli.main(["optimize", "--ulke", "HU"])
    out = root / "countries" / "HU" / "outputs"
    print(f"\nistekler {istekler}  sure {time.time() - t0:.0f} sn")

    # ---------------- kontroller
    hata = []
    beklenen = ["gecmis_saatlik.csv", "tahmin_7gun_saatlik.csv", "tahmin_7gun_gunluk.csv", "uzun_vade_gelecek_aylar.csv",
                "optimizasyon_raporu.csv", "son7gun_isabet.csv", "kalibrasyon_ufuk.json", "mevsim_k.json", "dashboard.html", "model_durumu.json"]
    for f in beklenen:
        if not (out / f).exists():
            hata.append(f"eksik cikti: {f}")
    st = json.loads((out / "model_durumu.json").read_text(encoding="utf-8"))
    lag = st["summary"]["zaman_kaymasi_korelasyon"]
    tepe = max(lag, key=lambda k: lag[k] if lag[k] == lag[k] else -1)
    print("zaman kaymasi korelasyonu:", {k: round(v, 3) for k, v in lag.items()}, "tepe:", tepe)
    if str(tepe) != "0":
        hata.append(f"zaman kaymasi tepe noktasi 0 degil: {tepe}")
    rap = pd.read_csv(out / "optimizasyon_raporu.csv", sep=";", decimal=",", encoding="utf-8-sig")
    t = rap[rap.donem == "test"].pivot_table(index="ufuk", columns="yontem", values="nMAE_pct")
    print(t.round(2).to_string())
    if "MAVIR resmi (D+1)" not in t.columns:
        hata.append("kiyas etiketi 'MAVIR resmi (D+1)' raporda yok")
    if not np.isfinite(t.to_numpy()[:, :]).any():
        hata.append("test nMAE degerleri bos")
    h = (out / "dashboard.html").read_text(encoding="utf-8")
    for s in ["Macaristan GES", "Budapeşte saati", "MAVIR"]:
        if s not in h:
            hata.append(f"panelde '{s}' yok")
    if "GPEE" in h or "Ukrayna haritas" in h:
        hata.append("panelde Ukrayna metni kalmis")
    fc = pd.read_csv(out / "tahmin_7gun_saatlik.csv", sep=";", decimal=",", encoding="utf-8-sig", parse_dates=["time_utc", "time_local"])
    off = (fc["time_local"] - fc["time_utc"]).dt.total_seconds().div(3600).unique()
    print("tahmin yerel-UTC farki (saat):", sorted(off))
    if not set(off) <= {1.0, 2.0}:
        hata.append(f"Budapeste saat farki beklenmedik: {off}")
    store = pd.read_csv(root / "countries/HU/data/store/hedef_saatlik.csv", parse_dates=["time_utc"])
    if store["time_utc"].duplicated().any():
        hata.append("hedef deposunda tekrar eden saat var")
    print(f"hedef deposu {len(store)} saat, {store.time_utc.min()} -> {store.time_utc.max()}, gerceklesen son {store.dropna(subset=['actual_mw']).time_utc.max()}")
    print("\nSONUC:", "TAMAM" if not hata else "HATA\n  " + "\n  ".join(hata))
    sys.exit(1 if hata else 0)


if __name__ == "__main__":
    main()
