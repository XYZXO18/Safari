"""
Activity Suggester
==================
Suggests budget-appropriate activities for a given destination vibe.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional

from config import DESTINATIONS
from google import genai
from google.genai import types

def load_reviews():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "reviews.json"), "r") as f:
            return json.load(f)
    except:
        return {"activities": {}, "destinations": {}}

_REVIEWS_DB = load_reviews()

# ─── Web-places cache (1-hour TTL) ───────────────────────────────────────────
_PLACES_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "places_cache.json"
_PLACES_CACHE: Optional[dict] = None
_PLACES_TTL = 3600


def _load_places_cache() -> dict:
    global _PLACES_CACHE
    if _PLACES_CACHE is None:
        if _PLACES_CACHE_FILE.exists():
            try:
                with open(_PLACES_CACHE_FILE, encoding="utf-8") as f:
                    _PLACES_CACHE = json.load(f)
            except Exception:
                _PLACES_CACHE = {}
        else:
            _PLACES_CACHE = {}
    return _PLACES_CACHE


def _save_places_cache(cache: dict) -> None:
    try:
        _PLACES_CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(_PLACES_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

@dataclass
class ActivityPlan:
    """Activities organized by day, within budget."""
    destination: str
    vibe: str
    days: int
    daily_budget: float
    currency: str = "SAR"
    daily_activities: Dict[int, List[dict]] = field(default_factory=dict)
    recommended_city: str = ""
    hotel: dict = field(default_factory=dict)
    timeline: dict = field(default_factory=dict)
    total_transit_cost: float = 0.0

    @property
    def summary(self) -> str:
        lines = [
            f"🎯 Activity Plan — {self.vibe.title()} ({self.recommended_city})",
            f"   Daily activity budget: {self.daily_budget:.0f} {self.currency}",
        ]
        if self.hotel:
            lines.append(f"   🏨 Recommended Hotel: {self.hotel.get('name', 'Local Hotel')}")
        lines.append("")
        for day, acts in sorted(self.daily_activities.items()):
            lines.append(f"   Day {day}:")
            for a in acts:
                name = a["name"] if isinstance(a, dict) else a
                lines.append(f"     • {name}")
        return "\n".join(lines)


_ACTIVITY_COSTS: Dict[str, float] = {
    "Snorkeling & diving": 200, "Beach camping": 50,
    "Seafood dinner by the shore": 120, "Jet ski rental": 250,
    "Corniche walk": 0, "Fish market visit": 30, "Sunset cruise": 180,
    "Cable car ride": 75, "Mountain hiking": 0, "Visit hanging village": 50,
    "Local honey tasting": 40, "Flower garden tours": 30,
    "Traditional village walk": 0, "Cliff-edge café": 60,
    "Stargazing camp": 150, "Off-road dune bashing": 300,
    "Hegra ancient ruins tour": 100, "Camel ride": 120,
    "Desert bonfire dinner": 100, "Sandboarding": 80, "Elephant Rock visit": 20,
    "Boulevard Riyadh City": 100, "Historical Diriyah tour": 60,
    "Fine dining experience": 250, "Mall exploration": 50,
    "Art gallery visit": 40, "Rooftop café": 80, "Local souq haggling": 30,
    "Historical downtown walking tour": 0, "Marina promenade stroll": 0, "Visit coastal landmarks": 20,
    "Nature reserve walking trail": 15, "Historic fort exploration": 25, "Valley viewpoint hike": 0,
    "Oasis heritage walking tour": 30, "Ancient tombs sightseeing": 50, "Desert canyon hike": 0,
    "City center landmark walk": 0, "National museum visit": 30, "Historical palaces walking tour": 40,
    "Modern architecture sightseeing": 0,
}


def get_web_places(city: str, vibe: str, city_coords: dict = None) -> dict:
    """Search the web dynamically using Gemini to find places with coords.
    Results are cached for 1 hour so Gemini is only called on cache miss."""
    cache_key = f"{city.lower()}__{vibe.lower()}"
    cache = _load_places_cache()
    entry = cache.get(cache_key)
    if entry and time.time() - entry["ts"] <= _PLACES_TTL:
        return entry["data"]

    from config import GEMINI_API_KEY, GEMINI_MODEL

    if not GEMINI_API_KEY:
        return {"hotel": {}, "activities": []}

    try:
        lat_ex = city_coords["lat"] if city_coords else 24.7
        lng_ex = city_coords["lng"] if city_coords else 46.7

        prompt = (
            f"Search the web for the top 8 specific, real sightseeing places and activities "
            f"in {city} ({vibe} vibe), and 1 specific real hotel in {city}. "
            f"Return ONLY a raw JSON object with this exact structure: "
            f"{{\"hotel\": {{\"name\": \"...\", \"lat\": {lat_ex}, \"lng\": {lng_ex}}}, "
            f"\"activities\": [{{\"name\": \"...\", \"lat\": {lat_ex}, \"lng\": {lng_ex}}}]}}"
            f" IMPORTANT: Provide accurate lat/lng coordinates for {city}. Do not just copy the example coordinates."
        )

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.2,
            )
        )
        text = response.text.strip()
            
        text = text.strip()
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx+1]
        data = json.loads(text)
        cache[cache_key] = {"data": data, "ts": time.time()}
        _save_places_cache(cache)
        return data
    except Exception as e:
        print(f"Web search failed: {e}")

    return {"hotel": {}, "activities": []}

def suggest_activities(
    destination: str, days: int, daily_activities_budget: float, currency: str = "SAR",
    city_override: Optional[str] = None,
) -> ActivityPlan:
    """Suggest activities that fit within the daily activities budget."""
    dest_lower = destination.lower().strip()
    dest_info = DESTINATIONS.get(dest_lower, DESTINATIONS["coast"])
    if dest_lower not in DESTINATIONS:
        dest_lower = "coast"

    cities = dest_info["cities"]
    # Use the specific city chosen by the user (e.g. "Makkah") rather than
    # defaulting to the first city in the vibe group (e.g. "Riyadh" for "city" vibe).
    if city_override:
        recommended_city = city_override.strip().title()
    else:
        recommended_city = cities[0] if cities else destination.title()

    from config import CITY_COORDS
    city_coords = CITY_COORDS.get(recommended_city.lower())
    if not city_coords:
        # Fallback to a neutral coordinate if city not in config
        # Ideally we'd geocode here, but for now we'll use (0,0) or a generic prompt hint
        city_coords = {"lat": 0.0, "lng": 0.0}

    # Base fallback activities
    all_activities = [{"name": a, "lat": None, "lng": None} for a in dest_info["activities"]]
    hotel = {}

    # ─── Dynamic Web Search ───
    web_data = get_web_places(recommended_city, dest_info["vibe"], city_coords)
    hotel = web_data.get("hotel", {})
    web_activities = web_data.get("activities", [])
    
    if web_activities:
        for wa in web_activities:
            name = wa.get("name", "")
            if name not in _ACTIVITY_COSTS:
                _ACTIVITY_COSTS[name] = random.choice([0, 30, 50, 100, 150])
        # Prioritize web activities by putting them at the front
        all_activities = web_activities + all_activities

    # Guarantee all places have coordinates
    if not hotel or not hotel.get("lat") or not hotel.get("lng"):
        hotel = {
            "name": hotel.get("name") or f"{recommended_city.title()} Grand Hotel",
            "lat": city_coords["lat"] + random.uniform(-0.02, 0.02),
            "lng": city_coords["lng"] + random.uniform(-0.02, 0.02)
        }
        
    for act in all_activities:
        if not act.get("lat") or not act.get("lng"):
            act["lat"] = city_coords["lat"] + random.uniform(-0.08, 0.08)
            act["lng"] = city_coords["lng"] + random.uniform(-0.08, 0.08)

    affordable = [a for a in all_activities if _ACTIVITY_COSTS.get(a.get("name", ""), 50) <= daily_activities_budget]
    if not affordable:
        affordable = [a for a in all_activities if _ACTIVITY_COSTS.get(a.get("name", ""), 50) <= 30]
    if not affordable:
        affordable = all_activities

    # Attach reviews data
    for act in affordable:
        act_name = act.get("name", "")
        if act_name in _REVIEWS_DB["activities"]:
            rev_data = _REVIEWS_DB["activities"][act_name]
            act["rating"] = rev_data.get("rating", 0)
            act["review_count"] = rev_data.get("review_count", 0)
            act["why_go"] = rev_data.get("why_go", "")
            act["reviews"] = rev_data.get("reviews", [])

    daily_activities: Dict[int, List[dict]] = {}
    pool = list(affordable)

    for day in range(1, days + 1):
        if not pool:
            pool = list(affordable)
        random.seed(day * 42 + hash(dest_lower))
        random.shuffle(pool)
        day_acts, day_cost = [], 0.0
        for act in pool[:]:
            act_cost = _ACTIVITY_COSTS.get(act.get("name", ""), 50)
            if day_cost + act_cost <= daily_activities_budget and len(day_acts) < 3:
                day_acts.append(act)
                day_cost += act_cost
                pool.remove(act)
        if not day_acts:
            free = [a for a in all_activities if _ACTIVITY_COSTS.get(a.get("name", ""), 50) == 0]
            day_acts = free[:1] if free else [all_activities[0]]
        daily_activities[day] = day_acts

    return ActivityPlan(
        destination=dest_lower, vibe=dest_info["vibe"], days=days,
        daily_budget=daily_activities_budget, currency=currency,
        daily_activities=daily_activities, recommended_city=recommended_city, hotel=hotel
    )
