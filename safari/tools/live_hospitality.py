"""
Live Hospitality Tool
=====================
Real-time web scraping / LLM-grounded search for hotels, restaurants, and cafes.

Strategy (in priority order):
  1. Gemini Search Grounding  — if GEMINI_API_KEY is set (most structured output)
  2. DuckDuckGo Text Search   — free, no API key, parse results with regex
  3. Fallback Static DB       — existing SQLite (safari/database.py) as last resort

All functions return List[VenueStub] — the shared Pydantic schema.
"""

from __future__ import annotations

import re
import json
import logging
from datetime import datetime
from typing import List, Optional

from safari.agent.schemas import VenueStub

logger = logging.getLogger(__name__)


# ─── Gemini Grounding Search ─────────────────────────────────────────────────

def _gemini_search_venues(
    query: str,
    venue_type: str,
    city: str,
    max_results: int = 5,
) -> List[VenueStub]:
    """
    Use Gemini's Google Search Grounding tool to find real venues with real prices.
    Returns structured VenueStub list parsed from the LLM response.
    """
    try:
        from config import GEMINI_API_KEY, GEMINI_MODEL
        if not GEMINI_API_KEY:
            return []

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        system_prompt = (
            "You are a travel research assistant. "
            "Search for real venues and return ONLY valid JSON. "
            "Do NOT invent data — use only what you find via search. "
            "Return a JSON array with objects having these fields: "
            "name (string), type (hotel|restaurant|cafe), price (number in SAR), "
            "rating (number 0-5), description (string, max 1 sentence), source_url (string or null). "
            "If you cannot find real data, return an empty array []."
        )

        user_prompt = (
            f"Search Google for: {query}\n\n"
            f"Find the top {max_results} real {venue_type}s in {city} with current prices. "
            f"Return ONLY a JSON array of venue objects."
        )

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            ),
        )

        raw = response.text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        if not isinstance(data, list):
            return []

        stubs = []
        for item in data[:max_results]:
            try:
                stubs.append(VenueStub(
                    name=str(item.get("name", "Unknown")),
                    type=item.get("type", venue_type),
                    price=float(item.get("price", 0)),
                    currency="SAR",
                    rating=item.get("rating"),
                    description=item.get("description"),
                    source_url=item.get("source_url"),
                ))
            except Exception as e:
                logger.warning(f"Skipping malformed venue item: {e}")
                continue

        logger.info(f"[Gemini Grounding] Found {len(stubs)} {venue_type}(s) in {city}")
        return stubs

    except Exception as e:
        logger.error(f"[Gemini Grounding] Failed for query '{query}': {e}")
        return []


# ─── DuckDuckGo Fallback Search ──────────────────────────────────────────────

def _ddg_search_venues(
    query: str,
    venue_type: str,
    city: str,
    budget: float,
    max_results: int = 5,
) -> List[VenueStub]:
    """
    Fallback: DuckDuckGo text search. Parses page snippets for venue names and prices.
    Less structured than Gemini but requires no API key.
    """
    try:
        from duckduckgo_search import DDGS

        stubs = []
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results * 3))

        # Simple pattern: extract price mentions from snippets
        price_pattern = re.compile(r"(?:SAR|SR|﷼|USD|\$)\s*([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)

        for r in results[:max_results * 2]:
            title = r.get("title", "")
            body = r.get("body", "")
            url = r.get("href", "")

            # Try to find a price in the snippet
            price_match = price_pattern.search(body)
            price = float(price_match.group(1).replace(",", "")) if price_match else 0.0

            # Basic quality filter: must mention the city
            if city.lower() not in (title + body).lower():
                continue

            # Budget filter: skip if price is way over budget
            if price > 0 and price > budget * 2:
                continue

            stubs.append(VenueStub(
                name=title[:80],  # cap title length
                type=venue_type,
                price=price,
                currency="SAR",
                rating=None,  # DuckDuckGo snippets rarely contain ratings
                description=body[:200] if body else None,
                source_url=url,
            ))

            if len(stubs) >= max_results:
                break

        logger.info(f"[DuckDuckGo] Found {len(stubs)} {venue_type}(s) in {city}")
        return stubs

    except ImportError:
        logger.warning("duckduckgo-search not installed. Run: pip install duckduckgo-search")
        return []
    except Exception as e:
        logger.error(f"[DuckDuckGo] Failed: {e}")
        return []


# ─── Static DB Fallback ──────────────────────────────────────────────────────

def _fallback_db_venues(city: str, venue_type: str, max_results: int = 5) -> List[VenueStub]:
    """
    Last resort: pull from the existing Safari SQLite database.
    Converts old DB format into VenueStub schema.
    """
    try:
        from safari.database import get_hospitality

        db_type = "hotel" if venue_type == "hotel" else "restaurant"
        rows = get_hospitality(city, type=db_type)

        stubs = []
        for r in rows[:max_results]:
            stubs.append(VenueStub(
                name=r["name"],
                type=venue_type,
                price=float(r.get("price", 0)),
                currency="SAR",
                rating=float(r.get("rating", 0)) or None,
                description=f"Fallback data for {r['name']} in {city}",
                source_url=None,
                lat=r.get("lat"),
                lng=r.get("lng"),
            ))

        logger.info(f"[Fallback DB] Found {len(stubs)} {venue_type}(s) in {city}")
        return stubs

    except Exception as e:
        logger.error(f"[Fallback DB] Failed: {e}")
        return []


# ─── Public Tool Functions ───────────────────────────────────────────────────

def search_hotels_live(
    city: str,
    budget_per_night: float,
    currency: str = "SAR",
    max_results: int = 5,
) -> List[VenueStub]:
    """
    Search for real hotels with live prices.
    Tries Gemini → DuckDuckGo → Fallback DB in order.
    """
    query = (
        f"best hotels in {city} under {budget_per_night} {currency} per night "
        f"with price 2025 2026 booking"
    )

    # Try Gemini grounding first
    results = _gemini_search_venues(query, "hotel", city, max_results)
    if results:
        return results

    # DuckDuckGo fallback
    results = _ddg_search_venues(query, "hotel", city, budget_per_night, max_results)
    if results:
        return results

    # Static DB last resort
    logger.warning(f"[Hotels] All live sources failed for {city}. Using fallback DB.")
    return _fallback_db_venues(city, "hotel", max_results)


def search_restaurants_live(
    city: str,
    interests: Optional[List[str]] = None,
    allergens: Optional[List[str]] = None,
    budget_per_meal: float = 100.0,
    max_results: int = 5,
) -> List[VenueStub]:
    """
    Search for real restaurants with live prices.
    Tries Gemini → DuckDuckGo → Fallback DB in order.
    """
    cuisine_hint = f"{'and'.join(interests)} cuisine" if interests else "local cuisine"
    allergen_hint = f"without {', '.join(allergens)}" if allergens else ""
    query = (
        f"best restaurants {cuisine_hint} in {city} {allergen_hint} "
        f"with price menu 2025 2026"
    )

    results = _gemini_search_venues(query, "restaurant", city, max_results)
    if results:
        return results

    results = _ddg_search_venues(query, "restaurant", city, budget_per_meal, max_results)
    if results:
        return results

    logger.warning(f"[Restaurants] All live sources failed for {city}. Using fallback DB.")
    return _fallback_db_venues(city, "restaurant", max_results)


def search_cafes_live(
    city: str,
    max_results: int = 3,
) -> List[VenueStub]:
    """
    Search for real cafes. Follows same Gemini → DDG → DB priority.
    """
    query = f"best cafes coffee shops in {city} 2025 2026 price"

    results = _gemini_search_venues(query, "cafe", city, max_results)
    if results:
        return results

    results = _ddg_search_venues(query, "cafe", city, 80.0, max_results)
    if results:
        return results

    logger.warning(f"[Cafes] All live sources failed for {city}. Using fallback DB.")
    return _fallback_db_venues(city, "cafe", max_results)
