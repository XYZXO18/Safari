"""
Transport Cost Calculator
=========================
Deterministic estimation of transportation costs.

Supports:
- **Car/Driving**: Fuel cost = distance × (consumption / 100) × fuel_price
- **Flight / Train / Bus**: distance × rate_per_km

All monetary values default to SAR unless otherwise specified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import (
    FUEL_CONSUMPTION,
    FUEL_PRICES_SAR,
    ROUTES,
    TRANSPORT_RATES_PER_KM,
)


@dataclass
class TransportEstimate:
    """Result of a transport cost calculation."""

    mode: str
    origin: str
    destination: str
    distance_km: float
    cost_one_way: float
    cost_round_trip: float
    currency: str = "SAR"
    breakdown: str = ""

    @property
    def summary(self) -> str:
        return (
            f"🚗 {self.mode.capitalize()} | {self.origin.title()} → {self.destination.title()}\n"
            f"   Distance: {self.distance_km:.0f} km (one way)\n"
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
    region: str = "saudi_arabia",
    round_trip: bool = True,
) -> TransportEstimate:
    """
    Estimate transport costs for a given mode and route.

    Parameters
    ----------
    mode : str
        Travel mode: 'car', 'flight', 'train', or 'bus'.
    origin : str
        Starting city/location.
    destination : str
        Target city/location or vibe (coast, mountains, desert).
    distance_km : float, optional
        Override the distance instead of looking it up.
    vehicle_type : str
        For car mode: 'sedan', 'suv', 'truck', or 'default'.
    region : str
        Region for fuel price lookup.
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
    395.24  # approximate
    """

    # Resolve distance
    dist = distance_km if distance_km else _lookup_distance(origin, destination)

    mode_lower = mode.lower().strip()

    if mode_lower == "car":
        # Fuel calculation
        consumption = FUEL_CONSUMPTION.get(vehicle_type, FUEL_CONSUMPTION["default"])
        fuel_price = FUEL_PRICES_SAR.get(region, FUEL_PRICES_SAR["default"])

        liters_needed = (dist / 100) * consumption
        cost_one_way = liters_needed * fuel_price

        breakdown = (
            f"📊 Fuel: {consumption} L/100km × {dist:.0f} km = {liters_needed:.1f} L "
            f"@ {fuel_price:.2f} SAR/L"
        )

    elif mode_lower in ("flight", "train", "bus"):
        rate = TRANSPORT_RATES_PER_KM.get(mode_lower, 0.30)
        cost_one_way = dist * rate

        breakdown = f"📊 Rate: {rate:.2f} SAR/km × {dist:.0f} km"

    else:
        raise ValueError(f"Unknown transport mode: {mode}")

    cost_rt = cost_one_way * 2 if round_trip else cost_one_way

    return TransportEstimate(
        mode=mode_lower,
        origin=origin,
        destination=destination,
        distance_km=dist,
        cost_one_way=round(cost_one_way, 2),
        cost_round_trip=round(cost_rt, 2),
        currency="SAR",
        breakdown=breakdown,
    )
