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
        console.print(f"[bold yellow][D] [Agent 2] DuckDuckGo Search used for {venue_type}s in {city} (Found: {len(stubs)})[/bold yellow]")
        return stubs

    except ImportError:
        logger.warning("duckduckgo-search not installed. Run: pip install duckduckgo-search")
        return []
    except Exception as e:
        logger.error(f"[DuckDuckGo] Failed: {e}")
        return []


# ─── Public Tool Functions ───────────────────────────────────────────────────

def search_hotels_live(
    city: str,
    budget_per_night: float = 500.0,
    currency: str = "SAR",
    max_results: int = 5,
) -> List[VenueStub]:
    """
    Fetch live hotel listings from Almosafer for the given city.
    - Returns exactly max_results (default 5) hotels with real-time prices.
    - Every new hotel found is saved to the local DB (name + location only, no price).
    - If the city catalogue has fewer than 20 hotels, a second scrape pass runs
      to build it up over time.
    """
    from safari.tools.almosafer import AlmosaferScraper
    from safari.database import upsert_hotel_static, get_hotel_count
    from config import CITY_COORDS
    import random

    console.print(f"[bold cyan][A] [Agent 2] Fetching live hotels from Almosafer for {city}...[/bold cyan]")

    scraper = AlmosaferScraper()
    raw = scraper.scrape_hotels(city, max_results=max_results)

    stubs: List[VenueStub] = []
    for h in raw:
        name = h.get("name", "").strip()
        if not name:
            continue

        price = h.get("price_per_night") or 0.0
        stars = int(h.get("stars") or 4)
        rating = float(h.get("rating") or 0.0)

        # Save new hotel to DB — name + coords only, price is never stored
        base = CITY_COORDS.get(city.lower(), {"lat": 24.7, "lng": 46.7})
        lat = base["lat"] + random.uniform(-0.05, 0.05)
        lng = base["lng"] + random.uniform(-0.05, 0.05)
        upsert_hotel_static(city, name, lat, lng, stars)

        stubs.append(VenueStub(
            name=name,
            type="hotel",
            price=price,
            currency="SAR",
            rating=rating if rating > 0 else None,
            description=f"{stars}★ hotel in {city.title()} — live from Almosafer",
            source_url=scraper.hotel_search_url(city, None, None),
        ))

    # Catalogue building: if city has <20 known hotels, scrape extra dates to grow it
    current_count = get_hotel_count(city)
    if current_count < 20 and len(raw) > 0:
        try:
            from datetime import date, timedelta
            extra_ci = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
            extra_co = (date.today() + timedelta(days=17)).strftime("%Y-%m-%d")
            extra_raw = scraper.scrape_hotels(city, extra_ci, extra_co, max_results=5)
            for eh in extra_raw:
                ename = eh.get("name", "").strip()
                if ename:
                    base = CITY_COORDS.get(city.lower(), {"lat": 24.7, "lng": 46.7})
                    elat = base["lat"] + random.uniform(-0.05, 0.05)
                    elng = base["lng"] + random.uniform(-0.05, 0.05)
                    upsert_hotel_static(city, ename, elat, elng, int(eh.get("stars") or 4))
            logger.info(f"[Almosafer] Catalogue for {city}: {get_hotel_count(city)} hotels stored.")
        except Exception as e:
            logger.warning(f"[Almosafer] Catalogue build error: {e}")

    if not stubs:
        console.print(f"[bold red][!] [Agent 2] Almosafer returned no hotels for {city}.[/bold red]")

    return stubs[:max_results]


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

    results = _ddg_search_venues(query, "restaurant", city, budget_per_meal, max_results)
    if results:
        return results

    console.print(f"[bold red][!] [Agent 2] No live restaurants found for {city}. (Fallback DB disabled)[/bold red]")
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

    results = _ddg_search_venues(query, "cafe", city, 80.0, max_results)
    if results:
        return results

    console.print(f"[bold red][!] [Agent 2] No live cafes found for {city}. (Fallback DB disabled)[/bold red]")
    return []
