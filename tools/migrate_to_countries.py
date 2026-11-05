r"""Eski klasor yapisini (tek ulke) yeni yapiya (countries/UA + ortak cache/) tasir. Bir kez calistirilir.

  python tools/migrate_to_countries.py            # tasir (once ne yapacagini listeler, onay ister)
  python tools/migrate_to_countries.py --evet     # onay sormadan
  python tools/migrate_to_countries.py --kuru     # yalnizca listeler, hicbir sey yapmaz
  python tools/migrate_to_countries.py --geri-al  # son tasimayi geri alir (tasima_kaydi.json'a gore)
  python tools/migrate_to_countries.py --kaynak "D:\EnergyPortal\UA_GES_Tahmin"
                                                  # YENI bir klasore acildiysa: eski proje klasorundeki veriyi
                                                  # buraya KOPYALAR (eski klasor oldugu gibi kalir)

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

Yerinde tasima ayni disk icinde yeniden adlandirmadir (veri kopyalanmaz, hizlidir). Hedefte ayni adli dosya varsa
(pakette gelen girdi xlsx'leri) sizin dosyaniz kullanilir, paketinki yedege alinir. --kaynak ile kopyalamada eski projenin verisi esastir: paketle gelen baslangic
dosyalarinin (seed) uzerine yazilir. Yedek/kayit klasoru: _tasima_yedek/<zaman>/.
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


def plan(src_root: Path = ROOT) -> list[tuple[Path, Path]]:
    """(kaynak, hedef) dosya/klasor tasima listesi. src_root: eski yapidaki proje (varsayilan: bu klasor)."""
    p: list[tuple[Path, Path]] = []
    d = src_root / "data"
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
        if (src_root / sub).exists():
            p.append((src_root / sub, UA / sub))
    return p


def kopyala(src: Path, dst: Path, kayit: list) -> int:
    """Dosya/klasoru kopyalar; hedefteki ayni adli dosyalarin uzerine yazar. Donus: uzerine yazilan dosya sayisi."""
    files = [src] if src.is_file() else [f for f in sorted(src.rglob("*")) if f.is_file()]
    ezilen = 0
    for f in files:
        t = dst if src.is_file() else dst / f.relative_to(src)
        ezilen += t.exists()
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)
    kayit.append([str(src), str(dst), len(files)])
    return ezilen


def tasi(src: Path, dst: Path, kayit: list, atlanan: list, yedek: Path) -> None:
    """Klasoru/dosyayi tasir. Hedefte ayni adli dosya varsa (pakette gelen girdi xlsx gibi) SIZIN dosyaniz kazanir:
    hedefteki dosya yedek/paket_dosyalari/ altina alinir, sizinki yerine konur. Her hareket kayda yazilir (--geri-al)."""
    def hareket(x: Path, y: Path) -> None:
        y.parent.mkdir(parents=True, exist_ok=True)
        x.rename(y)
        kayit.append([str(x), str(y)])

    if not dst.exists():
        hareket(src, dst)
        return
    files = [(src, dst)] if src.is_file() else [(f, dst / f.relative_to(src)) for f in sorted(src.rglob("*")) if f.is_file()]
    for f, t in files:
        if t.exists():
            hareket(t, yedek / "paket_dosyalari" / t.relative_to(ROOT))
            atlanan.append(str(t.relative_to(ROOT)))
        hareket(f, t)


def bos_klasorleri_sil(d: Path) -> None:
    if not d.exists():
        return
    for x in sorted(d.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if x.is_dir() and not any(x.iterdir()):
            x.rmdir()
    if d.is_dir() and not any(d.iterdir()):
        d.rmdir()


def config_birlestir(yedek: Path, notlar: list, src_root: Path = ROOT) -> None:
    eski_fp, yeni_fp = src_root / "config.json", UA / "config.json"
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
    if src_root == ROOT:
        eski_fp.rename(yedek / "config_eski_kok.json")
    else:
        shutil.copy2(eski_fp, yedek / "config_eski_kaynak.json")


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


def kaynaktan_kopyala(src_root: Path, a) -> None:
    if not (src_root / "data").exists() and not (src_root / "outputs").exists():
        sys.exit(f"HATA: {src_root} eski yapida bir proje degil (data\\ ya da outputs\\ yok).")
    if src_root == ROOT:
        sys.exit("HATA: --kaynak bu klasorun kendisi; yerinde tasima icin --kaynak vermeyin.")
    p = plan(src_root)
    print(f"Kaynak: {src_root}\nKopyalanacaklar (eski klasor degismez):")
    for s, d in p:
        print(f"  {s}  ->  {d.relative_to(ROOT)}")
    if (src_root / "config.json").exists():
        print("  config.json  ->  countries/UA/config.json ile birlestirilir")
    if a.kuru:
        return
    if not a.evet and input("Devam edilsin mi? [e/h] ").strip().lower() not in ("e", "evet", "y", "yes"):
        print("Iptal edildi.")
        return
    yedek = YEDEK / datetime.now().strftime("%Y%m%d_%H%M%S")
    yedek.mkdir(parents=True)
    kayit, notlar, ezilen = [], [], 0
    for s, d in p:
        ezilen += kopyala(s, d, kayit)
    config_birlestir(yedek, notlar, src_root)
    (yedek / "kopyalama_kaydi.json").write_text(json.dumps({"kaynak": str(src_root), "kopyalanan": kayit},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    for n in notlar:
        print("  " + n)
    print(f"Kopyalama tamam: {sum(k[2] for k in kayit)} dosya ({ezilen} tanesi paketle gelen baslangic dosyasinin yerine).")
    kontrol()
    print("Dogrulama icin (2-3 dk): python tests/golden/run_golden.py")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kuru", action="store_true")
    ap.add_argument("--evet", action="store_true")
    ap.add_argument("--geri-al", action="store_true")
    ap.add_argument("--kaynak", default=None, help="eski yapidaki proje klasoru (veri buraya kopyalanir)")
    a = ap.parse_args()
    if a.geri_al:
        geri_al()
        return
    if a.kaynak:
        kaynaktan_kopyala(Path(a.kaynak).resolve(), a)
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
            tasi(s, d, kayit, atlanan, yedek)
        config_birlestir(yedek, notlar)
        kalintilari_yedekle(yedek, kayit)
    finally:
        (yedek / "tasima_kaydi.json").write_text(json.dumps({"tasinan": kayit, "atlanan": atlanan}, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    bos_klasorleri_sil(ROOT / "data")
    for n in notlar:
        print("  " + n)
    if atlanan:
        print(f"  Not: {len(atlanan)} dosya pakette de vardi; sizin dosyaniz kullanildi, paketinki yedege alindi "
              f"({', '.join(Path(x).name for x in atlanan[:5])}{' ...' if len(atlanan) > 5 else ''})")
    print(f"Tasima tamam: {len(kayit)} oge. Kayit: {(yedek / 'tasima_kaydi.json').relative_to(ROOT)}")
    kontrol()
    print("Dogrulama icin (2-3 dk): python tests/golden/run_golden.py")


if __name__ == "__main__":
    main()
