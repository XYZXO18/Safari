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
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import List, Optional

from google import genai
from google.genai import types
from safari.database import get_cached_events, save_event, get_any_events_for_city

# ─── File-based event cache (8-hour TTL, city + date keyed) ──────────────────

_EVENTS_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "events_cache.json"
_EVENTS_CACHE: Optional[dict] = None
_EVENTS_TTL = 8 * 3600  # 8 hours


def _load_events_cache() -> dict:
    global _EVENTS_CACHE
    if _EVENTS_CACHE is None:
        if _EVENTS_CACHE_FILE.exists():
            try:
                with open(_EVENTS_CACHE_FILE, encoding="utf-8") as f:
                    _EVENTS_CACHE = json.load(f)
            except Exception:
                _EVENTS_CACHE = {}
        else:
            _EVENTS_CACHE = {}
    return _EVENTS_CACHE


def _save_events_cache(cache: dict) -> None:
    try:
        _EVENTS_CACHE_FILE.parent.mkdir(exist_ok=True)
        with open(_EVENTS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _events_cache_key(city: str, start_date: str, end_date: str) -> str:
    return f"{city.lower().strip()}__{start_date}__{end_date}"

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
    interests_str = f" The user is specifically interested in: {interests}." if interests else ""

    from config import CITY_COORDS, CITY_TO_COUNTRY
    
    # Try to find country from CITY_TO_COUNTRY, but if city is actually a country, use it
    country = CITY_TO_COUNTRY.get(city.lower())
    if not country:
        # Simple check: if city is in a known list of countries, use it as country
        known_countries = ["spain", "france", "italy", "germany", "japan", "china", "usa", "uk", "austria", "egypt", "jordan", "oman", "qatar", "uae"]
        if city.lower() in known_countries:
            country = city.title()
        else:
            country = "Saudi Arabia" # Fallback

    city_coords = CITY_COORDS.get(city.lower())
    if not city_coords:
        # If no coords, we'll try to let the AI find them, but provide a null-ish hint
        lat_ex = 0.0
        lng_ex = 0.0
    else:
        lat_ex = city_coords["lat"]
        lng_ex = city_coords["lng"]

    prompt = (
        f"Search the web for live events, concerts, festivals, exhibitions, "
        f"pop-up experiences, and social media trending gatherings happening in "
        f"{city}, {country} between {start_date} and {end_date}.{interests_str} "
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
        caller="Agent 1 · EventScanner",
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


# ─── Public API ──────────────────────────────────────────────────────────────

def find_live_events(
    location: str,
    start_date: str,
    end_date: str,
    interests: str = "",
    max_events: int = 10,
) -> EventScanResult:
    """
    Discover live events for a city + date range.
    Results are cached in data/events_cache.json for 8 hours.
    Budget, travel mode, and other trip params do NOT affect this cache —
    the same events are reused for any plan to the same city within the TTL.
    """
    from config import CITY_COORDS

    city_coords = CITY_COORDS.get(location.lower(), {"lat": 24.7136, "lng": 46.6753})
    cache_key = _events_cache_key(location, start_date, end_date)
    cache = _load_events_cache()

    # ── Step 1: Return file cache if still fresh (< 8 hours old) ───────────
    entry = cache.get(cache_key)
    if entry and time.time() - entry["fetched_at"] <= _EVENTS_TTL:
        age_mins = int((time.time() - entry["fetched_at"]) / 60)
        print(f"[EventCache] HIT — {location} ({age_mins}m old), {len(entry['events'])} events")
        events = [LiveEvent(**e) for e in entry["events"]]
        return EventScanResult(
            city=location,
            start_date=start_date,
            end_date=end_date,
            events=events[:max_events],
            total_event_cost=round(sum(e.estimated_cost_sar for e in events), 2),
            scan_source="file_cache",
        )

    # ── Step 2: Cache miss or expired — fetch fresh from web ───────────────
    web_events = _search_events_web(location, start_date, end_date, interests)
    scan_source = "web_search" if web_events else "none"

    # Fill missing coordinates before saving
    for ev in web_events:
        if ev.lat is None or ev.lng is None:
            ev.lat = city_coords["lat"]
            ev.lng = city_coords["lng"]
        save_event(location, ev.to_dict())

    events = list(web_events)

    # ── Step 3: Fall back to SQLite DB if web returned nothing ─────────────
    if not events:
        cached_data = get_cached_events(location, start_date, end_date) or get_any_events_for_city(location)
        for item in cached_data:
            events.append(LiveEvent(
                name=item['name'],
                date=item['event_date'],
                time=item.get('time', 'TBD'),
                estimated_cost_sar=item.get('estimated_cost_sar', 0),
                category=item.get('category', 'event'),
                source="db_cache",
                description=item.get('description', ''),
                venue=item.get('venue', ''),
                lat=item.get('lat') or city_coords["lat"],
                lng=item.get('lng') or city_coords["lng"],
            ))
        if events:
            scan_source = "db_cache"

    # ── Step 4: Apply interest filter ──────────────────────────────────────
    if interests and events:
        keywords = [k.strip().lower() for k in interests.split(",")]
        filtered = [
            ev for ev in events
            if any(k in f"{ev.name} {ev.description} {ev.category}".lower() for k in keywords)
        ]
        if filtered:
            events = filtered

    # ── Step 5: Deduplicate and fill any remaining missing coords ───────────
    seen, unique = set(), []
    for ev in events:
        if ev.name not in seen:
            seen.add(ev.name)
            if ev.lat is None or ev.lng is None:
                ev.lat = city_coords["lat"]
                ev.lng = city_coords["lng"]
            unique.append(ev)
    events = unique[:max_events]

    # ── Step 6: Persist to file cache ──────────────────────────────────────
    cache[cache_key] = {
        "fetched_at": time.time(),
        "events": [e.to_dict() for e in events],
    }
    _save_events_cache(cache)

    total_cost = sum(ev.estimated_cost_sar for ev in events)

    return EventScanResult(
        city=location,
        start_date=start_date,
        end_date=end_date,
        events=events,
        total_event_cost=round(total_cost, 2),
        scan_source=scan_source,
    )
