"""
Hospitality & Venue Data Engine
================================
Agent 2's tool layer.

Hotel data flow:
  1. Call search_hotels_live() (Gemini Search Grounding) → up to 5 live results with prices.
  2. For every hotel returned, call upsert_hotel_static() to persist
     name + coordinates in the DB (price is NEVER stored — always live).
  3. If city has <20 hotels in DB, run a second search to build the catalogue.
  4. Return HotelResult objects with live prices.

Restaurant data is still served from the local DB (no live equivalent).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta, date
from typing import List, Optional

from config import CITY_COORDS
from safari.database import (
    get_hospitality, book_hotel,
    upsert_hotel_static, get_hotel_count, get_known_hotels,
)
from safari.tools.almosafer import AlmosaferScraper  # kept for hotel_search_url only
from safari.tools.live_hospitality import search_hotels_live


# ─── Coordinate helper ────────────────────────────────────────────────────────

def _city_coords(city: str) -> tuple[float, float]:
    """Return (lat, lng) for a city, with a small random offset."""
    base = CITY_COORDS.get(city.lower(), {"lat": 24.7, "lng": 46.7})
    return (
        base["lat"] + random.uniform(-0.05, 0.05),
        base["lng"] + random.uniform(-0.05, 0.05),
    )


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class RoomPricing:
    room_type: str
    base_price_sar: float
    final_price_sar: float
    available: bool = True
    source: str = "Gemini Search"

    def to_dict(self) -> dict:
        return {
            "room_type": self.room_type,
            "base_price_sar": round(self.base_price_sar, 2),
            "final_price_sar": round(self.final_price_sar, 2),
            "available": self.available,
            "source": self.source,
        }


@dataclass
class HotelResult:
    id: str
    name: str
    city: str
    stars: int
    description: str
    rooms: List[RoomPricing]
    amenities: List[str]
    check_in: str
    check_out: str
    lat: float
    lng: float
    has_availability: bool
    live_price_sar: Optional[float] = None
    price_source: str = "Gemini Search"
    almosafer_url: str = ""
    rating: float = 0.0
    vibe: str = ""

    @property
    def best_deal(self) -> dict:
        if self.rooms:
            r = self.rooms[0]
            return {
                "room_type": r.room_type,
                "base_price_sar": r.base_price_sar,
                "final_price_sar": r.final_price_sar,
                "discount_percent": 0,
            }
        return {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "stars": self.stars,
            "rating": self.rating,
            "description": self.description,
            "rooms": [r.to_dict() for r in self.rooms],
            "amenities": self.amenities,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "lat": self.lat,
            "lng": self.lng,
            "has_availability": self.has_availability,
            "live_price_sar": self.live_price_sar,
            "price_source": self.price_source,
            "almosafer_url": self.almosafer_url,
            "best_deal": self.best_deal,
            "vibe": self.vibe,
        }


@dataclass
class MenuItemResult:
    name: str
    price_sar: float
    category: str
    is_signature: bool
    allergens: List[str]
    dietary: List[str]
    is_safe: bool
    flagged_allergens: List[str]

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


# ─── Hotel Functions ──────────────────────────────────────────────────────────

def search_hotels(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    room_type: Optional[str] = None,
    checkin: Optional[str] = None,
    checkout: Optional[str] = None,
    budget_per_night: Optional[float] = None,
) -> List[HotelResult]:
    """
    Fetch live hotel listings via Gemini Search Grounding.

    Steps:
      1. Call search_hotels_live() (Gemini) for 5 results with prices.
      2. Save any new hotels to the DB (name + coords only, no price).
      3. If city has <20 hotels in DB, run a second search to grow catalogue.
      4. Return HotelResult objects with live prices.
    """
    if not city:
        return []

    scraper = AlmosaferScraper()
    booking_url = scraper.hotel_search_url(city, checkin, checkout)

    # ── Step 1: live Gemini search (5 hotels + prices) ────────────────────────
    live_stubs = search_hotels_live(
        city=city,
        budget_per_night=budget_per_night or 500.0,
        max_results=5,
    )

    results: List[HotelResult] = []

    for stub in live_stubs:
        name = stub.name.strip()
        if not name:
            continue

        live_price = stub.price or 0.0
        rating = float(stub.rating or 0.0)

        # ── Step 2: persist name + coords (no price stored) ─────────────────
        lat, lng = _city_coords(city)
        upsert_hotel_static(city, name, lat, lng, 4)

        rooms = []
        if live_price > 0:
            rooms = [
                RoomPricing("Standard", live_price, live_price, True, "Gemini Search"),
                RoomPricing("Deluxe", live_price * 1.4, live_price * 1.4, True, "Gemini Search"),
            ]

        results.append(HotelResult(
            id=name[:20],
            name=name,
            city=city.title(),
            stars=4,
            rating=rating,
            description=stub.description or f"Hotel in {city.title()}",
            rooms=rooms,
            amenities=["WiFi", "Parking", "Air Conditioning", "Room Service"],
            check_in="14:00",
            check_out="12:00",
            lat=lat,
            lng=lng,
            has_availability=True,
            live_price_sar=live_price if live_price > 0 else None,
            price_source="Gemini Search",
            almosafer_url=booking_url,
            vibe=vibe or "",
        ))

    # ── Step 3: catalogue building — grow DB to 20+ hotels ───────────────────
    if get_hotel_count(city) < 20:
        try:
            extra = search_hotels_live(
                city=city,
                budget_per_night=(budget_per_night or 500.0) * 1.5,
                max_results=5,
            )
            for stub in extra:
                ename = stub.name.strip()
                if ename:
                    elat, elng = _city_coords(city)
                    upsert_hotel_static(city, ename, elat, elng, 4)
            print(f"📦 [Gemini] Catalogue for {city}: {get_hotel_count(city)} hotels stored.")
        except Exception as e:
            print(f"⚠️  [Gemini] Catalogue build error: {e}")

    return results


def get_hotel_details(hotel_id: str) -> Optional[HotelResult]:
    """Return details for a specific hotel by ID from the local cache."""
    from safari.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM hospitality WHERE id=? AND type="hotel"', (hotel_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    h = dict(row)
    return HotelResult(
        id=str(h["id"]),
        name=h["name"],
        city=h["city"].title(),
        stars=int(h.get("stars") or 4),
        rating=float(h.get("rating") or 0.0),
        description=f"Known property in {h['city'].title()}.",
        rooms=[],
        amenities=["WiFi", "Parking"],
        check_in="14:00",
        check_out="12:00",
        lat=float(h.get("lat") or 24.7),
        lng=float(h.get("lng") or 46.7),
        has_availability=True,
        live_price_sar=None,
        price_source="DB cache (no live price)",
    )


# ─── Restaurant Functions ─────────────────────────────────────────────────────

def _load_restaurants(city: str) -> list:
    rests = get_hospitality(city, type='restaurant')
    cafes = get_hospitality(city, type='cafe')
    return rests + cafes


def search_restaurants(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    cuisine: Optional[str] = None,
    allergens_to_avoid: Optional[List[str]] = None,
) -> List[RestaurantResult]:
    """Search restaurants by city. Data from local DB."""
    if not city:
        return []

    db_rests = _load_restaurants(city)
    results: List[RestaurantResult] = []

    for r in db_rests:
        if vibe and r.get("vibe", "").lower() != vibe.lower():
            continue

        tot_tables = r.get("total_tables") or 20
        reserved = r.get("available_tables") or random.randint(5, 18)
        available = max(0, tot_tables - reserved)

        vacancy = 1 - (reserved / tot_tables) if tot_tables > 0 else 0.5
        if vacancy >= 0.70:
            discount = 0.20
        elif vacancy >= 0.50:
            discount = 0.12
        elif vacancy >= 0.30:
            discount = 0.07
        else:
            discount = 0.0

        price = r.get("price") or 80
        menu_items = [
            MenuItemResult("Traditional Kabsa", price, "Main", True, [], [], True, []),
            MenuItemResult("Lentil Soup", price * 0.3, "Starter", False, [], [], True, []),
            MenuItemResult("Date Cake", price * 0.4, "Dessert", False, [], [], True, []),
        ]

        results.append(RestaurantResult(
            id=str(r["id"]),
            name=r["name"],
            city=r["city"],
            vibe=r.get("vibe", ""),
            cuisine=r.get("cuisine", "Traditional / Modern"),
            rating=r.get("rating") or 4.0,
            operating_hours={"open": "12:00", "close": "23:00"},
            total_tables=tot_tables,
            reserved_tables=reserved,
            available_tables=available,
            discount_percent=discount,
            menu=menu_items,
            top_dishes=["Traditional Kabsa"],
            lat=r.get("lat") or 24.7,
            lng=r.get("lng") or 46.7,
        ))

    return results


def get_restaurant_details(
    restaurant_id: str,
    allergens_to_avoid: Optional[List[str]] = None,
) -> Optional[RestaurantResult]:
    """Get restaurant details by ID."""
    from safari.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM hospitality WHERE id=? AND type IN ("restaurant","cafe")',
        (restaurant_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    tot = r.get("total_tables") or 20
    reserved = random.randint(5, 18)
    available = max(0, tot - reserved)
    price = r.get("price") or 80
    menu_items = [
        MenuItemResult("Traditional Kabsa", price, "Main", True, [], [], True, []),
        MenuItemResult("Lentil Soup", price * 0.3, "Starter", False, [], [], True, []),
        MenuItemResult("Date Cake", price * 0.4, "Dessert", False, [], [], True, []),
    ]
    return RestaurantResult(
        id=str(r["id"]), name=r["name"], city=r["city"],
        vibe=r.get("vibe", ""),
        cuisine=r.get("cuisine", "Traditional / Modern"),
        rating=r.get("rating") or 4.0,
        operating_hours={"open": "12:00", "close": "23:00"},
        total_tables=tot, reserved_tables=reserved,
        available_tables=available, discount_percent=0.07,
        menu=menu_items, top_dishes=["Traditional Kabsa"],
        lat=r.get("lat") or 24.7, lng=r.get("lng") or 46.7,
    )


# ─── Combined summary ─────────────────────────────────────────────────────────

def get_hospitality_summary(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    allergens: Optional[List[str]] = None,
) -> dict:
    """Combined hotels + restaurants summary."""
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
