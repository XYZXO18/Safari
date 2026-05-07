"""
Worker 2 — Live Hospitality Agent
===================================
Finds real-time hotels, restaurants, and cafes using live web data.

CHANGES from original:
  - Removed all SQLite/static DB calls
  - Uses live_hospitality.py tool (Gemini Grounding → DuckDuckGo → DB fallback)
  - Adds phase1_scrape() method for two-phase Orchestrator hand-off
  - Coordinates are NOT populated here (that is Agent 3's job)
  - Keeps process_request() as the public API for backward compatibility
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from safari.agent.schemas import (
    HospitalityInput, HospitalityOutput, VenueStub
)
from safari.tools.live_hospitality import (
    search_hotels_live,
    search_restaurants_live,
    search_cafes_live,
)

logger = logging.getLogger(__name__)


class HospitalityWorker:
    """
    Agent 2: Live Hospitality and Venue Discovery Agent.

    Responsible for finding REAL venue names and REAL prices from the web.
    Does NOT provide coordinates — that is delegated to Agent 3 (DistanceWorker).
    """

    def process_request(self, request: dict) -> dict:
        """
        Public API — kept for backward compatibility with the Orchestrator.

        Supported actions:
          - search_hotels       → returns hotels list
          - search_restaurants  → returns restaurants list
          - search_all          → hotels + restaurants + cafes in one call
          - natural_language    → free-form query (uses LLM)
        """
        action = request.get("action", "").lower()

        if action == "search_hotels":
            return self._handle_search_hotels(request)
        elif action == "search_restaurants":
            return self._handle_search_restaurants(request)
        elif action == "search_all":
            return self._handle_search_all(request)
        elif action == "natural_language":
            return self._handle_natural_language(request)
        else:
            # Default: full scrape
            return self._handle_search_all(request)

    # ─── Phase 1: Scrape (Two-Phase Hand-off) ─────────────────────────────────

    def phase1_scrape(self, input_data: HospitalityInput) -> HospitalityOutput:
        """
        Phase 1 of the two-phase Orchestrator hand-off.

        Scrapes live venue data (names + prices) but returns NO coordinates.
        The Orchestrator will pass this output to Agent 3 to fill in lat/lng.

        Args:
            input_data: HospitalityInput Pydantic model

        Returns:
            HospitalityOutput with venues (lat=None, lng=None)
        """
        logger.info(
            f"[HospitalityWorker] Phase 1 — Scraping live venues in {input_data.city} "
            f"(budget: {input_data.budget_per_night} {input_data.currency}/night)"
        )

        all_venues: List[VenueStub] = []
        warnings: List[str] = []
        data_source = "live_web"

        # ── Hotels ──────────────────────────────────────────────────────────
        try:
            hotels = search_hotels_live(
                city=input_data.city,
                budget_per_night=input_data.budget_per_night,
                currency=input_data.currency,
                max_results=input_data.max_results,
            )
            if not hotels:
                warnings.append(f"No hotels found live for {input_data.city} — check your budget or try a broader search.")
                data_source = "fallback_db"
            all_venues.extend(hotels)
            logger.info(f"  ✅ Hotels: {len(hotels)} found")
        except Exception as e:
            warnings.append(f"Hotel search failed: {e}")
            logger.error(f"[HospitalityWorker] Hotel search error: {e}")

        # ── Restaurants ──────────────────────────────────────────────────────
        try:
            restaurants = search_restaurants_live(
                city=input_data.city,
                interests=input_data.interests or [],
                allergens=input_data.allergens or [],
                budget_per_meal=input_data.budget_per_night * 0.2,  # ~20% of hotel budget
                max_results=input_data.max_results,
            )
            all_venues.extend(restaurants)
            logger.info(f"  ✅ Restaurants: {len(restaurants)} found")
        except Exception as e:
            warnings.append(f"Restaurant search failed: {e}")
            logger.error(f"[HospitalityWorker] Restaurant search error: {e}")

        # ── Cafes ────────────────────────────────────────────────────────────
        try:
            cafes = search_cafes_live(city=input_data.city, max_results=3)
            all_venues.extend(cafes)
            logger.info(f"  ✅ Cafes: {len(cafes)} found")
        except Exception as e:
            warnings.append(f"Cafe search failed: {e}")
            logger.error(f"[HospitalityWorker] Cafe search error: {e}")

        return HospitalityOutput(
            city=input_data.city,
            venues=all_venues,
            search_timestamp=datetime.utcnow().isoformat(),
            data_source=data_source,
            warnings=warnings,
        )

    # ─── Internal Handlers ────────────────────────────────────────────────────

    def _handle_search_hotels(self, req: dict) -> dict:
        city = req.get("city") or req.get("vibe", "")
        budget = float(req.get("budget_per_night", 500))
        currency = req.get("currency", "SAR")
        max_r = int(req.get("max_results", 5))

        hotels = search_hotels_live(city=city, budget_per_night=budget, currency=currency, max_results=max_r)

        return {
            "action": "search_hotels",
            "city": city,
            "count": len(hotels),
            "hotels": [v.model_dump() for v in hotels],
            "data_source": "live_web",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _handle_search_restaurants(self, req: dict) -> dict:
        city = req.get("city") or req.get("vibe", "")
        interests = req.get("interests", [])
        allergens = req.get("allergens", [])
        max_r = int(req.get("max_results", 5))

        restaurants = search_restaurants_live(
            city=city, interests=interests, allergens=allergens, max_results=max_r
        )

        return {
            "action": "search_restaurants",
            "city": city,
            "count": len(restaurants),
            "restaurants": [v.model_dump() for v in restaurants],
            "data_source": "live_web",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _handle_search_all(self, req: dict) -> dict:
        """Full venue scan: hotels + restaurants + cafes."""
        city = req.get("city") or req.get("vibe", "")
        budget = float(req.get("budget_per_night", 500))
        interests = req.get("interests", [])
        allergens = req.get("allergens", [])
        currency = req.get("currency", "SAR")

        input_model = HospitalityInput(
            city=city,
            budget_per_night=budget,
            currency=currency,
            interests=interests,
            allergens=allergens,
        )

        output: HospitalityOutput = self.phase1_scrape(input_model)

        hotels = [v for v in output.venues if v.type == "hotel"]
        restaurants = [v for v in output.venues if v.type == "restaurant"]
        cafes = [v for v in output.venues if v.type == "cafe"]

        return {
            "action": "search_all",
            "city": city,
            "hotels": [v.model_dump() for v in hotels],
            "restaurants": [v.model_dump() for v in restaurants],
            "cafes": [v.model_dump() for v in cafes],
            "data_source": output.data_source,
            "warnings": output.warnings,
            "timestamp": output.search_timestamp,
        }

    def _handle_natural_language(self, req: dict) -> dict:
        """
        Handle free-form queries via LLM + live search context.
        e.g. "Which hotel in Jeddah is best for a honeymoon?"
        """
        query = req.get("query", "")
        city = req.get("city") or req.get("vibe", "Jeddah")

        # First, get fresh live data
        search_result = self._handle_search_all({
            "city": city,
            "budget_per_night": req.get("budget_per_night", 500),
        })

        # Build LLM prompt with live context
        context_json = {
            "hotels": search_result["hotels"][:3],
            "restaurants": search_result["restaurants"][:3],
        }

        try:
            import requests as http_requests
            from config import OLLAMA_URL, OLLAMA_MODEL

            prompt = (
                f"User question: {query}\n\n"
                f"Available live venue data (use ONLY this, do not invent):\n"
                f"{context_json}\n\n"
                f"Answer the user's question based solely on the data above. "
                f"Include real prices and names."
            )

            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3},
            }
            resp = http_requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
            llm_response = resp.json().get("response", "LLM unavailable.")

        except Exception as e:
            llm_response = f"[LLM unavailable: {e}]"

        return {
            "action": "natural_language",
            "query": query,
            "response": llm_response,
            "data": search_result,
        }
