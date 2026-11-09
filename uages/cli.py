"""Komut satiri. Ornekler (proje klasorunde):

  python -m uages all              # hedef serisini guncelle (UA: GPEE) + gecmis analiz + 7 gun tahmin + uzun vade + dashboard
  python -m uages forecast         # sadece 7 gunluk tahmin + dashboard (kalibrasyon: son 'history' calismasindan)
  python -m uages history          # hedef serisini guncelle + gecmis performans + kalibrasyon
  python -m uages longterm         # gelecek 12 ay (ERA5 + PVGIS karma)
  python -m uages range 2027-01-01 2027-03-31   # istenen donem icin saatlik tipik beklenti CSV
  python -m uages dashboard        # outputs/ klasorunden dashboard.html uretir
  python -m uages fiyat [gun]      # son N gun (varsayilan 50): D-1 / gun ici tahmin sapmasi ve fiyat (SMF) korelasyonu
  python -m uages all --ulke UA    # ulke secimi (varsayilan UA; UAGES_ULKE ortam degiskeni de okunur)
Cevrim disi (sadece onbellek): UAGES_OFFLINE=1
Ciktilar: countries/<ULKE>/outputs/, gunluk/hata: countries/<ULKE>/logs/
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback

import pandas as pd

from . import analysis, forecast, longterm
from .config import ACTIVE, PATHS, csv_kw, eksik_girdiler, eski_duzen, load_config, rnd, tohumla  # noqa: F401  (csv_kw: dashboard buradan da alir)
from .countries import get_adapter


def _state_fp():
    return PATHS["out"] / "model_durumu.json"


def _save_state(upd: dict) -> None:
    st = _load_state()
    st.update(upd)
    _state_fp().write_text(json.dumps(st, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _load_state() -> dict:
    fp = _state_fp()
    return json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}


def cmd_update(cfg):
    ad = get_adapter(cfg)
    print(f"[1] Hedef deposu guncelleniyor ({ad.code})")
    ad.init_store(cfg)
    ad.update_store(cfg, verbose=False)


def cmd_history(cfg):
    cmd_update(cfg)
    print("[2] Gecmis hava + performans analizi")
    h = analysis.build_history(cfg, verbose=False)
    analysis.save_history(h, csv_kw(cfg))
    _save_state({"calib": h["calib"], "summary": h["summary"],
                 "history_run_utc": str(pd.Timestamp.now("UTC"))})
    s = h["summary"]
    print(f"    k_ref={s['k_ref']:.3f}  etkin MWp={s['mwp_etkin']:.0f}  son gerceklesen={s['son_gerceklesen']}")
    print(h["validation"].pipe(rnd, 2).to_string(index=False))
    # Ufka gore kalibrasyon + son 7 gun isabeti (her iki modda da hesaplanir; hata pipeline'i durdurmaz)
    print("[2b] Ufka gore kalibrasyon ve son 7 gun isabeti")
    try:
        from . import optimize
        r = optimize.refresh(cfg)
        _save_state({"ufuk_kalibrasyon_son_gun": r["kalibrasyon"]["fit_son_gun"]})
        print(r["son7"].pivot_table(index="ufuk", columns="yontem", values="nMAE_pct").pipe(rnd, 1).to_string())
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
    ad = get_adapter(cfg)
    regions = ad.load_regions(cfg)
    fc = forecast.build_forecast(cfg, st["calib"], regions, verbose=False)
    target = ad.load_target(cfg)
    forecast.attach_actuals(fc, target)
    # Revizyon: yeni tahmin arsive yazilmadan once arsivdeki onceki calismalarla karsilastirilir
    rev = None
    try:
        from . import revision
        rev = revision.build(fc, cfg, csv_kw(cfg), target)
        revision.save(rev, csv_kw(cfg))
    except Exception as e:  # noqa: BLE001
        print(f"    UYARI: tahmin revizyonu hesaplanamadi ({e})")
    forecast.save_forecast(fc, csv_kw(cfg))
    try:
        from . import revision
        revision.prune(cfg)
    except Exception as e:  # noqa: BLE001
        print(f"    UYARI: arsiv temizlenemedi ({e})")
    _save_state({"forecast_issued_utc": fc["issued_utc"], "forecast_calib_mode": fc["kalibrasyon_modu"]})
    print(f"    kalibrasyon modu: {fc['kalibrasyon_modu']}")
    print(fc["daily"].pipe(rnd, 1).to_string(index=False))
    if rev is not None:
        d = rev["daily"]
        d = d[d["date"] <= pd.Timestamp.now(cfg["local_tz"]).tz_localize(None).normalize()].tail(8)
        print("    gun ici (ufuk0) - gun oncesi (ufuk1) tahmin, MWh:")
        print(d[["date", "ufuk1_mwh", "ufuk0_mwh", "fark1_mwh", "fark1_pct", "gerceklesen_mwh"]].pipe(rnd, 1).to_string(index=False))
    return fc


def cmd_longterm(cfg):
    st = _load_state()
    if "calib" not in st:
        cmd_history(cfg)
        st = _load_state()
    print("[4] Uzun vade (ERA5 klimatoloji + PVGIS)")
    regions = get_adapter(cfg).load_regions(cfg)
    mk = pd.read_csv(PATHS["out"] / "kalibrasyon_aylik_k.csv", **csv_kw(cfg))
    lt = longterm.build_longterm(cfg, regions, st["calib"]["k_ref"], mk, verbose=False)
    longterm.save_longterm(lt, csv_kw(cfg))
    _save_state({"longterm_weights": lt["weights"], "longterm_run_utc": str(pd.Timestamp.now("UTC"))})
    print(lt["future"][["ay_basi", "karma_liste_mwh", "karma_kalibre_p50_mwh", "karma_kalibre_p90_mwh"]].pipe(rnd, 0).to_string(index=False))
    return lt


def cmd_range(cfg, start, end):
    st = _load_state()
    regions = get_adapter(cfg).load_regions(cfg)
    mk = pd.read_csv(PATHS["out"] / "kalibrasyon_aylik_k.csv", **csv_kw(cfg))
    lt = longterm.build_longterm(cfg, regions, st["calib"]["k_ref"], mk, verbose=False,
                                 period=(pd.Timestamp(start), pd.Timestamp(end)))
    fp = PATHS["out"] / f"beklenti_{start}_{end}.csv"
    lt["hourly"].pipe(rnd, 2).to_csv(fp, index=False, **csv_kw(cfg))
    print(f"  yazildi: {fp}")


def cmd_optimize(cfg, rebuild=False):
    from . import optimize
    print("[6] Kalibrasyon optimizasyonu (ufka gore; hicbir sey otomatik devreye girmez)")
    o = optimize.run(cfg, rebuild=rebuild)
    rep = o["rapor"]
    show = rep[rep["donem"].isin(["test", "son_7_gun"])].pivot_table(index=["donem", "ufuk"], columns="yontem", values="nMAE_pct")
    print(show.pipe(rnd, 2).to_string())
    print(f"  ayarlar: {o['aday']['ayarlar']}")
    print(f"  yazildi: {optimize.OUT_CSV_NAME}, {optimize.OUT_JSON_NAME}")
    return o


def cmd_fiyat(cfg, days=None):
    from . import fiyat
    print("[7] Tahmin sapmasi / revizyonu ve fiyat (SMF) korelasyonu")
    r = fiyat.run(cfg, days)
    print(r["isabet"].pipe(rnd, 2).to_string(index=False))
    if r.get("uretim") is not None:
        print("  Gunes uretimi ~ gunduz fiyati:")
        print(r["uretim"]["ozet"].pipe(rnd, 3).to_string(index=False))
        print(r["uretim"]["saat"].pipe(rnd, 2).to_string(index=False))
    print("  yazildi: fiyat_analiz_saatlik.csv, fiyat_analiz_gunluk.csv, fiyat_korelasyon_ozet.csv, fiyat_korelasyon_raporu.md")


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
    ap = argparse.ArgumentParser(prog="uages", description="Ulke bazli GES uretim analizi ve tahmini (varsayilan: Ukrayna)")
    ap.add_argument("komut", choices=["all", "update", "history", "forecast", "longterm", "range", "dashboard", "optimize", "fiyat"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--config", default=None, help="ayar dosyasi (varsayilan countries/<ULKE>/config.json)")
    ap.add_argument("--ulke", default=None, help="ulke kodu (varsayilan UAGES_ULKE ya da UA)")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config, a.ulke)
    except FileNotFoundError as e:
        print(f"HATA: {e}")
        sys.exit(2)
    from . import SERTIFIKA_DURUMU, net
    print(f"Ulke: {ACTIVE['code']}  ({PATHS['country']})")
    if net.VERIFY:
        print(f"  HTTPS sertifika dogrulamasi: acik ({'Windows/isletim sistemi deposu' if SERTIFIKA_DURUMU == 'aktif' else 'Python deposu'})")
    else:
        print("  UYARI: HTTPS sertifika dogrulamasi KAPALI (config ag.ssl_dogrulama=false). Acmak icin true yapin.")
    eski = eski_duzen()
    if eski:
        print(f"HATA: eski klasor yapisi bulundu ({', '.join(eski)}). Once TASIMA.bat ile verileri countries\\{ACTIVE['code']}\\ "
              "altina tasiyin (python tools/migrate_to_countries.py). Aksi halde yeni yapi bos depoyla calisir.")
        sys.exit(2)
    t = tohumla()
    if t:
        print(f"  Baslangic dosyalari kopyalandi (yeni kurulum): {', '.join(t)}")
    eksik = eksik_girdiler(cfg)
    if eksik:
        print("HATA: girdi dosyalari bulunamadi:\n  " + "\n  ".join(str(e) for e in eksik)
              + f"\nBu dosyalar countries\\{ACTIVE['code']}\\data\\input\\ altinda olmali. Eski proje klasorunuz varsa: "
              "python tools/migrate_to_countries.py --kaynak <eski klasor>")
        sys.exit(2)
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
        elif a.komut == "fiyat":
            cmd_fiyat(cfg, a.args[0] if a.args else None)
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
