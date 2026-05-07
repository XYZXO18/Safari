"""
Safari Web App
==============
Flask-based web interface for the Safari travel planner.
Serves a beautiful UI with interactive map, calendar, and form-based inputs.
"""

import sys
import os
import io

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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
        budget = float(data.get("budget", 3000))
        travel_mode = data.get("travel_mode", "car")
        destination = data.get("destination", "coast")
        days = int(data.get("days", 3))
        origin = data.get("origin", "riyadh")
        vehicle_type = data.get("vehicle_type", "default")
        currency = data.get("currency", "SAR")
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        interests = data.get("interests", "")
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid input: {e}"}), 400

    # If dates not provided, compute from today
    if not start_date or not end_date:
        from datetime import date, timedelta
        today = date.today()
        start = today + timedelta(days=1)
        end = start + timedelta(days=max(days - 1, 0))
        start_date = start.isoformat()
        end_date = end.isoformat()

    # Step 1: Transport calculation (shared for all paths)
    try:
        transport = calculate_transport_costs(
            mode=travel_mode,
            origin=origin,
            destination=destination,
            vehicle_type=vehicle_type,
        )

        def build_trip_path(path_type, target_budget, activities_limit=None):
            # Budget allocation
            breakdown = budget_allocator(
                total_budget=target_budget,
                transport_cost=transport.cost_round_trip,
                days=days,
                currency=currency,
            )

            # Scan for live events
            dest_info = DESTINATIONS.get(destination.lower(), DESTINATIONS.get("coast", {}))
            cities = dest_info.get("cities", [])
            scan_city = cities[0] if cities else destination.title()

            event_scan = find_live_events(
                location=scan_city,
                start_date=start_date,
                end_date=end_date,
                interests=interests,
                max_events=10,
            )

            # Adjust activities budget
            event_cost_per_day = event_scan.total_event_cost / days if days > 0 else 0
            adjusted_activities_budget = max(breakdown.activities_per_day - event_cost_per_day, 0)
            if activities_limit is not None:
                adjusted_activities_budget = min(adjusted_activities_budget, activities_limit)

            # Activity suggestions
            activities = suggest_activities(
                destination=destination,
                days=days,
                daily_activities_budget=adjusted_activities_budget,
                currency=currency,
            )

            # Inject live events
            if event_scan.has_events:
                for i, event in enumerate(event_scan.events):
                    target_day = (i % days) + 1
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
                    }
                    day_key = target_day
                    if day_key in activities.daily_activities:
                        activities.daily_activities[day_key].insert(0, event_activity)
                    else:
                        activities.daily_activities[day_key] = [event_activity]

            # Web + Social Media Research
            web_research = research_destination(
                city=scan_city,
                interests=interests,
            )

            # Inject trending spots
            if web_research.trending_spots:
                import random
                city_coords = CITY_COORDS.get(activities.recommended_city.lower(), {"lat": 24.7, "lng": 46.7})

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
                    }
                    day_key = target_day
                    if day_key in activities.daily_activities:
                        insert_pos = 0
                        for idx, act in enumerate(activities.daily_activities[day_key]):
                            if isinstance(act, dict) and act.get("is_live_event"):
                                insert_pos = idx + 1
                            else:
                                break
                        activities.daily_activities[day_key].insert(insert_pos, spot_activity)
                    else:
                        activities.daily_activities[day_key] = [spot_activity]

            # Get coordinates for map
            origin_coords = CITY_COORDS.get(origin.lower(), CITY_COORDS.get("riyadh"))
            dest_coords = CITY_COORDS.get(destination.lower(), CITY_COORDS.get("coast"))
            rec_city = activities.recommended_city.lower()
            rec_coords = CITY_COORDS.get(rec_city, dest_coords)

            # Hospitality Data
            # Delegate to Orchestrator Agent and its 3 Workers
            print(f"\\n[Orchestrator Agent] Delegating {path_type} path to Workers...")
            
            # Worker 1: Research
            print("  -> [Worker 1: Research] Finding activities and events.")
            # (Activities and events were computed above by tools, but conceptually Worker 1 owns this data)
            
            # Worker 2: Hospitality
            print("  -> [Worker 2: Hospitality] Fetching hotels and restaurants.")
            worker_2 = HospitalityWorker()
            try:
                hosp_res = worker_2.process_request({
                    "action": "search_hotels",
                    "city": activities.recommended_city,
                    "budget_per_night": breakdown.lodging_per_day,
                    "guests": 2
                })
                hotels = hosp_res.get("hotels", [])
                
                rest_res = worker_2.process_request({
                    "action": "search_restaurants",
                    "city": activities.recommended_city
                })
                restaurants = rest_res.get("restaurants", [])
                hospitality_data = {"hotels": hotels, "restaurants": restaurants}
                
                hotel_data = activities.hotel
                if hotels:
                    best_hotel = hotels[0]
                    hotel_data = {"name": best_hotel.get("name"), "lat": best_hotel.get("lat"), "lng": best_hotel.get("lng")}

                # Worker 3: Transport
                print("  -> [Worker 3: Transport] Calculating routing and timeline.")
                worker_3 = TransportWorker()
                timeline_req = {
                    "action": "plan_timeline",
                    "daily_activities": activities.daily_activities,
                    "hotel": hotel_data,
                    "travel_mode": travel_mode,
                    "vehicle_type": vehicle_type,
                    "origin": origin,
                    "destination": destination,
                }
                timeline_res = worker_3.process_request(timeline_req)
                timeline = timeline_res.get("timeline", {})
                total_transit_cost = timeline_res.get("total_transit_cost", 0)
                simulation_routes = timeline_res.get("simulation_routes", {})
                full_trip_dataset = timeline_res.get("full_trip_dataset", [])
                travel_time_str = timeline_res.get("inter_city_travel_time_str", "")
            except Exception as e:
                import traceback
                traceback.print_exc()
                error_msg = str(e)
                print(f"⚠️ [Orchestrator] Workers failed: {error_msg}. Calling Fixer Agent...")
                
                fixer = FixerWorker()
                # Attempt to fix hospitality
                hospitality_data = fixer.process_request(
                    {"city": activities.recommended_city, "vibe": path_type}, 
                    error_msg, "Hospitality"
                )
                
                # Attempt to fix transport/timeline
                timeline_res = fixer.process_request(
                    timeline_req, error_msg, "Transport"
                )
                
                timeline = timeline_res.get("timeline", {})
                total_transit_cost = timeline_res.get("total_transit_cost", 0)
                simulation_routes = timeline_res.get("simulation_routes", {})
                full_trip_dataset = timeline_res.get("full_trip_dataset", [])
                travel_time_str = timeline_res.get("inter_city_travel_time_str", "4h (Est)")

            # Lodging is PENDING until user selects a hotel
            # We keep the allocated lodging budget as max_lodging_budget for reference,
            # but set actual lodging to 0 until hotel is chosen.
            return {
                "path_type": path_type,
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
                },
                "budget": {
                    "total": target_budget,
                    "currency": currency,
                    "transport": transport.cost_round_trip,
                    "remaining": breakdown.remaining_budget,
                    "days": days,
                    "lodging": {"total": 0, "per_day": 0, "pending": True, "max_budget": breakdown.lodging_total, "max_per_day": breakdown.lodging_per_day},
                    "food": {"total": breakdown.food_total, "per_day": breakdown.food_per_day},
                    "activities": {"total": breakdown.activities_total, "per_day": breakdown.activities_per_day},
                    "buffer": {"total": breakdown.buffer_total, "per_day": breakdown.buffer_per_day},
                    "is_feasible": breakdown.is_feasible,
                    "warnings": breakdown.warnings,
                },
                "activities": {
                    "destination": activities.destination,
                    "vibe": activities.vibe,
                    "recommended_city": activities.recommended_city,
                    "daily_plan": {str(k): v for k, v in activities.daily_activities.items()},
                    "hotel": activities.hotel,
                },
                "events": event_scan.to_dict(),
                "web_research": web_research.to_dict() if web_research.has_data else None,
                "dates": {
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "map": {
                    "origin": origin_coords,
                    "destination": rec_coords,
                    "origin_name": origin.title(),
                    "dest_name": activities.recommended_city,
                },
                "hospitality": hospitality_data,
                "timeline": timeline,
                "total_transit_cost": total_transit_cost,
                "simulation_routes": simulation_routes,
                "full_trip_dataset": full_trip_dataset,
            }

        paths = []
        # Generate 3 alternative paths IN PARALLEL (massive speed boost)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        path_configs = [
            ("budget",   budget * 0.7, 30),
            ("balanced", budget,       None),
            ("premium",  budget * 1.5, None),
        ]

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(build_trip_path, ptype, pbudget, plimit): idx
                for idx, (ptype, pbudget, plimit) in enumerate(path_configs)
            }
            results = [None, None, None]
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    print(f"Path {path_configs[idx][0]} failed: {e}")
                    results[idx] = {"path_type": path_configs[idx][0], "error": str(e)}
            paths = results

        return jsonify({
            "paths": paths,
            "recommendation": 1 # Balanced is default
        })

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
    city = request.args.get('city')
    item_type = request.args.get('type')
    if not city:
        return jsonify({"error": "City is required"}), 400
    
    from safari.database import get_hospitality, randomize_hospitality
    randomize_hospitality(city)
    data = get_hospitality(city, item_type)
    return jsonify(data)

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
