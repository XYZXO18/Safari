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
from pathlib import Path
from typing import List, Optional, Tuple
from rich.console import Console

from safari.agent.schemas import (
    GeolocatedVenue, VenueStub,
    FlightPricing, CarRentalPricing
)

logger = logging.getLogger(__name__)
console = Console()

# ─── Flight / car-rental price cache (1-hour TTL) ────────────────────────────
_PRICE_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "flight_cache.json"
_PRICE_CACHE: Optional[dict] = None
_PRICE_TTL = 3600


def _load_price_cache() -> dict:
    global _PRICE_CACHE
    if _PRICE_CACHE is None:
        if _PRICE_CACHE_FILE.exists():
            try:
                with open(_PRICE_CACHE_FILE, encoding="utf-8") as f:
                    _PRICE_CACHE = json.load(f)
            except Exception:
                _PRICE_CACHE = {}
        else:
            _PRICE_CACHE = {}
    return _PRICE_CACHE


def _save_price_cache(cache: dict) -> None:
    try:
        _PRICE_CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(_PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[PriceCache] Could not save: {e}")


def _price_get(key: str) -> Optional[dict]:
    cache = _load_price_cache()
    entry = cache.get(key)
    if entry and time.time() - entry["ts"] <= _PRICE_TTL:
        return entry["data"]
    if entry:
        del cache[key]
    return None


def _price_put(key: str, data: dict) -> None:
    cache = _load_price_cache()
    cache[key] = {"data": data, "ts": time.time()}
    _save_price_cache(cache)


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

        from safari.gemini_log import log_gemini
        log_gemini("Agent 3 · Transport", f"geocoding '{venue_name}' in {city}")
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
    Results are cached for 1 hour — Gemini is only called on cache miss.
    """
    from config import AIRPORTS
    orig_key = origin.lower().strip()
    dest_key = destination.lower().strip()

    orig_info = AIRPORTS.get(orig_key, {})
    dest_info = AIRPORTS.get(dest_key, {})

    # Skip immediately if either city has no airport of its own
    if orig_info and orig_info.get("airport_city", orig_key) != orig_key:
        print(f"[FlightSearch] {origin} has no airport — skipping flight search.")
        return None
    if dest_info and dest_info.get("airport_city", dest_key) != dest_key:
        print(f"[FlightSearch] {destination} has no airport — skipping flight search.")
        return None

    cache_key = f"flight__{orig_key}__{dest_key}"
    cached = _price_get(cache_key)
    if cached:
        console.print(f"[bold green][F] [Agent 3] Flight price cache HIT: {origin} -> {destination}[/bold green]")
        return FlightPricing(**cached)

    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return None

        from google import genai
        from google.genai import types

        from safari.gemini_log import log_gemini
        log_gemini("Agent 3 · Transport", f"flight prices {origin} -> {destination}")
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
        result = FlightPricing(
            origin=origin,
            destination=destination,
            price_one_way=one_way,
            price_round_trip=round(one_way * 1.85, 2),
            currency="SAR",
            airline=data.get("airline"),
            duration_minutes=data.get("duration_minutes"),
            source="gemini_grounding",
            confidence="medium",
        )
        _price_put(cache_key, result.model_dump())
        return result

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
    Results are cached for 1 hour.
    """
    cache_key = f"rental__{city.lower()}"
    cached = _price_get(cache_key)
    if cached:
        console.print(f"[bold green][C] [Agent 3] Car rental cache HIT for {city}[/bold green]")
        return CarRentalPricing(**cached)

    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return None

        from google import genai
        from google.genai import types

        from safari.gemini_log import log_gemini
        log_gemini("Agent 3 · Transport", f"car rental prices in {city}")
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
        result = CarRentalPricing(
            city=city,
            price_per_day=price,
            currency="SAR",
            vehicle_type=data.get("vehicle_type"),
            company=data.get("company"),
            source="gemini_grounding",
            confidence="medium",
        )
        _price_put(cache_key, result.model_dump())
        return result

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


# ─── Live Bus / Train Search ──────────────────────────────────────────────────

# ─── Airport Lookup ──────────────────────────────────────────────────────────

def find_nearest_airport(city: str) -> dict:
    """
    Return the nearest airport info for a city.
    Returns dict with keys: airport_city, iata, name, km_to_airport, has_own_airport.
    Falls back to a Gemini search if city is not in the AIRPORTS table.
    """
    from config import AIRPORTS
    city_lower = city.lower().strip()
    info = AIRPORTS.get(city_lower)
    if info:
        return {**info, "has_own_airport": info["km_to_airport"] == 0}

    # Unknown city — ask Gemini for nearest airport
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return {"airport_city": city, "iata": "???", "name": "Unknown Airport",
                    "km_to_airport": 0, "has_own_airport": True}
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"What is the nearest commercial airport to {city}, Saudi Arabia? "
            f"Return ONLY valid JSON: {{\"airport_city\": string, \"iata\": string, "
            f"\"name\": string, \"km_to_airport\": number}}. No other text."
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.0,
            ),
        )
        raw = re.sub(r"^```(?:json)?\s*", "", response.text.strip())
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        km = float(data.get("km_to_airport", 0))
        return {
            "airport_city": data.get("airport_city", city),
            "iata": data.get("iata", "???"),
            "name": data.get("name", "Airport"),
            "km_to_airport": km,
            "has_own_airport": km == 0,
        }
    except Exception as e:
        logger.error(f"[Airport Lookup] Failed for {city}: {e}")
        return {"airport_city": city, "iata": "???", "name": "Nearest Airport",
                "km_to_airport": 0, "has_own_airport": True}


def build_via_airport_journey(
    origin: str,
    destination: str,
    travel_date: Optional[str] = None,
) -> Optional[dict]:
    """
    For origins without a direct airport, builds a two-leg journey:
      Leg 1: origin → nearest_airport  (car or bus — whichever is cheaper)
      Leg 2: nearest_airport → destination  (flight)

    Returns a dict describing both legs + totals, or None if flight search fails.
    """
    airport_info = find_nearest_airport(origin)
    if airport_info["has_own_airport"]:
        return None  # origin has its own airport — no via-journey needed

    airport_city = airport_info["airport_city"]
    km_to_airport = airport_info["km_to_airport"]

    # Leg 1 costs: drive vs SAPTCO bus
    from safari.tools.fuel import calculate_driving_cost
    fuel = calculate_driving_cost(km_to_airport, fuel_type="91", round_trip=False)
    leg1_car_cost = fuel["cost_one_way"]
    leg1_bus_cost = round(km_to_airport * 0.15, 2)       # ~0.15 SAR/km for SAPTCO
    leg1_car_time = round((km_to_airport / 110) * 60)    # minutes at 110 km/h
    leg1_bus_time = round((km_to_airport / 80) * 60) + 30  # slower + boarding

    # Use the cheaper leg1 option as the recommended one
    leg1_mode = "car" if leg1_car_cost <= leg1_bus_cost else "bus"
    leg1_cost = leg1_car_cost if leg1_mode == "car" else leg1_bus_cost
    leg1_time = leg1_car_time if leg1_mode == "car" else leg1_bus_time

    # Leg 2: flight from airport_city → destination
    flight = search_flight_prices(airport_city, destination, travel_date)
    if not flight:
        return None

    total_one_way = round(leg1_cost + flight.price_one_way, 2)
    total_round_trip = round(leg1_cost * 2 + flight.price_round_trip, 2)
    total_time = leg1_time + (flight.duration_minutes or 90) + 90  # +90 for airport

    return {
        "type": "via_airport",
        "origin": origin,
        "destination": destination,
        "airport_city": airport_city,
        "airport_iata": airport_info["iata"],
        "airport_name": airport_info["name"],
        "leg1": {
            "from": origin,
            "to": airport_city,
            "mode": leg1_mode,
            "distance_km": km_to_airport,
            "cost_sar": leg1_cost,
            "time_minutes": leg1_time,
            "fuel_detail": fuel if leg1_mode == "car" else None,
            "note": f"{'Drive' if leg1_mode == 'car' else 'Bus (SAPTCO)'} to {airport_info['name']}",
        },
        "leg2": {
            "from": airport_city,
            "to": destination,
            "mode": "flight",
            "airline": flight.airline,
            "price_one_way": flight.price_one_way,
            "price_round_trip": flight.price_round_trip,
            "duration_minutes": flight.duration_minutes,
            "source": flight.source,
        },
        "total_one_way": total_one_way,
        "total_round_trip": total_round_trip,
        "total_time_minutes": total_time,
        "also_available": {
            "car_to_airport": {"cost": leg1_car_cost, "time_minutes": leg1_car_time},
            "bus_to_airport": {"cost": leg1_bus_cost, "time_minutes": leg1_bus_time},
        },
    }


def _gemini_transport_search(prompt: str, caller_label: str) -> Optional[dict]:
    """Shared Gemini search helper for bus/train/transit queries. Returns parsed dict or None."""
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return None
        from google import genai
        from google.genai import types
        from safari.gemini_log import log_gemini
        log_gemini("Agent 3 · Transport", caller_label)
        client = genai.Client(api_key=GEMINI_API_KEY)
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
        return json.loads(raw)
    except Exception as e:
        logger.error(f"[Gemini Transport] {caller_label} failed: {e}")
        return None


def search_buses_live(origin: str, destination: str) -> dict:
    """
    Search for bus routes between two Saudi cities via Gemini.
    Returns a dict with operator, options list, and source.
    """
    prompt = (
        f"Search for bus services from {origin} to {destination} in Saudi Arabia right now. "
        f"Include SAPTCO and any other operators. "
        f"Return ONLY valid JSON: {{\"operator\": string, \"options\": ["
        f"{{\"class\": string, \"price_sar\": number, \"duration_hours\": number, \"frequency\": string}}], "
        f"\"booking_url\": string or null}}. "
        f"Return an empty options array if no service exists."
    )
    data = _gemini_transport_search(prompt, f"bus {origin}→{destination}")
    if data and data.get("options"):
        console.print(f"[bold green][B] Gemini Bus Search: {origin}→{destination} ({len(data['options'])} options)[/bold green]")
        data["source"] = "gemini_grounding"
        return data
    return {"operator": "SAPTCO", "options": [], "source": "not_found"}


def search_trains_live(origin: str, destination: str) -> dict:
    """
    Search for train routes between two Saudi cities via Gemini.
    Covers SAR (Saudi Railways) and Haramain High-Speed Railway.
    """
    prompt = (
        f"Search for train services from {origin} to {destination} in Saudi Arabia. "
        f"Include SAR (Saudi Railways Organization) and Haramain High-Speed Railway. "
        f"Return ONLY valid JSON: {{\"operator\": string, \"options\": ["
        f"{{\"class\": string, \"price_sar\": number, \"duration_minutes\": number, \"frequency\": string}}], "
        f"\"booking_url\": string or null}}. "
        f"Return an empty options array if no direct service exists."
    )
    data = _gemini_transport_search(prompt, f"train {origin}→{destination}")
    if data and data.get("options"):
        console.print(f"[bold green][T] Gemini Train Search: {origin}→{destination} ({len(data['options'])} options)[/bold green]")
        data["source"] = "gemini_grounding"
        return data
    return {"operator": "SAR", "options": [], "source": "not_found"}


def search_public_transit_live(city: str) -> list:
    """
    Search for local public transit options in a Saudi city via Gemini.
    Returns list of transit systems with fare info. Cached in DB for 7 days.
    """
    prompt = (
        f"Search for local public transportation options in {city}, Saudi Arabia. "
        f"Include metro lines, city buses, tram, and ride-hailing apps. "
        f"Return ONLY a valid JSON array: ["
        f"{{\"type\": string (metro/bus/tram/ridehail), \"name\": string, "
        f"\"fare_min_sar\": number, \"fare_max_sar\": number, "
        f"\"coverage\": string (short description of what areas it covers), "
        f"\"app\": string or null, \"notes\": string or null}}]. "
        f"Only include services that actually operate in {city}."
    )
    data = _gemini_transport_search(prompt, f"public transit {city}")
    if isinstance(data, list) and data:
        console.print(f"[bold green][P] Gemini Public Transit: {city} ({len(data)} services)[/bold green]")
        return data
    # Fallback: well-known static data for major cities
    return _public_transit_fallback(city)


def _public_transit_fallback(city: str) -> list:
    """Minimal static fallback for cities where Gemini search fails."""
    city_lower = city.lower()
    fallbacks = {
        "riyadh": [
            {"type": "metro", "name": "Riyadh Metro", "fare_min_sar": 4, "fare_max_sar": 6,
             "coverage": "6 lines covering central Riyadh, KAFD, King Abdullah, Riyadh Park",
             "app": "Riyadh Metro App", "notes": "Fully operational since 2024"},
            {"type": "bus", "name": "Riyadh Bus (Mowasalat)", "fare_min_sar": 3, "fare_max_sar": 4,
             "coverage": "Connects major districts and metro stations", "app": "Mowasalat App", "notes": None},
            {"type": "ridehail", "name": "Uber / Careem", "fare_min_sar": 10, "fare_max_sar": 80,
             "coverage": "City-wide", "app": "Uber / Careem", "notes": "Most convenient option"},
        ],
        "jeddah": [
            {"type": "bus", "name": "Jeddah Bus (Hafilat)", "fare_min_sar": 4, "fare_max_sar": 4,
             "coverage": "Major arterial routes across Jeddah", "app": "Hafilat App", "notes": None},
            {"type": "ridehail", "name": "Uber / Careem", "fare_min_sar": 10, "fare_max_sar": 80,
             "coverage": "City-wide", "app": "Uber / Careem", "notes": None},
        ],
        "makkah": [
            {"type": "metro", "name": "Haramain High-Speed Railway (to Jeddah/Madinah)", "fare_min_sar": 65, "fare_max_sar": 235,
             "coverage": "Makkah ↔ Jeddah ↔ Madinah", "app": "HHR App", "notes": "Inter-city, not local"},
            {"type": "bus", "name": "Makkah Bus", "fare_min_sar": 3, "fare_max_sar": 5,
             "coverage": "City routes + Holy Sites shuttle", "app": None, "notes": "Frequent during Hajj/Umrah season"},
        ],
        "madinah": [
            {"type": "metro", "name": "Haramain High-Speed Railway (to Jeddah/Makkah)", "fare_min_sar": 65, "fare_max_sar": 235,
             "coverage": "Madinah ↔ Jeddah ↔ Makkah", "app": "HHR App", "notes": "Inter-city"},
            {"type": "ridehail", "name": "Uber / Careem", "fare_min_sar": 8, "fare_max_sar": 50,
             "coverage": "City-wide", "app": "Uber / Careem", "notes": None},
        ],
    }
    return fallbacks.get(city_lower, [
        {"type": "ridehail", "name": "Uber / Careem", "fare_min_sar": 10, "fare_max_sar": 80,
         "coverage": "City-wide", "app": "Uber / Careem", "notes": "Available in most Saudi cities"},
    ])
