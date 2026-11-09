"""Macaristan adaptoru: ENTSO-E sayacli GES gerceklesen (A75 B16) hedef, MAVIR gun oncesi tahmini (A69 A01) kiyas,
GEM Global Solar Power Tracker'dan 8 hava bolgesi (tools/hu_girdi_hazirla.py).

Hedef deposu: countries/HU/data/store/hedef_saatlik.csv (hedef tablosu sozlesmesi, bkz. base.py).
ENTSO-E 15 dakikalik degerleri saatlik ortalamaya cevrilir (bir saatte ceyrek eksikse saat NaN). Zamanlar UTC aralik basi;
time_local = Europe/Budapest duvar saati (DST gunleri 23/25 saat). Cati (HMKE) sistemleri hedefte yok.
"""
from __future__ import annotations

import pandas as pd

from ..config import PATHS, inp
from ..sources import entsoe
from .base import CountryAdapter, world_atlas_outline

BOOL = ["flag_curtail_day", "flag_curtail_hour", "flag_night_anomaly", "use_for_training"]


def store_path():
    return PATHS["store"] / "hedef_saatlik.csv"


class HungaryAdapter(CountryAdapter):
    code = "HU"
    name = "Macaristan"
    benchmark_label = "MAVIR resmi (D+1)"
    benchmark_label_long = "MAVIR resmi tahmini (D+1)"
    panel_metin = [
        ("<title>Ukrayna GES Tahmin Paneli</title>", "<title>Macaristan GES Tahmin Paneli</title>"),
        ("Ukrayna GES <span>", "Macaristan GES <span>"),
        ("Kyiv saati", "Budapeşte saati"),
        ("</b> Kyiv, ${ago", "</b> Budapeşte, ${ago"),
        ("GPEE yeşil tarife grubu, 2026", "ENTSO-E sayaçlı GES (çatı sistemleri hariç)"),
        ('<span><i style="background:var(--s2)"></i>Cephe hattında kapasitesi olan bölge</span>', ""),
        ("Ukrayna haritasında", "Macaristan haritasında"),
        ("GPEE yalnızca filo toplamını yayımlıyor", "ENTSO-E yalnızca ülke toplamını yayımlıyor"),
        ("GPEE saatleri Kyiv yerel saatinde (k-1):00–k:00 aralığıdır.",
         "ENTSO-E değerleri UTC'dir; 15 dakikalık değerlerin saatlik ortalaması alınır."),
        ("GPEE serisi yalnızca yeşil tarife grubunu kapsar ve grubun MW'ı yayımlanmıyor.",
         "ENTSO-E serisi yalnızca sayaçlı santralleri kapsar (çatı sistemleri hariç); santral listesi GEM'den (≥1 MW, Şubat 2026)."),
        ("<li>D+1 için GPEE'nin kendi tahmini bu modelden daha isabetli; modelin katkısı D+2…D+7 ufku, şeffaf hava girdisi ve uzun vadedir.</li>",
         "<li>D+1'de kıyas noktası MAVIR'in gün öncesi tahmini (ENTSO-E A69); 2026 tüm gündüz saatlerinde nMAE ~%12.</li>"),
        ("<li>Kış k'sı düşük (Ocak 0,44). Kar örtüsü, düşük güneş açısı ve kış şebeke kısıtları birbirinden ayrıştırılamıyor. Ekim–Aralık k'sı güneş geometrisi simetrisiyle Mart/Şubat/Ocak değerlerinden alınır.</li>",
         "<li>Kış (Aralık–Ocak) hataları yüksek; kar örtüsü modellenmiyor. MAVIR'in kendi tahmini de bu aylarda ~%40 nMAE.</li>"),
        ("<li>426 yer tutucu faz oblast merkezinde duruyor (tahmin MW'ının yaklaşık yarısı); bölge ağırlıkları bu yüzden kaba.</li>",
         "<li>GEM listesinde 2025 kurulumları eksik (araştırma gecikmesi); seviye farkını kayan k karşılar.</li>"),
        ("Bilgisayardaki <code>guncelle.bat</code> GPEE deposunu", "Bilgisayardaki <code>CALISTIR_HU.bat</code> ENTSO-E deposunu"),
        ("GPEE", "MAVIR"),
    ]

    # --- hedef serisi (ENTSO-E)
    def _cek(self, cfg: dict, bas: pd.Timestamp, bit: pd.Timestamp) -> pd.DataFrame:
        e = cfg["entsoe"]
        api, eic, tok = e.get("api") or entsoe.API, e["eic"], entsoe.token()
        act = entsoe.saatlik(entsoe.cek(api, tok, eic, "gerceklesen", bas, bit))
        fc = entsoe.saatlik(entsoe.cek(api, tok, eic, "tso_gun_oncesi", bas, bit))
        idx = act.index.union(fc.index)
        if len(idx) == 0:
            return pd.DataFrame()
        idx = pd.DatetimeIndex(idx, name="time_utc")
        df = pd.DataFrame({
            "time_utc": idx,
            "time_local": idx.tz_localize("UTC").tz_convert(cfg["local_tz"]).tz_localize(None),
            "actual_mw": act.reindex(idx).to_numpy(), "forecast_mw": fc.reindex(idx).to_numpy(),
            "flag_curtail_day": False, "flag_curtail_hour": False, "flag_night_anomaly": False,
            "use_for_training": True, "source": "entsoe",
        })
        return df

    def _save(self, df: pd.DataFrame) -> None:
        df = df.sort_values("time_utc").drop_duplicates("time_utc", keep="last")
        df.to_csv(store_path(), index=False, date_format="%Y-%m-%d %H:%M:%S")

    def init_store(self, cfg: dict, overwrite: bool = False) -> pd.DataFrame:
        if store_path().exists() and not overwrite:
            return self.load_target(cfg)
        bas = pd.Timestamp(cfg["entsoe"].get("baslangic", "2019-09-01"))
        bit = pd.Timestamp.now("UTC").tz_localize(None).normalize() + pd.Timedelta(days=2)
        print(f"  ENTSO-E hedef deposu ilk kurulum: {bas.date()} -> {bit.date()}")
        df = self._cek(cfg, bas, bit)
        if df.empty:
            raise RuntimeError("ENTSO-E'den hedef verisi gelmedi")
        self._save(df)
        return self.load_target(cfg)

    def update_store(self, cfg: dict, verbose: bool = False) -> pd.DataFrame:
        """Son gerceklesen gunden 3 gun geri -> yarin (MAVIR D+1 dahil). Yeni deger NaN ise eskisi korunur.
        ENTSO-E'ye ulasilamazsa uyari verip mevcut depoyla devam eder (UA'daki GPEE davranisiyla ayni)."""
        store = self.load_target(cfg)
        last = store.loc[store["actual_mw"].notna(), "time_utc"].max()
        bas = (last.normalize() if pd.notna(last) else pd.Timestamp(cfg["entsoe"].get("baslangic", "2019-09-01"))) - pd.Timedelta(days=3)
        bit = pd.Timestamp.now("UTC").tz_localize(None).normalize() + pd.Timedelta(days=2)
        try:
            new = self._cek(cfg, bas, bit)
        except (entsoe.EntsoeHata, SystemExit, Exception) as e:  # noqa: BLE001
            print(f"  UYARI: ENTSO-E guncellenemedi ({e}); mevcut depoyla devam")
            return store
        if new.empty:
            return store
        m = store.set_index("time_utc")
        n = new.set_index("time_utc")
        for c in ["actual_mw", "forecast_mw"]:
            n[c] = n[c].fillna(m[c].reindex(n.index))
        out = pd.concat([m[~m.index.isin(n.index)], n]).reset_index()
        self._save(out)
        if verbose:
            print(f"  ENTSO-E: {len(new)} saat guncellendi")
        return self.load_target(cfg)

    def load_target(self, cfg: dict) -> pd.DataFrame:
        if not store_path().exists():
            return self.init_store(cfg)
        df = pd.read_csv(store_path(), parse_dates=["time_utc", "time_local"])
        for c in BOOL:
            df[c] = df[c].astype(str).str.lower().isin(["true", "1"])
        return df.sort_values("time_utc").reset_index(drop=True)

    # --- bolgeler ve santraller (GEM)
    def load_regions(self, cfg: dict) -> pd.DataFrame:
        df = pd.read_csv(inp(cfg, "regions_csv"))
        out = df[["region", "lat", "lon", "mw", "mwp", "phases"]].copy()
        out["region"] = out["region"].astype(int)
        out = out.sort_values("region").reset_index(drop=True)
        out["weight"] = out["mwp"] / out["mwp"].sum()
        return out

    def load_plants(self, cfg: dict) -> pd.DataFrame:
        df = pd.read_csv(inp(cfg, "plants_csv"))
        return df.rename(columns={"county": "oblast"})

    def map_outline(self) -> dict | None:
        return world_atlas_outline({"348"}, PATHS["cache"] / "hungary_outline.json", None, "Macaristan")
