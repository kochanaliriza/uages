"""Optimizasyon icin Open-Meteo verisini onbellege ceker: ufka gore tahmin arsivi (Previous Runs) + uydu isinimi.

  python tools/fetch_optim_data.py [--pause 15] [--ulke UA]

Sira: Previous Runs en yeni ceyrekten geriye (son donem once hazir olsun), sonra uydu (yillik parcalar).
Ucretsiz katman limitlerine uyar: istekler arasi bekleme (varsayilan 15 sn ~ saatte 240 istek),
dakikalik/saatlik limitte bekler, gunluk limitte durur. Ayni komut tekrar calistirilinca onbellekteki parcalari atlar.
Kabaca maliyet: Previous Runs 8 bolge x 4 model x ~12 ceyrek, her biri ~19 istek esdegeri (29 degisken, ~92 gun);
uydu 8 bolge x 7 yil, her biri ~26 istek esdegeri. Toplam ~9.000; gunluk limit 10.000.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd

from uages.config import load_config
from uages.countries import get_adapter
from uages.dataset import chunks, pr_start, sat_start
from uages.sources import openmeteo as om


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", type=float, default=15.0)
    ap.add_argument("--ulke", default=None)
    a = ap.parse_args()
    cfg = load_config(ulke=a.ulke)
    regions = get_adapter(cfg).load_regions(cfg)
    models = list(cfg["forecast"]["model_weights"])
    yesterday = pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    jobs = [("prev", m, r, s, e) for s, e in chunks(pr_start(cfg), yesterday, "QS") for m in models for _, r in regions.iterrows()]
    jobs += [("sat", None, r, s, e) for s, e in chunks(sat_start(cfg), yesterday, "YS") for _, r in regions.iterrows()]
    print(f"{len(jobs)} parca ({sum(j[0] == 'prev' for j in jobs)} Previous Runs, {sum(j[0] == 'sat' for j in jobs)} uydu)", flush=True)
    t0, fetched = time.time(), 0
    for i, (kind, m, r, s, e) in enumerate(jobs, 1):
        n_cache = len(list(om.cache_dir().glob("*.json")))
        try:
            if kind == "prev":
                om.previous_runs(r["lat"], r["lon"], s, e, m)
            else:
                om.satellite(r["lat"], r["lon"], s, e)
        except om.DailyLimit:
            print(f"Gunluk limit doldu ({i - 1}/{len(jobs)} parca hazir). Yarin ayni komutla devam edin.", flush=True)
            sys.exit(3)
        except Exception as ex:  # noqa: BLE001
            print(f"  HATA {kind} {m} bolge {int(r['region'])} {s.date()}: {ex}", flush=True)
            continue
        if len(list(om.cache_dir().glob("*.json"))) > n_cache:  # yeni istek atildi -> nezaket beklemesi
            fetched += 1
            time.sleep(a.pause)
        if i % 25 == 0 or i == len(jobs):
            print(f"  {i}/{len(jobs)}  yeni istek {fetched}  {(time.time() - t0) / 60:.0f} dk", flush=True)
    print("Bitti.", flush=True)


if __name__ == "__main__":
    main()
