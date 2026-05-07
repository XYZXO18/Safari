"""
Hospitality Agent (Agent 2)
============================
Fetches live hotel data from Almosafer and manages restaurant information.

Hotels:  Sourced live from almosafer.com — 5 per search, prices always real-time.
         New hotels are automatically added to the local DB (name + location only).
Restaurants: Served from local DB.
"""

from __future__ import annotations

from safari.tools.hospitality import (
    search_hotels,
    search_restaurants,
    get_hotel_details,
    get_restaurant_details,
    get_hospitality_summary,
)
from safari.database import get_hotel_count


HOSPITALITY_SYSTEM_PROMPT = """You are the **Hospitality Agent** for Safari.

## Role
You fetch LIVE hotel pricing from Almosafer and manage restaurant data.

## Hotels
- Always fetch from Almosafer (real-time prices, no cached/dummy prices)
- Return exactly 5 hotels per search with their live nightly rate
- New hotels are auto-saved to the local catalogue (name + location only)
- Over time the city catalogue grows to 20+ hotels

## Restaurants
- Served from local DB with dynamic table availability

## Output format
Always return structured JSON so the Orchestrator can parse it directly.
"""


class HospitalityWorker:
    """
    Agent 2 — Hospitality Agent.
    Fetches live hotel data from Almosafer and handles restaurant queries.
    """

    def process_request(self, request: dict) -> dict:
        """
        Supported actions:
          - search_hotels
          - hotel_details
          - search_restaurants
          - restaurant_details
          - restaurant_menu
          - hospitality_summary
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
        elif action == "geolocate_venues":
            return self._handle_geolocate(request)
        else:
            return {"error": f"Unknown action: {action}"}

    # ── Hotels ────────────────────────────────────────────────────────────────

    def _handle_search_hotels(self, req: dict) -> dict:
        city = req.get("city")
        vibe = req.get("vibe")
        room_type = req.get("room_type")
        checkin = req.get("checkin")
        checkout = req.get("checkout")
        budget_per_night = req.get("budget_per_night")

        results = search_hotels(
            city=city,
            vibe=vibe,
            room_type=room_type,
            checkin=checkin,
            checkout=checkout,
            budget_per_night=budget_per_night,
        )

        return {
            "action": "search_hotels",
            "count": len(results),
            "city_catalogue_size": get_hotel_count(city) if city else 0,
            "hotels": [h.to_dict() for h in results],
        }

    def _handle_hotel_details(self, req: dict) -> dict:
        hotel_id = req.get("hotel_id")
        if not hotel_id:
            return {"error": "hotel_id is required"}
        result = get_hotel_details(hotel_id)
        if not result:
            return {"error": f"Hotel not found: {hotel_id}"}
        return {"action": "hotel_details", "hotel": result.to_dict()}

    # ── Restaurants ───────────────────────────────────────────────────────────

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
        return {"action": "restaurant_details", "restaurant": result.to_dict()}

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

    # ── Summary ───────────────────────────────────────────────────────────────

    def _handle_summary(self, req: dict) -> dict:
        city = req.get("city")
        vibe = req.get("vibe")
        allergens = req.get("allergens", [])
        summary = get_hospitality_summary(city=city, vibe=vibe, allergens=allergens)
        return {"action": "hospitality_summary", **summary}

    # ── Geolocate passthrough (Transport worker owns geocoding) ───────────────

    def _handle_geolocate(self, req: dict) -> dict:
        """Simple pass-through: venues already have coords from search_hotels."""
        venues = req.get("venues", [])
        # Tag each venue with type so Transport worker can filter
        for v in venues:
            if "stars" in v and "type" not in v:
                v["type"] = "hotel"
            elif "cuisine" in v and "type" not in v:
                v["type"] = "restaurant"
        return {"action": "geolocate_venues", "venues": venues}
