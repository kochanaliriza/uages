"""Altin test: refactor sonrasi kodun, refactor oncesi kodla (tests/golden/referans) AYNI sonucu verdigini kanitlar.

  python tests/golden/run_golden.py                # referans + yeni kod, karsilastirma
  python tests/golden/run_golden.py --kayit         # onbellek_listesi.txt'yi yeniden uretir (referans koduyla)

Ne yapar:
  1. tests/golden/_calisma/ altinda iki gecici proje kurar: `ref` (dondurulmus eski kod, eski klasor yapisi) ve
     `yeni` (bu depodaki kod, kendi klasor yapisi). Ikisi de ayni girdileri alir:
       - girdi/gpee_hourly.csv (1 Kasim 2026 deposu), girdi/mevsim_k.json, girdi/ukraine_outline_v2.json
       - data/input/*.xlsx (projedeki canli kopya)
       - hava onbellegi: onbellek_listesi.txt'deki dosyalar canli onbellekten (cache/ ya da data/cache/) baglanir,
         onbellek_ek/ ile ustune yazilir (7 gunluk tahmin + ensemble: canli onbellekte her calismada degisir)
  2. Her ikisini saat 2026-11-01 15:22 UTC'ye sabitlenmis, ag kapali, `all` + `optimize` olarak calistirir.
  3. Tum cikti CSV'lerini ve kalibrasyon JSON'larini karsilastirir: sayisal fark <= 1e-9, metin birebir.
  4. Bilgi amacli: referans ciktilarini orijinal 1 Kasim ciktilariyla (beklenen/) da karsilastirir.
Cikis kodu 0 = ozdes. Sure ~2-3 dk; disk ~0,5 GB gecici (bitince silinir, --tut ile kalir).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
WORK = HERE / "_calisma"
FROZEN = "2026-11-01 15:22"
TOL = 1e-9
JSONS = ["kalibrasyon_ufuk.json", "mevsim_k.json", "kalibrasyon_aday.json", "model_durumu.json"]


def yeni_duzen(root: Path) -> bool:
    return (root / "countries" / "UA" / "config.json").exists()


def canli_onbellek() -> Path:
    for c in [REPO / "cache", REPO / "data" / "cache"]:
        if (c / "openmeteo").exists():
            return c
    sys.exit("HATA: canli hava onbellegi bulunamadi (cache/ ya da data/cache/)")


def canli_girdi() -> Path:
    for c in [REPO / "countries" / "UA" / "data" / "input", REPO / "data" / "input"]:
        if c.exists():
            return c
    sys.exit("HATA: girdi klasoru bulunamadi")


def bagla(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def hava_onbellegi(hedef: Path, liste: list[str]) -> list[str]:
    """hedef/{openmeteo,pvgis}: listedeki dosyalar + onbellek_ek. Eksik dosya adlarini dondurur."""
    src = canli_onbellek()
    ek = HERE / "onbellek_ek"
    eksik = []
    for rel in liste:
        if not rel.startswith(("openmeteo/", "pvgis/")):
            continue
        if (ek / rel).exists():
            continue
        if (src / rel).exists():
            bagla(src / rel, hedef / rel)
        else:
            eksik.append(rel)
    for f in ek.rglob("*.json"):
        bagla(f, hedef / f.relative_to(ek))
    return eksik


def kur(ad: str, kod_kaynagi: Path, liste: list[str]) -> tuple[Path, Path]:
    """Gecici proje kurar. Donus: (proje, cikti klasoru)."""
    p = WORK / ad
    shutil.copytree(kod_kaynagi / "uages", p / "uages", ignore=shutil.ignore_patterns("__pycache__"))
    g = HERE / "girdi"
    if yeni_duzen(kod_kaynagi):
        c = p / "countries" / "UA"
        c.mkdir(parents=True)
        shutil.copy2(kod_kaynagi / "countries" / "UA" / "config.json", c / "config.json")
        # Grafik penceresi (forecast.past_days) canli ayarda 7 gune cikti; dondurulmus onbellek referansin
        # istegiyle (3 gun) kayitli -> test kopyasinda referans degerine sabitlenir (hesap mantigi ayni)
        ref_cfg = json.loads((HERE / "referans" / "config.json").read_text("utf-8"))
        yc = json.loads((c / "config.json").read_text("utf-8"))
        yc["forecast"]["past_days"] = ref_cfg["forecast"]["past_days"]
        (c / "config.json").write_text(json.dumps(yc, ensure_ascii=False, indent=2), encoding="utf-8")
        data, out, wcache = c / "data", c / "outputs", p / "cache"
    else:
        shutil.copy2(kod_kaynagi / "config.json", p / "config.json")
        data, out, wcache = p / "data", p / "outputs", p / "data" / "cache"
    shutil.copytree(canli_girdi(), data / "input")
    (data / "store").mkdir(parents=True)
    shutil.copy2(g / "gpee_hourly.csv", data / "store" / "gpee_hourly.csv")
    (data / "cache").mkdir(parents=True, exist_ok=True)
    shutil.copy2(g / "ukraine_outline_v2.json", data / "cache" / "ukraine_outline_v2.json")
    out.mkdir(parents=True)
    shutil.copy2(g / "mevsim_k.json", out / "mevsim_k.json")
    eksik = hava_onbellegi(wcache, liste)
    if eksik:
        sys.exit(f"HATA: canli onbellekte {len(eksik)} dosya yok (ilk 5: {eksik[:5]}). "
                 "Onbellek silinmis olabilir; tools/fetch_optim_data.py ile yeniden doldurun.")
    return p, out


def calistir(proj: Path, kayit: Path | None = None) -> float:
    t0 = time.time()
    cmd = [sys.executable, str(HERE / "runner.py"), str(proj), FROZEN] + (["--kayit", str(kayit)] if kayit else [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
    r = subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (proj / "calisma.log").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:])
        sys.exit(f"HATA: {proj.name} calismasi basarisiz (log: {proj / 'calisma.log'})")
    return time.time() - t0


def csv_oku(fp: Path) -> pd.DataFrame:
    return pd.read_csv(fp, sep=";", decimal=",", encoding="utf-8-sig", low_memory=False)


def csv_fark(a: Path, b: Path) -> tuple[bool, str]:
    x, y = csv_oku(a), csv_oku(b)
    if list(x.columns) != list(y.columns) or x.shape != y.shape:
        return False, f"bicim farkli {x.shape} vs {y.shape}"
    num = x.select_dtypes("number").columns.intersection(y.select_dtypes("number").columns)
    d = 0.0
    if len(num):
        xa, ya = x[num].to_numpy(float), y[num].to_numpy(float)
        if not np.array_equal(np.isnan(xa), np.isnan(ya)):
            return False, "NaN konumlari farkli"
        d = float(np.nanmax(np.abs(xa - ya), initial=0.0))
    oth = [c for c in x.columns if c not in num]
    neq = sum(int((x[c].astype(str) != y[c].astype(str)).sum()) for c in oth)
    return (d <= TOL and neq == 0), f"maks_fark={d:.1e} metin_fark={neq}"


def json_fark(a, b, yol="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{yol}/{k}: anahtar eksik" for k in set(a) ^ set(b)]
        for k in set(a) & set(b):
            out += json_fark(a[k], b[k], f"{yol}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{yol}: uzunluk {len(a)} vs {len(b)}"]
        return sum((json_fark(x, y, f"{yol}[{i}]") for i, (x, y) in enumerate(zip(a, b))), [])
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if (a == b or abs(a - b) <= TOL or (a != a and b != b)) else [f"{yol}: {a} vs {b}"]
    return [] if a == b else [f"{yol}: {a!r} vs {b!r}"]


def karsilastir(ref: Path, yeni: Path, baslik: str, jsonlar=True) -> int:
    print(f"\n== {baslik}")
    hata = 0
    for fa in sorted(ref.glob("*.csv")):
        fb = yeni / fa.name
        ok, msg = csv_fark(fa, fb) if fb.exists() else (False, "dosya yok")
        hata += not ok
        print(f"  {'OK  ' if ok else 'FARK'} {fa.name:34s} {msg}")
    if jsonlar:
        for n in JSONS:
            if not (ref / n).exists():
                continue
            fb = yeni / n
            d = json_fark(json.loads((ref / n).read_text("utf-8")), json.loads(fb.read_text("utf-8"))) if fb.exists() else ["dosya yok"]
            hata += bool(d)
            print(f"  {'OK  ' if not d else 'FARK'} {n:34s} {'' if not d else '; '.join(d[:3])}")
    return hata


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kayit", action="store_true", help="onbellek_listesi.txt'yi referans koduyla yeniden uret")
    ap.add_argument("--tut", action="store_true", help="gecici klasoru silme")
    a = ap.parse_args()
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    liste_fp = HERE / "onbellek_listesi.txt"
    try:
        if a.kayit:
            # Kayit icin tum canli onbellek baglanir
            src = canli_onbellek()
            liste = [str(f.relative_to(src)).replace("\\", "/") for f in src.rglob("*.json")]
            p, _ = kur("ref", HERE / "referans", liste)
            calistir(p, kayit=WORK / "okunan.txt")
            okunan = [x for x in (WORK / "okunan.txt").read_text("utf-8").split() if x.startswith(("openmeteo/", "pvgis/"))]
            liste_fp.write_text("\n".join(sorted(okunan)) + "\n", encoding="utf-8")
            print(f"yazildi: {liste_fp} ({len(okunan)} dosya)")
            return
        liste = liste_fp.read_text("utf-8").split()
        p_ref, o_ref = kur("ref", HERE / "referans", liste)
        print(f"referans kod calisiyor ... {calistir(p_ref):.0f} sn")
        p_new, o_new = kur("yeni", REPO, liste)
        print(f"yeni kod calisiyor ({'countries/UA' if yeni_duzen(REPO) else 'eski duzen'}) ... {calistir(p_new):.0f} sn")
        hata = karsilastir(o_ref, o_new, "REFERANS (eski kod) vs YENI KOD — karar verici")
        bilgi = karsilastir(HERE / "beklenen", o_ref, "Bilgi: 1 Kasim orijinal ciktilari vs referans calisma", jsonlar=False)
        print(f"\nSONUC: {'OZDES — yeni kod referansla ayni sonucu veriyor' if hata == 0 else f'{hata} dosyada FARK'}"
              f"  (bilgi: orijinal 1 Kasim ciktilariyla {bilgi} fark)")
        sys.exit(0 if hata == 0 else 1)
    finally:
        if not a.tut:
            shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
