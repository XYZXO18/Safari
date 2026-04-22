"""
Activity Suggester
==================
Suggests budget-appropriate activities for a given destination vibe.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Dict

from config import DESTINATIONS


from google import genai
from google.genai import types
import json

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
}


def get_web_places(city: str, vibe: str) -> dict:
    """Search the web dynamically using Gemini's Google Search grounding to find places with coords."""
    from config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        return {"hotel": {}, "activities": []}
        
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Search the web for the top 8 specific, real sightseeing places and activities "
            f"in {city} ({vibe} vibe), and 1 specific real hotel in {city}. "
            f"Return ONLY a raw JSON object with this exact structure: "
            f"{{\"hotel\": {{\"name\": \"...\", \"lat\": 24.7, \"lng\": 46.7}}, "
            f"\"activities\": [{{\"name\": \"...\", \"lat\": 24.7, \"lng\": 46.7}}]}}"
        )
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.2,
                response_mime_type="application/json",
            )
        )
        
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data
    except Exception as e:
        print(f"Web search failed: {e}")
        
    return {"hotel": {}, "activities": []}

def suggest_activities(
    destination: str, days: int, daily_activities_budget: float, currency: str = "SAR",
) -> ActivityPlan:
    """Suggest activities that fit within the daily activities budget."""
    dest_lower = destination.lower().strip()
    dest_info = DESTINATIONS.get(dest_lower, DESTINATIONS["coast"])
    if dest_lower not in DESTINATIONS:
        dest_lower = "coast"

    cities = dest_info["cities"]
    recommended_city = cities[0] if cities else destination.title()
    
    from config import CITY_COORDS
    city_coords = CITY_COORDS.get(recommended_city.lower(), CITY_COORDS.get(dest_lower, {"lat": 24.7, "lng": 46.7}))

    # Base fallback activities
    all_activities = [{"name": a, "lat": None, "lng": None} for a in dest_info["activities"]]
    hotel = {}

    # ─── Dynamic Web Search ───
    web_data = get_web_places(recommended_city, dest_info["vibe"])
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
