"""
Local cache for Intigriti program overviews.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from auth import CONFIG_DIR

PROGRAMS_CACHE_FILE = CONFIG_DIR / "programs_cache.json"
DEFAULT_TTL_SECONDS = 6 * 60 * 60


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_programs_cache(max_age_seconds: int = DEFAULT_TTL_SECONDS) -> list[dict[str, Any]] | None:
    if not PROGRAMS_CACHE_FILE.exists():
        return None
    try:
        data = json.loads(PROGRAMS_CACHE_FILE.read_text())
        cached_at = float(data.get("cached_at", 0))
        if max_age_seconds > 0 and time.time() - cached_at > max_age_seconds:
            return None
        records = data.get("records", [])
        return records if isinstance(records, list) else None
    except Exception:
        return None


def save_programs_cache(records: list[dict[str, Any]]) -> None:
    _ensure_config_dir()
    PROGRAMS_CACHE_FILE.write_text(
        json.dumps({"cached_at": int(time.time()), "records": records}, indent=2)
    )


def clear_programs_cache() -> None:
    try:
        PROGRAMS_CACHE_FILE.unlink()
    except FileNotFoundError:
        pass


def find_cached_program(query: str, max_age_seconds: int = DEFAULT_TTL_SECONDS) -> list[dict[str, Any]]:
    query_norm = query.strip().lower()
    if not query_norm:
        return []
    records = load_programs_cache(max_age_seconds=max_age_seconds) or []
    matches: list[dict[str, Any]] = []
    for item in records:
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("id", "handle", "name", "industry")
        ).lower()
        if query_norm in haystack:
            matches.append(item)
    return matches
