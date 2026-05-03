"""
Fuel Cost Calculator
====================
Reads the local offline fuel_prices.json database and calculates
driving costs based on distance, fuel grade, vehicle type, and
average consumption.

This module eliminates the need for external fuel-price APIs — all
data lives in `data/fuel_prices.json` at the project root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from config import VEHICLE_KM_PER_LITER

# ─── Locate the fuel_prices.json relative to the project root ────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # safari/tools/fuel.py → project root
_FUEL_DB_PATH = _PROJECT_ROOT / "data" / "fuel_prices.json"


def _load_fuel_db() -> dict:
    """
    Load the fuel price database from the local JSON file.

    Returns
    -------
    dict
        Parsed contents of fuel_prices.json.

    Raises
    ------
    FileNotFoundError
        If fuel_prices.json does not exist at the expected path.
    """
    if not _FUEL_DB_PATH.exists():
        raise FileNotFoundError(
            f"Fuel price database not found at {_FUEL_DB_PATH}. "
            f"Please ensure data/fuel_prices.json exists in the project root."
        )

    with open(_FUEL_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_driving_cost(
    distance_km: float,
    fuel_type: str = "91",
    round_trip: bool = True,
    custom_km_per_liter: Optional[float] = None,
    vehicle_type: str = "default",
) -> dict:
    """
    Calculate the fuel cost for a driving trip using the local fuel database.

    Parameters
    ----------
    distance_km : float
        One-way distance in kilometers.
    fuel_type : str
        Fuel grade to use: '91' (RON 91) or '95' (RON 95). Defaults to '91'.
    round_trip : bool
        If True (default), the result accounts for a round-trip (cost × 2).
    custom_km_per_liter : float, optional
        Override the default average consumption from the database.
    vehicle_type : str
        Vehicle category: 'sedan', 'suv', 'truck', '4x4', or 'default'.
        Controls fuel efficiency. Truck/4x4 uses ~8 km/L; sedan ~13 km/L.

    Returns
    -------
    dict
        {
            "distance_km": float,         # one-way distance
            "fuel_type": str,             # '91' or '95'
            "fuel_name": str,             # e.g. 'RON 91'
            "price_per_liter": float,     # SAR per liter
            "km_per_liter": float,        # fuel efficiency used
            "vehicle_type": str,          # vehicle category used
            "liters_one_way": float,      # liters needed one way
            "cost_one_way": float,        # SAR cost one way
            "cost_round_trip": float,     # SAR cost round trip
            "is_round_trip": bool,        # whether round_trip was applied
            "currency": str,              # always 'SAR'
        }

    Examples
    --------
    >>> result = calculate_driving_cost(1100, vehicle_type="truck")
    >>> result["cost_round_trip"]
    # 1100 km ÷ 8 km/L = 137.5 L × 2.18 SAR/L × 2 = ~599.5 SAR
    """
    db = _load_fuel_db()

    # ─── Resolve fuel grade ──────────────────────────────────────────────
    fuel_type_str = str(fuel_type).strip()
    fuel_grades = db.get("fuel_grades", {})

    if fuel_type_str not in fuel_grades:
        raise ValueError(
            f"Unknown fuel type '{fuel_type_str}'. "
            f"Available grades: {list(fuel_grades.keys())}"
        )

    grade_info = fuel_grades[fuel_type_str]
    price_per_liter = grade_info["price_sar_per_liter"]
    fuel_name = grade_info["name"]

    # ─── Resolve consumption ─────────────────────────────────────────────
    # Priority: explicit override > vehicle-type lookup > JSON default
    vtype = vehicle_type.lower().strip() if vehicle_type else "default"
    if custom_km_per_liter:
        km_per_liter = custom_km_per_liter
    else:
        km_per_liter = VEHICLE_KM_PER_LITER.get(vtype, db.get("average_car_km_per_liter", 12))

    # ─── Calculate ───────────────────────────────────────────────────────
    liters_one_way = distance_km / km_per_liter
    cost_one_way = liters_one_way * price_per_liter
    cost_round_trip = cost_one_way * 2 if round_trip else cost_one_way

    return {
        "distance_km": distance_km,
        "fuel_type": fuel_type_str,
        "fuel_name": fuel_name,
        "price_per_liter": price_per_liter,
        "km_per_liter": km_per_liter,
        "vehicle_type": vtype,
        "liters_one_way": round(liters_one_way, 2),
        "cost_one_way": round(cost_one_way, 2),
        "cost_round_trip": round(cost_round_trip, 2),
        "is_round_trip": round_trip,
        "currency": db.get("currency", "SAR"),
    }
