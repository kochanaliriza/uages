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

import pandas as pd


class CountryAdapter:
    code: str = ""
    name: str = ""
    benchmark_label: str = "TSO resmi (D+1)"            # optimizasyon / son 7 gun tablolarindaki yontem adi
    benchmark_label_long: str = "TSO resmi tahmini (D+1)"  # gecmis dogrulama tablosundaki yontem adi

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
