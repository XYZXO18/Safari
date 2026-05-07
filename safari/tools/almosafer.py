"""
Almosafer Live Scraper
======================
Fetches real-time hotel and flight data directly from almosafer.com.

Strategy:
  1. Build the correct Almosafer search URL.
  2. Request the page with realistic browser headers.
  3. Parse __NEXT_DATA__ (Next.js SSR JSON) embedded in the HTML —
     this contains all search results without needing JS execution.
  4. Extract hotel/flight cards from the parsed JSON tree.
  5. Return up to 5 results per search with live prices.

No dummy/mock data exists in this module.
"""

from __future__ import annotations

import json
import re
import sys
import time
import random
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional

import requests

# Fix Windows console encoding so emoji/Unicode in print() doesn't crash
if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except AttributeError:
        pass

# ─── City → IATA + Almosafer slug mapping ─────────────────────────────────────
CITY_IATA = {
    "riyadh":   "RUH",
    "jeddah":   "JED",
    "dammam":   "DMM",
    "abha":     "AHB",
    "medina":   "MED",
    "taif":     "TIF",
    "yanbu":    "YNB",
    "tabuk":    "TUU",
    "hail":     "HAS",
    "al-ula":   "ULH",
    "coast":    "JED",
    "mountains":"AHB",
    "desert":   "ULH",
    "city":     "RUH",
}

CITY_ALMOSAFER_SLUG = {
    "riyadh":   "Riyadh",
    "jeddah":   "Jeddah",
    "dammam":   "Dammam",
    "abha":     "Abha",
    "medina":   "Medina",
    "taif":     "Taif",
    "yanbu":    "Yanbu",
    "tabuk":    "Tabuk",
    "hail":     "Hail",
    "al-ula":   "AlUla",
    "coast":    "Jeddah",
    "mountains":"Abha",
    "desert":   "AlUla",
    "city":     "Riyadh",
}

# Realistic browser headers to avoid bot detection
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.almosafer.com/en",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Cache-Control": "max-age=0",
}


def _resolve_dates(checkin: Optional[str], checkout: Optional[str]) -> tuple[str, str]:
    """Return (checkin, checkout) as DD-MM-YYYY strings, defaulting to +7/+10 days."""
    today = date.today()
    if not checkin:
        ci = today + timedelta(days=7)
    else:
        try:
            if "-" in checkin and len(checkin.split("-")[0]) == 4:
                ci = datetime.strptime(checkin, "%Y-%m-%d").date()
            else:
                ci = datetime.strptime(checkin, "%d-%m-%Y").date()
        except Exception:
            ci = today + timedelta(days=7)

    if not checkout:
        co = ci + timedelta(days=3)
    else:
        try:
            if "-" in checkout and len(checkout.split("-")[0]) == 4:
                co = datetime.strptime(checkout, "%Y-%m-%d").date()
            else:
                co = datetime.strptime(checkout, "%d-%m-%Y").date()
        except Exception:
            co = ci + timedelta(days=3)

    return ci.strftime("%d-%m-%Y"), co.strftime("%d-%m-%Y")


def _fetch_page(url: str, timeout: int = 20) -> Optional[str]:
    """Fetch a page with browser headers. Returns HTML text or None on failure."""
    try:
        session = requests.Session()
        # Brief random delay to be polite
        time.sleep(random.uniform(0.5, 1.5))
        resp = session.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"⚠️  [Almosafer] HTTP fetch failed for {url}: {e}")
        return None


def _extract_next_data(html: str) -> Optional[dict]:
    """Extract the __NEXT_DATA__ JSON blob embedded by Next.js in the HTML."""
    try:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html, re.DOTALL
        )
        if match:
            return json.loads(match.group(1))
    except Exception as e:
        print(f"⚠️  [Almosafer] __NEXT_DATA__ parse error: {e}")
    return None


def _deep_find(obj, key: str) -> list:
    """Recursively walk a nested dict/list to find all values for a given key."""
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                results.append(v)
            else:
                results.extend(_deep_find(v, key))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_deep_find(item, key))
    return results


def _parse_hotels_from_next_data(data: dict) -> List[Dict]:
    """Walk the Next.js data tree to find hotel listings."""
    hotels = []

    # Search for hotel-like structures — different keys Almosafer might use
    for candidate_key in ("hotels", "hotelList", "results", "items", "properties"):
        found = _deep_find(data, candidate_key)
        for item in found:
            if isinstance(item, list):
                for h in item:
                    parsed = _try_parse_hotel_entry(h)
                    if parsed:
                        hotels.append(parsed)
            elif isinstance(item, dict):
                parsed = _try_parse_hotel_entry(item)
                if parsed:
                    hotels.append(parsed)
        if hotels:
            break

    return hotels


def _try_parse_hotel_entry(h: dict) -> Optional[Dict]:
    """Try to extract hotel fields from an unknown dict structure."""
    if not isinstance(h, dict):
        return None

    # Look for a name field
    name = (
        h.get("name") or h.get("hotelName") or h.get("title") or
        h.get("propertyName") or h.get("hotel_name")
    )
    if not name or not isinstance(name, str) or len(name) < 3:
        return None

    # Look for a price field
    price = None
    for price_key in ("price", "rate", "lowestPrice", "startingPrice",
                       "pricePerNight", "amount", "totalPrice", "minPrice"):
        v = h.get(price_key)
        if v is not None:
            try:
                price = float(str(v).replace(",", "").strip())
                if price > 0:
                    break
            except Exception:
                pass

    # Look for nested price
    if price is None:
        price_obj = h.get("pricing") or h.get("priceInfo") or h.get("rates")
        if isinstance(price_obj, dict):
            for pk in ("amount", "price", "total", "value", "perNight"):
                v = price_obj.get(pk)
                if v is not None:
                    try:
                        price = float(str(v).replace(",", "").strip())
                        if price > 0:
                            break
                    except Exception:
                        pass

    # Stars
    stars = h.get("stars") or h.get("starRating") or h.get("category") or 4
    try:
        stars = int(float(str(stars)))
    except Exception:
        stars = 4

    # Rating
    rating = h.get("rating") or h.get("guestRating") or h.get("reviewScore") or 0
    try:
        rating = round(float(str(rating)), 1)
    except Exception:
        rating = 0.0

    # Almosafer hotel ID or slug
    hotel_id = (
        h.get("id") or h.get("hotelId") or h.get("propertyId") or
        re.sub(r"[^a-z0-9]", "_", name.lower())[:30]
    )

    return {
        "id": str(hotel_id),
        "name": name.strip(),
        "price_per_night": price,
        "stars": stars,
        "rating": rating,
        "source": "almosafer_live",
    }


def _parse_hotels_from_bs4(html: str) -> List[Dict]:
    """Fallback: use BeautifulSoup to extract hotel cards from rendered HTML."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        hotels = []

        # Almosafer uses data-testid attributes on hotel cards
        selectors = [
            "[data-testid='HotelSearchResult__HotelName']",
            "[data-testid='hotel-name']",
            ".hotel-name",
            "h3.hotel__name",
            "[class*='hotelName']",
            "[class*='HotelName']",
            "[class*='hotel-name']",
            "[class*='property-name']",
        ]

        name_els = []
        for sel in selectors:
            name_els = soup.select(sel)
            if name_els:
                break

        price_els = []
        for price_sel in [
            "[data-testid='HotelSearchResult__PriceValue']",
            "[data-testid='hotel-price']",
            ".hotel-price",
            "[class*='price']",
        ]:
            price_els = soup.select(price_sel)
            if price_els:
                break

        for i, el in enumerate(name_els[:10]):
            name = el.get_text(strip=True)
            price = None
            if i < len(price_els):
                price_text = price_els[i].get_text(strip=True)
                # Extract digits from price text (e.g. "SAR 450" or "450 ﷼")
                nums = re.findall(r"[\d,]+", price_text)
                if nums:
                    try:
                        price = float(nums[0].replace(",", ""))
                    except Exception:
                        pass

            if name and len(name) > 3:
                hotels.append({
                    "id": re.sub(r"[^a-z0-9]", "_", name.lower())[:30],
                    "name": name,
                    "price_per_night": price,
                    "stars": 4,
                    "rating": 0.0,
                    "source": "almosafer_bs4",
                })

        return hotels
    except ImportError:
        print("⚠️  [Almosafer] BeautifulSoup not installed — cannot parse HTML.")
        return []
    except Exception as e:
        print(f"⚠️  [Almosafer] BS4 parse error: {e}")
        return []


# ─── Public API ────────────────────────────────────────────────────────────────

class AlmosaferScraper:
    """
    Live scraper for almosafer.com hotel and flight data.
    No mock or dummy data — all results come from the live site.
    """

    BASE = "https://www.almosafer.com/en"

    # ── URL builders ────────────────────────────────────────────────────────────

    @staticmethod
    def hotel_search_url(city: str, checkin: str, checkout: str, adults: int = 2) -> str:
        """
        Almosafer hotel search URL.
        Format: /en/hotels/{City}/{DD-MM-YYYY}/{DD-MM-YYYY}/{N}_adult
        """
        slug = CITY_ALMOSAFER_SLUG.get(city.lower(), city.title())
        ci, co = _resolve_dates(checkin, checkout)
        return f"{AlmosaferScraper.BASE}/hotels/{slug}/{ci}/{co}/{adults}_adult"

    @staticmethod
    def flight_search_url(origin: str, destination: str, dep_date: str,
                           cabin: str = "Economy", adults: int = 1) -> str:
        """
        Almosafer one-way flight search URL.
        Format: /en/flights/{ORIG}-{DEST}/{YYYY-MM-DD}/{Cabin}/{N}Adult
        """
        orig_iata = CITY_IATA.get(origin.lower(), origin.upper()[:3])
        dest_iata = CITY_IATA.get(destination.lower(), destination.upper()[:3])

        # Ensure YYYY-MM-DD
        try:
            if "-" in dep_date and len(dep_date.split("-")[0]) == 2:
                dep_date = datetime.strptime(dep_date, "%d-%m-%Y").strftime("%Y-%m-%d")
        except Exception:
            dep_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

        return (
            f"{AlmosaferScraper.BASE}/flights/"
            f"{orig_iata}-{dest_iata}/{dep_date}/{cabin}/{adults}Adult"
        )

    # ── Scrapers ────────────────────────────────────────────────────────────────

    def scrape_hotels(
        self,
        city: str,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None,
        adults: int = 2,
        max_results: int = 5,
    ) -> List[Dict]:
        """
        Fetch live hotel listings from Almosafer for a city.
        Returns up to `max_results` hotels with live prices.
        No mock data — raises no errors, but returns [] on complete failure.
        """
        url = self.hotel_search_url(city, checkin, checkout, adults)
        print(f"📡 [Almosafer] Hotel search → {url}")

        html = _fetch_page(url)
        if not html:
            print(f"⚠️  [Almosafer] No HTML received for hotel search in {city}.")
            return []

        hotels: List[Dict] = []

        # Try Next.js data first (most reliable)
        next_data = _extract_next_data(html)
        if next_data:
            hotels = _parse_hotels_from_next_data(next_data)
            print(f"✅ [Almosafer] __NEXT_DATA__ yielded {len(hotels)} hotels for {city}")

        # Fallback: BeautifulSoup HTML parsing
        if not hotels:
            hotels = _parse_hotels_from_bs4(html)
            print(f"ℹ️  [Almosafer] BS4 fallback yielded {len(hotels)} hotels for {city}")

        if not hotels:
            print(f"❌ [Almosafer] Could not extract hotel data for {city}.")

        return hotels[:max_results]

    def scrape_flights(
        self,
        origin: str,
        destination: str,
        dep_date: Optional[str] = None,
        adults: int = 1,
    ) -> List[Dict]:
        """
        Fetch live flight listings from Almosafer.
        Returns flight options with live prices.
        No mock data.
        """
        if not dep_date:
            dep_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")

        url = self.flight_search_url(origin, destination, dep_date)
        print(f"📡 [Almosafer] Flight search → {url}")

        html = _fetch_page(url)
        if not html:
            print(f"⚠️  [Almosafer] No HTML received for flight search {origin}→{destination}.")
            return []

        flights: List[Dict] = []

        next_data = _extract_next_data(html)
        if next_data:
            # Look for flight-like structures
            for key in ("flights", "flightList", "results", "itineraries", "options"):
                found = _deep_find(next_data, key)
                for item in found:
                    if isinstance(item, list):
                        for f in item:
                            parsed = _try_parse_flight_entry(f, origin, destination)
                            if parsed:
                                flights.append(parsed)
                    elif isinstance(item, dict):
                        parsed = _try_parse_flight_entry(item, origin, destination)
                        if parsed:
                            flights.append(parsed)
                if flights:
                    break

        if not flights:
            # Try BeautifulSoup for flights
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "lxml")
                price_els = soup.select("[data-testid='FlightSearchResult__PriceValue']")
                airline_els = soup.select("[data-testid='FlightSearchResult__AirlineName']")

                for i, p_el in enumerate(price_els[:5]):
                    price_text = p_el.get_text(strip=True)
                    nums = re.findall(r"[\d,]+", price_text)
                    price = float(nums[0].replace(",", "")) if nums else None
                    airline = airline_els[i].get_text(strip=True) if i < len(airline_els) else "Unknown"
                    if price:
                        flights.append({
                            "airline": airline,
                            "price_sar": price,
                            "duration": "~2h",
                            "source": "almosafer_bs4",
                        })
            except Exception as e:
                print(f"⚠️  [Almosafer] Flight BS4 parse error: {e}")

        if not flights:
            print(f"❌ [Almosafer] Could not extract flight data for {origin}→{destination}.")

        return flights[:5]


def _try_parse_flight_entry(f: dict, origin: str, destination: str) -> Optional[Dict]:
    """Try to extract flight fields from an unknown dict structure."""
    if not isinstance(f, dict):
        return None

    price = None
    for pk in ("price", "amount", "totalPrice", "total", "fare", "lowestFare"):
        v = f.get(pk)
        if v is not None:
            try:
                price = float(str(v).replace(",", "").strip())
                if price > 0:
                    break
            except Exception:
                pass

    if price is None:
        return None

    airline = (
        f.get("airline") or f.get("airlineName") or f.get("carrier") or
        f.get("marketingCarrier") or "Unknown"
    )
    if isinstance(airline, dict):
        airline = airline.get("name") or airline.get("code") or "Unknown"

    duration = f.get("duration") or f.get("flightDuration") or "~2h"

    return {
        "airline": str(airline).strip(),
        "price_sar": price,
        "duration": str(duration),
        "origin": origin,
        "destination": destination,
        "source": "almosafer_live",
    }
