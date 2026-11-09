"""Tahmin dogrulama metrikleri: ufka / aya / hava sinifina gore nMAE, nRMSE, bias, skill score, pinball, kapsama.

Kullanim (proje klasorunde):
  python .claude/skills/pv-forecast/scripts/forecast_metrics.py countries/UA/outputs/gecmis_saatlik.csv \
      --actual actual_mw --pred model_gunoncesi_kalibre_mw forecast_mw --ref forecast_mw \
      --mask "elev>0 and not flag_curtail_model" --by month

  # Ufka gore (sutun 'lead' gun ya da saat), bant kapsamasi ile:
  python .../forecast_metrics.py arsiv_birlesik.csv --pred tahmin_p50_mw --lo tahmin_p10_mw --hi tahmin_p90_mw \
      --by lead --q-lo 0.1 --q-hi 0.9

Girdi: CSV (proje bicimi sep=';' decimal=',' otomatik algilanir) ya da parquet.
Normalizasyon: ortalama gerceklesen (maske icindeki saatler) -- raporda yazilir. --norm ile sabit deger (ör. kurulu guc) verilebilir.
Cikti: stdout tablo; --out ile CSV.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd


def read_any(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    with open(path, encoding="utf-8-sig") as f:
        head = f.readline()
    if head.count(";") > head.count(","):
        return pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig")
    return pd.read_csv(path, encoding="utf-8-sig")


def pinball(y, q_pred, q: float) -> float:
    d = y - q_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def block(df: pd.DataFrame, actual: str, preds: list[str], ref: str | None, norm: float | None,
          lo: str | None, hi: str | None, q_lo: float, q_hi: float) -> list[dict]:
    rows = []
    a_all = df[actual]
    n = norm if norm else float(a_all.mean())
    ref_rmse = None
    if ref:
        ok = a_all.notna() & df[ref].notna()
        ref_rmse = float(np.sqrt(((df.loc[ok, ref] - a_all[ok]) ** 2).mean())) if ok.any() else None
    for p in preds:
        ok = a_all.notna() & df[p].notna()
        if not ok.any():
            continue
        e = df.loc[ok, p] - a_all[ok]
        rmse = float(np.sqrt((e ** 2).mean()))
        r = {"yontem": p, "n_saat": int(ok.sum()), "norm_MW": round(n, 1),
             "nMAE_pct": e.abs().mean() / n * 100, "nRMSE_pct": rmse / n * 100, "bias_pct": e.mean() / n * 100}
        if ref_rmse and p != ref:
            r["skill_vs_ref"] = 1 - rmse / ref_rmse
        rows.append(r)
    if lo and hi and lo in df and hi in df:
        ok = a_all.notna() & df[lo].notna() & df[hi].notna()
        y = a_all[ok].to_numpy()
        rows.append({"yontem": f"bant[{lo},{hi}]", "n_saat": int(ok.sum()), "norm_MW": round(n, 1),
                     "kapsama_pct": float(((y >= df.loc[ok, lo]) & (y <= df.loc[ok, hi])).mean() * 100),
                     "beklenen_kapsama_pct": (q_hi - q_lo) * 100,
                     "genislik_pct": float((df.loc[ok, hi] - df.loc[ok, lo]).mean() / n * 100),
                     f"pinball_q{q_lo}_pct": pinball(y, df.loc[ok, lo].to_numpy(), q_lo) / n * 100,
                     f"pinball_q{q_hi}_pct": pinball(y, df.loc[ok, hi].to_numpy(), q_hi) / n * 100})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--actual", default="actual_mw")
    ap.add_argument("--pred", nargs="+", required=True)
    ap.add_argument("--ref", default=None, help="skill score referansi (ör. forecast_mw = GPEE)")
    ap.add_argument("--mask", default="elev>0", help="pandas query ifadesi; '' = maske yok")
    ap.add_argument("--by", default=None, help="lead | month | hour | <sutun adi>")
    ap.add_argument("--time-col", default="time_local")
    ap.add_argument("--norm", type=float, default=None)
    ap.add_argument("--lo", default=None)
    ap.add_argument("--hi", default=None)
    ap.add_argument("--q-lo", type=float, default=0.1)
    ap.add_argument("--q-hi", type=float, default=0.9)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    df = read_any(a.path)
    for c in df.columns:
        if df[c].dtype == object and df[c].astype(str).str.lower().isin(["true", "false"]).all():
            df[c] = df[c].astype(str).str.lower() == "true"
    if a.mask:
        df = df.query(a.mask)
    if a.time_col in df:
        t = pd.to_datetime(df[a.time_col])
        df = df.assign(month=t.dt.to_period("M").astype(str), hour=t.dt.hour)
    # Ortak saatler: tum yontemler ayni saatlerde kiyaslanir
    cols = [a.actual] + a.pred + ([a.ref] if a.ref and a.ref not in a.pred else [])
    df = df.dropna(subset=cols)
    if df.empty:
        sys.exit("Maske/ortak saat sonrasi veri kalmadi.")

    groups = [("tum", df)] if not a.by else list(df.groupby(a.by))
    rows = []
    for key, g in groups:
        for r in block(g, a.actual, a.pred, a.ref, a.norm, a.lo, a.hi, a.q_lo, a.q_hi):
            rows.append({(a.by or "grup"): key, **r})
    out = pd.DataFrame(rows)
    norm_txt = f"sabit {a.norm} MW" if a.norm else "maske icindeki ortalama gerceklesen (grup bazinda)"
    print(f"Maske: {a.mask or 'yok'} | normalizasyon: {norm_txt} | ortak saat: {len(df)}")
    print(out.round(3).to_string(index=False))
    if a.out:
        out.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
