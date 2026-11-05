"""Esdegerlik testi: optimize.py'deki vektorel kalibrasyon, azalimsiz ve config ayarlariyla calistirildiginda
calibrate.walk_forward (mevcut yontem) ile ayni saatlik tahmini uretmeli.

  python tools/check_vector_calib.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd

from uages import analysis, calibrate as cal, optimize as opt
from uages.config import load_config

cfg = load_config()
c = cfg["calibration"]
h = analysis.build_history(cfg, verbose=False)
df = h["hourly"]
ref = df["model_gunoncesi_kalibre_mw"].to_numpy(float)

d0 = df["time_local"].min().normalize()
di = (df["time_local"].dt.normalize() - d0).dt.days.to_numpy()
N = di.max() + 1
P = df["model_fc_mw"].to_numpy(float)
m = cal.training_mask(df, cfg, "model_fc_mw").to_numpy()
b = cal.kt_bin(df["kt_fc"])
cb = opt.cube(di, df["time_local"].dt.hour.to_numpy(), b, df["actual_mw"].to_numpy(float), np.nan_to_num(P), m, N)
path = opt.fit_path(cb, c["window_days"], c["shape_window_days"], c["shape_shrink_n"], None, c["shape_clip"])
night = np.full(N, h["calib"]["night"])
vec = opt.predict(path, di, df["time_local"].dt.hour.to_numpy(), b, P, df["elev"].to_numpy(float), 0, 2, night)

ok = np.isfinite(ref) & np.isfinite(vec) & (df["elev"].to_numpy() >= -3)
only_ref, only_vec = (np.isfinite(ref) & ~np.isfinite(vec)).sum(), (~np.isfinite(ref) & np.isfinite(vec) & (df["time_local"] >= h["summary"]["yuruyen_dogrulama_baslangic"]).to_numpy()).sum()
d = np.abs(ref[ok] - vec[ok])
print(f"karsilastirilan saat {ok.sum()}  maks fark {d.max():.6f} MW  ortalama fark {d.mean():.2e} MW")
print(f"yalniz mevcut yontemde olan {only_ref}, yalniz vektorelde olan (dogrulama donemi icinde) {only_vec}")
sys.exit(0 if d.max() < 1e-6 and only_ref == 0 else 1)
