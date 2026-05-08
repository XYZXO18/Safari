#!/usr/bin/env python3
"""
One-time script to pre-fetch and cache OSRM road distances for all city pairs.

Run once:  python build_city_distances.py
Results are saved to data/city_distances.json and reused by the app forever.
Missing pairs are fetched automatically at runtime and added to the file.
"""
import json
import time
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import CITY_COORDS


def get_road_distance_osrm(from_lat, from_lng, to_lat, to_lng):
    """Minimal inline OSRM call to avoid triggering the full safari package."""
    import requests
    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{from_lng},{from_lat};{to_lng},{to_lat}"
        f"?overview=false&annotations=false"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            return {
                "distance_km": round(route["distance"] / 1000, 2),
                "duration_minutes": round(route["duration"] / 60),
            }
    except Exception as e:
        print(f"    OSRM error: {e}")
    return None

CACHE_FILE = Path(__file__).parent / "data" / "city_distances.json"

# Real cities only — skip vibe aliases
REAL_CITIES = [c for c in CITY_COORDS if c not in ("coast", "mountains", "desert", "city")]


def cache_key(city_a: str, city_b: str) -> str:
    a, b = sorted([city_a.lower().strip(), city_b.lower().strip()])
    return f"{a}__{b}"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def main():
    cache = load_cache()
    pairs = list(combinations(REAL_CITIES, 2))
    total = len(pairs)

    print(f"Pre-fetching OSRM road distances for {total} city pairs...")
    print(f"Results will be saved to: {CACHE_FILE}\n")

    new_count = 0
    skip_count = 0
    fail_count = 0

    for i, (city_a, city_b) in enumerate(pairs, 1):
        key = cache_key(city_a, city_b)

        if key in cache:
            skip_count += 1
            print(f"  [{i:02d}/{total}] SKIP  {city_a} ↔ {city_b}  ({cache[key]['distance_km']} km, cached)")
            continue

        coords_a = CITY_COORDS[city_a]
        coords_b = CITY_COORDS[city_b]

        result = get_road_distance_osrm(
            coords_a["lat"], coords_a["lng"],
            coords_b["lat"], coords_b["lng"],
        )

        if result and result.get("distance_km", 0) > 0:
            cache[key] = {
                "city_a": city_a,
                "city_b": city_b,
                "distance_km": result["distance_km"],
                "duration_minutes": result["duration_minutes"],
                "source": "osrm",
            }
            new_count += 1
            print(f"  [{i:02d}/{total}] OK    {city_a} <-> {city_b}:  {result['distance_km']} km  ({result['duration_minutes']} min)")
            save_cache(cache)  # Save after each fetch so interruption loses nothing
        else:
            fail_count += 1
            print(f"  [{i:02d}/{total}] FAIL  {city_a} <-> {city_b}:  OSRM failed, skipping")

        time.sleep(0.6)  # Respect OSRM public server rate limit

    print(f"\nDone — {new_count} fetched, {skip_count} already cached, {fail_count} failed")
    print(f"Cache: {CACHE_FILE}")


if __name__ == "__main__":
    main()
