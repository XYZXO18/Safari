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
from config import DESTINATIONS, CITY_COORDS, ROUTES
from safari.input_parser import TripRequest
from safari.tools.transport import calculate_transport_costs
from safari.tools.budget import budget_allocator
from safari.tools.activities import suggest_activities
from safari.tools.event_scanner import find_live_events

app = Flask(__name__, static_folder="static", template_folder="templates")


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

    # Step 1: Transport calculation
    transport = calculate_transport_costs(
        mode=travel_mode,
        origin=origin,
        destination=destination,
        vehicle_type=vehicle_type,
    )

    # Step 2: Budget allocation
    breakdown = budget_allocator(
        total_budget=budget,
        transport_cost=transport.cost_round_trip,
        days=days,
        currency=currency,
    )

    # Step 3: Scan for live events
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

    # Step 4: Adjust activities budget for event costs
    event_cost_per_day = event_scan.total_event_cost / days if days > 0 else 0
    adjusted_activities_budget = max(breakdown.activities_per_day - event_cost_per_day, 0)

    # Step 5: Activity suggestions (with adjusted budget)
    activities = suggest_activities(
        destination=destination,
        days=days,
        daily_activities_budget=adjusted_activities_budget,
        currency=currency,
    )

    # Step 6: Inject live events into the daily plan
    if event_scan.has_events:
        for i, event in enumerate(event_scan.events):
            target_day = (i % days) + 1
            event_activity = {
                "id": f"evt_{i}_{event.name.replace(' ', '_').lower()[:10]}",
                "name": f"\ud83c\udfaa LIVE: {event.name}",
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

    # Get coordinates for map
    origin_coords = CITY_COORDS.get(origin.lower(), CITY_COORDS.get("riyadh"))
    dest_coords = CITY_COORDS.get(destination.lower(), CITY_COORDS.get("coast"))

    # Find the recommended city's coords if different from vibe
    rec_city = activities.recommended_city.lower()
    rec_coords = CITY_COORDS.get(rec_city, dest_coords)

    # Build response
    result = {
        "transport": {
            "mode": transport.mode,
            "origin": origin.title(),
            "destination": activities.recommended_city,
            "distance_km": transport.distance_km,
            "cost_one_way": transport.cost_one_way,
            "cost_round_trip": transport.cost_round_trip,
        },
        "budget": {
            "total": budget,
            "currency": currency,
            "transport": transport.cost_round_trip,
            "remaining": breakdown.remaining_budget,
            "days": days,
            "lodging": {"total": breakdown.lodging_total, "per_day": breakdown.lodging_per_day},
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
    }

    return jsonify(result)


if __name__ == "__main__":
    print("\n🧭 Safari Web UI starting...")
    print("   Open http://localhost:5000 in your browser\n")
    app.run(debug=True, port=5000)
