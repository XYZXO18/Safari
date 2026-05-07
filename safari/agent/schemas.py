"""
Agent JSON Schemas (Pydantic v2)
================================
Strict data contracts for every agent hand-off in the Safari pipeline.

Flow:
  User → TripRequest
  Orchestrator → HospitalityInput → Agent2
  Agent2       → HospitalityOutput (venue stubs, no coords)
  Orchestrator → DistanceInput → Agent3 (Phase 1: geocode)
  Agent3       → GeolocationOutput (venues + coords)
  Orchestrator → DistanceInput → Agent3 (Phase 2: travel costs)
  Agent3       → DistanceOutput (flights, car rentals)
  Orchestrator → MasterPlanJSON → LLM
"""

from __future__ import annotations

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ─── Shared Primitives ────────────────────────────────────────────────────────

class TripDates(BaseModel):
    start: str = Field(..., description="ISO date: YYYY-MM-DD")
    end: str = Field(..., description="ISO date: YYYY-MM-DD")


# ─── Agent 2: Hospitality ─────────────────────────────────────────────────────

class HospitalityInput(BaseModel):
    """
    What the Orchestrator sends to Agent 2.
    """
    city: str = Field(..., description="Target city, e.g. 'Jeddah'")
    budget_per_night: float = Field(..., gt=0, description="Max SAR per hotel night")
    currency: str = Field(default="SAR")
    interests: List[str] = Field(default_factory=list, description="e.g. ['beach','seafood']")
    allergens: List[str] = Field(default_factory=list, description="e.g. ['nuts','gluten']")
    max_results: int = Field(default=5, ge=1, le=20)


class VenueStub(BaseModel):
    """
    A single venue returned by Agent 2 — coordinates are null until Agent 3 fills them.
    """
    name: str
    type: Literal["hotel", "restaurant", "cafe"]
    price: float = Field(..., description="Price per night (hotel) or per meal (restaurant/cafe)")
    currency: str = "SAR"
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    description: Optional[str] = None
    source_url: Optional[str] = None
    # Filled by Agent 3
    lat: Optional[float] = None
    lng: Optional[float] = None

    @field_validator("rating", mode="before")
    @classmethod
    def clamp_rating(cls, v):
        if v is None:
            return v
        return round(min(max(float(v), 0.0), 5.0), 1)


class HospitalityOutput(BaseModel):
    """
    Agent 2's Phase-1 response: venue names + prices, NO coordinates yet.
    """
    city: str
    venues: List[VenueStub]
    search_timestamp: str = Field(..., description="ISO datetime of the search")
    data_source: Literal["live_web", "gemini_grounding", "fallback_db"] = "live_web"
    warnings: List[str] = Field(default_factory=list)


# ─── Agent 3: Distance & Logistics ───────────────────────────────────────────

class DistanceInput(BaseModel):
    """
    What the Orchestrator sends to Agent 3.
    Contains the venue stubs from Agent 2 (no coords) + trip route info.
    """
    venues: List[VenueStub] = Field(default_factory=list, description="From Agent 2 output")
    origin: str = Field(..., description="Departure city, e.g. 'Riyadh'")
    destination: str = Field(..., description="Target city, e.g. 'Jeddah'")
    travel_mode: Literal["car", "flight", "train", "bus"] = "car"
    trip_dates: Optional[TripDates] = None
    currency: str = "SAR"


class GeolocatedVenue(BaseModel):
    """
    A venue enriched with real coordinates and routing info by Agent 3.
    """
    name: str
    type: str
    lat: float
    lng: float
    geocode_source: Literal["nominatim", "google_maps", "gemini", "fallback"] = "nominatim"
    # Road routing from hotel to this venue (populated for restaurants/cafes)
    road_distance_km: Optional[float] = None
    drive_time_minutes: Optional[int] = None
    walk_time_minutes: Optional[int] = None


class FlightPricing(BaseModel):
    """Real-time flight pricing from live search."""
    origin: str
    destination: str
    price_one_way: float
    price_round_trip: float
    currency: str = "SAR"
    airline: Optional[str] = None
    duration_minutes: Optional[int] = None
    source: Literal["live_search", "gemini_grounding", "fallback_estimate"] = "live_search"
    confidence: Literal["high", "medium", "low"] = "medium"


class CarRentalPricing(BaseModel):
    """Real-time car rental pricing from live search."""
    city: str
    price_per_day: float
    currency: str = "SAR"
    vehicle_type: Optional[str] = None
    company: Optional[str] = None
    source: Literal["live_search", "gemini_grounding", "fallback_estimate"] = "live_search"
    confidence: Literal["high", "medium", "low"] = "medium"


class TravelCosts(BaseModel):
    """Combined inter-city travel costs."""
    flight: Optional[FlightPricing] = None
    car_rental: Optional[CarRentalPricing] = None
    fuel_estimate: Optional[dict] = None  # kept for car-drive mode


class DistanceOutput(BaseModel):
    """
    Agent 3's complete response:
    - Geolocated venues (coordinates filled in)
    - Real road distances between venues
    - Live flight/car-rental pricing
    """
    origin: str
    destination: str
    geolocated_venues: List[GeolocatedVenue]
    travel_costs: TravelCosts
    total_intra_city_distance_km: float = 0.0
    data_sources: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
