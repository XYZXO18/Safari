"""
Worker 3 — Live Distance & Logistics Agent
==========================================
Owns all geolocation, road distances, real routing, and live travel pricing.

NEW CAPABILITIES (vs original):
  - phase1_geolocate()  : fills venue coordinates from Agent 2 using Nominatim → Gemini
  - phase2_travel_costs(): live flight + car rental prices via Gemini Search Grounding
  - Real road distances via OSRM public API (replaces Haversine-only)
  - All existing timeline/simulation logic is preserved as fallback

DATA FLOW:
  Orchestrator → phase1_geolocate(venue_stubs) → GeolocatedVenue list
  Orchestrator → phase2_travel_costs(origin, destination) → FlightPricing + CarRentalPricing
  Orchestrator → process_request("plan_timeline") → daily legs + simulation routes (unchanged)
"""

from __future__ import annotations

import math
import logging
from typing import Optional, List, Tuple

from safari.agent.schemas import (
    DistanceInput, DistanceOutput,
    GeolocatedVenue, VenueStub,
    FlightPricing, CarRentalPricing, TravelCosts
)
from safari.tools.live_distance import (
    geocode_venues,
    search_flight_prices,
    search_flight_prices_fallback,
    search_car_rental_prices,
    search_car_rental_fallback,
    get_road_distance,
)
from config import OLLAMA_URL, OLLAMA_MODEL, ROUTES

logger = logging.getLogger(__name__)


# ─── Speed Table (unchanged from original) ─────────────────────────────────
_SPEED = {
    "walk":           5,
    "drive_city":    50,
    "drive_highway": 110,
    "taxi":          55,
    "public":        35,
}


def _travel_time_minutes(dist_km: float, mode: str) -> int:
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
    return max(1, round((dist_km / speed) * 60)) if speed > 0 else 0


class TransportWorker:
    """
    Agent 3 — Live Distance & Logistics Agent.

    Two new public methods for the Orchestrator two-phase pattern:
      phase1_geolocate()   — fill coordinates for Agent 2's venue list
      phase2_travel_costs() — live flight + car-rental pricing
    
    Existing process_request() unchanged for backward compat.
    """

    def __init__(self):
        self.ollama_url = OLLAMA_URL
        self.model = OLLAMA_MODEL

    # ─── Phase 1: Geolocate Agent 2's Venues ─────────────────────────────────

    def phase1_geolocate(
        self,
        venue_stubs: List[VenueStub],
        city: str,
    ) -> List[GeolocatedVenue]:
        """
        Takes the venue stubs from Agent 2 (no coordinates) and fills in real-world
        lat/lng using Nominatim (OpenStreetMap) → Gemini Search Grounding → fallback.

        Also calculates road distances (OSRM → Haversine fallback) from the best hotel
        to each restaurant/cafe.

        Args:
            venue_stubs: List[VenueStub] from HospitalityOutput.venues
            city: The destination city string

        Returns:
            List[GeolocatedVenue] with lat, lng, road_distance_km, drive_time_minutes
        """
        logger.info(f"[TransportWorker] Phase 1 — Geolocating {len(venue_stubs)} venues in {city}")

        # Find hotel coords first (used as origin for road distances)
        hotel_coords: Optional[Tuple[float, float]] = None
        hotel_stubs = [v for v in venue_stubs if v.type == "hotel"]
        other_stubs = [v for v in venue_stubs if v.type != "hotel"]

        # Geolocate hotels first
        geolocated_hotels = geocode_venues(hotel_stubs, city, hotel_coords=None)

        # Use the first hotel as the reference point for all distance calculations
        if geolocated_hotels:
            h = geolocated_hotels[0]
            hotel_coords = (h.lat, h.lng)
            logger.info(f"  ✅ Hotel reference point: {h.name} ({h.lat:.4f}, {h.lng:.4f})")

        # Geolocate restaurants + cafes (with hotel as origin)
        geolocated_others = geocode_venues(other_stubs, city, hotel_coords=hotel_coords)

        all_geolocated = geolocated_hotels + geolocated_others

        # Summary log
        sources = {}
        for v in all_geolocated:
            sources[v.geocode_source] = sources.get(v.geocode_source, 0) + 1
        logger.info(f"  ✅ Geocoding complete. Sources: {sources}")

        return all_geolocated

    # ─── Phase 2: Live Travel Costs ───────────────────────────────────────────

    def phase2_travel_costs(
        self,
        origin: str,
        destination: str,
        travel_mode: str = "car",
        trip_dates: Optional[dict] = None,
        days: int = 3,
    ) -> TravelCosts:
        """
        Fetches live inter-city travel pricing:
          - Flights: Gemini Search Grounding → static JSON fallback
          - Car rental: Gemini Search Grounding → flat-rate fallback
          - Fuel estimate: existing calculate_driving_cost() logic (for car mode)

        Args:
            origin: Departure city
            destination: Destination city
            travel_mode: "car" | "flight" | "train" | "bus"
            trip_dates: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
            days: Number of trip days (for car rental total)

        Returns:
            TravelCosts with flight and/or car_rental populated
        """
        logger.info(f"[TransportWorker] Phase 2 — Live travel costs: {origin} → {destination} ({travel_mode})")

        flight: Optional[FlightPricing] = None
        car_rental: Optional[CarRentalPricing] = None
        fuel_estimate: Optional[dict] = None

        travel_date = trip_dates.get("start") if trip_dates else None

        # ── Flight Pricing ──────────────────────────────────────────────────
        if travel_mode == "flight":
            logger.info("  🔍 Searching live flight prices...")
            flight = search_flight_prices(origin, destination, travel_date)
            if not flight:
                logger.warning("  ⚠️ Live flight search failed — using static fallback")
                flight = search_flight_prices_fallback(origin, destination)
            logger.info(
                f"  ✅ Flight: {flight.price_one_way} {flight.currency} one-way "
                f"({flight.airline or 'Unknown'}) [{flight.source}]"
            )

        # ── Car Rental Pricing ──────────────────────────────────────────────
        # Always search car rental (useful even for flight travelers who rent on arrival)
        logger.info("  🔍 Searching live car rental prices...")
        car_rental = search_car_rental_prices(city=destination, days=days)
        if not car_rental:
            logger.warning("  ⚠️ Live car rental search failed — using flat-rate fallback")
            car_rental = search_car_rental_fallback(destination)
        logger.info(
            f"  ✅ Car rental: {car_rental.price_per_day} {car_rental.currency}/day "
            f"({car_rental.company or 'Unknown'}) [{car_rental.source}]"
        )

        # ── Fuel Estimate (for car-drive travelers) ─────────────────────────
        if travel_mode == "car":
            try:
                from safari.tools.fuel import calculate_driving_cost
                from safari.tools.transport import _lookup_distance
                dist = _lookup_distance(origin, destination)
                fuel_estimate = calculate_driving_cost(dist, round_trip=True)
                logger.info(f"  ✅ Fuel estimate: {fuel_estimate['cost_round_trip']} SAR round-trip")
            except Exception as e:
                logger.warning(f"  ⚠️ Fuel estimate failed: {e}")

        return TravelCosts(
            flight=flight,
            car_rental=car_rental,
            fuel_estimate=fuel_estimate,
        )

    # ─── Full Structured Call (for Orchestrator master plan) ──────────────────

    def run_full_logistics(self, input_data: DistanceInput) -> DistanceOutput:
        """
        Convenience method: runs Phase 1 + Phase 2 in sequence.
        Returns a complete DistanceOutput with venues + travel costs.
        """
        # Phase 1
        geolocated = self.phase1_geolocate(input_data.venues, input_data.destination)

        # Total intra-city distance
        total_intra = sum(
            v.road_distance_km for v in geolocated
            if v.road_distance_km is not None
        )

        # Phase 2
        travel_costs = self.phase2_travel_costs(
            origin=input_data.origin,
            destination=input_data.destination,
            travel_mode=input_data.travel_mode,
            trip_dates=input_data.trip_dates.model_dump() if input_data.trip_dates else None,
        )

        data_sources = list({v.geocode_source for v in geolocated})
        if travel_costs.flight:
            data_sources.append(travel_costs.flight.source)
        if travel_costs.car_rental:
            data_sources.append(travel_costs.car_rental.source)

        return DistanceOutput(
            origin=input_data.origin,
            destination=input_data.destination,
            geolocated_venues=geolocated,
            travel_costs=travel_costs,
            total_intra_city_distance_km=round(total_intra, 2),
            data_sources=data_sources,
        )

    # ─── Existing process_request() — Backward Compatible ────────────────────

    def process_request(self, request: dict) -> dict:
        """
        Original public API — fully preserved for backward compatibility.
        New actions added: geolocate_venues, get_travel_costs.
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
        # ── NEW ACTIONS ──────────────────────────────────────────────────────
        elif action == "geolocate_venues":
            return self._handle_geolocate(request)
        elif action == "get_travel_costs":
            return self._handle_travel_costs(request)
        else:
            return {"error": f"Unknown travel action: {action}"}

    def _handle_geolocate(self, req: dict) -> dict:
        """
        New action: geolocate a list of venue stubs.
        Input: {"action": "geolocate_venues", "venues": [...], "city": "Jeddah"}
        """
        raw_venues = req.get("venues", [])
        city = req.get("city", "Jeddah")

        stubs = [VenueStub(**v) if isinstance(v, dict) else v for v in raw_venues]
        geolocated = self.phase1_geolocate(stubs, city)

        return {
            "action": "geolocate_venues",
            "city": city,
            "venues": [v.model_dump() for v in geolocated],
            "count": len(geolocated),
        }

    def _handle_travel_costs(self, req: dict) -> dict:
        """
        New action: get live inter-city travel costs.
        """
        costs = self.phase2_travel_costs(
            origin=req.get("origin", "Riyadh"),
            destination=req.get("destination", "Jeddah"),
            travel_mode=req.get("travel_mode", "car"),
            trip_dates=req.get("trip_dates"),
            days=int(req.get("days", 3)),
        )
        return {
            "action": "get_travel_costs",
            "travel_costs": costs.model_dump(),
        }

    # ─── Existing Handlers (unchanged) ────────────────────────────────────────

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _make_leg(self, from_name, from_lat, from_lng, to_name, to_lat, to_lng, mode_key, mode_label, cost) -> dict:
        # Now uses OSRM for real road distances if possible
        osrm = get_road_distance(from_lat, from_lng, to_lat, to_lng)
        dist = osrm["distance_km"]
        time_mins = osrm["duration_minutes"]

        return {
            "from_name": from_name, "from_lat": from_lat, "from_lng": from_lng,
            "to_name": to_name, "to_lat": to_lat, "to_lng": to_lng,
            "mode": mode_label,
            "dist": round(dist, 2),
            "time_minutes": time_mins,
            "cost": round(cost, 2),
        }

    def _handle_calculate(self, req: dict) -> dict:
        from safari.tools.transport import calculate_transport_costs
        mode = req.get("mode", "car")
        origin = req.get("origin", "riyadh")
        destination = req.get("destination", "coast")
        vehicle_type = req.get("vehicle_type", "default")
        try:
            estimate = calculate_transport_costs(mode=mode, origin=origin, destination=destination, vehicle_type=vehicle_type)
            time_hrs = estimate.distance_km / _SPEED["drive_highway"] if mode in ("car", "driving") else estimate.distance_km / 800
            return {
                "action": "calculate_route", "status": "success",
                "transport": {
                    "mode": estimate.mode, "origin": estimate.origin, "destination": estimate.destination,
                    "distance_km": estimate.distance_km, "cost_one_way": estimate.cost_one_way,
                    "cost_round_trip": estimate.cost_round_trip,
                    "time_minutes_one_way": round(time_hrs * 60),
                    "currency": estimate.currency, "breakdown": estimate.breakdown, "summary": estimate.summary,
                },
            }
        except Exception as e:
            return {"action": "calculate_route", "status": "error", "error": str(e)}

    def _handle_compare(self, req: dict) -> dict:
        from safari.tools.transport import calculate_transport_costs
        origin = req.get("origin", "riyadh")
        destination = req.get("destination", "coast")
        comparisons = []
        for mode in ["car", "flight", "train", "bus"]:
            try:
                est = calculate_transport_costs(mode=mode, origin=origin, destination=destination)
                speed = _SPEED["drive_highway"] if mode == "car" else 800
                time_mins = round((est.distance_km / speed) * 60)
                comparisons.append({
                    "mode": est.mode, "distance_km": est.distance_km,
                    "cost_one_way": est.cost_one_way, "cost_round_trip": est.cost_round_trip,
                    "time_minutes_one_way": time_mins, "breakdown": est.breakdown,
                })
            except Exception:
                continue
        comparisons.sort(key=lambda x: x["cost_round_trip"])
        cheapest = comparisons[0]["mode"] if comparisons else "unknown"
        return {
            "action": "compare_modes", "origin": origin, "destination": destination,
            "modes": comparisons, "cheapest": cheapest,
            "recommendation": f"Cheapest: {cheapest} at {comparisons[0]['cost_round_trip']:.0f} SAR" if comparisons else "No routes",
        }

    def _handle_routes(self, req: dict) -> dict:
        routes, seen = [], set()
        for (o, d), dist in ROUTES.items():
            key = tuple(sorted([o, d]))
            if key not in seen and o != "default":
                seen.add(key)
                routes.append({"origin": o.title(), "destination": d.title(), "distance_km": dist})
        routes.sort(key=lambda x: x["distance_km"])
        return {"action": "get_routes", "routes": routes, "count": len(routes)}

    def _handle_timeline(self, req: dict) -> dict:
        """
        Existing timeline handler — unchanged in logic.
        Now uses OSRM-backed _make_leg() for real road distances.
        """
        daily_activities = req.get("daily_activities", {})
        hotel = req.get("hotel", {})
        travel_mode = req.get("travel_mode", "car")
        origin = req.get("origin", "riyadh")
        destination = req.get("destination", "coast")
        vehicle_type = req.get("vehicle_type", "default")

        hotel_lat = hotel.get("lat", 0)
        hotel_lng = hotel.get("lng", 0)
        hotel_name = hotel.get("name", "Hotel")

        has_own_car = travel_mode == "car"

        from safari.tools.transport import calculate_transport_costs
        inter_city_est = calculate_transport_costs(
            mode=travel_mode, origin=origin, destination=destination, vehicle_type=vehicle_type
        )

        timeline = {}
        simulation_routes = {}
        full_trip_dataset = []
        total_transit_cost = 0.0

        for day_str, acts in daily_activities.items():
            day = int(day_str)
            day_legs = []

            sim_points = [{"name": hotel_name, "lat": hotel_lat, "lng": hotel_lng, "type": "hotel", "day": day}]
            current_lat, current_lng, current_name = hotel_lat, hotel_lng, hotel_name

            if day == 1:
                from config import CITY_COORDS
                oc = CITY_COORDS.get(origin.lower(), {"lat": 24.7, "lng": 46.7})
                inter_leg = {
                    "from_name": origin.title(), "from_lat": oc["lat"], "from_lng": oc["lng"],
                    "to_name": hotel_name, "to_lat": hotel_lat, "to_lng": hotel_lng,
                    "mode": f"{'🚗' if travel_mode=='car' else '✈️'} Long-haul",
                    "dist": inter_city_est.distance_km, "time_minutes": inter_city_est.travel_time_minutes,
                    "cost": inter_city_est.cost_one_way, "type": "inter_city",
                }
                day_legs.append(inter_leg)
                full_trip_dataset.append(inter_leg)
                sim_points.insert(0, {"name": origin.title(), "lat": oc["lat"], "lng": oc["lng"], "type": "origin", "day": day})

            car_parked_lat, car_parked_lng, car_parked_name = hotel_lat, hotel_lng, hotel_name
            day_taxi_cost = 0.0
            day_driving_cost = 0.0

            for act in acts:
                dest_lat = act.get("lat", current_lat)
                dest_lng = act.get("lng", current_lng)
                act_name = act.get("name", "Stop")

                dist = self._haversine(current_lat, current_lng, dest_lat, dest_lng)
                if dist < 0.05:
                    sim_points.append({"name": act_name, "lat": dest_lat, "lng": dest_lng, "type": "activity", "day": day})
                    continue

                if dist < 1.0:
                    leg = self._make_leg(current_name, current_lat, current_lng, act_name, dest_lat, dest_lng, "walk", "🚶 Walk", 0)
                    day_legs.append(leg)
                elif has_own_car:
                    dist_to_car = self._haversine(current_lat, current_lng, car_parked_lat, car_parked_lng)
                    if dist_to_car > 0.1:
                        wl = self._make_leg(current_name, current_lat, current_lng, "Parked Car", car_parked_lat, car_parked_lng, "walk", "🚶 Walk to car", 0)
                        day_legs.append(wl)
                        current_lat, current_lng, current_name = car_parked_lat, car_parked_lng, "Parked Car"
                    from safari.tools.fuel import calculate_driving_cost
                    drive_dist = self._haversine(current_lat, current_lng, dest_lat, dest_lng)
                    fuel_est = calculate_driving_cost(drive_dist, round_trip=False, vehicle_type=vehicle_type)
                    cost = fuel_est["cost_one_way"]
                    day_driving_cost += cost
                    leg = self._make_leg(current_name, current_lat, current_lng, act_name, dest_lat, dest_lng, "drive", "🚗 Drive", cost)
                    day_legs.append(leg)
                    car_parked_lat, car_parked_lng, car_parked_name = dest_lat, dest_lng, act_name
                else:
                    public_cost = 5 + (dist * 1.5 * 0.5)
                    taxi_cost = 10 + (dist * 2.5)
                    if public_cost < taxi_cost and dist > 3.0:
                        leg = self._make_leg(current_name, current_lat, current_lng, act_name, dest_lat, dest_lng, "public", "🚌 Public Transport", public_cost)
                        day_taxi_cost += public_cost
                    else:
                        leg = self._make_leg(current_name, current_lat, current_lng, act_name, dest_lat, dest_lng, "taxi", "🚕 Taxi", taxi_cost)
                        day_taxi_cost += taxi_cost
                    day_legs.append(leg)

                current_lat, current_lng, current_name = dest_lat, dest_lng, act_name
                sim_points.append({"name": act_name, "lat": dest_lat, "lng": dest_lng, "type": "activity", "day": day})

            dist_to_hotel = self._haversine(current_lat, current_lng, hotel_lat, hotel_lng)
            if dist_to_hotel > 0.1:
                if has_own_car:
                    from safari.tools.fuel import calculate_driving_cost
                    dist_to_car = self._haversine(current_lat, current_lng, car_parked_lat, car_parked_lng)
                    if dist_to_car > 0.1:
                        wl = self._make_leg(current_name, current_lat, current_lng, "Parked Car", car_parked_lat, car_parked_lng, "walk", "🚶 Walk to car", 0)
                        day_legs.append(wl)
                        dist_to_hotel = self._haversine(car_parked_lat, car_parked_lng, hotel_lat, hotel_lng)
                        current_lat, current_lng, current_name = car_parked_lat, car_parked_lng, "Parked Car"
                    fuel_est = calculate_driving_cost(dist_to_hotel, round_trip=False, vehicle_type=vehicle_type)
                    cost = fuel_est["cost_one_way"]
                    day_driving_cost += cost
                    leg = self._make_leg(current_name, current_lat, current_lng, hotel_name, hotel_lat, hotel_lng, "drive", "🚗 Drive back to Hotel", cost)
                    day_legs.append(leg)
                else:
                    taxi_cost = 10 + (dist_to_hotel * 2.5)
                    day_taxi_cost += taxi_cost
                    leg = self._make_leg(current_name, current_lat, current_lng, hotel_name, hotel_lat, hotel_lng, "taxi", "🚕 Taxi back to Hotel", taxi_cost)
                    day_legs.append(leg)

            sim_points.append({"name": hotel_name, "lat": hotel_lat, "lng": hotel_lng, "type": "hotel_return", "day": day})

            if day == int(list(daily_activities.keys())[-1]):
                from config import CITY_COORDS
                oc = CITY_COORDS.get(origin.lower(), {"lat": 24.7, "lng": 46.7})
                return_leg = {
                    "from_name": hotel_name, "from_lat": hotel_lat, "from_lng": hotel_lng,
                    "to_name": origin.title(), "to_lat": oc["lat"], "to_lng": oc["lng"],
                    "mode": f"{'🚗' if travel_mode=='car' else '✈️'} Return",
                    "dist": inter_city_est.distance_km, "time_minutes": inter_city_est.travel_time_minutes,
                    "cost": inter_city_est.cost_one_way, "type": "inter_city",
                }
                day_legs.append(return_leg)
                full_trip_dataset.append(return_leg)

            for leg in day_legs:
                if leg not in full_trip_dataset:
                    full_trip_dataset.append(leg)

            rent_car_cost_per_day = 120
            recommendation = ""
            if not has_own_car and day_taxi_cost > rent_car_cost_per_day:
                recommendation = f"💡 Tip: You spent {day_taxi_cost:.0f} SAR on transport today. Renting a car (~{rent_car_cost_per_day} SAR/day) would be cheaper!"

            day_cost = day_driving_cost if has_own_car else day_taxi_cost
            total_transit_cost += day_cost

            timeline[day_str] = {"legs": day_legs, "day_cost": round(day_cost, 2), "recommendation": recommendation}
            simulation_routes[day_str] = sim_points

        travel_time_str = ""
        if full_trip_dataset and full_trip_dataset[0].get("type") == "inter_city":
            fl = full_trip_dataset[0]
            hrs = fl["time_minutes"] // 60
            mins = fl["time_minutes"] % 60
            travel_time_str = f"{hrs}h {mins}m"

        return {
            "action": "plan_timeline", "status": "success",
            "timeline": timeline,
            "total_transit_cost": round(total_transit_cost, 2),
            "simulation_routes": simulation_routes,
            "full_trip_dataset": full_trip_dataset,
            "inter_city_travel_time_str": travel_time_str,
        }
