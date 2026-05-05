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
    Look up the distance between two points from the route table.
    Falls back to a default estimate if the exact pair is not found.
    """
    origin_l = origin.lower().strip()
    dest_l = destination.lower().strip()

    # Direct lookup
    if (origin_l, dest_l) in ROUTES:
        return ROUTES[(origin_l, dest_l)]

    # Reverse lookup (routes are symmetric)
    if (dest_l, origin_l) in ROUTES:
        return ROUTES[(dest_l, origin_l)]

    # Default by vibe
    if ("default", dest_l) in ROUTES:
        return ROUTES[("default", dest_l)]

    # Final fallback
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

    else:
        raise ValueError(f"Unknown transport mode: {mode}")

    # Estimate travel time
    if mode_lower in ("car", "driving"):
        # Saudi highway speed approx 110-120 km/h avg including stops
        avg_speed = 110 
        time_mins = round((dist / avg_speed) * 60)
    elif mode_lower == "flight":
        # Flight time + 2 hours buffer for airport
        time_mins = round((dist / 800) * 60) + 120
    elif mode_lower == "train":
        # Haramain High Speed or SAR: avg 200 km/h
        time_mins = round((dist / 200) * 60) + 30
    elif mode_lower == "bus":
        # Bus speed approx 80 km/h
        time_mins = round((dist / 80) * 60) + 30
    else:
        time_mins = 0

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
