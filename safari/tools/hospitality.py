"""
Hospitality & Venue Data Engine
================================
Core business logic for hotels and restaurants.
Handles: search, dynamic pricing, allergen checks, availability.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# ─── Data Loading ────────────────────────────────────────────────────────────

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")


def _load_hotels() -> List[dict]:
    path = os.path.join(_DATA_DIR, "hotels.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["hotels"]


def _load_restaurants() -> List[dict]:
    path = os.path.join(_DATA_DIR, "restaurants.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["restaurants"]


# ─── Dynamic Discount Calculation ────────────────────────────────────────────

def _hotel_discount(occupied: int, total: int) -> float:
    """
    Calculate hotel discount based on room vacancy.
    Higher vacancy → bigger discount to attract guests.
    """
    if total == 0:
        return 0.0
    vacancy_rate = 1 - (occupied / total)
    if vacancy_rate >= 0.70:
        return 0.25
    elif vacancy_rate >= 0.50:
        return 0.15
    elif vacancy_rate >= 0.30:
        return 0.10
    elif vacancy_rate >= 0.10:
        return 0.05
    else:
        return 0.0


def _restaurant_discount(reserved: int, total: int) -> float:
    """
    Calculate restaurant discount based on table vacancy.
    Emptier restaurant → bigger discount to fill seats.
    """
    if total == 0:
        return 0.0
    vacancy_rate = 1 - (reserved / total)
    if vacancy_rate >= 0.70:
        return 0.20
    elif vacancy_rate >= 0.50:
        return 0.12
    elif vacancy_rate >= 0.30:
        return 0.07
    else:
        return 0.0


# ─── Result Data Classes ────────────────────────────────────────────────────

@dataclass
class RoomPricing:
    room_type: str
    total_rooms: int
    occupied: int
    available: int
    base_price_sar: float
    discount_percent: float
    final_price_sar: float
    occupancy_rate: float

    def to_dict(self) -> dict:
        return {
            "room_type": self.room_type,
            "total_rooms": self.total_rooms,
            "occupied": self.occupied,
            "available": self.available,
            "base_price_sar": self.base_price_sar,
            "discount_percent": round(self.discount_percent * 100, 1),
            "final_price_sar": round(self.final_price_sar, 2),
            "occupancy_rate": round(self.occupancy_rate * 100, 1),
        }


@dataclass
class HotelResult:
    id: str
    name: str
    city: str
    vibe: str
    stars: int
    description: str
    rooms: List[RoomPricing]
    amenities: List[str]
    check_in: str
    check_out: str
    lat: float
    lng: float
    has_availability: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "vibe": self.vibe,
            "stars": self.stars,
            "description": self.description,
            "rooms": [r.to_dict() for r in self.rooms],
            "amenities": self.amenities,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "lat": self.lat,
            "lng": self.lng,
            "has_availability": self.has_availability,
        }


@dataclass
class MenuItemResult:
    name: str
    price_sar: float
    category: str
    is_signature: bool
    allergens: List[str]
    dietary: List[str]
    is_safe: bool  # True if no flagged allergens
    flagged_allergens: List[str]  # Allergens that match user's avoid list

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price_sar": self.price_sar,
            "category": self.category,
            "is_signature": self.is_signature,
            "allergens": self.allergens,
            "dietary": self.dietary,
            "is_safe": self.is_safe,
            "flagged_allergens": self.flagged_allergens,
        }


@dataclass
class RestaurantResult:
    id: str
    name: str
    city: str
    vibe: str
    cuisine: str
    rating: float
    operating_hours: dict
    total_tables: int
    reserved_tables: int
    available_tables: int
    discount_percent: float
    menu: List[MenuItemResult]
    top_dishes: List[str]
    lat: float
    lng: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "vibe": self.vibe,
            "cuisine": self.cuisine,
            "rating": self.rating,
            "operating_hours": self.operating_hours,
            "total_tables": self.total_tables,
            "reserved_tables": self.reserved_tables,
            "available_tables": self.available_tables,
            "discount_percent": round(self.discount_percent * 100, 1),
            "menu": [m.to_dict() for m in self.menu],
            "top_dishes": self.top_dishes,
            "lat": self.lat,
            "lng": self.lng,
        }


# ─── Hotel Functions ─────────────────────────────────────────────────────────

def search_hotels(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    room_type: Optional[str] = None,
) -> List[HotelResult]:
    """
    Search hotels by city and/or vibe. Returns all hotels with dynamic pricing.
    """
    hotels = _load_hotels()
    results = []

    for h in hotels:
        # Filter by city
        if city and h["city"].lower() != city.lower():
            continue
        # Filter by vibe
        if vibe and h.get("vibe", "").lower() != vibe.lower():
            continue

        room_results = []
        has_availability = False

        for r in h["rooms"]:
            # Filter by room type if specified
            if room_type and r["type"].lower() != room_type.lower():
                continue

            available = r["total"] - r["occupied"]
            discount = _hotel_discount(r["occupied"], r["total"])
            final_price = r["base_price_sar"] * (1 - discount)
            occupancy = r["occupied"] / r["total"] if r["total"] > 0 else 0

            if available > 0:
                has_availability = True

            room_results.append(RoomPricing(
                room_type=r["type"],
                total_rooms=r["total"],
                occupied=r["occupied"],
                available=available,
                base_price_sar=r["base_price_sar"],
                discount_percent=discount,
                final_price_sar=final_price,
                occupancy_rate=occupancy,
            ))

        if not room_results:
            continue

        results.append(HotelResult(
            id=h["id"],
            name=h["name"],
            city=h["city"],
            vibe=h.get("vibe", ""),
            stars=h["stars"],
            description=h["description"],
            rooms=room_results,
            amenities=h["amenities"],
            check_in=h["check_in"],
            check_out=h["check_out"],
            lat=h["lat"],
            lng=h["lng"],
            has_availability=has_availability,
        ))

    return results


def get_hotel_details(hotel_id: str) -> Optional[HotelResult]:
    """Get full details for a specific hotel by ID."""
    hotels = _load_hotels()
    for h in hotels:
        if h["id"] == hotel_id:
            room_results = []
            has_availability = False
            for r in h["rooms"]:
                available = r["total"] - r["occupied"]
                discount = _hotel_discount(r["occupied"], r["total"])
                final_price = r["base_price_sar"] * (1 - discount)
                occupancy = r["occupied"] / r["total"] if r["total"] > 0 else 0
                if available > 0:
                    has_availability = True
                room_results.append(RoomPricing(
                    room_type=r["type"],
                    total_rooms=r["total"],
                    occupied=r["occupied"],
                    available=available,
                    base_price_sar=r["base_price_sar"],
                    discount_percent=discount,
                    final_price_sar=final_price,
                    occupancy_rate=occupancy,
                ))
            return HotelResult(
                id=h["id"], name=h["name"], city=h["city"],
                vibe=h.get("vibe", ""), stars=h["stars"],
                description=h["description"], rooms=room_results,
                amenities=h["amenities"], check_in=h["check_in"],
                check_out=h["check_out"], lat=h["lat"], lng=h["lng"],
                has_availability=has_availability,
            )
    return None


# ─── Restaurant Functions ────────────────────────────────────────────────────

def search_restaurants(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    cuisine: Optional[str] = None,
    allergens_to_avoid: Optional[List[str]] = None,
) -> List[RestaurantResult]:
    """
    Search restaurants by city, vibe, or cuisine.
    Optionally checks allergens across entire menu.
    """
    restaurants = _load_restaurants()
    results = []

    for r in restaurants:
        if city and r["city"].lower() != city.lower():
            continue
        if vibe and r.get("vibe", "").lower() != vibe.lower():
            continue
        if cuisine and cuisine.lower() not in r["cuisine"].lower():
            continue

        avoid = [a.lower() for a in (allergens_to_avoid or [])]

        tables = r["tables"]
        available = tables["total"] - tables["reserved"]
        discount = _restaurant_discount(tables["reserved"], tables["total"])

        menu_results = []
        for item in r["menu"]:
            item_allergens = [a.lower() for a in item.get("allergens", [])]
            flagged = [a for a in avoid if a in item_allergens]
            menu_results.append(MenuItemResult(
                name=item["name"],
                price_sar=item["price_sar"],
                category=item["category"],
                is_signature=item.get("is_signature", False),
                allergens=item.get("allergens", []),
                dietary=item.get("dietary", []),
                is_safe=len(flagged) == 0,
                flagged_allergens=flagged,
            ))

        top_dishes = [
            item["name"] for item in r["menu"]
            if item.get("is_signature", False)
        ]

        results.append(RestaurantResult(
            id=r["id"],
            name=r["name"],
            city=r["city"],
            vibe=r.get("vibe", ""),
            cuisine=r["cuisine"],
            rating=r["rating"],
            operating_hours=r["operating_hours"],
            total_tables=tables["total"],
            reserved_tables=tables["reserved"],
            available_tables=available,
            discount_percent=discount,
            menu=menu_results,
            top_dishes=top_dishes,
            lat=r["lat"],
            lng=r["lng"],
        ))

    return results


def get_restaurant_details(
    restaurant_id: str,
    allergens_to_avoid: Optional[List[str]] = None,
) -> Optional[RestaurantResult]:
    """Get full restaurant details with allergen checking."""
    restaurants = _load_restaurants()
    avoid = [a.lower() for a in (allergens_to_avoid or [])]

    for r in restaurants:
        if r["id"] != restaurant_id:
            continue

        tables = r["tables"]
        available = tables["total"] - tables["reserved"]
        discount = _restaurant_discount(tables["reserved"], tables["total"])

        menu_results = []
        for item in r["menu"]:
            item_allergens = [a.lower() for a in item.get("allergens", [])]
            flagged = [a for a in avoid if a in item_allergens]
            menu_results.append(MenuItemResult(
                name=item["name"],
                price_sar=item["price_sar"],
                category=item["category"],
                is_signature=item.get("is_signature", False),
                allergens=item.get("allergens", []),
                dietary=item.get("dietary", []),
                is_safe=len(flagged) == 0,
                flagged_allergens=flagged,
            ))

        top_dishes = [
            item["name"] for item in r["menu"]
            if item.get("is_signature", False)
        ]

        return RestaurantResult(
            id=r["id"], name=r["name"], city=r["city"],
            vibe=r.get("vibe", ""), cuisine=r["cuisine"],
            rating=r["rating"], operating_hours=r["operating_hours"],
            total_tables=tables["total"],
            reserved_tables=tables["reserved"],
            available_tables=available,
            discount_percent=discount,
            menu=menu_results,
            top_dishes=top_dishes,
            lat=r["lat"], lng=r["lng"],
        )
    return None


# ─── Hospitality Summary (for Agent 1 integration) ──────────────────────────

def get_hospitality_summary(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    allergens: Optional[List[str]] = None,
) -> dict:
    """
    Get a combined summary of hotels and restaurants for a destination.
    Used by Agent 1 to build itineraries.
    """
    hotels = search_hotels(city=city, vibe=vibe)
    restaurants = search_restaurants(city=city, vibe=vibe, allergens_to_avoid=allergens)

    return {
        "city": city or vibe or "all",
        "hotels": {
            "count": len(hotels),
            "with_availability": sum(1 for h in hotels if h.has_availability),
            "fully_booked": sum(1 for h in hotels if not h.has_availability),
            "listings": [h.to_dict() for h in hotels],
        },
        "restaurants": {
            "count": len(restaurants),
            "listings": [r.to_dict() for r in restaurants],
        },
    }
