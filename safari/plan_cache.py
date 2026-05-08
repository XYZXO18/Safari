"""
Trip Plan Cache
===============
Caches full /api/plan responses keyed by input parameters.
Results are reused for 5 hours when the exact same parameters are sent again.

Storage: data/plan_cache.json
Format:
  { "<md5-key>": { "params": {...}, "result": {...}, "cached_at": "<iso-timestamp>" } }
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent.parent / "data" / "plan_cache.json"
CACHE_TTL_HOURS = 5

# Loaded once per process; written back on every save.
_CACHE: Optional[dict] = None


# ─── Key generation ──────────────────────────────────────────────────────────

def make_cache_key(params: dict) -> str:
    """
    Stable MD5 hash of the normalised input parameters.
    Sorting keys ensures dict ordering doesn't affect the hash.
    """
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode()).hexdigest()


def _normalise_params(raw: dict) -> dict:
    """
    Strip fields that shouldn't affect whether results are reusable
    (e.g. whitespace variations) and normalise types.
    """
    return {
        "budget":       round(float(raw.get("budget", 3000)), 2),
        "travel_mode":  str(raw.get("travel_mode", "car")).strip().lower(),
        "destination":  str(raw.get("destination", "coast")).strip().lower(),
        "days":         int(raw.get("days", 3)),
        "origin":       str(raw.get("origin", "riyadh")).strip().lower(),
        "vehicle_type": str(raw.get("vehicle_type", "default")).strip().lower(),
        "currency":     str(raw.get("currency", "SAR")).strip().upper(),
        "start_date":   str(raw.get("start_date", "")).strip(),
        "end_date":     str(raw.get("end_date", "")).strip(),
        "interests":    str(raw.get("interests", "")).strip().lower(),
    }


# ─── File I/O ────────────────────────────────────────────────────────────────

def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception as e:
            logger.warning(f"[PlanCache] Could not read cache file: {e}")
            _CACHE = {}
    else:
        _CACHE = {}

    _prune_expired(_CACHE)
    return _CACHE


def _save(cache: dict) -> None:
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[PlanCache] Could not write cache file: {e}")


def _prune_expired(cache: dict) -> None:
    """Remove entries older than TTL in-place."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)
    expired = [
        k for k, v in cache.items()
        if datetime.fromisoformat(v["cached_at"]) < cutoff
    ]
    for k in expired:
        del cache[k]
    if expired:
        logger.debug(f"[PlanCache] Pruned {len(expired)} expired entries.")


# ─── Public API ──────────────────────────────────────────────────────────────

def get_cached_plan(raw_params: dict) -> Optional[dict]:
    """
    Return a cached plan result if one exists for these params within the last 5 hours.
    Returns None if no valid cache entry is found.
    """
    params = _normalise_params(raw_params)
    key = make_cache_key(params)
    cache = _load()

    entry = cache.get(key)
    if not entry:
        return None

    cached_at = datetime.fromisoformat(entry["cached_at"])
    age = datetime.now(timezone.utc) - cached_at
    if age > timedelta(hours=CACHE_TTL_HOURS):
        del cache[key]
        _save(cache)
        return None

    age_mins = int(age.total_seconds() / 60)
    logger.info(f"[PlanCache] HIT — {params['origin']} -> {params['destination']} "
                f"({age_mins} min old)")
    return entry["result"]


def save_plan(raw_params: dict, result: dict) -> None:
    """
    Save a plan result to the cache.
    """
    params = _normalise_params(raw_params)
    key = make_cache_key(params)
    cache = _load()

    cache[key] = {
        "params": params,
        "result": result,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(cache)
    logger.info(f"[PlanCache] SAVED — {params['origin']} -> {params['destination']}")
