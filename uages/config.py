"""Ayar yukleme, aktif ulke ve klasor yollari.

Klasor yapisi (ulke basina):
  countries/<KOD>/config.json            ulke ayarlari
  countries/<KOD>/data/input/            girdi dosyalari (config.inputs yollari bu klasore goredir)
  countries/<KOD>/data/store/            hedef deposu (UA: gpee_hourly.csv)
  countries/<KOD>/data/cache/            ulkeye ozel onbellek (egitim tablosu, harita siniri)
  countries/<KOD>/outputs/  logs/
  cache/openmeteo/  cache/pvgis/         ortak hava onbellegi (anahtar = URL + parametre, ulkeler arasi paylasilir)

Aktif ulke: load_config(ulke=...) / --ulke / UAGES_ULKE ortam degiskeni; hicbiri yoksa UA.
PATHS sozlugu yerinde guncellenir; modullerde yollar cagri aninda okunur (import aninda sabitlenmez).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COUNTRY = "UA"
PATHS: dict[str, Path] = {}
ACTIVE = {"code": DEFAULT_COUNTRY}

# config.optimize anahtarlari yoksa kullanilan varsayilanlar (UA'nin tarihsel degerleri)
OPTIMIZE_DEFAULTS = {"test_start": "2026-05-01", "lag_days": 2,
                     "prev_runs_start": "2024-01-01", "satellite_start": "2020-07-01"}


def country_dir(code: str) -> Path:
    return ROOT / "countries" / code.upper()


def activate(code: str | None = None, mkdir: bool = True) -> str:
    """Aktif ulkeyi ayarlar ve PATHS'i gunceller. Donus: ulke kodu."""
    code = (code or os.environ.get("UAGES_ULKE") or DEFAULT_COUNTRY).upper()
    c = country_dir(code)
    PATHS.update({
        "country": c,
        "input": c / "data" / "input",
        "store": c / "data" / "store",
        "cache": c / "data" / "cache",
        "out": c / "outputs",
        "logs": c / "logs",
        "wcache": ROOT / "cache",
    })
    ACTIVE["code"] = code
    if mkdir:
        for k in ["store", "cache", "out", "logs", "wcache"]:
            PATHS[k].mkdir(parents=True, exist_ok=True)
    return code


activate(mkdir=False)


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None, ulke: str | None = None) -> dict:
    """Ulkeyi etkinlestirir ve countries/<KOD>/config.json'u (ya da verilen dosyayi) okur."""
    code = activate(ulke, mkdir=False)
    path = Path(path) if path else PATHS["country"] / "config.json"
    if not path.exists():
        mevcut = sorted(p.parent.name for p in (ROOT / "countries").glob("*/config.json"))
        raise FileNotFoundError(f"{code} icin ayar dosyasi yok: {path} (mevcut ulkeler: {', '.join(mevcut) or '-'})")
    activate(code)  # klasorleri yalnizca gecerli ulke icin olustur
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def region_pv(cfg: dict, region_id: int | str) -> dict:
    """Bolge bazli PV parametreleri (genel + override)."""
    over = cfg.get("region_overrides", {}).get(str(region_id), {})
    return _deep_merge(cfg["pv"], over)


def inp(cfg: dict, key: str) -> Path:
    """config.inputs[key] yolu, aktif ulke klasorune gore."""
    return PATHS["country"] / cfg["inputs"][key]


def opt(cfg: dict, key: str):
    """config.optimize[key]; yoksa OPTIMIZE_DEFAULTS."""
    return cfg.get("optimize", {}).get(key, OPTIMIZE_DEFAULTS[key])


def csv_kw(cfg: dict) -> dict:
    c = cfg.get("csv", {})
    return {"sep": c.get("sep", ","), "decimal": c.get("decimal", "."), "encoding": c.get("encoding", "utf-8")}


def rnd(df, n: int):
    """Yalnizca sayisal sutunlari yuvarlar (DataFrame.round ile ayni sonuc, tarih sutunlarinda uyari vermez)."""
    num = df.select_dtypes("number").columns
    return df.round({c: n for c in num}) if len(num) else df


def normalize_weights(w: dict) -> dict:
    w = {k: float(v) for k, v in w.items() if v and float(v) > 0}
    s = sum(w.values())
    return {k: v / s for k, v in w.items()} if s > 0 else {}
