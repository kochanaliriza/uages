"""Ulke adaptoru kayit defteri.

config.json -> "country": {"code": "UA", "adapter": "ua"}. Yeni ulke: bu sozluge bir satir + adaptor modulu.
"""
from __future__ import annotations

import importlib

from .base import CountryAdapter

REGISTRY = {
    "ua": "uages.countries.ua:UkraineAdapter",
}
_instances: dict[str, CountryAdapter] = {}


def get_adapter(cfg: dict) -> CountryAdapter:
    name = cfg.get("country", {}).get("adapter", "ua").lower()
    if name not in _instances:
        if name not in REGISTRY:
            raise KeyError(f"Bilinmeyen ulke adaptoru: {name} (kayitli: {', '.join(REGISTRY)})")
        mod, cls = REGISTRY[name].split(":")
        _instances[name] = getattr(importlib.import_module(mod), cls)()
    return _instances[name]
