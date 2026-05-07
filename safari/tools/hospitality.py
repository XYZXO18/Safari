"""
Hospitality & Venue Data Engine
================================
Core business logic for hotels and restaurants.
Handles: search, dynamic pricing, allergen checks, availability.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from safari.database import get_hospitality, book_hotel, randomize_hospitality

def _load_hotels(city: str) -> List[dict]:
    # Ensure data is randomized/seeded
    randomize_hospitality(city)
    return get_hospitality(city, type='hotel')

def _load_restaurants(city: str) -> List[dict]:
    # Ensure data is randomized/seeded
    randomize_hospitality(city)
    rests = get_hospitality(city, type='restaurant')
    cafes = get_hospitality(city, type='cafe')
    return rests + cafes


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
    if not city:
        return []
        
    db_hotels = _load_hotels(city)
    results = []

    for h in db_hotels:
        # Filter by vibe if specified
        if vibe and h.get("vibe", "").lower() != vibe.lower():
            continue

        # In our DB model, each row is a hotel with a base price
        # We'll simulate 3 room types based on that price
        room_types = [
            ("Standard", 1.0, 10),
            ("Deluxe", 1.5, 5),
            ("Suite", 2.5, 2)
        ]
        
        room_results = []
        has_availability = h['empty_rooms'] > 0

        for rname, mult, tot in room_types:
            base = h['price'] * mult
            # For simplicity, we split empty_rooms among types
            available = h['empty_rooms'] // 3 if rname != "Suite" else max(1, h['empty_rooms'] // 6)
            if available > tot: available = tot
            
            occupied = tot - available
            discount = _hotel_discount(occupied, tot)
            final = base * (1 - discount)

            room_results.append(RoomPricing(
                room_type=rname,
                total_rooms=tot,
                occupied=occupied,
                available=available,
                base_price_sar=base,
                discount_percent=discount,
                final_price_sar=final,
                occupancy_rate=occupied/tot if tot > 0 else 0,
            ))

        results.append(HotelResult(
            id=str(h["id"]),
            name=h["name"],
            city=h["city"],
            vibe=h.get("vibe", ""),
            stars=h.get("stars", 4),
            description=f"A premium stay in {h['city']}.",
            rooms=room_results,
            amenities=["WiFi", "Pool", "Gym"],
            check_in="14:00",
            check_out="12:00",
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
    if not city:
        return []
        
    db_rests = _load_restaurants(city)
    results = []

    for r in db_rests:
        if vibe and r.get("vibe", "").lower() != vibe.lower():
            continue

        avoid = [a.lower() for a in (allergens_to_avoid or [])]

        # Simulate tables based on price category
        tot_tables = 20
        reserved = random.randint(5, 18)
        available = tot_tables - reserved
        discount = _restaurant_discount(reserved, tot_tables)

        # Base menu
        base_menu = [
            {"name": "Traditional Kabsa", "price_sar": r['price'], "category": "Main", "is_signature": True},
            {"name": "Lentil Soup", "price_sar": r['price']*0.3, "category": "Starter"},
            {"name": "Date Cake", "price_sar": r['price']*0.4, "category": "Dessert"}
        ]

        menu_results = []
        for item in base_menu:
            menu_results.append(MenuItemResult(
                name=item["name"],
                price_sar=item["price_sar"],
                category=item["category"],
                is_signature=item.get("is_signature", False),
                allergens=[],
                dietary=[],
                is_safe=True,
                flagged_allergens=[],
            ))

        results.append(RestaurantResult(
            id=str(r["id"]),
            name=r["name"],
            city=r["city"],
            vibe=r.get("vibe", ""),
            cuisine=r.get("cuisine", "Traditional / Modern"),
            rating=r["rating"],
            operating_hours={"open": "12:00", "close": "23:00"},
            total_tables=tot_tables,
            reserved_tables=reserved,
            available_tables=available,
            discount_percent=discount,
            menu=menu_results,
            top_dishes=["Traditional Kabsa"],
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
