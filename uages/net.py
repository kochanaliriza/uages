"""HTTP istekleri icin ortak ag ayarlari.

HTTPS sertifika dogrulamasi: countries/<KOD>/config.json -> "ag": {"ssl_dogrulama": true|false}
ya da ortam degiskeni UAGES_SSL_DOGRULAMA=0/1 (config'e gore onceliklidir).
false: sertifika dogrulanmaz (kurumsal SSL denetimi yapan aglar icin). Bu durumda baglantinin gercekten Open-Meteo /
PVGIS / GPEE'ye gittigi garanti edilmez; yalnizca herkese acik veri cekildigi ve hicbir parola/anahtar gonderilmedigi
icin kabul edilebilir bir risktir. Mumkunse true + truststore (Windows sertifika deposu) tercih edin.
"""
from __future__ import annotations

import os

VERIFY = True


def ayarla(cfg: dict) -> bool:
    """Config/ortam degiskenine gore dogrulamayi ayarlar. Donus: dogrulama acik mi."""
    global VERIFY
    env = os.environ.get("UAGES_SSL_DOGRULAMA")
    VERIFY = (env != "0") if env is not None else bool(cfg.get("ag", {}).get("ssl_dogrulama", True))
    if not VERIFY:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass
    return VERIFY


def kw() -> dict:
    """requests.get/post'a eklenecek ayarlar."""
    return {"verify": VERIFY}
