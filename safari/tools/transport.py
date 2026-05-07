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

from dataclasses import dataclass
from typing import Optional

from config import (
    ROUTES,
    TRANSPORT_RATES_PER_KM,
    CITY_COORDS,
)
from safari.tools.fuel import calculate_driving_cost


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
    Tries OSRM live routing first; falls back to ROUTES table.
    """
    from config import CITY_COORDS, ROUTES
    from safari.tools.almosafer import CITY_ALMOSAFER_SLUG

    # Resolve vibe names to real cities for coordinate lookup
    origin_city = CITY_ALMOSAFER_SLUG.get(origin.lower(), origin).lower()
    dest_city = CITY_ALMOSAFER_SLUG.get(destination.lower(), destination).lower()

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
                return result["distance_km"]
        except Exception as e:
            print(f"[Transport] OSRM distance failed ({origin}→{destination}): {e}")

    # Fallback: ROUTES table
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
            resolved_origin = CITY_ALMOSAFER_SLUG.get(origin.lower(), origin.title())
            resolved_dest = CITY_ALMOSAFER_SLUG.get(destination.lower(), destination.title())
            try:
                from safari.tools.live_distance import search_flight_prices
                flight_pricing = search_flight_prices(resolved_origin, resolved_dest)
                if flight_pricing and flight_pricing.price_one_way > 0:
                    cost_one_way = flight_pricing.price_one_way
                    cost_rt = flight_pricing.price_round_trip if round_trip else cost_one_way
                    time_mins = (flight_pricing.duration_minutes or 90) + 60
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
                # Final fallback ONLY if Almosafer is totally unreachable
                cost_one_way = dist * 0.45
                time_mins = round((dist / 800) * 60) + 120
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
            breakdown = f"📊 {provider} | Estimated distance-based calculation ({cost_one_way / dist:.2f} SAR/km)"


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
