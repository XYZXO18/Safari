"""
Hospitality Agent (Agent 2)
============================
The Hospitality and Venue Data Agent for the Safari travel system.
Uses Ollama as its LLM brain to interpret requests and query the
local hotel/restaurant database.

Agent 1 (Research & Planning) delegates hotel/restaurant queries here.
"""

from __future__ import annotations

import json
from typing import Optional, List

import requests

from config import OLLAMA_URL, OLLAMA_MODEL
from safari.tools.hospitality import (
    search_hotels,
    search_restaurants,
    get_hotel_details,
    get_restaurant_details,
    get_hospitality_summary,
)

HOSPITALITY_SYSTEM_PROMPT = """You are the **Hospitality and Venue Data Agent** for the Safari travel assistant.

## Your Role
You query and manage local database records for Hotels and Restaurants.
You receive structured requests and respond with accurate data from your database.

## Your Core Responsibilities

### Hotel Management
- Track room availability and room types (Single, Double, Suite)
- Report base prices for requested dates
- Calculate and apply dynamic discounts based on occupancy:
  - 70%+ vacancy → 25% discount
  - 50-69% vacancy → 15% discount
  - 30-49% vacancy → 10% discount
  - 10-29% vacancy → 5% discount
  - <10% vacancy → 0% discount

### Restaurant Management
- Provide operating hours and table availability
- Recommend top dishes and specialties
- Strictly verify allergens in menu items
- Apply dynamic discounts based on table occupancy:
  - 70%+ vacancy → 20% discount
  - 50-69% vacancy → 12% discount
  - 30-49% vacancy → 7% discount
  - <30% vacancy → 0% discount

## Rules
1. NEVER invent data — only use what the database returns
2. ALWAYS include: base_price, discount_percent, final_price
3. Output structured JSON so Agent 1 can parse it
4. For allergen checks, be STRICT — flag every match
5. Communicate clearly and concisely
"""


def _call_ollama(prompt: str, system: str = HOSPITALITY_SYSTEM_PROMPT) -> str:
    """Call the local Ollama LLM."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 4096},
        }
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        return response.json()["response"]
    except Exception as e:
        return f"[LLM unavailable: {e}]"


class HospitalityWorker:
    """
    Agent 2: Hospitality and Venue Data Agent.
    Processes structured requests about hotels and restaurants.
    """

    def __init__(self):
        self.ollama_url = OLLAMA_URL
        self.model = OLLAMA_MODEL

    def process_request(self, request: dict) -> dict:
        """
        Main entry point. Processes a structured request and returns data.

        Supported actions:
          - search_hotels
          - hotel_details
          - search_restaurants
          - restaurant_details
          - restaurant_menu
          - hospitality_summary
          - natural_language (free-form query via LLM)
        """
        action = request.get("action", "").lower()

        if action == "search_hotels":
            return self._handle_search_hotels(request)
        elif action == "hotel_details":
            return self._handle_hotel_details(request)
        elif action == "search_restaurants":
            return self._handle_search_restaurants(request)
        elif action == "restaurant_details":
            return self._handle_restaurant_details(request)
        elif action == "restaurant_menu":
            return self._handle_restaurant_menu(request)
        elif action == "hospitality_summary":
            return self._handle_summary(request)
        elif action == "natural_language":
            return self._handle_natural_language(request)
        else:
            return {"error": f"Unknown action: {action}"}

    def _handle_search_hotels(self, req: dict) -> dict:
        city = req.get("city")
        vibe = req.get("vibe")
        room_type = req.get("room_type")

        results = search_hotels(city=city, vibe=vibe, room_type=room_type)
        return {
            "action": "search_hotels",
            "count": len(results),
            "hotels": [h.to_dict() for h in results],
        }

    def _handle_hotel_details(self, req: dict) -> dict:
        hotel_id = req.get("hotel_id")
        if not hotel_id:
            return {"error": "hotel_id is required"}

        result = get_hotel_details(hotel_id)
        if not result:
            return {"error": f"Hotel not found: {hotel_id}"}

        return {
            "action": "hotel_details",
            "hotel": result.to_dict(),
        }

    def _handle_search_restaurants(self, req: dict) -> dict:
        city = req.get("city")
        vibe = req.get("vibe")
        cuisine = req.get("cuisine")
        allergens = req.get("allergens", [])

        results = search_restaurants(
            city=city, vibe=vibe, cuisine=cuisine,
            allergens_to_avoid=allergens,
        )
        return {
            "action": "search_restaurants",
            "count": len(results),
            "restaurants": [r.to_dict() for r in results],
        }

    def _handle_restaurant_details(self, req: dict) -> dict:
        restaurant_id = req.get("restaurant_id")
        allergens = req.get("allergens", [])
        if not restaurant_id:
            return {"error": "restaurant_id is required"}

        result = get_restaurant_details(restaurant_id, allergens_to_avoid=allergens)
        if not result:
            return {"error": f"Restaurant not found: {restaurant_id}"}

        return {
            "action": "restaurant_details",
            "restaurant": result.to_dict(),
        }

    def _handle_restaurant_menu(self, req: dict) -> dict:
        restaurant_id = req.get("restaurant_id")
        allergens = req.get("allergens", [])
        if not restaurant_id:
            return {"error": "restaurant_id is required"}

        result = get_restaurant_details(restaurant_id, allergens_to_avoid=allergens)
        if not result:
            return {"error": f"Restaurant not found: {restaurant_id}"}

        return {
            "action": "restaurant_menu",
            "restaurant_name": result.name,
            "menu": [m.to_dict() for m in result.menu],
            "top_dishes": result.top_dishes,
            "discount_percent": round(result.discount_percent * 100, 1),
        }

    def _handle_summary(self, req: dict) -> dict:
        city = req.get("city")
        vibe = req.get("vibe")
        allergens = req.get("allergens", [])

        summary = get_hospitality_summary(city=city, vibe=vibe, allergens=allergens)
        return {
            "action": "hospitality_summary",
            **summary,
        }

    def _handle_natural_language(self, req: dict) -> dict:
        """Handle free-form queries by combining DB data with LLM interpretation."""
        query = req.get("query", "")
        city = req.get("city")
        vibe = req.get("vibe")

        # Get relevant data
        summary = get_hospitality_summary(city=city, vibe=vibe)

        # Build prompt with database context
        prompt = (
            f"User query: {query}\n\n"
            f"Database context (use ONLY this data):\n"
            f"{json.dumps(summary, indent=2, default=str)}\n\n"
            f"Respond with accurate information from the database above. "
            f"Include prices with discounts applied. Never invent data."
        )

        llm_response = _call_ollama(prompt)

        return {
            "action": "natural_language",
            "query": query,
            "response": llm_response,
            "data": summary,
        }
