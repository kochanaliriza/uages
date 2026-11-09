"""GPEE ayristiricisinin DST gunlerinde xlsx v2 (elle duzeltilmis) ile uyumunu kontrol eder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import date
import pandas as pd
from uages.config import load_config
from uages.countries.ua_gpee import fetch_day, load_gpee
cfg = load_config(ulke="UA"); st = load_gpee(cfg).set_index("time_utc")
for d in [date(2026, 3, 28), date(2026, 3, 29), date(2026, 3, 30), date(2026, 7, 15)]:
    a = fetch_day(d).set_index("time_utc")
    j = a[["actual_mw", "forecast_mw"]].join(st[["actual_mw", "forecast_mw"]], rsuffix="_xlsx")
    da = (j.actual_mw - j.actual_mw_xlsx).abs().max(); df_ = (j.forecast_mw - j.forecast_mw_xlsx).abs().max()
    print(d, "saat", len(a), "maks fark gerceklesen", round(da, 3), "tahmin", round(df_, 3))
