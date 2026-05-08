"""
Transport Cost Calculator
=========================
Deterministic estimation of transportation costs.

Supports:
- **Car/Driving**: Uses the local fuel_prices.json database via calculate_driving_cost()
  for accurate RON 91/95 pricing and km/L consumption model.
- **Flight / Train / Bus**: distance × rate_per_km

All monetary values default to SAR unless otherwise specified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import (
    ROUTES,
    TRANSPORT_RATES_PER_KM,
    CITY_COORDS,
    can_travel_by_car,
)
from safari.tools.fuel import calculate_driving_cost

# ─── Persistent distance cache ────────────────────────────────────────────────
# Loaded once from data/city_distances.json; new OSRM results are appended.
_DIST_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "city_distances.json"
_DIST_CACHE: Optional[dict] = None


def _dist_key(city_a: str, city_b: str) -> str:
    a, b = sorted([city_a.lower().strip(), city_b.lower().strip()])
    return f"{a}__{b}"


def _load_dist_cache() -> dict:
    global _DIST_CACHE
    if _DIST_CACHE is None:
        if _DIST_CACHE_FILE.exists():
            try:
                with open(_DIST_CACHE_FILE, encoding="utf-8") as f:
                    _DIST_CACHE = json.load(f)
            except Exception:
                _DIST_CACHE = {}
        else:
            _DIST_CACHE = {}
    return _DIST_CACHE


def _save_dist_cache(cache: dict) -> None:
    try:
        _DIST_CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(_DIST_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Transport] Could not write distance cache: {e}")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km — what an aircraft actually flies."""
    from math import radians, sin, cos, asin, sqrt
    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _flight_distance_km(origin: str, destination: str, fallback_km: float) -> float:
    """Great-circle km between origin and destination, falling back to road km."""
    from safari.tools.almosafer import CITY_ALMOSAFER_SLUG
    o = CITY_ALMOSAFER_SLUG.get(origin.lower(), origin).lower()
    d = CITY_ALMOSAFER_SLUG.get(destination.lower(), destination).lower()
    oc = CITY_COORDS.get(o) or CITY_COORDS.get(origin.lower())
    dc = CITY_COORDS.get(d) or CITY_COORDS.get(destination.lower())
    if oc and dc:
        return _haversine_km(oc["lat"], oc["lng"], dc["lat"], dc["lng"])
    return fallback_km


def _estimate_flight_minutes(great_circle_km: float) -> int:
    """Realistic block time: ~800 km/h cruise + 30 min taxi/climb/descent."""
    if great_circle_km <= 0:
        return 0
    return round((great_circle_km / 800.0) * 60) + 30


@dataclass
class TransportEstimate:
    """Result of a transport cost calculation."""

    mode: str
    origin: str
    destination: str
    distance_km: float
    cost_one_way: float
    cost_round_trip: float
    travel_time_minutes: int = 0
    currency: str = "SAR"
    breakdown: str = ""

    @property
    def travel_time_str(self) -> str:
        hours = self.travel_time_minutes // 60
        mins = self.travel_time_minutes % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    @property
    def summary(self) -> str:
        time_str = self.travel_time_str
        
        return (
            f"🚗 {self.mode.capitalize()} | {self.origin.title()} → {self.destination.title()}\n"
            f"   Distance: {self.distance_km:.0f} km | Est. Time: {time_str}\n"
            f"   Cost: {self.cost_one_way:.0f} {self.currency} one-way "
            f"/ {self.cost_round_trip:.0f} {self.currency} round-trip\n"
            f"   {self.breakdown}"
        )


def _lookup_distance(origin: str, destination: str) -> float:
    """
    Get real road distance between two cities.

    Order of preference:
      1. data/city_distances.json  (pre-fetched OSRM data, loaded once in memory)
      2. OSRM live API             (result saved to file for future calls)
      3. config.ROUTES table       (static fallback)
      4. 500 km default            (last resort)
    """
    from safari.tools.almosafer import CITY_ALMOSAFER_SLUG

    # Resolve vibe names to real cities for coordinate lookup
    origin_city = CITY_ALMOSAFER_SLUG.get(origin.lower(), origin).lower()
    dest_city = CITY_ALMOSAFER_SLUG.get(destination.lower(), destination).lower()

    key = _dist_key(origin_city, dest_city)
    cache = _load_dist_cache()

    # 1. Cached result
    if key in cache:
        return cache[key]["distance_km"]

    # 2. Live OSRM — only called when pair is absent from the cache
    orig_coords = CITY_COORDS.get(origin_city) or CITY_COORDS.get(origin.lower())
    dest_coords = CITY_COORDS.get(dest_city) or CITY_COORDS.get(destination.lower())

    if orig_coords and dest_coords:
        try:
            from safari.tools.live_distance import get_road_distance_osrm
            result = get_road_distance_osrm(
                orig_coords["lat"], orig_coords["lng"],
                dest_coords["lat"], dest_coords["lng"],
            )
            if result and result.get("distance_km", 0) > 0:
                cache[key] = {
                    "city_a": origin_city,
                    "city_b": dest_city,
                    "distance_km": result["distance_km"],
                    "duration_minutes": result["duration_minutes"],
                    "source": "osrm",
                }
                _save_dist_cache(cache)
                return result["distance_km"]
        except Exception as e:
            print(f"[Transport] OSRM distance failed ({origin}→{destination}): {e}")

    # 3. Static ROUTES table fallback
    origin_l = origin.lower().strip()
    dest_l = destination.lower().strip()
    if (origin_l, dest_l) in ROUTES:
        return ROUTES[(origin_l, dest_l)]
    if (dest_l, origin_l) in ROUTES:
        return ROUTES[(dest_l, origin_l)]
    if ("default", dest_l) in ROUTES:
        return ROUTES[("default", dest_l)]

    return 500.0


def calculate_transport_costs(
    mode: str,
    origin: str = "riyadh",
    destination: str = "coast",
    distance_km: Optional[float] = None,
    vehicle_type: str = "default",
    fuel_type: str = "91",
    round_trip: bool = True,
) -> TransportEstimate:
    """
    Estimate transport costs for a given mode and route.

    Parameters
    ----------
    mode : str
        Travel mode: 'car', 'driving', 'flight', 'train', or 'bus'.
    origin : str
        Starting city/location.
    destination : str
        Target city/location or vibe (coast, mountains, desert).
    distance_km : float, optional
        Override the distance instead of looking it up.
    vehicle_type : str
        For car mode: 'sedan', 'suv', 'truck', or 'default'.
        (Currently used as label only; consumption comes from fuel_prices.json.)
    fuel_type : str
        Fuel grade: '91' (RON 91) or '95' (RON 95). Default '91'.
    round_trip : bool
        If True, calculate round-trip cost. Default True.

    Returns
    -------
    TransportEstimate
        Dataclass with full cost breakdown.

    Examples
    --------
    >>> result = calculate_transport_costs("car", "riyadh", "jeddah")
    >>> result.cost_round_trip
    344.97  # 950km ÷ 12km/L = 79.17L × 2.18 SAR/L × 2
    """

    # Resolve distance
    dist = distance_km if distance_km else _lookup_distance(origin, destination)

    mode_lower = mode.lower().strip()

    cost_one_way = 0.0
    cost_rt = 0.0
    breakdown = ""
    time_mins = 0

    # ── Cross-border car validation ────────────────────────────────────────────
    if mode_lower in ("car", "driving"):
        car_ok, car_reason = can_travel_by_car(origin, destination)
        if not car_ok:
            return TransportEstimate(
                mode="car",
                origin=origin,
                destination=destination,
                distance_km=dist,
                cost_one_way=0.0,
                cost_round_trip=0.0,
                travel_time_minutes=0,
                currency="SAR",
                breakdown=f"🚫 {car_reason}",
            )

    if mode_lower in ("car", "driving"):
        # ─── Use the local fuel_prices.json database ───────────────────────
        fuel_result = calculate_driving_cost(
            distance_km=dist,
            fuel_type=fuel_type,
            round_trip=round_trip,
            vehicle_type=vehicle_type,
        )

        cost_one_way = fuel_result["cost_one_way"]
        cost_rt = fuel_result["cost_round_trip"]

        vehicle_label = vehicle_type.title() if vehicle_type not in ("default", "") else "Car"
        breakdown = (
            f"📊 {vehicle_label} | Fuel ({fuel_result['fuel_name']}): "
            f"{dist:.0f} km ÷ {fuel_result['km_per_liter']} km/L = "
            f"{fuel_result['liters_one_way']:.1f} L "
            f"@ {fuel_result['price_per_liter']:.2f} SAR/L"
        )
        avg_speed = 110 
        time_mins = round((dist / avg_speed) * 60)

    else:
        # Load the transportation logistics JSON
        import json
        import os
        import re
        
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "safari_transportation_logistics_filtered.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)["saudi_arabia_transportation"]
        except Exception as e:
            print(f"Error loading transport JSON: {e}")
            data = {}

        def parse_duration(duration_str):
            """Convert '2h 45m' to minutes."""
            h_match = re.search(r'(\d+)h', duration_str)
            m_match = re.search(r'(\d+)m', duration_str)
            h = int(h_match.group(1)) if h_match else 0
            m = int(m_match.group(1)) if m_match else 0
            return h * 60 + m

        def find_route(routes_list, orig, dest):
            orig_lower = orig.lower()
            dest_lower = dest.lower()
            
            # Map common names (like coast -> jeddah)
            mapping = {"coast": "jeddah", "mountains": "abha", "desert": "alula", "city": "riyadh"}
            o_clean = mapping.get(orig_lower, orig_lower)
            d_clean = mapping.get(dest_lower, dest_lower)

            for route in routes_list:
                r_from = route["from"].lower()
                r_to = route["to"].lower()
                # Direct match
                if (o_clean in r_from and d_clean in r_to):
                    return route
                # Reverse match (assume symmetric pricing/time for simplicity)
                if (d_clean in r_from and o_clean in r_to):
                    return route
            return None

        route_found = None
        provider = ""

        if mode_lower == "flight":
            # Almosafer flight pages are JS-rendered and cannot be scraped statically.
            # Use Gemini Search Grounding for live prices instead.
            from safari.tools.almosafer import CITY_ALMOSAFER_SLUG
            from config import AIRPORTS
            resolved_origin = CITY_ALMOSAFER_SLUG.get(origin.lower(), origin.title())
            resolved_dest = CITY_ALMOSAFER_SLUG.get(destination.lower(), destination.title())
            orig_airport = AIRPORTS.get(origin.lower(), {})
            dest_airport  = AIRPORTS.get(destination.lower(), {})
            orig_has_airport = not orig_airport or orig_airport.get("airport_city", origin.lower()) == origin.lower()
            dest_has_airport = not dest_airport or dest_airport.get("airport_city", destination.lower()) == destination.lower()
            try:
                from safari.tools.live_distance import search_flight_prices
                if not orig_has_airport or not dest_has_airport:
                    print(f"[Transport] Skipping flight search — no airport at {'origin' if not orig_has_airport else 'destination'}.")
                    flight_pricing = None
                else:
                    flight_pricing = search_flight_prices(resolved_origin, resolved_dest)
                if flight_pricing and flight_pricing.price_one_way > 0:
                    cost_one_way = flight_pricing.price_one_way
                    cost_rt = flight_pricing.price_round_trip if round_trip else cost_one_way
                    # Sanity-check the returned duration against great-circle time:
                    # if Gemini returned a layover-inclusive figure that's >2× the
                    # nonstop estimate, prefer the computed estimate.
                    gc_km = _flight_distance_km(origin, destination, dist)
                    nonstop_est = _estimate_flight_minutes(gc_km)
                    raw_dur = flight_pricing.duration_minutes or 0
                    if raw_dur > 0 and (nonstop_est == 0 or raw_dur <= 2 * nonstop_est):
                        time_mins = raw_dur + 60   # +60 for airport buffer
                    else:
                        time_mins = (nonstop_est or 90) + 60
                    airline = flight_pricing.airline or "Flight"
                    breakdown = f"✈️ {airline}: {cost_one_way:.0f} SAR one-way [{flight_pricing.source}]"
                    route_found = {"from": resolved_origin, "to": resolved_dest}
                else:
                    route_found = None
            except Exception as e:
                print(f"[Transport] Gemini flight search failed: {e}")
                route_found = None
            
        elif mode_lower == "train":
            for network in data.get("train_networks", []):
                r = find_route(network.get("routes", []), origin, destination)
                if r:
                    route_found = r
                    provider = network.get("network_name", "Train")
                    break
                    
        elif mode_lower == "bus":
            for network in data.get("bus_networks", []):
                r = find_route(network.get("major_routes", []), origin, destination)
                if r:
                    route_found = r
                    provider = network.get("network_name", "Bus")
                    break

        if route_found:
            if cost_one_way == 0.0:
                cost_one_way = float(route_found.get("average_cost_sar", 0))
            
            cost_rt = cost_one_way * 2 if round_trip else cost_one_way
            
            if "average_duration" in route_found:
                time_mins = parse_duration(route_found["average_duration"])
            
            # Add airport buffer time for flights if time_mins was set from route_found
            if mode_lower == "flight" and "average_duration" in route_found:
                time_mins += 120
            
            breakdown = f"🎫 {provider} | Exact match found in logistics database for {route_found['from']} ↔ {route_found['to']}"
        else:
            # Fallback estimation if route not in JSON
            if mode_lower == "flight":
                # Final fallback ONLY if Almosafer is totally unreachable.
                # Time uses great-circle distance (planes don't follow roads),
                # cost still uses road km as a rough proxy for a fare estimate.
                gc_km = _flight_distance_km(origin, destination, dist)
                cost_one_way = dist * 0.45
                time_mins = _estimate_flight_minutes(gc_km) + 90  # +90 airport buffer
                breakdown = "⚠️ Almosafer unreachable. Using distance-based estimate."
            elif mode_lower == "train":
                cost_one_way = dist * 0.25
                time_mins = round((dist / 200) * 60) + 30
                provider = "Estimated Train"
            elif mode_lower == "bus":
                cost_one_way = dist * 0.15
                time_mins = round((dist / 80) * 60) + 30
                provider = "Estimated Bus"
            else:
                cost_one_way = dist * 0.3
                time_mins = 0
                provider = "Unknown Transport"

            cost_rt = cost_one_way * 2 if round_trip else cost_one_way
            rate_str = f"{cost_one_way / dist:.2f} SAR/km" if dist > 0 else "N/A"
            breakdown = f"📊 {provider} | Estimated distance-based calculation ({rate_str})"


    return TransportEstimate(
        mode=mode_lower,
        origin=origin,
        destination=destination,
        distance_km=dist,
        cost_one_way=round(cost_one_way, 2),
        cost_round_trip=round(cost_rt, 2),
        travel_time_minutes=time_mins,
        currency="SAR",
        breakdown=breakdown,
    )
