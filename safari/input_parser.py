"""
Input Parser
============
Extracts and validates structured trip parameters from raw user input.
Uses regex-based extraction with LLM fallback for ambiguous queries.

Outputs a TripRequest dataclass containing:
- budget (float)
- currency (str)
- travel_mode (str)
- destination (str)
- days (int)
- origin (str, optional)
- vehicle_type (str, optional)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TripRequest:
    """Structured representation of a user's travel request."""

    budget: float
    currency: str = "SAR"
    travel_mode: str = "car"          # car | flight | train | bus
    destination: str = "coast"
    days: int = 3
    origin: str = "riyadh"
    vehicle_type: str = "default"     # sedan | suv | truck | default
    raw_input: str = ""

    def __post_init__(self):
        """Normalize and validate fields after initialization."""
        self.travel_mode = self.travel_mode.lower().strip()
        self.destination = self.destination.lower().strip()
        self.origin = self.origin.lower().strip()
        self.vehicle_type = self.vehicle_type.lower().strip()
        self.currency = self.currency.upper().strip()

        if self.budget <= 0:
            raise ValueError(f"Budget must be positive, got {self.budget}")
        if self.days <= 0:
            raise ValueError(f"Days must be positive, got {self.days}")
        if self.travel_mode not in ("car", "flight", "train", "bus", "drive", "driving", "fly", "flying"):
            raise ValueError(f"Unknown travel mode: {self.travel_mode}")

        # Normalize travel mode aliases
        mode_aliases = {
            "drive": "car",
            "driving": "car",
            "fly": "flight",
            "flying": "flight",
        }
        self.travel_mode = mode_aliases.get(self.travel_mode, self.travel_mode)

    @property
    def daily_budget_before_transport(self) -> float:
        """Rough per-day budget (before transport is subtracted)."""
        return self.budget / self.days


# ─── Regex Patterns ──────────────────────────────────────────────────────────

_BUDGET_PATTERN = re.compile(
    r"(?:i have|budget(?:\s+is)?|got|with)\s+"
    r"(?:(?P<currency>[A-Za-z$€£﷼]+)\s*)?"
    r"(?P<amount>[\d,]+(?:\.\d{1,2})?)"
    r"(?:\s*(?P<currency_after>sar|riyals?|riyal|usd|dollars?|eur|euros?|gbp|pounds?|aed|dirhams?|egp))?"
    ,
    re.IGNORECASE,
)

_DAYS_PATTERN = re.compile(
    r"(?:for\s+)?(?P<days>\d+)\s*(?:days?|nights?)",
    re.IGNORECASE,
)

_MODE_PATTERN = re.compile(
    r"(?P<mode>driv(?:e|ing)|fly(?:ing)?|flight|train|bus|car)",
    re.IGNORECASE,
)

_DESTINATION_PATTERN = re.compile(
    r"(?:to\s+(?:the\s+)?)?(?P<dest>coast|beach|mountains?|desert|city|"
    r"jeddah|riyadh|dammam|abha|al[- ]?ula|yanbu|taif|medina|al[- ]?ahsa|jubail|umluj|al[- ]?lith|"
    r"al[- ]?baha|edge\s+of\s+the\s+world|empty\s+quarter)",
    re.IGNORECASE,
)

_ORIGIN_PATTERN = re.compile(
    r"(?:from\s+)(?P<origin>riyadh|jeddah|dammam|medina|abha|taif|yanbu|jubail)",
    re.IGNORECASE,
)

_VEHICLE_PATTERN = re.compile(
    r"(?:my\s+)?(?P<vehicle>sedan|suv|truck|pickup|4x4)",
    re.IGNORECASE,
)

# ─── Currency Normalization ──────────────────────────────────────────────────

_CURRENCY_MAP = {
    "sar": "SAR", "riyal": "SAR", "riyals": "SAR", "﷼": "SAR",
    "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR", "€": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "£": "GBP",
    "aed": "AED", "dirham": "AED", "dirhams": "AED",
    "egp": "EGP",
}


def _normalize_currency(raw: Optional[str]) -> str:
    """Convert a raw currency string to a standard 3-letter code."""
    if not raw:
        return "SAR"
    return _CURRENCY_MAP.get(raw.lower().strip(), "SAR")


# ─── Destination Normalization ───────────────────────────────────────────────

_DEST_VIBE_MAP = {
    "beach": "coast",
    "mountain": "mountains",
    "jeddah": "coast",
    "yanbu": "coast",
    "umluj": "coast",
    "al lith": "coast",
    "al-lith": "coast",
    "abha": "mountains",
    "al baha": "mountains",
    "al-baha": "mountains",
    "taif": "mountains",
    "al ula": "desert",
    "al-ula": "desert",
    "alula": "desert",
    "edge of the world": "desert",
    "empty quarter": "desert",
    "riyadh": "city",
    "dammam": "city",
}


def _normalize_destination(raw: str) -> str:
    """Map a raw destination string to a canonical vibe category."""
    lower = raw.lower().strip()
    return _DEST_VIBE_MAP.get(lower, lower)


# ─── Main Parser ─────────────────────────────────────────────────────────────

def parse_user_input(text: str) -> TripRequest:
    """
    Parse a natural-language trip request into a structured TripRequest.

    Examples
    --------
    >>> parse_user_input("I have 3000 Riyals, driving my car to the coast for 4 days")
    TripRequest(budget=3000.0, currency='SAR', travel_mode='car', destination='coast', days=4, ...)

    >>> parse_user_input("Budget is $2000, flying to Abha for 5 days from Jeddah")
    TripRequest(budget=2000.0, currency='USD', travel_mode='flight', destination='mountains', days=5, ...)
    """

    # ── Extract budget ──
    budget_match = _BUDGET_PATTERN.search(text)
    if budget_match:
        amount_str = budget_match.group("amount").replace(",", "")
        budget = float(amount_str)
        currency_raw = budget_match.group("currency") or budget_match.group("currency_after")
        currency = _normalize_currency(currency_raw)
    else:
        # Fallback: find any number that looks like a budget
        numbers = re.findall(r"[\d,]+(?:\.\d{1,2})?", text)
        if numbers:
            budget = float(numbers[0].replace(",", ""))
            currency = "SAR"
        else:
            raise ValueError("Could not extract a budget from the input.")

    # ── Extract days ──
    days_match = _DAYS_PATTERN.search(text)
    days = int(days_match.group("days")) if days_match else 3

    # ── Extract travel mode ──
    mode_match = _MODE_PATTERN.search(text)
    travel_mode = mode_match.group("mode").lower() if mode_match else "car"

    # ── Extract destination ──
    dest_match = _DESTINATION_PATTERN.search(text)
    raw_dest = dest_match.group("dest") if dest_match else "coast"
    destination = _normalize_destination(raw_dest)

    # ── Extract origin ──
    origin_match = _ORIGIN_PATTERN.search(text)
    origin = origin_match.group("origin").lower() if origin_match else "riyadh"

    # ── Extract vehicle type ──
    vehicle_match = _VEHICLE_PATTERN.search(text)
    vehicle_type = "default"
    if vehicle_match:
        v = vehicle_match.group("vehicle").lower()
        if v in ("4x4", "pickup"):
            vehicle_type = "truck"
        else:
            vehicle_type = v

    return TripRequest(
        budget=budget,
        currency=currency,
        travel_mode=travel_mode,
        destination=destination,
        days=days,
        origin=origin,
        vehicle_type=vehicle_type,
        raw_input=text,
    )
