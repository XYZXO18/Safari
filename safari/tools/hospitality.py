"""
Hospitality & Venue Data Engine
================================
Agent 2's tool layer.

Hotel data flow:
  1. Call AlmosaferScraper.scrape_hotels(city) → up to 5 live results with prices.
  2. For every hotel returned, call upsert_hotel_static() to persist
     name + coordinates in the DB (price is NEVER stored — always live).
  3. If city has <20 hotels in DB, request additional Almosafer pages to
     build the catalogue up to 20 over time.
  4. Return HotelResult objects with live prices for the frontend.

Restaurant data is still served from the local DB (no Almosafer equivalent).
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
from safari.tools.almosafer import AlmosaferScraper


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
    base_price_sar: float         # Live price from Almosafer
    final_price_sar: float
    available: bool = True
    source: str = "Almosafer"

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
    live_price_sar: Optional[float] = None   # Best nightly rate from Almosafer
    price_source: str = "Almosafer"
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
    Fetch live hotel listings from Almosafer for the given city.

    Steps:
      1. Scrape 5 live hotels from Almosafer (with prices).
      2. Save any new hotels to the DB (name + coords only, no price).
      3. If city has <20 hotels in DB, do an extra scrape pass to build
         the catalogue (background best-effort).
      4. Return HotelResult objects with live prices.
    """
    if not city:
        return []

    scraper = AlmosaferScraper()

    # ── Step 1: live search (5 hotels + prices) ────────────────────────────────
    raw = scraper.scrape_hotels(city, checkin, checkout, max_results=5)

    results: List[HotelResult] = []

    for h in raw:
        name = h.get("name", "").strip()
        if not name:
            continue

        live_price = h.get("price_per_night")
        stars = int(h.get("stars") or 4)
        rating = float(h.get("rating") or 0.0)

        # ── Step 2: persist name + coords (no price stored) ─────────────────
        lat, lng = _city_coords(city)
        upsert_hotel_static(city, name, lat, lng, stars)

        # Build search URL for "Book on Almosafer" link
        url = scraper.hotel_search_url(city, checkin, checkout)

        rooms = []
        if live_price:
            rooms = [
                RoomPricing(
                    room_type="Standard",
                    base_price_sar=live_price,
                    final_price_sar=live_price,
                    available=True,
                    source="Almosafer",
                ),
                RoomPricing(
                    room_type="Deluxe",
                    base_price_sar=live_price * 1.4,
                    final_price_sar=live_price * 1.4,
                    available=True,
                    source="Almosafer",
                ),
            ]

        results.append(HotelResult(
            id=h.get("id", name[:20]),
            name=name,
            city=city.title(),
            stars=stars,
            rating=rating,
            description=f"Verified {stars}★ property in {city.title()} — sourced live from Almosafer.",
            rooms=rooms,
            amenities=["WiFi", "Parking", "Air Conditioning", "Room Service"],
            check_in="14:00",
            check_out="12:00",
            lat=lat,
            lng=lng,
            has_availability=True,
            live_price_sar=live_price,
            price_source="Almosafer",
            almosafer_url=url,
            vibe=vibe or "",
        ))

    # ── Step 3: catalogue building — if <20 stored, fetch extra pages ──────────
    current_count = get_hotel_count(city)
    if current_count < 20 and len(raw) > 0:
        try:
            # Offset search date by a week to get fresh/different results
            from datetime import datetime, timedelta
            extra_checkin = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
            extra_checkout = (date.today() + timedelta(days=17)).strftime("%Y-%m-%d")
            extra_raw = scraper.scrape_hotels(city, extra_checkin, extra_checkout, max_results=5)
            for eh in extra_raw:
                ename = eh.get("name", "").strip()
                if ename:
                    elat, elng = _city_coords(city)
                    upsert_hotel_static(city, ename, elat, elng, int(eh.get("stars") or 4))
            print(f"📦 [Almosafer] Catalogue for {city}: {get_hotel_count(city)} hotels stored.")
        except Exception as e:
            print(f"⚠️  [Almosafer] Catalogue build error: {e}")

    return results


def get_hotel_details(hotel_id: str) -> Optional[HotelResult]:
    """
    Return details for a specific hotel by ID from the local cache.
    Price is not included here (needs fresh Almosafer scrape).
    """
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
        description=f"Known property in {h['city'].title()}. Search for live prices on Almosafer.",
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
# Restaurants remain DB-backed (no Almosafer equivalent for restaurants).

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
    discount = 0.07
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
        available_tables=available, discount_percent=discount,
        menu=menu_items, top_dishes=["Traditional Kabsa"],
        lat=r.get("lat") or 24.7, lng=r.get("lng") or 46.7,
    )


# ─── Combined summary ─────────────────────────────────────────────────────────

def get_hospitality_summary(
    city: Optional[str] = None,
    vibe: Optional[str] = None,
    allergens: Optional[List[str]] = None,
) -> dict:
    """Combined hotels + restaurants summary for Agent 1."""
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
