"""
Travel Intelligence Agent (Agent 3)
=====================================
Full ownership of ALL travel-related decisions and data:

  • Inter-city routing (long-haul: car/flight/train/bus) with fuel breakdown
  • Intra-city daily scheduling: ordered stops, driving/walking/taxi legs
  • Travel-time estimation (minutes) for every leg
  • Ordered route-point list for map simulation
  • Car-rental vs taxi cost comparison per day

Every leg emitted by this agent contains:
  - from_name, to_name
  - from_lat, from_lng, to_lat, to_lng
  - mode  (emoji label)
  - dist  (km)
  - time_minutes
  - cost  (SAR)
"""

from __future__ import annotations

import math
from typing import Optional

from config import OLLAMA_URL, OLLAMA_MODEL, ROUTES
from safari.tools.transport import calculate_transport_costs, TransportEstimate
from safari.tools.fuel import calculate_driving_cost


# ─── Speed Table (km/h) ──────────────────────────────────────────────────────
# Context-aware: city trips are slower than highway legs
_SPEED = {
    "walk":    5,
    "drive_city":    50,   # < 20 km
    "drive_highway": 110,  # >= 20 km (Saudi highway speed)
    "taxi":    55,
    "public":  35,
}


def _travel_time_minutes(dist_km: float, mode: str) -> int:
    """Return estimated travel time in minutes for a given distance and mode."""
    if mode == "walk":
        speed = _SPEED["walk"]
    elif mode in ("drive", "car"):
        speed = _SPEED["drive_city"] if dist_km < 20 else _SPEED["drive_highway"]
    elif mode == "taxi":
        speed = _SPEED["taxi"]
    elif mode == "public":
        speed = _SPEED["public"]
    else:
        speed = _SPEED["drive_city"]

    if speed <= 0:
        return 0
    return max(1, round((dist_km / speed) * 60))


TRANSPORT_SYSTEM_PROMPT = """You are the **Travel Intelligence Agent** for the Safari travel system.

## Your Role
You own ALL travel-related decisions and data — both inter-city logistics and
daily intra-city routing. Your outputs drive the map, the itinerary timeline,
and the route simulation.

## Capabilities
- Calculate inter-city driving costs (fuel, vehicle type, distance)
- Estimate flight, train, bus costs for long-haul routes
- Build ordered daily routes: hotel → stops → hotel
- Calculate travel time (minutes) for every leg based on mode and distance
- Recommend cheapest daily transport (own-car vs taxi vs public vs car-rental)
- Return simulation route-points for animated map playback

## Rules
1. Always include time_minutes on every leg
2. Always include from/to lat/lng so the map can draw the animation
3. Output structured JSON for the Orchestrator — no prose
"""


class TransportWorker:
    """
    Agent 3 — Travel Intelligence Agent.
    Owns all transportation planning end-to-end.
    """

    def __init__(self):
        self.ollama_url = OLLAMA_URL
        self.model = OLLAMA_MODEL

    def process_request(self, request: dict) -> dict:
        """
        Supported actions:
          - plan_timeline   : Build daily route with time + cost per leg
          - calculate_route : Inter-city cost for a single mode + route
          - compare_modes   : Compare all modes for a route
          - get_routes      : List known routes
        """
        action = request.get("action", "").lower()

        if action == "plan_timeline":
            return self._handle_timeline(request)
        elif action == "calculate_route":
            return self._handle_calculate(request)
        elif action == "compare_modes":
            return self._handle_compare(request)
        elif action == "get_routes":
            return self._handle_routes(request)
        else:
            return {"error": f"Unknown travel action: {action}"}

    # ─── Inter-city ──────────────────────────────────────────────────────────

    def phase2_travel_costs(self, origin: str, destination: str, travel_mode: str, days: int) -> dict:
        """
        Fetch live flight and car rental prices from priority sources (Almosafer).
        """
        from safari.tools.almosafer import CITY_ALMOSAFER_SLUG

        flights = []
        if travel_mode.lower() == "flight":
            resolved_origin = CITY_ALMOSAFER_SLUG.get(origin.lower(), origin.title())
            resolved_dest = CITY_ALMOSAFER_SLUG.get(destination.lower(), destination.title())
            try:
                from safari.tools.live_distance import (
                    search_flight_prices, find_nearest_airport, build_via_airport_journey,
                )
                from config import AIRPORTS
                dest_airport_info = AIRPORTS.get(destination.lower(), {})
                dest_has_airport = (not dest_airport_info or
                    dest_airport_info.get("airport_city", destination.lower()) == destination.lower())
                airport_info = find_nearest_airport(origin.lower())
                if not airport_info["has_own_airport"]:
                    # Origin has no airport — build via-airport combined journey
                    via = build_via_airport_journey(resolved_origin, resolved_dest)
                    if via:
                        flights = [{
                            "airline": f"Via {via['airport_iata']}: {via['leg1']['note']} + {via['leg2']['airline'] or 'Flight'}",
                            "price_sar": via["total_one_way"],
                            "duration": f"{via['total_time_minutes']}m",
                            "source": "via_airport",
                            "via_airport": via,
                        }]
                elif not dest_has_airport:
                    print(f"[WorkerTransport] Skipping flight search — {destination} has no airport.")
                else:
                    flight_pricing = search_flight_prices(resolved_origin, resolved_dest)
                    if flight_pricing and flight_pricing.price_one_way > 0:
                        flights = [{
                            "airline": flight_pricing.airline or "Flight",
                            "price_sar": flight_pricing.price_one_way,
                            "duration": f"{flight_pricing.duration_minutes or 90}m",
                            "source": flight_pricing.source,
                        }]
            except Exception as e:
                print(f"[Worker3] Gemini flight search failed: {e}")
            
        # Mock model_dump behavior to match user's expected usage in app.py
        class MockResult:
            def __init__(self, data): self.data = data
            def model_dump(self): return self.data
            
        return MockResult({
            "status": "success",
            "flights": flights,
            "origin": origin,
            "destination": destination,
            "travel_mode": travel_mode
        })

    def _handle_calculate(self, req: dict) -> dict:
        mode = req.get("mode", "car")
        origin = req.get("origin", "riyadh")
        destination = req.get("destination", "coast")
        vehicle_type = req.get("vehicle_type", "default")

        try:
            estimate = calculate_transport_costs(
                mode=mode, origin=origin,
                destination=destination, vehicle_type=vehicle_type,
            )
            # Travel time for the long-haul (highway)
            time_hrs = estimate.distance_km / _SPEED["drive_highway"] if mode in ("car", "driving") else estimate.distance_km / 800
            time_mins = round(time_hrs * 60)

            return {
                "action": "calculate_route",
                "status": "success",
                "transport": {
                    "mode": estimate.mode,
                    "origin": estimate.origin,
                    "destination": estimate.destination,
                    "distance_km": estimate.distance_km,
                    "cost_one_way": estimate.cost_one_way,
                    "cost_round_trip": estimate.cost_round_trip,
                    "time_minutes_one_way": time_mins,
                    "currency": estimate.currency,
                    "breakdown": estimate.breakdown,
                    "summary": estimate.summary,
                },
            }
        except Exception as e:
            return {"action": "calculate_route", "status": "error", "error": str(e)}

    def _handle_compare(self, req: dict) -> dict:
        origin = req.get("origin", "riyadh")
        destination = req.get("destination", "coast")
        modes = ["car", "flight", "train", "bus"]
        comparisons = []

        for mode in modes:
            try:
                est = calculate_transport_costs(
                    mode=mode, origin=origin, destination=destination,
                )
                speed = _SPEED["drive_highway"] if mode == "car" else 800
                time_mins = round((est.distance_km / speed) * 60)
                comparisons.append({
                    "mode": est.mode,
                    "distance_km": est.distance_km,
                    "cost_one_way": est.cost_one_way,
                    "cost_round_trip": est.cost_round_trip,
                    "time_minutes_one_way": time_mins,
                    "breakdown": est.breakdown,
                })
            except Exception:
                continue

        comparisons.sort(key=lambda x: x["cost_round_trip"])
        cheapest = comparisons[0]["mode"] if comparisons else "unknown"

        return {
            "action": "compare_modes",
            "origin": origin,
            "destination": destination,
            "modes": comparisons,
            "cheapest": cheapest,
            "recommendation": (
                f"Cheapest: {cheapest} at {comparisons[0]['cost_round_trip']:.0f} SAR round-trip"
                if comparisons else "No routes available"
            ),
        }

    def _handle_routes(self, req: dict) -> dict:
        routes = []
        seen = set()
        for (o, d), dist in ROUTES.items():
            key = tuple(sorted([o, d]))
            if key not in seen and o != "default":
                seen.add(key)
                routes.append({
                    "origin": o.title(),
                    "destination": d.title(),
                    "distance_km": dist,
                })
        routes.sort(key=lambda x: x["distance_km"])
        return {"action": "get_routes", "routes": routes, "count": len(routes)}

    # ─── Haversine ───────────────────────────────────────────────────────────

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        # Handle cases where coordinates might be None or invalid
        try:
            if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
                return 0.0
            
            R = 6371
            dlat = math.radians(float(lat2) - float(lat1))
            dlon = math.radians(float(lon2) - float(lon1))
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c
        except (TypeError, ValueError):
            return 0.0

    # ─── Daily Timeline ──────────────────────────────────────────────────────

    def _make_leg(
        self,
        from_name: str, from_lat: float, from_lng: float,
        to_name: str, to_lat: float, to_lng: float,
        mode_key: str, mode_label: str, cost: float,
    ) -> dict:
        dist = self._haversine(from_lat, from_lng, to_lat, to_lng)
        return {
            "from_name": from_name,
            "from_lat": from_lat,
            "from_lng": from_lng,
            "to_name": to_name,
            "to_lat": to_lat,
            "to_lng": to_lng,
            "mode": mode_label,
            "dist": round(dist, 2),
            "time_minutes": _travel_time_minutes(dist, mode_key),
            "cost": round(cost, 2),
        }

    def _handle_timeline(self, req: dict) -> dict:
        daily_activities = req.get("daily_activities", {})
        hotel = req.get("hotel", {})
        travel_mode = req.get("travel_mode", "car")
        origin = req.get("origin", "riyadh")
        destination = req.get("destination", "coast")
        vehicle_type = req.get("vehicle_type", "default")

        hotel_lat = float(hotel.get("lat") or 0)
        hotel_lng = float(hotel.get("lng") or 0)
        hotel_name = hotel.get("name") or "Hotel"

        has_own_car = travel_mode == "car"

        timeline = {}
        total_transit_cost = 0.0
        # Inter-city long-haul legs
        from safari.tools.transport import calculate_transport_costs
        inter_city_est = calculate_transport_costs(
            mode=travel_mode,
            origin=origin,
            destination=destination,
            vehicle_type=vehicle_type
        )
        
        # Ordered simulation points per day
        simulation_routes = {}
        
        # Full Trip Dataset (All legs from start to finish)
        full_trip_dataset = []

        for day_str, acts in daily_activities.items():
            day = int(day_str)
            day_legs: list[dict] = []

            # Simulation route for this day: hotel + all stops + hotel
            sim_points = [{
                "name": hotel_name,
                "lat": hotel_lat,
                "lng": hotel_lng,
                "type": "hotel",
                "day": day,
            }]

            current_lat, current_lng = hotel_lat, hotel_lng
            current_name = hotel_name
            
            # If Day 1, add the Inter-city leg from Origin to Destination
            if day == 1:
                from config import CITY_COORDS
                origin_coords = CITY_COORDS.get(origin.lower(), {"lat": 24.7, "lng": 46.7})
                
                inter_city_leg = {
                    "from_name": origin.title(),
                    "from_lat": origin_coords["lat"],
                    "from_lng": origin_coords["lng"],
                    "to_name": hotel_name,
                    "to_lat": hotel_lat,
                    "to_lng": hotel_lng,
                    "mode": f"{'🚗' if travel_mode == 'car' else '✈️'} Long-haul",
                    "dist": inter_city_est.distance_km,
                    "time_minutes": inter_city_est.travel_time_minutes,
                    "cost": inter_city_est.cost_one_way,
                    "type": "inter_city"
                }
                day_legs.append(inter_city_leg)
                full_trip_dataset.append(inter_city_leg)
                
                # Update starting point for activities
                sim_points.insert(0, {
                    "name": origin.title(),
                    "lat": origin_coords["lat"],
                    "lng": origin_coords["lng"],
                    "type": "origin",
                    "day": day,
                })

            car_parked_lat, car_parked_lng = hotel_lat, hotel_lng
            car_parked_name = hotel_name

            day_taxi_cost = 0.0
            day_driving_cost = 0.0

            for act in acts:
                dest_lat = act.get("lat")
                if dest_lat is None: dest_lat = current_lat
                dest_lng = act.get("lng")
                if dest_lng is None: dest_lng = current_lng
                
                act_name = act.get("name") or "Stop"

                dist = self._haversine(current_lat, current_lng, dest_lat, dest_lng)
                if dist < 0.05:
                    # Already at this location — add to sim but no leg
                    sim_points.append({
                        "name": act_name, "lat": dest_lat, "lng": dest_lng,
                        "type": "activity", "day": day,
                    })
                    continue

                if dist < 1.0:
                    # ── Walk ────────────────────────────────────────────────
                    leg = self._make_leg(
                        current_name, current_lat, current_lng,
                        act_name, dest_lat, dest_lng,
                        "walk", "🚶 Walk", 0,
                    )
                    day_legs.append(leg)

                elif has_own_car:
                    # ── Drive (own car) ─────────────────────────────────────
                    # Walk back to car if needed
                    dist_to_car = self._haversine(current_lat, current_lng, car_parked_lat, car_parked_lng)
                    if dist_to_car > 0.1:
                        walk_leg = self._make_leg(
                            current_name, current_lat, current_lng,
                            "Parked Car", car_parked_lat, car_parked_lng,
                            "walk", "🚶 Walk to car", 0,
                        )
                        day_legs.append(walk_leg)
                        current_lat, current_lng = car_parked_lat, car_parked_lng
                        current_name = "Parked Car"

                    drive_dist = self._haversine(current_lat, current_lng, dest_lat, dest_lng)
                    fuel_est = calculate_driving_cost(drive_dist, round_trip=False, vehicle_type=vehicle_type)
                    cost = fuel_est["cost_one_way"]
                    day_driving_cost += cost

                    leg = self._make_leg(
                        current_name, current_lat, current_lng,
                        act_name, dest_lat, dest_lng,
                        "drive", "🚗 Drive", cost,
                    )
                    day_legs.append(leg)
                    car_parked_lat, car_parked_lng = dest_lat, dest_lng
                    car_parked_name = act_name

                else:
                    # ── Taxi / Public ────────────────────────────────────────
                    public_cost = 5 + (dist * 1.5 * 0.5)
                    taxi_cost = 10 + (dist * 2.5)

                    if public_cost < taxi_cost and dist > 3.0:
                        leg = self._make_leg(
                            current_name, current_lat, current_lng,
                            act_name, dest_lat, dest_lng,
                            "public", "🚌 Public Transport", public_cost,
                        )
                        day_taxi_cost += public_cost
                    else:
                        leg = self._make_leg(
                            current_name, current_lat, current_lng,
                            act_name, dest_lat, dest_lng,
                            "taxi", "🚕 Taxi", taxi_cost,
                        )
                        day_taxi_cost += taxi_cost
                    day_legs.append(leg)

                current_lat, current_lng = dest_lat, dest_lng
                current_name = act_name

                sim_points.append({
                    "name": act_name, "lat": dest_lat, "lng": dest_lng,
                    "type": "activity", "day": day,
                })

            # ── Return to hotel ──────────────────────────────────────────────
            dist_to_hotel = self._haversine(current_lat, current_lng, hotel_lat, hotel_lng)
            if dist_to_hotel > 0.1:
                if has_own_car:
                    dist_to_car = self._haversine(current_lat, current_lng, car_parked_lat, car_parked_lng)
                    if dist_to_car > 0.1:
                        walk_leg = self._make_leg(
                            current_name, current_lat, current_lng,
                            "Parked Car", car_parked_lat, car_parked_lng,
                            "walk", "🚶 Walk to car", 0,
                        )
                        day_legs.append(walk_leg)
                        dist_to_hotel = self._haversine(car_parked_lat, car_parked_lng, hotel_lat, hotel_lng)
                        current_lat, current_lng = car_parked_lat, car_parked_lng
                        current_name = "Parked Car"

                    fuel_est = calculate_driving_cost(dist_to_hotel, round_trip=False, vehicle_type=vehicle_type)
                    cost = fuel_est["cost_one_way"]
                    day_driving_cost += cost
                    leg = self._make_leg(
                        current_name, current_lat, current_lng,
                        hotel_name, hotel_lat, hotel_lng,
                        "drive", "🚗 Drive back to Hotel", cost,
                    )
                    day_legs.append(leg)
                else:
                    taxi_cost = 10 + (dist_to_hotel * 2.5)
                    day_taxi_cost += taxi_cost
                    leg = self._make_leg(
                        current_name, current_lat, current_lng,
                        hotel_name, hotel_lat, hotel_lng,
                        "taxi", "🚕 Taxi back to Hotel", taxi_cost,
                    )
                    day_legs.append(leg)

            sim_points.append({
                "name": hotel_name, "lat": hotel_lat, "lng": hotel_lng,
                "type": "hotel_return", "day": day,
            })
            
            # If Last Day, add the Inter-city leg from Destination to Origin
            if day == int(list(daily_activities.keys())[-1]):
                from config import CITY_COORDS
                origin_coords = CITY_COORDS.get(origin.lower(), {"lat": 24.7, "lng": 46.7})
                
                return_leg = {
                    "from_name": hotel_name,
                    "from_lat": hotel_lat,
                    "from_lng": hotel_lng,
                    "to_name": origin.title(),
                    "to_lat": origin_coords["lat"],
                    "to_lng": origin_coords["lng"],
                    "mode": f"{'🚗' if travel_mode == 'car' else '✈️'} Return",
                    "dist": inter_city_est.distance_km,
                    "time_minutes": inter_city_est.travel_time_minutes,
                    "cost": inter_city_est.cost_one_way,
                    "type": "inter_city"
                }
                day_legs.append(return_leg)
                full_trip_dataset.append(return_leg)
                sim_points.append({
                    "name": origin.title(),
                    "lat": origin_coords["lat"],
                    "lng": origin_coords["lng"],
                    "type": "origin_return",
                    "day": day,
                })

            # Add daily legs to full dataset
            for leg in day_legs:
                if leg not in full_trip_dataset:
                    full_trip_dataset.append(leg)

            # Car rental recommendation
            rent_car_cost_per_day = 120
            recommendation = ""
            if not has_own_car and day_taxi_cost > rent_car_cost_per_day:
                recommendation = (
                    f"💡 Tip: You spent {day_taxi_cost:.0f} SAR on transport today. "
                    f"Renting a car (~{rent_car_cost_per_day} SAR/day) would be cheaper!"
                )

            day_cost = day_driving_cost if has_own_car else day_taxi_cost
            total_transit_cost += day_cost

            timeline[day_str] = {
                "legs": day_legs,
                "day_cost": round(day_cost, 2),
                "recommendation": recommendation,
            }
            simulation_routes[day_str] = sim_points

        # Get travel time from first leg of full_trip_dataset if available
        travel_time_str = ""
        if full_trip_dataset:
            first_leg = full_trip_dataset[0]
            if first_leg.get("type") == "inter_city":
                hrs = first_leg['time_minutes'] // 60
                mins = first_leg['time_minutes'] % 60
                travel_time_str = f"{hrs}h {mins}m"

        return {
            "action": "plan_timeline",
            "status": "success",
            "timeline": timeline,
            "total_transit_cost": round(total_transit_cost, 2),
            "simulation_routes": simulation_routes,
            "full_trip_dataset": full_trip_dataset,
            "inter_city_travel_time_str": travel_time_str
        }
