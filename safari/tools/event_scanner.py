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
    from config import GEMINI_API_KEY

    if not GEMINI_API_KEY:
        return []

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        interests_str = f" The user is specifically interested in: {interests}." if interests else ""

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
            f'"lat": 24.7, "lng": 46.7}}'
            f"\nIf no events are found, return an empty array: []"
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )

        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)

        # Handle both array and object responses
        if isinstance(data, dict):
            data = data.get("events", [data])

        events = []
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

    except Exception as e:
        print(f"Event web search failed: {e}")
        return []


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

    Uses a hybrid approach:
      1. First attempts real-time web search via Gemini Google Search grounding.
      2. Falls back to a curated local seasonal event database.

    Parameters
    ----------
    location : str
        The destination city (e.g., 'Riyadh', 'Jeddah', 'Al-Ula').
    start_date : str
        Trip start date in ISO format (YYYY-MM-DD).
    end_date : str
        Trip end date in ISO format (YYYY-MM-DD).
    max_events : int
        Maximum number of events to return (default 3).

    Returns
    -------
    EventScanResult
        Contains a list of LiveEvent objects with names, dates, costs,
        and metadata. Also includes total_event_cost for budget deduction.

    Examples
    --------
    >>> result = find_live_events("Riyadh", "2026-05-01", "2026-05-03")
    >>> result.has_events
    True
    >>> result.events[0].name
    'Riyadh Season'
    """

    # ─── Method A: Try web search first ──────────────────────────────
    events = _search_events_web(location, start_date, end_date, interests)
    scan_source = "web_search" if events else "none"

    # ─── Method B: Fall back to local database ───────────────────────
    if not events:
        events = _search_events_local(location, start_date, end_date, interests)
        scan_source = "local_db" if events else "none"

    # ─── Deduplicate by name ─────────────────────────────────────────
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
