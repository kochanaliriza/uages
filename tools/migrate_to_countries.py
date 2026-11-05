"""Eski klasor yapisini (tek ulke) yeni yapiya (countries/UA + ortak cache/) tasir. Bir kez calistirilir.

  python tools/migrate_to_countries.py            # tasir (once ne yapacagini listeler, onay ister)
  python tools/migrate_to_countries.py --evet     # onay sormadan
  python tools/migrate_to_countries.py --kuru     # yalnizca listeler, hicbir sey yapmaz
  python tools/migrate_to_countries.py --geri-al  # son tasimayi geri alir (tasima_kaydi.json'a gore)

Eski -> yeni:
  data/input/                -> countries/UA/data/input/
  data/store/                -> countries/UA/data/store/
  data/cache/openmeteo/      -> cache/openmeteo/          (ortak hava onbellegi)
  data/cache/pvgis/          -> cache/pvgis/
  data/cache/<diger dosya>   -> countries/UA/data/cache/  (egitim_ufuk.pkl, ukraine_outline_v2.json)
  outputs/                   -> countries/UA/outputs/
  logs/                      -> countries/UA/logs/
  config.json (kok)          -> yeni countries/UA/config.json ile karsilastirilir; sizin degistirdiginiz degerler
                                yeni dosyaya islenir, eski dosya yedege alinir
  uages/gpee.py, uages/inputs.py (eski kod kalintilari) -> yedege alinir

Tasima ayni disk icinde yeniden adlandirmadir (veri kopyalanmaz, hizlidir). Hedefte ayni adli dosya varsa uzerine
yazilmaz; atlanir ve listelenir. Yedek/kayit klasoru: _tasima_yedek/<zaman>/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = ROOT / "countries" / "UA"
YEDEK = ROOT / "_tasima_yedek"
YENI_ANAHTARLAR = {"country", "optimize"}


def plan() -> list[tuple[Path, Path]]:
    """(kaynak, hedef) dosya/klasor tasima listesi."""
    p: list[tuple[Path, Path]] = []
    d = ROOT / "data"
    for sub in ["input", "store"]:
        if (d / sub).exists():
            p.append((d / sub, UA / "data" / sub))
    c = d / "cache"
    if c.exists():
        for sub in ["openmeteo", "pvgis"]:
            if (c / sub).exists():
                p.append((c / sub, ROOT / "cache" / sub))
        for f in c.iterdir():
            if f.name not in ("openmeteo", "pvgis"):
                p.append((f, UA / "data" / "cache" / f.name))
    for sub in ["outputs", "logs"]:
        if (ROOT / sub).exists():
            p.append((ROOT / sub, UA / sub))
    return p


def tasi(src: Path, dst: Path, kayit: list, atlanan: list) -> None:
    """Klasoru tasir; hedef varsa icerigi dosya dosya birlestirir (uzerine yazmaz)."""
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        kayit.append([str(src), str(dst)])
        return
    if src.is_file():
        atlanan.append(str(dst))
        return
    for f in sorted(src.rglob("*")):
        if f.is_dir():
            continue
        t = dst / f.relative_to(src)
        if t.exists():
            atlanan.append(str(t))
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        f.rename(t)
        kayit.append([str(f), str(t)])


def bos_klasorleri_sil(d: Path) -> None:
    if not d.exists():
        return
    for x in sorted(d.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if x.is_dir() and not any(x.iterdir()):
            x.rmdir()
    if d.is_dir() and not any(d.iterdir()):
        d.rmdir()


def config_birlestir(yedek: Path, notlar: list) -> None:
    eski_fp, yeni_fp = ROOT / "config.json", UA / "config.json"
    if not eski_fp.exists():
        return
    eski = json.loads(eski_fp.read_text(encoding="utf-8"))
    yeni = json.loads(yeni_fp.read_text(encoding="utf-8"))
    farklar = []

    def birlestir(e: dict, y: dict, yol: str) -> None:
        for k, v in e.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and isinstance(y.get(k), dict):
                birlestir(v, y[k], f"{yol}{k}.")
            elif y.get(k) != v:
                farklar.append(f"{yol}{k}: {y.get(k)!r} -> {v!r}")
                y[k] = v

    birlestir({k: v for k, v in eski.items() if k not in YENI_ANAHTARLAR}, yeni, "")
    if farklar:
        shutil.copy2(yeni_fp, yedek / "countries_UA_config_paket.json")
        yeni_fp.write_text(json.dumps(yeni, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        notlar.append("config.json: sizin degerleriniz yeni dosyaya islendi:\n    " + "\n    ".join(farklar))
    else:
        notlar.append("config.json: degisiklik yok (paketteki ayarlarla ayni)")
    eski_fp.rename(yedek / "config_eski_kok.json")


def kalintilari_yedekle(yedek: Path, kayit: list) -> None:
    for rel in ["uages/gpee.py", "uages/inputs.py"]:
        f = ROOT / rel
        if f.exists():
            t = yedek / "eski_kod" / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            f.rename(t)
            kayit.append([str(f), str(t)])


def kontrol() -> None:
    sys.path.insert(0, str(ROOT))
    from uages.config import load_config
    from uages.countries import get_adapter
    cfg = load_config(ulke="UA")
    ad = get_adapter(cfg)
    t = ad.load_target(cfg)
    r = ad.load_regions(cfg)
    om = len(list((ROOT / "cache" / "openmeteo").glob("*.json")))
    pv = len(list((ROOT / "cache" / "pvgis").glob("*.json")))
    print(f"  kontrol: hedef deposu {len(t)} satir (son {t['time_local'].max()}), {len(r)} bolge, "
          f"onbellek openmeteo {om} / pvgis {pv} dosya")


def geri_al() -> None:
    kayitlar = sorted(YEDEK.glob("*/tasima_kaydi.json"))
    if not kayitlar:
        sys.exit("Geri alinacak tasima kaydi yok.")
    fp = kayitlar[-1]
    k = json.loads(fp.read_text(encoding="utf-8"))
    for src, dst in reversed(k["tasinan"]):
        s, d = Path(src), Path(dst)
        if d.exists() and not s.exists():
            s.parent.mkdir(parents=True, exist_ok=True)
            d.rename(s)
    eski_cfg = fp.parent / "config_eski_kok.json"
    if eski_cfg.exists():
        eski_cfg.rename(ROOT / "config.json")
    paket_cfg = fp.parent / "countries_UA_config_paket.json"
    if paket_cfg.exists():
        shutil.copy2(paket_cfg, UA / "config.json")
    fp.rename(fp.with_name("tasima_kaydi_geri_alindi.json"))
    print(f"Geri alindi ({len(k['tasinan'])} tasima). Eski kodu da geri istiyorsaniz eski proje kopyanizi geri yukleyin.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kuru", action="store_true")
    ap.add_argument("--evet", action="store_true")
    ap.add_argument("--geri-al", action="store_true")
    a = ap.parse_args()
    if a.geri_al:
        geri_al()
        return
    p = plan()
    kok_cfg = (ROOT / "config.json").exists()
    if not p and not kok_cfg:
        print("Tasinacak eski klasor yok; proje zaten yeni yapida.")
        kontrol()
        return
    print("Yapilacak tasimalar:")
    for s, d in p:
        print(f"  {s.relative_to(ROOT)}  ->  {d.relative_to(ROOT)}")
    if kok_cfg:
        print("  config.json (kok)  ->  countries/UA/config.json ile birlestirilir, eski dosya yedege")
    if a.kuru:
        return
    if not a.evet and input("Devam edilsin mi? [e/h] ").strip().lower() not in ("e", "evet", "y", "yes"):
        print("Iptal edildi.")
        return
    yedek = YEDEK / datetime.now().strftime("%Y%m%d_%H%M%S")
    yedek.mkdir(parents=True)
    kayit, atlanan, notlar = [], [], []
    try:
        for s, d in p:
            tasi(s, d, kayit, atlanan)
        config_birlestir(yedek, notlar)
        kalintilari_yedekle(yedek, kayit)
    finally:
        (yedek / "tasima_kaydi.json").write_text(json.dumps({"tasinan": kayit, "atlanan": atlanan}, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    bos_klasorleri_sil(ROOT / "data")
    for n in notlar:
        print("  " + n)
    if atlanan:
        print(f"  UYARI: hedefte zaten olan {len(atlanan)} dosya atlandi (kaynakta duruyor), ilk 5: {atlanan[:5]}")
    print(f"Tasima tamam: {len(kayit)} oge. Kayit: {(yedek / 'tasima_kaydi.json').relative_to(ROOT)}")
    kontrol()
    print("Dogrulama icin (2-3 dk): python tests/golden/run_golden.py")


if __name__ == "__main__":
    main()
