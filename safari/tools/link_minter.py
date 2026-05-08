"""
Link Minter
===========
Drives a headless Chromium browser through Almosafer's flight search to capture
the session-bound `/flight/traveller/sl-...` URL that is normally only reachable
by clicking Search Results -> Check Prices -> Select a fare.

Notes / caveats
---------------
- The minted URL contains a server-issued session token. It may be IP-bound; if
  Almosafer rejects the session when the end user opens it from a different IP
  than this server, the URL falls back to the search-results page.
- Selectors WILL drift over time. This module is a best-effort tool, not a
  guaranteed deep-link.
- Bot detection (Cloudflare, etc.) may block headless launches; rotate the user
  agent and use a stealthy launch profile.
- Runs synchronously via `playwright.sync_api` — call from a worker thread if
  the host process is async.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

# In-process cache so we don't replay the headless flow for the same params.
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes — sessions usually expire faster

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _cache_get(key: str) -> Optional[str]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        ts, url = entry
        if time.time() - ts > _CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return url


def _cache_put(key: str, url: str) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), url)


def mint_flight_traveller_url(
    origin_iata: str,
    dest_iata: str,
    dep_date: str,
    cabin: str = "Economy",
    adults: int = 1,
    fare_index: int = 0,
    timeout_ms: int = 35000,
) -> dict:
    """
    Drive Almosafer to the flight traveller-details page and return the URL.

    Returns a dict: {"url": <minted URL>, "fallback": False, "error": None}
    On failure, returns {"url": <search URL>, "fallback": True, "error": "..."}.
    """
    from safari.tools.almosafer import AlmosaferScraper

    search_url = AlmosaferScraper.flight_search_url(
        origin_iata, dest_iata, dep_date, cabin=cabin, adults=adults,
    )
    cache_key = f"flight|{origin_iata}|{dest_iata}|{dep_date}|{cabin}|{adults}|{fare_index}"

    cached = _cache_get(cache_key)
    if cached:
        return {"url": cached, "fallback": False, "error": None, "cached": True}

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {
            "url": search_url, "fallback": True,
            "error": "playwright not installed — run: pip install playwright && playwright install chromium",
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
            ])
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Step 1: click the first "Check Prices" button on the results page.
            check_btn = page.locator("button:has-text('Check Prices')").first
            check_btn.wait_for(state="visible", timeout=timeout_ms)
            check_btn.click()

            # Step 2: wait for fare-type cards, click the chosen "Select" button.
            select_btns = page.locator("button:has-text('Select')")
            select_btns.first.wait_for(state="visible", timeout=timeout_ms)
            count = select_btns.count()
            idx = max(0, min(fare_index, count - 1)) if count else 0
            select_btns.nth(idx).click()

            # Step 3: wait until the URL becomes the traveller page.
            page.wait_for_url("**/flight/traveller/**", timeout=timeout_ms)
            final_url = page.url
            ctx.close()
            browser.close()

            _cache_put(cache_key, final_url)
            return {"url": final_url, "fallback": False, "error": None, "cached": False}

    except Exception as e:  # PWTimeout, navigation errors, anything
        return {"url": search_url, "fallback": True, "error": str(e)[:200]}


def mint_hotel_checkout_url(
    city: str,
    checkin: str,
    checkout: str,
    adults: int = 2,
    hotel_name: Optional[str] = None,
    timeout_ms: int = 35000,
) -> dict:
    """
    Drive Almosafer hotel search → pick a hotel → 'See rooms' to capture the
    rooms/checkout URL.

    Returns same shape as mint_flight_traveller_url.
    """
    from safari.tools.almosafer import AlmosaferScraper

    search_url = AlmosaferScraper.hotel_search_url(city, checkin, checkout, adults=adults)
    cache_key = f"hotel|{city.lower()}|{checkin}|{checkout}|{adults}|{(hotel_name or '').lower()}"

    cached = _cache_get(cache_key)
    if cached:
        return {"url": cached, "fallback": False, "error": None, "cached": True}

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return {
            "url": search_url, "fallback": True,
            "error": "playwright not installed — run: pip install playwright && playwright install chromium",
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
            ])
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Pick the hotel: by name if provided, else the first "See rooms".
            see_rooms = None
            if hotel_name:
                # Find a card containing the hotel name, then its See rooms button
                card = page.locator(f"text='{hotel_name}'").first
                try:
                    card.wait_for(state="visible", timeout=10000)
                    see_rooms = card.locator(
                        "xpath=ancestor::*[.//button[contains(., 'See rooms')]][1]"
                    ).locator("button:has-text('See rooms')").first
                except Exception:
                    see_rooms = None

            if see_rooms is None:
                see_rooms = page.locator("button:has-text('See rooms')").first

            see_rooms.wait_for(state="visible", timeout=timeout_ms)

            # Open in same tab — capture URL after navigation.
            with page.expect_navigation(timeout=timeout_ms, wait_until="domcontentloaded"):
                see_rooms.click()

            final_url = page.url
            ctx.close()
            browser.close()

            _cache_put(cache_key, final_url)
            return {"url": final_url, "fallback": False, "error": None, "cached": False}

    except Exception as e:
        return {"url": search_url, "fallback": True, "error": str(e)[:200]}
