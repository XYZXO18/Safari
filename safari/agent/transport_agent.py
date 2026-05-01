"""
Transport Agent (Agent 3)
==========================
Handles all transportation planning: route calculation, cost estimation,
and travel mode recommendations based on budget and schedule.

Wraps the existing transport & fuel tools into an agent interface
that communicates with the Orchestrator.
"""

from __future__ import annotations

import json
import math
from typing import Optional

import requests

from config import OLLAMA_URL, OLLAMA_MODEL, ROUTES
from safari.tools.transport import calculate_transport_costs, TransportEstimate
from safari.tools.fuel import calculate_driving_cost


TRANSPORT_SYSTEM_PROMPT = """You are the **Transport & Logistics Agent** for the Safari travel system.

## Your Role
You handle all transportation planning: calculating routes, costs, and recommending
the best travel mode based on the user's budget and schedule.

## Capabilities
- Calculate driving costs (fuel prices from local database)
- Estimate flight, train, and bus costs
- Compare transport modes for the same route
- Recommend the cheapest or fastest option
- Provide route breakdowns with per-km costs

## Rules
1. Use ONLY the data from your transport database
2. Always show: distance, cost_one_way, cost_round_trip
3. Include fuel breakdown for driving (fuel type, L consumed, price/L)
4. Output structured data for the Orchestrator
"""


class TransportAgent:
    """
    Agent 3: Transport & Logistics Agent.
    Processes transport-related requests.
    """

    def __init__(self):
        self.ollama_url = OLLAMA_URL
        self.model = OLLAMA_MODEL

    def process_request(self, request: dict) -> dict:
        """
        Process a transport request.

        Supported actions:
          - calculate_route: Get cost for a specific mode + route
          - compare_modes: Compare all modes for the same route
          - get_routes: List available routes
        """
        action = request.get("action", "").lower()

        if action == "plan_timeline":
            return self._handle_timeline(request)

        if action == "calculate_route":
            return self._handle_calculate(request)
        elif action == "compare_modes":
            return self._handle_compare(request)
        elif action == "get_routes":
            return self._handle_routes(request)
        else:
            return {"error": f"Unknown transport action: {action}"}

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
                comparisons.append({
                    "mode": est.mode,
                    "distance_km": est.distance_km,
                    "cost_one_way": est.cost_one_way,
                    "cost_round_trip": est.cost_round_trip,
                    "breakdown": est.breakdown,
                })
            except Exception:
                continue

        # Sort by cost
        comparisons.sort(key=lambda x: x["cost_round_trip"])
        cheapest = comparisons[0]["mode"] if comparisons else "unknown"

        return {
            "action": "compare_modes",
            "origin": origin,
            "destination": destination,
            "modes": comparisons,
            "cheapest": cheapest,
            "recommendation": f"The cheapest option is {cheapest} "
                            f"at {comparisons[0]['cost_round_trip']:.0f} SAR round-trip" if comparisons else "No routes available",
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

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _handle_timeline(self, req: dict) -> dict:
        daily_activities = req.get("daily_activities", {})
        hotel = req.get("hotel", {})
        travel_mode = req.get("travel_mode", "flight")

        hotel_lat = hotel.get("lat", 0)
        hotel_lng = hotel.get("lng", 0)

        timeline = {}
        total_transit_cost = 0

        for day_str, acts in daily_activities.items():
            day = int(day_str)
            day_timeline = []
            
            # Start at hotel
            current_lat, current_lng = hotel_lat, hotel_lng
            
            # Car tracking
            has_own_car = (travel_mode == "car")
            car_parked_at = (hotel_lat, hotel_lng) if has_own_car else None
            
            day_taxi_cost = 0
            day_driving_cost = 0

            for i, act in enumerate(acts):
                dest_lat = act.get("lat", current_lat)
                dest_lng = act.get("lng", current_lng)
                
                dist = self._haversine(current_lat, current_lng, dest_lat, dest_lng)
                
                if dist < 0.1:
                    continue  # Already there
                    
                mode_used = ""
                cost = 0

                if dist < 1.0:
                    mode_used = "walk"
                    cost = 0
                    day_timeline.append({"from": "Current", "to": act["name"], "mode": "🚶 Walk", "dist": dist, "cost": 0})
                    current_lat, current_lng = dest_lat, dest_lng
                else:
                    if has_own_car:
                        # Need to get to car if we walked away from it
                        dist_to_car = self._haversine(current_lat, current_lng, car_parked_at[0], car_parked_at[1])
                        if dist_to_car > 0.1:
                            day_timeline.append({"from": "Current", "to": "Parked Car", "mode": "🚶 Walk back to car", "dist": dist_to_car, "cost": 0})
                            current_lat, current_lng = car_parked_at[0], car_parked_at[1]
                            dist = self._haversine(current_lat, current_lng, dest_lat, dest_lng) # Recalculate dist from car
                        
                        # Drive
                        fuel_est = calculate_driving_cost(dist, round_trip=False)
                        cost = fuel_est["cost_one_way"]
                        day_driving_cost += cost
                        mode_used = "drive"
                        day_timeline.append({"from": "Current", "to": act["name"], "mode": "🚗 Drive (Banzin Cost)", "dist": dist, "cost": cost})
                        car_parked_at = (dest_lat, dest_lng)
                        current_lat, current_lng = dest_lat, dest_lng
                    else:
                        # Taxi vs Public Transport
                        public_dist = dist * 1.5 # Public transport is usually less direct
                        public_cost = 5 + (public_dist * 0.5) # Base fare + 0.5 SAR/km
                        taxi_cost = 10 + (dist * 2.5) # Base fare + 2.5 SAR/km
                        
                        if public_cost < taxi_cost and dist > 3.0:
                            mode_used = "public"
                            cost = public_cost
                            day_timeline.append({"from": "Current", "to": act["name"], "mode": "🚌 Public Transport", "dist": dist, "cost": cost})
                        else:
                            mode_used = "taxi"
                            cost = taxi_cost
                            day_timeline.append({"from": "Current", "to": act["name"], "mode": "🚕 Taxi", "dist": dist, "cost": cost})
                        
                        day_taxi_cost += cost
                        current_lat, current_lng = dest_lat, dest_lng

            # Return to hotel
            dist_to_hotel = self._haversine(current_lat, current_lng, hotel_lat, hotel_lng)
            if dist_to_hotel > 0.1:
                if has_own_car:
                    dist_to_car = self._haversine(current_lat, current_lng, car_parked_at[0], car_parked_at[1])
                    if dist_to_car > 0.1:
                        day_timeline.append({"from": "Current", "to": "Parked Car", "mode": "🚶 Walk back to car", "dist": dist_to_car, "cost": 0})
                        dist_to_hotel = self._haversine(car_parked_at[0], car_parked_at[1], hotel_lat, hotel_lng)
                    
                    fuel_est = calculate_driving_cost(dist_to_hotel, round_trip=False)
                    cost = fuel_est["cost_one_way"]
                    day_driving_cost += cost
                    day_timeline.append({"from": "Current", "to": "Hotel", "mode": "🚗 Drive back to Hotel", "dist": dist_to_hotel, "cost": cost})
                else:
                    taxi_cost = 10 + (dist_to_hotel * 2.5)
                    day_taxi_cost += taxi_cost
                    day_timeline.append({"from": "Current", "to": "Hotel", "mode": "🚕 Taxi back to Hotel", "dist": dist_to_hotel, "cost": taxi_cost})

            # Check if renting a car is cheaper
            rent_car_cost_per_day = 120 # SAR
            recommendation = ""
            if not has_own_car and day_taxi_cost > rent_car_cost_per_day:
                recommendation = f"💡 Tip: You spent {day_taxi_cost:.0f} SAR on transport today. Renting a car (~{rent_car_cost_per_day} SAR/day) would be cheaper!"
            
            timeline[day_str] = {
                "legs": day_timeline,
                "day_cost": day_taxi_cost if not has_own_car else day_driving_cost,
                "recommendation": recommendation
            }
            total_transit_cost += timeline[day_str]["day_cost"]

        return {
            "action": "plan_timeline",
            "status": "success",
            "timeline": timeline,
            "total_transit_cost": total_transit_cost
        }
