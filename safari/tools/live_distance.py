"""
Live Distance & Geolocation Tool
=================================
Real-time geocoding, road-distance calculation, and travel price search.

Strategy per capability:

  Geocoding:
    1. Nominatim (OpenStreetMap, free, no key)
    2. Gemini Search Grounding (LLM-assisted, uses existing GEMINI_API_KEY)
    3. Fallback: city center coords from config.CITY_COORDS

  Road Distances:
    1. OSRM Public API (free, returns actual road distances)
    2. Fallback: Haversine straight-line × 1.3 correction factor

  Flight Prices:
    1. Gemini Search Grounding
    2. Fallback: existing safari_transportation_logistics_filtered.json static data

  Car Rental Prices:
    1. Gemini Search Grounding
    2. Fallback: flat estimate (120 SAR/day)
"""

from __future__ import annotations

import re
import json
import math
import logging
import time
from typing import List, Optional, Tuple
from rich.console import Console

from safari.agent.schemas import (
    GeolocatedVenue, VenueStub,
    FlightPricing, CarRentalPricing
)

logger = logging.getLogger(__name__)
console = Console()

# ─── Geocoding ────────────────────────────────────────────────────────────────

def geocode_nominatim(venue_name: str, city: str) -> Optional[Tuple[float, float]]:
    """
    Query OpenStreetMap Nominatim to get lat/lng for a venue.
    Free, no API key. Rate limited to 1 req/sec per OSM policy.
    Returns (lat, lng) or None.
    """
    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError

        geolocator = Nominatim(user_agent="safari_travel_planner_v1")
        query = f"{venue_name}, {city}, Saudi Arabia"
        location = geolocator.geocode(query, timeout=10)

        if location:
            logger.debug(f"[Nominatim] ✅ {venue_name} → ({location.latitude:.4f}, {location.longitude:.4f})")
            console.print(f"[bold cyan][N] [Agent 3] Nominatim Geocoding used for: {venue_name}[/bold cyan]")
            return (location.latitude, location.longitude)

        # Retry with just the city if full name fails
        location = geolocator.geocode(f"{city}, Saudi Arabia", timeout=10)
        if location:
            logger.debug(f"[Nominatim] Fallback city coords for {venue_name}")
            return (location.latitude, location.longitude)

        return None

    except ImportError:
        logger.warning("geopy not installed. Run: pip install geopy")
        return None
    except Exception as e:
        logger.error(f"[Nominatim] Error for '{venue_name}': {e}")
        return None


def geocode_gemini(venue_name: str, city: str) -> Optional[Tuple[float, float]]:
    """
    Ask Gemini (with Search Grounding) for the exact coordinates of a venue.
    Returns (lat, lng) or None.
    """
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return None

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Search Google for the exact GPS coordinates of '{venue_name}' in {city}, Saudi Arabia. "
            f"Return ONLY a JSON object with keys 'lat' and 'lng' as decimal numbers. "
            f"Example: {{\"lat\": 21.4858, \"lng\": 39.1925}}. No other text."
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
            ),
        )

        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        lat, lng = float(data["lat"]), float(data["lng"])

        # Sanity check: Saudi Arabia bounding box
        if 16.0 <= lat <= 32.5 and 34.5 <= lng <= 56.0:
            logger.debug(f"[Gemini Geocode] ✅ {venue_name} → ({lat:.4f}, {lng:.4f})")
            console.print(f"[bold blue][G] [Agent 3] Gemini Search Geocoding used for: {venue_name}[/bold blue]")
            return (lat, lng)

        logger.warning(f"[Gemini Geocode] Coordinates out of Saudi Arabia bounds for {venue_name}")
        return None

    except Exception as e:
        logger.error(f"[Gemini Geocode] Error for '{venue_name}': {e}")
        return None


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Road Distance (OSRM) ─────────────────────────────────────────────────────

def get_road_distance_osrm(
    from_lat: float, from_lng: float,
    to_lat: float, to_lng: float,
) -> Optional[dict]:
    """
    Query the public OSRM (Open Source Routing Machine) API for real road distance.
    Free, no API key. Returns dict with distance_km and duration_minutes.
    """
    try:
        import requests

        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{from_lng},{from_lat};{to_lng},{to_lat}"
            f"?overview=false&annotations=false"
        )

        resp = requests.get(url, timeout=8)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") == "Ok" and data.get("routes"):
            route = data["routes"][0]
            console.print(f"[bold magenta][O] [Agent 3] OSRM Road Distance used[/bold magenta]")
            return {
                "distance_km": round(route["distance"] / 1000, 2),
                "duration_minutes": round(route["duration"] / 60),
                "source": "osrm",
            }

        return None

    except Exception as e:
        logger.warning(f"[OSRM] Failed: {e}. Falling back to Haversine.")
        return None


def get_road_distance(
    from_lat: float, from_lng: float,
    to_lat: float, to_lng: float,
) -> Optional[dict]:
    """
    Get road distance between two points.
    OSRM ONLY. No fallbacks.
    """
    routing = get_road_distance_osrm(from_lat, from_lng, to_lat, to_lng)
    if not routing:
        console.print(f"[bold red][!] [Agent 3] OSRM Road Distance API failed. (No fallback)[/bold red]")
    return routing


# ─── Geolocation of Venue List ────────────────────────────────────────────────

def geocode_venues(
    venue_stubs: List[VenueStub],
    city: str,
    hotel_coords: Optional[Tuple[float, float]] = None,
) -> List[GeolocatedVenue]:
    """
    Takes Agent 2's venue list (no coords) and fills in real-world coordinates.
    Also calculates road distance from hotel to each venue.

    Strategy: Nominatim → Gemini → city-center fallback.
    """
    from config import CITY_COORDS

    city_fallback = CITY_COORDS.get(city.lower(), {"lat": 24.7136, "lng": 46.6753})
    geolocated = []

    for stub in venue_stubs:
        lat, lng = None, None
        source = "fallback"

        # Step 1: Nominatim
        coords = geocode_nominatim(stub.name, city)
        if coords:
            lat, lng = coords
            source = "nominatim"
        else:
            # Step 2: Gemini
            time.sleep(0.5)  # be gentle with APIs
            coords = geocode_gemini(stub.name, city)
            if coords:
                lat, lng = coords
                source = "gemini"
            else:
                console.print(f"[bold red][!] [Agent 3] Geocoding failed for: {stub.name}. (No fallback)[/bold red]")
                continue # Skip this venue if it can't be geolocated

        # Road distance from hotel (if hotel coords known)
        road_dist = None
        drive_mins = None
        walk_mins = None

        if hotel_coords and stub.type != "hotel":
            routing = get_road_distance(hotel_coords[0], hotel_coords[1], lat, lng)
            road_dist = routing["distance_km"]
            drive_mins = routing["duration_minutes"]
            walk_mins = round((road_dist / 5) * 60) if road_dist < 3 else None  # walk if < 3km

        geolocated.append(GeolocatedVenue(
            name=stub.name,
            type=stub.type,
            lat=round(lat, 6),
            lng=round(lng, 6),
            geocode_source=source,
            road_distance_km=road_dist,
            drive_time_minutes=drive_mins,
            walk_time_minutes=walk_mins,
        ))

        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec

    return geolocated


# ─── Live Flight Prices ───────────────────────────────────────────────────────

def search_flight_prices(
    origin: str,
    destination: str,
    travel_date: Optional[str] = None,
) -> Optional[FlightPricing]:
    """
    Use Gemini Search Grounding to find real-time flight prices.
    Returns FlightPricing or None if search fails.
    """
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return None

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        date_hint = f"on {travel_date}" if travel_date else "in the next few weeks"
        prompt = (
            f"Search Google Flights for the cheapest one-way flight from {origin} to {destination} "
            f"{date_hint}. Return ONLY valid JSON with fields: "
            f"price_one_way (number in SAR), airline (string), duration_minutes (integer). "
            f"Example: {{\"price_one_way\": 350, \"airline\": \"Flynas\", \"duration_minutes\": 90}}. "
            f"No other text."
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
            ),
        )

        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        one_way = float(data.get("price_one_way", 0))
        if one_way <= 0:
            return None

        console.print(f"[bold green][F] [Agent 3] Gemini Flight Search used: {origin} to {destination}[/bold green]")
        return FlightPricing(
            origin=origin,
            destination=destination,
            price_one_way=one_way,
            price_round_trip=round(one_way * 1.85, 2),  # typical round-trip multiplier
            currency="SAR",
            airline=data.get("airline"),
            duration_minutes=data.get("duration_minutes"),
            source="gemini_grounding",
            confidence="medium",
        )

    except Exception as e:
        logger.error(f"[Flight Search] Failed ({origin}→{destination}): {e}")
        return None


# ─── Live Car Rental Prices ───────────────────────────────────────────────────

def search_car_rental_prices(
    city: str,
    days: int = 3,
) -> Optional[CarRentalPricing]:
    """
    Use Gemini Search Grounding to find real car rental prices in the destination city.
    """
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return None

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Search Google for the cheapest car rental per day in {city}, Saudi Arabia right now. "
            f"Return ONLY valid JSON: {{\"price_per_day\": <number in SAR>, \"vehicle_type\": <string>, \"company\": <string>}}. "
            f"No other text."
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.0,
            ),
        )

        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)

        price = float(data.get("price_per_day", 0))
        if price <= 0:
            return None

        console.print(f"[bold green][C] [Agent 3] Gemini Car Rental Search used for {city}[/bold green]")
        return CarRentalPricing(
            city=city,
            price_per_day=price,
            currency="SAR",
            vehicle_type=data.get("vehicle_type"),
            company=data.get("company"),
            source="gemini_grounding",
            confidence="medium",
        )

    except Exception as e:
        logger.error(f"[Car Rental Search] Failed for {city}: {e}")
        return None


def search_car_rental_fallback(city: str) -> CarRentalPricing:
    """Flat-rate fallback if live car rental search fails."""
    return CarRentalPricing(
        city=city,
        price_per_day=120.0,
        currency="SAR",
        vehicle_type="Economy",
        company="Estimated",
        source="fallback_estimate",
        confidence="low",
    )
