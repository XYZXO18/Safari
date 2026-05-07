"""
Event Scanner
=============
Discovers live, time-sensitive events (concerts, festivals, pop-ups,
local gatherings) in a destination city during the user's travel dates.

Hybrid approach:
    Method A — Gemini Google-Search grounding: Queries the live web for
               social-media posts and event listings matching the city + dates.
    Method B — Fallback curated seasonal events: A lightweight local database
               of recurring events/festivals by region, used when the web
               search is unavailable or returns no results.

Returns 2-3 highly relevant events with names, dates, and estimated costs.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from google import genai
from google.genai import types
from safari.database import get_cached_events, save_event

def get_ddg_results(query: str, max_results: int = 5) -> str:
    """Fetch search results from DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return "\n".join([f"Source: {r.get('title', '')} - {r.get('body', '')}" for r in results])
    except Exception as e:
        print(f"DDG Search failed: {e}")
        return ""


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class LiveEvent:
    """A single discovered live event."""

    name: str
    date: str                          # human-readable date string
    estimated_cost_sar: float          # ticket / entry cost estimate
    category: str = "event"            # concert | festival | popup | exhibition | sport
    source: str = "web_search"         # web_search | local_db
    description: str = ""
    venue: str = ""
    time: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "date": self.date,
            "estimated_cost_sar": self.estimated_cost_sar,
            "category": self.category,
            "source": self.source,
            "description": self.description,
            "venue": self.venue,
            "time": self.time,
            "lat": self.lat,
            "lng": self.lng,
        }


@dataclass
class EventScanResult:
    """Result of an event scan for a destination + date range."""

    city: str
    start_date: str
    end_date: str
    events: List[LiveEvent] = field(default_factory=list)
    total_event_cost: float = 0.0
    scan_source: str = "none"          # web_search | local_db | none

    @property
    def has_events(self) -> bool:
        return len(self.events) > 0

    @property
    def summary(self) -> str:
        if not self.events:
            return f"🎭 No live events found in {self.city} for {self.start_date} – {self.end_date}"
        lines = [
            f"🎭 Live Events in {self.city} ({self.start_date} → {self.end_date})",
            f"   Source: {self.scan_source}",
            "",
        ]
        for i, ev in enumerate(self.events, 1):
            lines.append(f"   {i}. 🎪 {ev.name}")
            time_str = f" @ {ev.time}" if ev.time else ""
            lines.append(f"      📅 {ev.date}{time_str} | 💰 ~{ev.estimated_cost_sar:.0f} SAR")
            if ev.venue:
                lines.append(f"      📍 {ev.venue}")
            if ev.description:
                lines.append(f"      ℹ️  {ev.description}")
            lines.append("")
        lines.append(f"   Total event costs: {self.total_event_cost:.0f} SAR")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "events": [e.to_dict() for e in self.events],
            "total_event_cost": self.total_event_cost,
            "scan_source": self.scan_source,
        }


# ─── Method A: Gemini Web Search ────────────────────────────────────────────

def _search_events_web(city: str, start_date: str, end_date: str, interests: str = "") -> List[LiveEvent]:
    """
    Use Gemini's Google Search grounding to discover real-time events.

    Sends a targeted query looking for concerts, festivals, exhibitions,
    pop-up events, and social-media-trending gatherings in the given
    city during the specified date range.
    """
    from config import USE_LOCAL_AI

    interests_str = f" The user is specifically interested in: {interests}." if interests else ""

    from config import CITY_COORDS
    city_coords = CITY_COORDS.get(city.lower(), {"lat": 24.7, "lng": 46.7})
    lat_ex = city_coords["lat"]
    lng_ex = city_coords["lng"]

    prompt = (
        f"Search the web for live events, concerts, festivals, exhibitions, "
        f"pop-up experiences, and social media trending gatherings happening in "
        f"{city}, Saudi Arabia between {start_date} and {end_date}.{interests_str} "
        f"Include events from sites like: eventbrite.com, ticketmaster.com, "
        f"visitSaudi.com, x.com, instagram.com. "
        f"Return ONLY a raw JSON array of up to 10 most interesting events "
        f"with this exact structure per item: "
        f'{{"name": "...", "date": "...", "time": "18:00 or TBD", "estimated_cost_sar": 0, '
        f'"category": "concert|festival|popup|exhibition|sport", '
        f'"description": "one sentence", "venue": "venue name", '
        f'"lat": {lat_ex}, "lng": {lng_ex}}}'
        f"\nIMPORTANT: Provide accurate lat/lng coordinates for {city}. Do not just copy the example coordinates."
        f"\nIf no events are found, return an empty array: []"
    )

    from safari.ai_client import generate_with_search, _parse_json

    text = generate_with_search(
        prompt=prompt,
        json_mode=True,
        timeout=60,
    )
    
    if not text or "AI search generation failed" in text:
        return []

    try:
        data = _parse_json(text)
    except Exception as e:
        print(f"Failed to parse event JSON: {e}")
        return []

    # Handle both array and object responses
    if isinstance(data, dict):
        data = data.get("events", [data])

    events = []
    if isinstance(data, list):
        for item in data[:10]:  # Cap at 10 events
            events.append(LiveEvent(
                name=item.get("name", "Unknown Event"),
                date=item.get("date", start_date),
                time=item.get("time", "TBD"),
                estimated_cost_sar=float(item.get("estimated_cost_sar", 0)),
                category=item.get("category", "event"),
                source="web_search",
                description=item.get("description", ""),
                venue=item.get("venue", ""),
                lat=item.get("lat"),
                lng=item.get("lng"),
            ))

    return events


# ─── Method B: Local Seasonal Event Database ────────────────────────────────

_SEASONAL_EVENTS = {
    "riyadh": [
        {"name": "Riyadh Season", "months": [10, 11, 12, 1, 2, 3],
         "cost": 150, "category": "festival", "time": "16:00",
         "description": "Mega entertainment festival with concerts, shows, and experiences",
         "venue": "Boulevard Riyadh City"},
        {"name": "Riyadh International Book Fair", "months": [3, 4],
         "cost": 20, "category": "exhibition", "time": "10:00",
         "description": "Annual literary festival with author talks and book exhibits",
         "venue": "Riyadh International Convention Center"},
        {"name": "Riyadh Art Festival", "months": [1, 2, 3],
         "cost": 0, "category": "exhibition", "time": "18:00",
         "description": "Public art installations and gallery showcases across the city",
         "venue": "Various locations across Riyadh"},
    ],
    "jeddah": [
        {"name": "Jeddah Season", "months": [6, 7, 8],
         "cost": 120, "category": "festival", "time": "17:00",
         "description": "Summer entertainment festival with waterfront events and concerts",
         "venue": "Jeddah Waterfront"},
        {"name": "Red Sea International Film Festival", "months": [11, 12],
         "cost": 80, "category": "festival", "time": "19:00",
         "description": "International film screenings and celebrity appearances",
         "venue": "Jeddah Historical District"},
        {"name": "Jeddah Historic District Nights", "months": [1, 2, 3, 10, 11, 12],
         "cost": 0, "category": "popup", "time": "20:00",
         "description": "Night market with street food, local crafts, and live performances in Al-Balad",
         "venue": "Al-Balad Historic District"},
    ],
    "abha": [
        {"name": "Abha Summer Festival", "months": [6, 7, 8],
         "cost": 50, "category": "festival", "time": "15:00",
         "description": "Cultural festival with traditional music, art, and mountain activities",
         "venue": "Abha City Center"},
        {"name": "Flower Men Festival", "months": [3, 4, 5],
         "cost": 0, "category": "festival", "time": "09:00",
         "description": "Celebration of the Qahtani Flower Men tradition with local heritage",
         "venue": "Rijal Almaa Village"},
    ],
    "al-ula": [
        {"name": "AlUla Arts Festival (Desert X)", "months": [1, 2, 3],
         "cost": 100, "category": "exhibition", "time": "08:00",
         "description": "Contemporary art installations in the desert landscape",
         "venue": "AlUla Desert"},
        {"name": "Winter at Tantora", "months": [12, 1, 2],
         "cost": 200, "category": "concert", "time": "20:00",
         "description": "World-class concerts and cultural experiences at Hegra",
         "venue": "Maraya Concert Hall"},
        {"name": "AlUla Skies Festival", "months": [10, 11],
         "cost": 75, "category": "festival", "time": "06:00",
         "description": "Hot air balloon rides and stargazing experiences over ancient landscapes",
         "venue": "AlUla Skies"},
    ],
    "taif": [
        {"name": "Taif Rose Festival", "months": [3, 4],
         "cost": 0, "category": "festival", "time": "08:00",
         "description": "Celebration of the famous Taif rose harvest with local markets",
         "venue": "Taif Rose Farms"},
        {"name": "Taif Season", "months": [7, 8],
         "cost": 80, "category": "festival", "time": "16:00",
         "description": "Summer highland festival with entertainment and cultural events",
         "venue": "Taif City"},
    ],
    "dammam": [
        {"name": "Sharqiah Season", "months": [1, 2, 3],
         "cost": 100, "category": "festival", "time": "17:00",
         "description": "Eastern Province entertainment festival with family activities",
         "venue": "King Abdulaziz Center for World Culture"},
    ],
    "yanbu": [
        {"name": "Yanbu Flower Festival", "months": [3, 4],
         "cost": 0, "category": "festival", "time": "16:00",
         "description": "Spring flower displays and garden exhibitions",
         "venue": "Yanbu Al Bahr"},
    ],
    "medina": [
        {"name": "Medina Cultural Heritage Week", "months": [1, 9, 10],
         "cost": 0, "category": "exhibition", "time": "09:00",
         "description": "Historical exhibitions and cultural tours of Medina's heritage sites",
         "venue": "Various historical sites"},
    ],
}

# Map vibe categories to representative cities for fallback
_VIBE_TO_CITY = {
    "coast": "jeddah",
    "mountains": "abha",
    "desert": "al-ula",
    "city": "riyadh",
}


def _search_events_local(city: str, start_date: str, end_date: str, interests: str = "") -> List[LiveEvent]:
    """
    Search the local seasonal event database for events that overlap
    with the user's travel dates.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (ValueError, TypeError):
        # If dates can't be parsed, use current month
        today = date.today()
        start = today
        end = today + timedelta(days=3)

    travel_months = set()
    current = start
    while current <= end:
        travel_months.add(current.month)
        current += timedelta(days=15)  # step by ~half a month
    travel_months.add(end.month)

    city_lower = city.lower().strip().replace(" ", "-")

    # Try exact city match, then vibe-based fallback
    city_events = _SEASONAL_EVENTS.get(city_lower, {})
    if not city_events:
        # Try matching without hyphens
        for key in _SEASONAL_EVENTS:
            if key.replace("-", "") == city_lower.replace("-", ""):
                city_events = _SEASONAL_EVENTS[key]
                break

    if not city_events:
        # Vibe fallback
        for vibe, vibe_city in _VIBE_TO_CITY.items():
            if vibe_city in city_lower or city_lower in vibe_city:
                city_events = _SEASONAL_EVENTS.get(vibe_city, [])
                break

    if not city_events:
        return []

    matching = []
    for ev_data in city_events:
        event_months = set(ev_data.get("months", []))
        if travel_months & event_months:  # intersection = overlap
            matching.append(LiveEvent(
                name=ev_data["name"],
                date=f"{start_date} – {end_date}",
                time=ev_data.get("time", "TBD"),
                estimated_cost_sar=float(ev_data.get("cost", 0)),
                category=ev_data.get("category", "event"),
                source="local_db",
                description=ev_data.get("description", ""),
                venue=ev_data.get("venue", ""),
            ))

    # Filter local events by interests (simple keyword match if interests provided)
    if interests:
        keywords = [k.strip().lower() for k in interests.split(",")]
        filtered = []
        for ev in matching:
            ev_text = f"{ev.name} {ev.description} {ev.category}".lower()
            if any(k in ev_text for k in keywords):
                filtered.append(ev)
        if filtered:
            matching = filtered

    return matching[:10]  # Cap at 10


# ─── Public API ──────────────────────────────────────────────────────────────

def find_live_events(
    location: str,
    start_date: str,
    end_date: str,
    interests: str = "",
    max_events: int = 10,
) -> EventScanResult:
    """
    Discover live, time-sensitive events in a destination during travel dates.

    Hybrid approach:
      1. First check the local SQLite database for cached events.
      2. If not enough events, search real-time web via Gemini Google Search grounding.
      3. Falls back to a curated local seasonal event database if still nothing.
      4. Saves any new web results back to the local SQLite database.
    """

    # ─── Step 1: Check SQLite Cache first ────────────────────────────
    cached_data = get_cached_events(location, start_date, end_date)
    events = []
    if cached_data:
        for item in cached_data:
            events.append(LiveEvent(
                name=item['name'],
                date=item['event_date'],
                time=item['time'],
                estimated_cost_sar=item['estimated_cost_sar'],
                category=item['category'],
                source="local_cache",
                description=item['description'],
                venue=item['venue'],
                lat=item['lat'],
                lng=item['lng']
            ))
        print(f"   [Cache Hit] Found {len(events)} events in database for {location}")

        # Filter cached events by interests
        if interests:
            keywords = [k.strip().lower() for k in interests.split(",")]
            filtered = []
            for ev in events:
                ev_text = f"{ev.name} {ev.description} {ev.category}".lower()
                if any(k in ev_text for k in keywords):
                    filtered.append(ev)
            events = filtered
            print(f"   [Cache Hit] {len(events)} events match interests: {interests}")

    # ─── Step 2: Try web search if needed (e.g. if cache has < 3 events) ──
    if len(events) < 3:
        web_events = _search_events_web(location, start_date, end_date, interests)
        if web_events:
            # Add unique ones to our list and save to DB
            existing_names = {e.name for e in events}
            new_added = 0
            for ev in web_events:
                if ev.name not in existing_names:
                    events.append(ev)
                    existing_names.add(ev.name)
                    # Save to DB for future use
                    save_event(location, ev.to_dict())
                    new_added += 1
            if new_added > 0:
                print(f"   [Web Search] Added {new_added} new events to database for {location}")

    scan_source = "hybrid" if events else "none"

    # ─── Step 3: Fall back to local seasonal dictionary if still empty ──
    if not events:
        events = _search_events_local(location, start_date, end_date, interests)
        scan_source = "local_db" if events else "none"

    # ─── Deduplicate and Cap ─────────────────────────────────────────
    seen_names = set()
    unique_events = []
    for ev in events:
        if ev.name not in seen_names:
            seen_names.add(ev.name)
            unique_events.append(ev)
    events = unique_events[:max_events]

    # ─── Calculate total cost ────────────────────────────────────────
    total_cost = sum(ev.estimated_cost_sar for ev in events)

    return EventScanResult(
        city=location,
        start_date=start_date,
        end_date=end_date,
        events=events,
        total_event_cost=round(total_cost, 2),
        scan_source=scan_source,
    )
