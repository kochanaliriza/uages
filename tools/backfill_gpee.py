"""GPEE gecmisini ayri bir dosyaya ceker, sonra ana depoya ekler.

  python tools/backfill_gpee.py fetch [--start 2020-07-01] [--end 2025-12-31] [--workers 3]
  python tools/backfill_gpee.py check      # gun basina saat sayisi, DST, eksik gun, uc degerler
  python tools/backfill_gpee.py merge      # data/store/gpee_backfill.csv -> gpee_hourly.csv (once yedek alinir)

Kaldigi yerden devam eder: dosyada olan gunler atlanir, hatali gunler sonraki calistirmada yeniden denenir.
Ana depodaki satirlar her zaman korunur; geri doldurma yalnizca depoda olmayan saatleri ekler.
GPEE gerceklesen serisi 2020-07 ortasindan itibaren yayimli (oncesi tamamen 0 -> NaN).
"""
import argparse
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
import requests

from uages.config import PATHS, load_config
from uages.gpee import fetch_day, local_hours
from uages.inputs import GPEE_STORE, load_gpee, save_gpee

BACKFILL = PATHS["store"] / "gpee_backfill.csv"
EMPTY = PATHS["store"] / "gpee_backfill_bos.txt"
_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def get_day(d: date, tz: str, pause: float):
    """Gun verisi; yayimlanmamissa None. Zaman asimi / ag hatasinda artan beklemeyle yeniden dener."""
    err = None
    for i in range(5):
        try:
            df = fetch_day(d, tz, _session())
            time.sleep(pause)
            return df.assign(source="gpee_backfill")
        except ValueError:
            return None
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"{d}: {err}")


def fetch(cfg, start: date, end: date, workers: int, pause: float):
    tz = cfg["local_tz"]
    done = set()
    if BACKFILL.exists():
        done |= set(pd.read_csv(BACKFILL, usecols=["time_local"], parse_dates=["time_local"])["time_local"].dt.date)
    if EMPTY.exists():
        done |= {date.fromisoformat(x) for x in EMPTY.read_text().split()}
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    todo = [d for d in days if d not in done]
    print(f"{len(days)} gun, {len(days) - len(todo)} hazir, {len(todo)} cekilecek ({workers} paralel)", flush=True)
    failed, t0 = [], time.time()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(get_day, d, tz, pause): d for d in todo}
        for i, f in enumerate(as_completed(futs), 1):
            d = futs[f]
            try:
                df = f.result()
            except Exception as e:  # noqa: BLE001
                failed.append(d)
                print(f"  HATA {e}", flush=True)
                continue
            if df is None:
                with open(EMPTY, "a") as fh:
                    fh.write(f"{d}\n")
            else:
                df.to_csv(BACKFILL, mode="a", header=not BACKFILL.exists(), index=False,
                          date_format="%Y-%m-%d %H:%M:%S")
            if i % 50 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"  {i}/{len(todo)}  {el / 60:.1f} dk  kalan ~{el / i * (len(todo) - i) / 60:.1f} dk", flush=True)
    print(f"Bitti. Hatali gun: {len(failed)} {sorted(failed)[:20]}", flush=True)


def check(cfg):
    tz = cfg["local_tz"]
    bf = pd.read_csv(BACKFILL, parse_dates=["time_utc", "time_local"])
    print(f"satir {len(bf)}  donem {bf.time_local.min()} .. {bf.time_local.max()}")
    print(f"tekrarlanan time_utc: {bf.time_utc.duplicated().sum()}")
    per_day = bf.groupby(bf.time_local.dt.date).size()
    exp = pd.Series({d: len(local_hours(d, tz)) for d in per_day.index})
    bad = per_day[per_day != exp]
    print(f"saat sayisi beklenenden farkli gun: {len(bad)}  {bad.head(10).to_dict()}")
    print(f"23/25 saatlik (DST) gunler: {sorted(str(d) for d in exp[exp != 24].index)}")
    full = pd.date_range(bf.time_local.min().normalize(), bf.time_local.max().normalize(), freq="D").date
    missing = sorted(set(full) - set(per_day.index))
    print(f"eksik gun: {len(missing)}  {[str(d) for d in missing[:20]]}")
    a = bf.set_index("time_local")["actual_mw"]
    print(f"gerceklesen NaN saat: {a.isna().sum()}  min {a.min():.1f}  max {a.max():.1f}")
    print("yil bazinda gerceklesen (GWh) / maks MW / GPEE tahmin (GWh):")
    y = bf.groupby(bf.time_local.dt.year).agg(act_gwh=("actual_mw", lambda s: s.clip(lower=0).sum() / 1000),
                                              act_max=("actual_mw", "max"),
                                              fc_gwh=("forecast_mw", lambda s: s.clip(lower=0).sum() / 1000),
                                              nan_saat=("actual_mw", lambda s: int(s.isna().sum())))
    print(y.round(1).to_string())


def merge(cfg):
    store = load_gpee(cfg)
    bf = pd.read_csv(BACKFILL, parse_dates=["time_utc", "time_local"]).drop_duplicates("time_utc", keep="last")
    new = bf[~bf["time_utc"].isin(store["time_utc"])]
    backup = GPEE_STORE.with_name(f"gpee_hourly_yedek_{pd.Timestamp.now():%Y%m%d_%H%M}.csv")
    shutil.copy(GPEE_STORE, backup)
    save_gpee(pd.concat([store, new], ignore_index=True))
    print(f"yedek: {backup.name}  depo {len(store)} -> {len(store) + len(new)} satir (+{len(new)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("komut", choices=["fetch", "check", "merge"])
    ap.add_argument("--start", default="2020-07-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.3)
    a = ap.parse_args()
    cfg = load_config()
    if a.komut == "fetch":
        fetch(cfg, date.fromisoformat(a.start), date.fromisoformat(a.end), a.workers, a.pause)
    elif a.komut == "check":
        check(cfg)
    else:
        merge(cfg)


if __name__ == "__main__":
    main()
