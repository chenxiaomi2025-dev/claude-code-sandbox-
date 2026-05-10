"""Load YAML config files (companies, sources)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from intel.config.settings import settings

CONFIG_DIR = Path(__file__).resolve().parent


def _read_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def load_companies() -> list[dict[str, Any]]:
    data = _read_yaml("companies.yaml")
    return list(data.get("companies", []))


@lru_cache(maxsize=1)
def load_sources() -> dict[str, list[dict[str, Any]]]:
    data = _read_yaml("sources.yaml")
    return {k: list(v) for k, v in data.items() if isinstance(v, list)}


def company_keywords() -> dict[str, list[str]]:
    """Return {ticker: [name, alt-names, aliases...]} used for keyword matching.

    Aliases declared in companies.yaml under `aliases:` are merged in.
    """
    out: dict[str, list[str]] = {}
    for c in load_companies():
        keys: set[str] = {c["name"]}
        for a in c.get("aliases") or []:
            if a:
                keys.add(a)
        ticker = c["ticker"]
        if not c.get("private"):
            keys.add(ticker.split(".")[0])
        out[ticker] = sorted(k for k in keys if k)
    return out


__all__ = ["load_companies", "load_sources", "company_keywords", "settings"]
