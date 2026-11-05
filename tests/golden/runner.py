"""Altin test calistiricisi (run_golden.py tarafindan alt surec olarak cagrilir; elle cagirmayin).

  python runner.py <proje_klasoru> <sabit_saat_utc> [--kayit <dosya>]

Proje klasorundeki `uages` paketini (referans ya da yeni) sabitlenmis saatle, ag erisimi kapali ve
yalnizca onbellekle calistirir: `all` (history + forecast + longterm + dashboard), ardindan `optimize`.
--kayit: okunan onbellek dosyalarinin listesini yazar (onbellek_listesi.txt uretmek icin).
"""
from __future__ import annotations

import os
import pathlib
import sys

proj = os.path.abspath(sys.argv[1])
FROZEN_STR = sys.argv[2]
kayit = sys.argv[sys.argv.index("--kayit") + 1] if "--kayit" in sys.argv else None

sys.path.insert(0, proj)
os.chdir(proj)
os.environ["UAGES_OFFLINE"] = "1"
os.environ.pop("UAGES_ULKE", None)

import pandas as pd  # noqa: E402
import requests  # noqa: E402

FROZEN = pd.Timestamp(FROZEN_STR)


def _now(tz=None):
    return FROZEN.tz_localize("UTC").tz_convert(tz) if tz else FROZEN


pd.Timestamp.now = staticmethod(_now)


def _no_net(*a, **k):
    raise RuntimeError(f"altin test: ag erisimi kapali ({a[0] if a else ''})")


requests.get = requests.post = _no_net
requests.Session.get = requests.Session.post = lambda self, *a, **k: _no_net(*a)

okunan: set[str] = set()
if kayit:
    _rt = pathlib.Path.read_text

    def _rt_log(self, *a, **k):
        s = str(self).replace("\\", "/")
        if "/cache/" in s:
            okunan.add(s.split("/cache/", 1)[1])
        return _rt(self, *a, **k)

    pathlib.Path.read_text = _rt_log

from uages import cli  # noqa: E402

# Hedef deposu guncellemesi (GPEE) kapali: depo, testin girdi kopyasidir
try:
    from uages import gpee as _g  # referans (eski) yapi
    _g.update_store = lambda cfg, **k: None
except ImportError:
    pass
try:
    from uages.countries import ua as _ua  # yeni yapi
    _ua.UkraineAdapter.update_store = lambda self, cfg, **k: None
except ImportError:
    pass

try:
    cli.main(["all"])
    cli.main(["optimize"])
finally:
    if kayit:
        pathlib.Path(kayit).write_text("\n".join(sorted(okunan)) + "\n", encoding="utf-8")
