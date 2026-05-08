"""
Safari Web App
==============
Flask-based web interface for the Safari travel planner.
Serves a beautiful UI with interactive map, calendar, and form-based inputs.
"""

import sys
import os
import io

# Force UTF-8 on Windows without replacing the stream (avoids crash on Flask reloader)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, io.UnsupportedOperation):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify
from config import DESTINATIONS, CITY_COORDS, ROUTES, OLLAMA_URL, OLLAMA_MODEL
import requests
from safari.input_parser import TripRequest
from safari.tools.transport import calculate_transport_costs
from safari.tools.budget import budget_allocator
from safari.tools.activities import suggest_activities
from safari.tools.event_scanner import find_live_events
from safari.tools.web_research import research_destination
from safari.plan_cache import get_cached_plan, save_plan
from safari.agent.orchestrator_agent import OrchestratorAgent
from safari.agent.worker_research import ResearchWorker
from safari.agent.worker_hospitality import HospitalityWorker
from safari.agent.worker_transport import TransportWorker
from safari.agent.worker_fixer import FixerWorker
from google import genai
from safari.database import create_snapshot
app = Flask(__name__, static_folder="static", template_folder="templates")
worker_hospitality = HospitalityWorker()


@app.route("/")
def index():
    """Serve the main UI."""
    return render_template("index.html")


@app.route("/api/destinations")
def get_destinations():
    """Return available destinations with coordinates."""
    result = {}
    for vibe, info in DESTINATIONS.items():
        result[vibe] = {
            "cities": info["cities"],
            "vibe": info["vibe"],
            "activities": info["activities"],
            "avg_hotel_sar": info["avg_hotel_sar"],
            "avg_meal_sar": info["avg_meal_sar"],
            "coords": CITY_COORDS.get(vibe, {"lat": 24.7, "lng": 46.7}),
        }
    return jsonify(result)


@app.route("/api/coords")
def get_coords():
    """Return all city coordinates."""
    return jsonify(CITY_COORDS)


@app.route("/api/plan", methods=["POST"])
def plan_trip():
    """Process trip planning request and return structured data."""
    data = request.json

    try:
        raw_budget = data.get("budget")
        budget = float(raw_budget) if raw_budget not in (None, "", 0, "0") else 0.0
        suggest_budget = (budget == 0.0)
        travel_mode = data.get("travel_mode", "car")
        destination = data.get("destination", "coast").strip().lower()
        days = max(int(data.get("days", 3)), 1)
        origin = data.get("origin", "riyadh")
        vehicle_type = data.get("vehicle_type", "default")
        currency = data.get("currency", "SAR")
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        interests = data.get("interests", "")
        adults = max(int(data.get("adults", 1) or 1), 1)
        children = max(int(data.get("children", 0) or 0), 0)
        rooms = max(int(data.get("rooms", 1) or 1), 1)
        has_own_lodging = bool(data.get("has_own_lodging", False))
        min_hotel_stars = max(int(data.get("min_hotel_stars", 0) or 0), 0)
        min_restaurant_rating = float(data.get("min_restaurant_rating", 0) or 0)
        flight_class = str(data.get("flight_class", "coach") or "coach").lower()
        flight_stops = str(data.get("flight_stops", "any") or "any").lower()
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid input: {e}"}), 400

    # ── Plan cache: return existing result if same params within last 5 hours ──
    cached = get_cached_plan(data)
    if cached is not None:
        print(f"[PlanCache] HIT — returning cached plan for {origin} -> {destination}")
        return jsonify(cached)

    # Resolve country name → default city, then city → vibe
    from config import CITY_TO_VIBE, COUNTRY_TO_DEFAULT_CITY
    specific_city = None
    if destination not in DESTINATIONS:
        # 1. Country name? Map to the country's flagship tourist city first
        country_city = COUNTRY_TO_DEFAULT_CITY.get(destination)
        if country_city:
            specific_city = country_city
            destination = CITY_TO_VIBE.get(country_city, "city")
        else:
            # 2. Specific city name? Resolve to its vibe
            resolved_vibe = CITY_TO_VIBE.get(destination)
            if resolved_vibe:
                specific_city = destination
                destination = resolved_vibe
            else:
                # 3. Unknown — treat as a city and default vibe to city
                specific_city = destination if destination else None
                destination = "city"

    # If dates not provided, compute from today
    if not start_date or not end_date:
        from datetime import date, timedelta
        today = date.today()
        start = today + timedelta(days=1)
        end = start + timedelta(days=max(days - 1, 0))
        start_date = start.isoformat()
        end_date = end.isoformat()

    try:
        # ── Fast local operations (no I/O) ────────────────────────────────────
        transport = calculate_transport_costs(
            mode=travel_mode,
            origin=origin,
            destination=specific_city if specific_city else destination,
            vehicle_type=vehicle_type,
        )

        # Ticket-based modes scale per traveler (children at 0.75×).
        # Car/driving is per-vehicle, so the fuel bill doesn't multiply.
        ticket_factor = 1.0
        class_factor = 1.0
        class_label = ""
        if travel_mode.lower() in ("flight", "train", "bus"):
            ticket_factor = adults + 0.75 * children

            # Cabin/ticket class multiplier (only meaningful for flights, but applied
            # to train/bus too — most carriers also have a premium tier).
            if travel_mode.lower() == "flight":
                class_multipliers = {
                    "coach": 1.0, "economy": 1.0,
                    "premium": 1.6, "premium_economy": 1.6,
                    "business": 3.0,
                    "first": 5.0,
                }
                class_factor = class_multipliers.get(flight_class, 1.0)
                if class_factor != 1.0:
                    class_label = f" · {flight_class.replace('_', ' ').title()} class"

            total_factor = ticket_factor * class_factor
            transport.cost_one_way = round(transport.cost_one_way * total_factor, 2)
            transport.cost_round_trip = round(transport.cost_round_trip * total_factor, 2)
            stops_label = "" if flight_stops in ("any", "") else f" · {flight_stops.replace('_', ' ')}"
            transport.breakdown = (
                f"{transport.breakdown} × {ticket_factor:g} pax "
                f"({adults} adult{'s' if adults != 1 else ''}"
                f"{f' + {children} child(0.75×)' if children else ''})"
                f"{class_label}{stops_label}"
            )

        breakdown = budget_allocator(
            total_budget=budget,
            transport_cost=transport.cost_round_trip,
            days=days,
            currency=currency,
            adults=adults,
            children=children,
            has_own_lodging=has_own_lodging,
        )
        
        # If budget was suggested, update the 'budget' variable to the total suggested amount
        if suggest_budget:
            budget = breakdown.total_budget
            print(f"[Budget] Suggesting mid-range budget: {budget} {currency}")

        # Derive the target city without a Gemini call — used for all parallel queries
        dest_info = DESTINATIONS.get(destination.lower(), DESTINATIONS.get("coast", {}))
        cities = dest_info.get("cities", [])
        scan_city = specific_city.title() if specific_city else (cities[0] if cities else destination.title())

        # ── All slow I/O tasks fire at the same time ──────────────────────────
        from concurrent.futures import ThreadPoolExecutor
        worker_2 = HospitalityWorker()
        worker_3 = TransportWorker()

        with ThreadPoolExecutor(max_workers=6) as executor:
            f_activities = executor.submit(
                suggest_activities,
                destination=destination,
                days=days,
                daily_activities_budget=breakdown.activities_per_day,
                currency=currency,
                city_override=specific_city,
            )
            f_events = executor.submit(
                find_live_events,
                location=scan_city,
                start_date=start_date,
                end_date=end_date,
                interests=interests,
                max_events=10,
            )
            f_research = executor.submit(
                research_destination,
                city=scan_city,
                interests=interests,
            )
            f_hotels = None if has_own_lodging else executor.submit(worker_2.process_request, {
                "action": "search_hotels",
                "city": scan_city,
                "budget_per_night": breakdown.lodging_per_day,
                "guests": adults + children,
                "rooms": rooms,
            })
            f_restaurants = executor.submit(worker_2.process_request, {
                "action": "search_restaurants",
                "city": scan_city,
            })
            f_travel_costs = executor.submit(
                worker_3.phase2_travel_costs,
                origin=origin,
                destination=scan_city,
                travel_mode=travel_mode,
                days=days,
            )

        activities    = f_activities.result()
        event_scan    = f_events.result()
        web_research  = f_research.result()
        hotels        = f_hotels.result().get("hotels", []) if f_hotels else []
        restaurants   = f_restaurants.result().get("restaurants", [])

        # Apply user filters: minimum hotel stars, minimum restaurant rating.
        # Higher than the minimum is allowed; lower is removed.
        if min_hotel_stars > 0:
            hotels = [h for h in hotels if (h.get("stars") or 0) >= min_hotel_stars]
        if min_restaurant_rating > 0:
            restaurants = [r for r in restaurants if (r.get("rating") or 0) >= min_restaurant_rating]

        # ── Booking-link enrichment ───────────────────────────────────────────
        # Make sure every payable item carries a URL the user can click to book.
        from urllib.parse import quote_plus
        from safari.tools.almosafer import AlmosaferScraper as _Scraper

        for h in hotels:
            if not h.get("almosafer_url"):
                try:
                    h["almosafer_url"] = _Scraper.hotel_search_url(
                        scan_city, start_date, end_date, adults=adults,
                    )
                except Exception:
                    h["almosafer_url"] = (
                        f"https://www.almosafer.com/en/hotels?city={quote_plus(scan_city)}"
                    )
            # Per-hotel deep link via Booking.com — goes straight to the
            # property page (and its checkout) instead of a generic results list.
            h_name = h.get("name") or ""
            h["booking_url"] = (
                "https://www.booking.com/searchresults.html?"
                + f"ss={quote_plus(h_name + ' ' + scan_city)}"
                + f"&checkin={start_date}&checkout={end_date}"
                + f"&group_adults={adults}&group_children={children}"
                + f"&no_rooms={rooms}"
            )

        for r in restaurants:
            r_name = r.get("name") or ""
            r_city = r.get("city") or scan_city
            r["almosafer_url"] = (
                f"https://www.google.com/search?q={quote_plus(r_name + ' ' + r_city + ' reservation')}"
            )
            r["booking_url"] = r["almosafer_url"]

        # Flight booking deep-link (only meaningful for flight mode)
        flight_booking_url = ""
        if travel_mode.lower() == "flight":
            cabin_map = {
                "coach": "Economy", "economy": "Economy",
                "premium": "PremiumEconomy", "premium_economy": "PremiumEconomy",
                "business": "Business",
                "first": "First",
            }
            try:
                flight_booking_url = _Scraper.flight_search_url(
                    origin=origin,
                    destination=specific_city if specific_city else destination,
                    dep_date=start_date,
                    cabin=cabin_map.get(flight_class, "Economy"),
                    adults=adults,
                )
            except Exception:
                flight_booking_url = (
                    f"https://www.almosafer.com/en/flights?origin={quote_plus(origin)}"
                    f"&destination={quote_plus(specific_city or destination)}"
                )
        travel_costs  = f_travel_costs.result()

        # ── Inject live events ────────────────────────────────────────────────
        if event_scan.has_events:
            for i, event in enumerate(event_scan.events):
                target_day = (i % days) + 1
                evt_booking = (
                    f"https://www.google.com/search?q="
                    f"{quote_plus(event.name + ' ' + scan_city + ' tickets')}"
                )
                event_activity = {
                    "id": f"evt_{i}_{event.name.replace(' ', '_').lower()[:10]}",
                    "name": f"🎪 LIVE: {event.name}",
                    "lat": event.lat,
                    "lng": event.lng,
                    "is_live_event": True,
                    "cost": event.estimated_cost_sar,
                    "venue": event.venue,
                    "time": event.time,
                    "description": event.description,
                    "booking_url": evt_booking,
                }
                if target_day in activities.daily_activities:
                    activities.daily_activities[target_day].insert(0, event_activity)
                else:
                    activities.daily_activities[target_day] = [event_activity]

        # ── Inject trending spots ─────────────────────────────────────────────
        if web_research.trending_spots:
            import random
            city_coords = CITY_COORDS.get(activities.recommended_city.lower(), {"lat": 0.0, "lng": 0.0})
            for i, spot in enumerate(web_research.trending_spots[:days * 2]):
                target_day = (i % days) + 1
                spot_activity = {
                    "id": f"trend_{i}_{spot.name.replace(' ', '_').lower()[:10]}",
                    "name": f"🔥 TRENDING: {spot.name}",
                    "lat": spot.lat or (city_coords["lat"] + random.uniform(-0.05, 0.05)),
                    "lng": spot.lng or (city_coords["lng"] + random.uniform(-0.05, 0.05)),
                    "is_trending_spot": True,
                    "cost": spot.estimated_cost_sar,
                    "category": spot.category,
                    "description": spot.description,
                    "social_buzz": spot.social_buzz,
                    "rating": spot.rating,
                    "price_range": spot.price_range,
                    "tags": spot.tags,
                    "source": spot.source,
                    "booking_url": (
                        f"https://www.google.com/search?q="
                        f"{quote_plus(spot.name + ' ' + scan_city + ' tickets booking')}"
                    ),
                }
                if target_day in activities.daily_activities:
                    insert_pos = 0
                    for idx, act in enumerate(activities.daily_activities[target_day]):
                        if isinstance(act, dict) and act.get("is_live_event"):
                            insert_pos = idx + 1
                        else:
                            break
                    activities.daily_activities[target_day].insert(insert_pos, spot_activity)
                else:
                    activities.daily_activities[target_day] = [spot_activity]

        # ── Map coordinates ───────────────────────────────────────────────────
        origin_coords = CITY_COORDS.get(origin.lower(), CITY_COORDS.get("riyadh"))
        dest_coords   = CITY_COORDS.get(destination.lower(), CITY_COORDS.get("coast"))
        rec_coords    = CITY_COORDS.get(activities.recommended_city.lower(), dest_coords)

        # ── Timeline (pure math, fast) ────────────────────────────────────────
        hotel_data = activities.hotel
        if hotels:
            best = hotels[0]
            hotel_data = {"name": best.get("name"), "lat": best.get("lat"), "lng": best.get("lng")}

        timeline_res = worker_3.process_request({
            "action": "plan_timeline",
            "daily_activities": activities.daily_activities,
            "hotel": hotel_data,
            "travel_mode": travel_mode,
            "vehicle_type": vehicle_type,
            "origin": origin,
            "destination": destination,
        })

        plan = {
            "transport": {
                "mode": transport.mode,
                "origin": origin.title(),
                "destination": activities.recommended_city,
                "distance_km": transport.distance_km,
                "travel_time_str": transport.travel_time_str,
                "cost_one_way": transport.cost_one_way,
                "cost_round_trip": transport.cost_round_trip,
                "breakdown": transport.breakdown,
                "vehicle_type": vehicle_type,
                "booking_url": flight_booking_url,
            },
            "budget": {
                "total": budget,
                "currency": currency,
                "transport": transport.cost_round_trip,
                "remaining": breakdown.remaining_budget,
                "days": days,
                "lodging": {
                    "total": 0,
                    "per_day": 0,
                    "pending": not has_own_lodging,
                    "max_budget": breakdown.lodging_total,
                    "max_per_day": breakdown.lodging_per_day,
                    "user_provided": has_own_lodging,
                },
                "party": {
                    "adults": adults,
                    "children": children,
                    "rooms": rooms,
                    "food_people_factor": adults + 0.75 * children,
                },
                "filters": {
                    "min_hotel_stars": min_hotel_stars,
                    "min_restaurant_rating": min_restaurant_rating,
                    "flight_class": flight_class,
                    "flight_stops": flight_stops,
                },
                "food":       {"total": breakdown.food_total,       "per_day": breakdown.food_per_day},
                "activities": {"total": breakdown.activities_total, "per_day": breakdown.activities_per_day},
                "buffer":     {"total": breakdown.buffer_total,     "per_day": breakdown.buffer_per_day},
                "is_feasible": breakdown.is_feasible,
                "is_suggested": breakdown.is_suggested,
                "warnings":    breakdown.warnings,
            },
            "activities": {
                "destination":      activities.destination,
                "vibe":             activities.vibe,
                "recommended_city": activities.recommended_city,
                "daily_plan":       {str(k): v for k, v in activities.daily_activities.items()},
                "hotel":            activities.hotel,
            },
            "events":       (lambda d: (d.update({"events": [
                                dict(e, booking_url=(
                                    f"https://www.google.com/search?q="
                                    f"{quote_plus((e.get('name') or '') + ' ' + scan_city + ' tickets')}"
                                )) for e in d.get("events", [])
                            ]}) or d))(event_scan.to_dict()),
            "web_research": web_research.to_dict() if web_research.has_data else None,
            "dates":        {"start_date": start_date, "end_date": end_date},
            "map": {
                "origin":      origin_coords,
                "destination": rec_coords,
                "origin_name": origin.title(),
                "dest_name":   activities.recommended_city,
            },
            "hospitality": {
                "hotels":       hotels,
                "restaurants":  restaurants,
                "travel_costs": travel_costs.model_dump(),
            },
            "timeline":          timeline_res.get("timeline", {}),
            "total_transit_cost": timeline_res.get("total_transit_cost", 0),
            "simulation_routes": timeline_res.get("simulation_routes", {}),
            "full_trip_dataset": timeline_res.get("full_trip_dataset", []),
        }

        plan_result = {"paths": [plan], "recommendation": 0}
        save_plan(data, plan_result)
        return jsonify(plan_result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Planning failed: {str(e)}"}), 500


@app.route("/hospitality")
def hospitality_page():
    """Serve the hospitality browser UI."""
    return render_template("hospitality.html")


@app.route("/api/hotels")
def api_hotels():
    """Search hotels. Query params: city, vibe, room_type."""
    result = worker_hospitality.process_request({
        "action": "search_hotels",
        "city": request.args.get("city"),
        "vibe": request.args.get("vibe"),
        "room_type": request.args.get("room_type"),
    })
    return jsonify(result)


@app.route("/api/hotels/<hotel_id>")
def api_hotel_details(hotel_id):
    """Get hotel details by ID."""
    result = worker_hospitality.process_request({
        "action": "hotel_details",
        "hotel_id": hotel_id,
    })
    return jsonify(result)


@app.route("/api/restaurants")
def api_restaurants():
    """Search restaurants. Query params: city, vibe, cuisine, allergens (comma-sep)."""
    allergens_str = request.args.get("allergens", "")
    allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
    result = worker_hospitality.process_request({
        "action": "search_restaurants",
        "city": request.args.get("city"),
        "vibe": request.args.get("vibe"),
        "cuisine": request.args.get("cuisine"),
        "allergens": allergens,
    })
    return jsonify(result)


@app.route("/api/restaurants/<restaurant_id>/menu")
def api_restaurant_menu(restaurant_id):
    """Get restaurant menu with allergen checking."""
    allergens_str = request.args.get("allergens", "")
    allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
    result = worker_hospitality.process_request({
        "action": "restaurant_menu",
        "restaurant_id": restaurant_id,
        "allergens": allergens,
    })
    return jsonify(result)


@app.route("/api/hospitality/summary")
def api_hospitality_summary():
    """Get combined hotels + restaurants summary for a destination."""
    allergens_str = request.args.get("allergens", "")
    allergens = [a.strip() for a in allergens_str.split(",") if a.strip()] if allergens_str else []
    result = worker_hospitality.process_request({
        "action": "hospitality_summary",
        "city": request.args.get("city"),
        "vibe": request.args.get("vibe"),
        "allergens": allergens,
    })
    return jsonify(result)


import re
import json

@app.route("/api/chat", methods=["POST"])
def chat():
    """Chat endpoint that can make decisions and update the app state."""
    try:
        data = request.json
        user_msg = data.get("message", "")
        current_state = data.get("state", {})
        
        system_prompt = f"""You are the SFR Travel Agent AI.
Current trip settings: {current_state}

Respond to the user naturally, friendly, and briefly (under 3 sentences).
If the user asks to change their trip or gives new preferences (e.g. "I want to go to the beach", "Let's do 5 days", "Set my budget to 4000", "I want to fly"), you MUST append a JSON object at the very end of your response enclosed in <cmd> and </cmd> tags with the updated fields.
Valid fields to update (only include what changed): 
- budget (integer)
- origin (string: riyadh, jeddah, dammam)
- vibe (string: coast, mountains, desert, city)
- travel_mode (string: car, flight, train, bus)
- days (integer)
- interests (string)

Example:
Sure, I've updated your trip to 5 days at the coast!
<cmd>{{"days": 5, "vibe": "coast"}}</cmd>
"""
        
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": user_msg,
            "system": system_prompt,
            "stream": False,
            "options": {"temperature": 0.1}
        }
        
        res = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=30)
        res.raise_for_status()
        reply = res.json().get("response", "")
        
        # Parse commands
        commands = {}
        cmd_match = re.search(r'<cmd>(.*?)</cmd>', reply, re.DOTALL)
        if cmd_match:
            try:
                commands = json.loads(cmd_match.group(1))
            except Exception as e:
                print(f"Failed to parse cmd json: {e}")
            reply = re.sub(r'<cmd>.*?</cmd>', '', reply, flags=re.DOTALL).strip()
            
        return jsonify({"reply": reply, "commands": commands})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({"reply": f"I'm here to help! Make sure your local Ollama instance is running. (Error: {e})"}), 200


@app.route("/api/snapshot", methods=["POST"])
def api_snapshot():
    """Manually trigger a database snapshot."""
    path = create_snapshot()
    if path:
        return jsonify({"status": "success", "snapshot_path": path})
    return jsonify({"status": "error", "message": "Failed to create snapshot"}), 500

@app.route('/api/hospitality', methods=['GET'])
def api_get_hospitality():
    """
    Return hospitality listings for a city.
    Hotels: fetched live from Almosafer (5 with prices + grow DB catalogue).
    Restaurants/cafes: from local DB.
    """
    city = request.args.get('city')
    item_type = request.args.get('type')
    if not city:
        return jsonify({"error": "City is required"}), 400

    results = []

    if item_type in (None, 'all', 'hotel'):
        # Live Almosafer fetch
        hosp_res = worker_hospitality.process_request({
            "action": "search_hotels",
            "city": city,
        })
        for h in hosp_res.get("hotels", []):
            h["type"] = "hotel"
            results.append(h)

    if item_type in (None, 'all', 'restaurant', 'cafe'):
        rest_res = worker_hospitality.process_request({
            "action": "search_restaurants",
            "city": city,
        })
        for r in rest_res.get("restaurants", []):
            r["type"] = "restaurant"
            results.append(r)

    return jsonify(results)

@app.route('/api/book', methods=['POST'])
def api_book_hotel():
    data = request.json
    hotel_id = data.get('hotel_id')
    if not hotel_id:
        return jsonify({"error": "hotel_id is required"}), 400
    
    from safari.database import book_hotel
    book_hotel(hotel_id)
    return jsonify({"status": "success", "message": "Hotel booked successfully"})


@app.route('/api/select-hotel', methods=['POST'])
def api_select_hotel():
    """User selects a hotel — recalculate lodging into the budget."""
    data = request.json
    hotel_name = data.get('hotel_name', '')
    price_per_night = float(data.get('price_per_night', 0))
    days = int(data.get('days', 1))
    total_budget = float(data.get('total_budget', 0))
    currency = data.get('currency', 'SAR')

    lodging_total = price_per_night * days
    return jsonify({
        "status": "success",
        "hotel_name": hotel_name,
        "lodging": {
            "total": round(lodging_total, 2),
            "per_day": round(price_per_night, 2),
            "pending": False,
        }
    })


@app.route('/api/recommend-hotel', methods=['POST'])
def api_recommend_hotel():
    """
    Find the hotel closest to the geographic centroid of all planned activities.
    Expects JSON: { hotels: [...], activities_daily_plan: {...} }
    Returns the recommended hotel with a distance score.
    """
    import math
    data = request.json
    hotels = data.get('hotels', [])
    daily_plan = data.get('activities_daily_plan', {})

    if not hotels:
        return jsonify({"error": "No hotels provided"}), 400

    # Collect all activity coordinates
    act_coords = []
    for day_key, acts in daily_plan.items():
        for act in acts:
            if isinstance(act, dict) and act.get('lat') and act.get('lng'):
                act_coords.append((act['lat'], act['lng']))

    if not act_coords:
        # No geo-located activities — just return the first hotel
        return jsonify({"recommended_hotel_index": 0, "reason": "No activity coordinates available"})

    # Compute centroid of activities
    centroid_lat = sum(c[0] for c in act_coords) / len(act_coords)
    centroid_lng = sum(c[1] for c in act_coords) / len(act_coords)

    # Find hotel closest to centroid (Haversine distance)
    def haversine(lat1, lng1, lat2, lng2):
        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
        return R * 2 * math.asin(math.sqrt(a))

    best_idx = 0
    best_dist = float('inf')
    distances = []
    for i, h in enumerate(hotels):
        if h.get('lat') and h.get('lng'):
            d = haversine(centroid_lat, centroid_lng, h['lat'], h['lng'])
            distances.append(round(d, 2))
            if d < best_dist:
                best_dist = d
                best_idx = i
        else:
            distances.append(None)

    return jsonify({
        "recommended_hotel_index": best_idx,
        "centroid": {"lat": round(centroid_lat, 5), "lng": round(centroid_lng, 5)},
        "distances_km": distances,
        "reason": f"Closest to the center of {len(act_coords)} planned activities (~{best_dist:.1f} km)"
    })


@app.route('/api/transport/options', methods=['GET'])
def api_transport_options():
    """
    Get inter-city transport options for a route.
    Query params: origin, destination, mode (flight|bus|train), days
    Returns live results (cached 1 day).
    """
    origin = request.args.get('origin', '').strip()
    destination = request.args.get('destination', '').strip()
    mode = request.args.get('mode', 'flight').lower()
    days = int(request.args.get('days', 1))

    if not origin or not destination:
        return jsonify({"error": "origin and destination required"}), 400

    from safari.database import get_inter_city_transport, save_inter_city_transport

    # Return cached result if available
    cached = get_inter_city_transport(origin, destination, mode)
    if cached:
        cached['cached'] = True
        return jsonify(cached)

    from safari.tools.live_distance import (
        search_flight_prices, search_buses_live, search_trains_live,
        search_car_rental_prices, search_car_rental_fallback,
        find_nearest_airport, build_via_airport_journey,
    )
    from safari.tools.fuel import calculate_driving_cost
    from config import AIRPORTS

    result = {"origin": origin, "destination": destination, "mode": mode, "cached": False}

    if mode == "flight":
        from config import AIRPORTS as _AIRPORTS
        dest_ap = _AIRPORTS.get(destination.lower(), {})
        dest_has_airport = (not dest_ap or
            dest_ap.get("airport_city", destination.lower()) == destination.lower())

        airport_info = find_nearest_airport(origin)
        if not airport_info["has_own_airport"]:
            # Origin has no airport → build a via-airport two-leg journey
            via = build_via_airport_journey(origin, destination)
            if via:
                result["via_airport"] = via
                result["flights"] = []
                result["note"] = (
                    f"No airport in {origin.title()}. Showing combined journey via "
                    f"{airport_info['name']} ({airport_info['iata']})."
                )
            else:
                result["flights"] = []
                result["note"] = f"No airport in {origin.title()} and flight search failed."
        elif not dest_has_airport:
            result["flights"] = []
            result["note"] = f"No airport in {destination.title()}. Consider flying to nearest city."
        else:
            pricing = search_flight_prices(origin, destination)
            if pricing:
                result["flights"] = [{
                    "airline": pricing.airline or "Flight",
                    "price_one_way": pricing.price_one_way,
                    "price_round_trip": pricing.price_round_trip,
                    "duration_minutes": pricing.duration_minutes,
                    "currency": "SAR",
                    "source": pricing.source,
                    "confidence": pricing.confidence,
                }]
            else:
                result["flights"] = []
            result["note"] = "Prices from Gemini Search Grounding — check airline sites for exact fares."

    elif mode == "bus":
        bus_data = search_buses_live(origin, destination)
        result.update(bus_data)

    elif mode == "train":
        train_data = search_trains_live(origin, destination)
        result.update(train_data)

    # Also include car rental for non-car modes (for at-destination use)
    rental = search_car_rental_prices(destination, days) or search_car_rental_fallback(destination)
    from safari.tools.transport import _lookup_distance
    dist_km = _lookup_distance(origin, destination)
    fuel_data = calculate_driving_cost(dist_km, fuel_type="91", round_trip=True)
    result["car_rental"] = {
        "price_per_day": rental.price_per_day,
        "total_for_trip": round(rental.price_per_day * days, 2),
        "vehicle_type": rental.vehicle_type,
        "company": rental.company,
        "currency": "SAR",
        "source": rental.source,
    }
    result["fuel_if_renting"] = {
        "distance_km_roundtrip": round(dist_km * 2, 1),
        "cost_round_trip": fuel_data["cost_round_trip"],
        "liters": round(fuel_data["liters_one_way"] * 2, 1),
        "price_per_liter": fuel_data["price_per_liter"],
        "fuel_name": fuel_data["fuel_name"],
    }

    save_inter_city_transport(origin, destination, mode, result)
    return jsonify(result)


@app.route('/api/transport/local', methods=['GET'])
def api_transport_local():
    """
    Get local transport options for a destination city.
    Returns: public transit (cached 7 days) + taxi estimate ranges.
    Query params: city
    """
    city = request.args.get('city', '').strip()
    if not city:
        return jsonify({"error": "city required"}), 400

    from safari.database import get_public_transit, save_public_transit
    from safari.tools.live_distance import search_public_transit_live

    transit = get_public_transit(city)
    if not transit:
        transit = search_public_transit_live(city)
        if transit:
            save_public_transit(city, transit)

    # Taxi ranges per city (conservative estimates based on Uber/Careem Saudi pricing)
    taxi_ranges = {
        "riyadh":  {"short": "12–25", "medium": "25–60", "airport": "60–120"},
        "jeddah":  {"short": "10–20", "medium": "20–50", "airport": "50–100"},
        "dammam":  {"short": "10–20", "medium": "20–45", "airport": "40–80"},
        "makkah":  {"short": "15–30", "medium": "30–70", "airport": "70–130"},
        "madinah": {"short": "10–20", "medium": "20–45", "airport": "50–90"},
        "abha":    {"short": "8–15",  "medium": "15–35", "airport": "35–65"},
    }
    taxi = taxi_ranges.get(city.lower(), {"short": "10–25", "medium": "25–60", "airport": "50–110"})

    return jsonify({
        "city": city,
        "public_transit": transit,
        "taxi": {
            "currency": "SAR",
            "short_trip_sar": taxi["short"],
            "medium_trip_sar": taxi["medium"],
            "airport_to_city_sar": taxi["airport"],
            "apps": ["Uber", "Careem", "Jeeny"],
            "note": "Estimated fare ranges — actual cost depends on distance and time of day.",
        },
    })


@app.route('/api/transport/car-rental', methods=['GET'])
def api_car_rental():
    """
    Get car rental prices + fuel estimate for a destination city.
    Query params: city, days, distance_km (optional one-way distance from origin)
    """
    city = request.args.get('city', '').strip()
    days = int(request.args.get('days', 3))
    distance_km = float(request.args.get('distance_km', 0))

    if not city:
        return jsonify({"error": "city required"}), 400

    from safari.tools.live_distance import search_car_rental_prices, search_car_rental_fallback
    from safari.tools.fuel import calculate_driving_cost

    rental = search_car_rental_prices(city, days) or search_car_rental_fallback(city)

    fuel_data = None
    if distance_km > 0:
        fuel_data = calculate_driving_cost(distance_km, fuel_type="91", round_trip=True)

    return jsonify({
        "city": city,
        "days": days,
        "rental": {
            "price_per_day": rental.price_per_day,
            "total_rental_cost": round(rental.price_per_day * days, 2),
            "vehicle_type": rental.vehicle_type or "Economy",
            "company": rental.company or "Various",
            "currency": "SAR",
            "source": rental.source,
            "confidence": rental.confidence,
        },
        "fuel": {
            "cost_round_trip": fuel_data["cost_round_trip"] if fuel_data else None,
            "liters_round_trip": round(fuel_data["liters_one_way"] * 2, 1) if fuel_data else None,
            "price_per_liter": fuel_data["price_per_liter"] if fuel_data else 2.18,
            "fuel_name": fuel_data["fuel_name"] if fuel_data else "RON 91",
        } if fuel_data else None,
        "total_estimate": round(rental.price_per_day * days + (fuel_data["cost_round_trip"] if fuel_data else 0), 2),
    })


@app.route('/api/mint-link', methods=['POST'])
def api_mint_link():
    """
    Drive a headless browser to mint a deep checkout URL.
    Body: { type: 'flight'|'hotel', ... }
    """
    from safari.tools.link_minter import (
        mint_flight_traveller_url, mint_hotel_checkout_url,
    )
    data = request.json or {}
    kind = (data.get("type") or "").lower()

    if kind == "flight":
        result = mint_flight_traveller_url(
            origin_iata=str(data.get("origin", "")).strip(),
            dest_iata=str(data.get("destination", "")).strip(),
            dep_date=str(data.get("dep_date", "")).strip(),
            cabin=str(data.get("cabin", "Economy")).strip() or "Economy",
            adults=max(int(data.get("adults", 1) or 1), 1),
            fare_index=max(int(data.get("fare_index", 0) or 0), 0),
        )
        return jsonify(result)

    if kind == "hotel":
        result = mint_hotel_checkout_url(
            city=str(data.get("city", "")).strip(),
            checkin=str(data.get("checkin", "")).strip(),
            checkout=str(data.get("checkout", "")).strip(),
            adults=max(int(data.get("adults", 1) or 1), 1),
            hotel_name=(data.get("hotel_name") or None),
        )
        return jsonify(result)

    return jsonify({"error": "type must be 'flight' or 'hotel'"}), 400


if __name__ == "__main__":
    import threading
    import webbrowser

    def open_browser():
        import time
        time.sleep(1.5)  # Wait for Flask to be ready
        webbrowser.open("http://localhost:5000")

    print("\n🧭 SFR Web UI starting...")
    print("   Opening http://localhost:5000 in your browser...")
    print("   🏨 Hospitality: http://localhost:5000/hospitality\n")

    # Only auto-open on the first run (not the reloader subprocess)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(debug=True, port=5000)
