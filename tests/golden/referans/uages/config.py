"""Ayar yukleme ve klasor yollari."""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATHS = {
    "store": ROOT / "data" / "store",
    "cache": ROOT / "data" / "cache",
    "out": ROOT / "outputs",
    "logs": ROOT / "logs",
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.json"
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for p in PATHS.values():
        p.mkdir(parents=True, exist_ok=True)
    return cfg


def region_pv(cfg: dict, region_id: int | str) -> dict:
    """Bolge bazli PV parametreleri (genel + override)."""
    over = cfg.get("region_overrides", {}).get(str(region_id), {})
    return _deep_merge(cfg["pv"], over)


def inp(cfg: dict, key: str) -> Path:
    return ROOT / cfg["inputs"][key]


def normalize_weights(w: dict) -> dict:
    w = {k: float(v) for k, v in w.items() if v and float(v) > 0}
    s = sum(w.values())
    return {k: v / s for k, v in w.items()} if s > 0 else {}
