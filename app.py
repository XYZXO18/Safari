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
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid input: {e}"}), 400

    # Run calculations
    transport = calculate_transport_costs(
        mode=travel_mode,
        origin=origin,
        destination=destination,
        vehicle_type=vehicle_type,
    )

    breakdown = budget_allocator(
        total_budget=budget,
        transport_cost=transport.cost_round_trip,
        days=days,
        currency=currency,
    )

    activities = suggest_activities(
        destination=destination,
        days=days,
        daily_activities_budget=breakdown.activities_per_day,
        currency=currency,
    )

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
