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
from rich.console import Console

from safari.agent.schemas import VenueStub

logger = logging.getLogger(__name__)
console = Console()


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
        from safari.gemini_log import log_gemini

        log_gemini("Agent 2 · Hospitality", f"{venue_type} search for {city}")
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
        console.print(f"[bold green][G] [Agent 2] Gemini Search Grounding used for {venue_type}s in {city} (Found: {len(stubs)})[/bold green]")
        return stubs

    except Exception as e:
        logger.error(f"[Gemini Grounding] Failed for query '{query}': {e}")
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
    Tries Gemini → DuckDuckGo. No DB fallback.
    """
    query = (
        f"best hotels in {city} under {budget_per_night} {currency} per night "
        f"with price 2025 2026 booking"
    )

    results = _gemini_search_venues(query, "hotel", city, max_results)
    if results:
        return results

    console.print(f"[bold red][!] [Agent 2] No live hotels found for {city}.[/bold red]")
    return []


def search_restaurants_live(
    city: str,
    interests: Optional[List[str]] = None,
    allergens: Optional[List[str]] = None,
    budget_per_meal: float = 100.0,
    max_results: int = 5,
) -> List[VenueStub]:
    """
    Search for real restaurants with live prices.
    Tries Gemini → DuckDuckGo. No DB fallback.
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

    console.print(f"[bold red][!] [Agent 2] No live restaurants found for {city}.[/bold red]")
    return []


def search_cafes_live(
    city: str,
    max_results: int = 3,
) -> List[VenueStub]:
    """
    Search for real cafes. Tries Gemini → DuckDuckGo. No DB fallback.
    """
    query = f"best cafes coffee shops in {city} 2025 2026 price"

    results = _gemini_search_venues(query, "cafe", city, max_results)
    if results:
        return results

    console.print(f"[bold red][!] [Agent 2] No live cafes found for {city}.[/bold red]")
    return []
