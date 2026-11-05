"""Komut satiri. Ornekler (proje klasorunde):

  python -m uages all              # GPEE guncelle + gecmis analiz + 7 gun tahmin + uzun vade + dashboard
  python -m uages forecast         # sadece 7 gunluk tahmin + dashboard (kalibrasyon: son 'history' calismasindan)
  python -m uages history          # GPEE guncelle + gecmis performans + kalibrasyon
  python -m uages longterm         # gelecek 12 ay (ERA5 + PVGIS karma)
  python -m uages range 2027-01-01 2027-03-31   # istenen donem icin saatlik tipik beklenti CSV
  python -m uages dashboard        # outputs/ klasorunden dashboard.html uretir
Cevrim disi (sadece onbellek): UAGES_OFFLINE=1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback

import pandas as pd

from . import analysis, forecast, gpee, longterm
from .config import PATHS, load_config
from .inputs import init_gpee_store, load_gpee, load_regions

STATE = PATHS["out"] / "model_durumu.json"


def csv_kw(cfg: dict) -> dict:
    c = cfg.get("csv", {})
    return {"sep": c.get("sep", ","), "decimal": c.get("decimal", "."), "encoding": c.get("encoding", "utf-8")}


def _save_state(upd: dict) -> None:
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    st.update(upd)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def cmd_update(cfg):
    print("[1] GPEE deposu guncelleniyor")
    init_gpee_store(cfg)
    gpee.update_store(cfg, verbose=False)


def cmd_history(cfg):
    cmd_update(cfg)
    print("[2] Gecmis hava + performans analizi")
    h = analysis.build_history(cfg, verbose=False)
    analysis.save_history(h, csv_kw(cfg))
    _save_state({"calib": h["calib"], "summary": h["summary"],
                 "history_run_utc": str(pd.Timestamp.now("UTC"))})
    s = h["summary"]
    print(f"    k_ref={s['k_ref']:.3f}  etkin MWp={s['mwp_etkin']:.0f}  son gerceklesen={s['son_gerceklesen']}")
    print(h["validation"].round(2).to_string(index=False))
    # Ufka gore kalibrasyon + son 7 gun isabeti (her iki modda da hesaplanir; hata pipeline'i durdurmaz)
    print("[2b] Ufka gore kalibrasyon ve son 7 gun isabeti")
    try:
        from . import optimize
        r = optimize.refresh(cfg)
        _save_state({"ufuk_kalibrasyon_son_gun": r["kalibrasyon"]["fit_son_gun"]})
        print(r["son7"].pivot_table(index="ufuk", columns="yontem", values="nMAE_pct").round(1).to_string())
    except Exception as e:  # noqa: BLE001
        print(f"    UYARI: ufka gore kalibrasyon yenilenemedi ({e}); tahmin {cfg['calibration'].get('mode', 'mevcut')} moduyla devam eder")
    return h


def cmd_forecast(cfg):
    st = _load_state()
    if "calib" not in st:
        print("  Kalibrasyon yok -> once history calisiyor")
        cmd_history(cfg)
        st = _load_state()
    print("[3] 7 gunluk tahmin")
    regions = load_regions(cfg)
    fc = forecast.build_forecast(cfg, st["calib"], regions, verbose=False)
    forecast.attach_actuals(fc, load_gpee(cfg))
    forecast.save_forecast(fc, csv_kw(cfg))
    _save_state({"forecast_issued_utc": fc["issued_utc"], "forecast_calib_mode": fc["kalibrasyon_modu"]})
    print(f"    kalibrasyon modu: {fc['kalibrasyon_modu']}")
    print(fc["daily"].round(1).to_string(index=False))
    return fc


def cmd_longterm(cfg):
    st = _load_state()
    if "calib" not in st:
        cmd_history(cfg)
        st = _load_state()
    print("[4] Uzun vade (ERA5 klimatoloji + PVGIS)")
    regions = load_regions(cfg)
    mk = pd.read_csv(PATHS["out"] / "kalibrasyon_aylik_k.csv", **{k: v for k, v in csv_kw(cfg).items()})
    lt = longterm.build_longterm(cfg, regions, st["calib"]["k_ref"], mk, verbose=False)
    longterm.save_longterm(lt, csv_kw(cfg))
    _save_state({"longterm_weights": lt["weights"], "longterm_run_utc": str(pd.Timestamp.now("UTC"))})
    print(lt["future"][["ay_basi", "karma_liste_mwh", "karma_kalibre_p50_mwh", "karma_kalibre_p90_mwh"]].round(0).to_string(index=False))
    return lt


def cmd_range(cfg, start, end):
    st = _load_state()
    regions = load_regions(cfg)
    mk = pd.read_csv(PATHS["out"] / "kalibrasyon_aylik_k.csv", **csv_kw(cfg))
    lt = longterm.build_longterm(cfg, regions, st["calib"]["k_ref"], mk, verbose=False,
                                 period=(pd.Timestamp(start), pd.Timestamp(end)))
    fp = PATHS["out"] / f"beklenti_{start}_{end}.csv"
    lt["hourly"].round(2).to_csv(fp, index=False, **csv_kw(cfg))
    print(f"  yazildi: {fp}")


def cmd_optimize(cfg, rebuild=False):
    from . import optimize
    print("[6] Kalibrasyon optimizasyonu (ufka gore; hicbir sey otomatik devreye girmez)")
    o = optimize.run(cfg, rebuild=rebuild)
    rep = o["rapor"]
    show = rep[rep["donem"].isin(["test", "son_7_gun"])].pivot_table(index=["donem", "ufuk"], columns="yontem", values="nMAE_pct")
    print(show.round(2).to_string())
    print(f"  ayarlar: {o['aday']['ayarlar']}")
    print(f"  yazildi: {optimize.OUT_CSV.name}, {optimize.OUT_JSON.name}")
    return o


def cmd_dashboard(cfg):
    from . import dashboard
    print("[5] Dashboard")
    fp = dashboard.build(cfg)
    print(f"  yazildi: {fp}")


def main(argv=None):
    # Windows'ta dosyaya yonlendirilen cikti yerel kod sayfasina (cp1254) duser; gunluk UTF-8 kalsin
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(prog="uages", description="Ukrayna GES uretim analizi ve tahmini")
    ap.add_argument("komut", choices=["all", "update", "history", "forecast", "longterm", "range", "dashboard", "optimize"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    t0 = time.time()
    try:
        if a.komut == "update":
            cmd_update(cfg)
        elif a.komut == "history":
            cmd_history(cfg); cmd_dashboard(cfg)
        elif a.komut == "forecast":
            cmd_forecast(cfg); cmd_dashboard(cfg)
        elif a.komut == "longterm":
            cmd_longterm(cfg); cmd_dashboard(cfg)
        elif a.komut == "range":
            cmd_range(cfg, *a.args[:2])
        elif a.komut == "dashboard":
            cmd_dashboard(cfg)
        elif a.komut == "optimize":
            cmd_optimize(cfg, rebuild="yeniden" in a.args)
        elif a.komut == "all":
            cmd_history(cfg); cmd_forecast(cfg); cmd_longterm(cfg); cmd_dashboard(cfg)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        (PATHS["logs"] / "son_hata.txt").write_text(traceback.format_exc(), encoding="utf-8")
        sys.exit(1)
    print(f"Tamam ({time.time() - t0:.0f} sn)")


if __name__ == "__main__":
    main()
