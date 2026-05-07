"""
Test Suite — Live Agent 2 & Agent 3
=====================================
Tests schema validation, tool function contracts, and agent hand-off flow.
Uses mocked HTTP responses so tests run offline without real API keys.

Run with:
    python -m pytest test_live_agents.py -v
  or standalone:
    python test_live_agents.py
"""

from __future__ import annotations

import json
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Make root importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from safari.agent.schemas import (
    HospitalityInput, HospitalityOutput, VenueStub,
    DistanceInput, DistanceOutput, GeolocatedVenue,
    FlightPricing, CarRentalPricing, TravelCosts, TripDates,
)


# ─── Schema Tests ─────────────────────────────────────────────────────────────

class TestSchemas(unittest.TestCase):

    def test_hospitality_input_valid(self):
        h = HospitalityInput(city="Jeddah", budget_per_night=600.0)
        self.assertEqual(h.city, "Jeddah")
        self.assertEqual(h.currency, "SAR")

    def test_hospitality_input_rejects_zero_budget(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            HospitalityInput(city="Jeddah", budget_per_night=0)

    def test_venue_stub_rating_clamp(self):
        v = VenueStub(name="Test Hotel", type="hotel", price=500, rating=5.9)
        self.assertEqual(v.rating, 5.0)

    def test_venue_stub_null_coords(self):
        v = VenueStub(name="Rosewood Jeddah", type="hotel", price=580)
        self.assertIsNone(v.lat)
        self.assertIsNone(v.lng)

    def test_hospitality_output_serializable(self):
        out = HospitalityOutput(
            city="Jeddah",
            venues=[VenueStub(name="Hotel A", type="hotel", price=400)],
            search_timestamp="2026-01-01T12:00:00",
        )
        d = out.model_dump()
        self.assertEqual(d["city"], "Jeddah")
        self.assertEqual(len(d["venues"]), 1)
        self.assertIsNone(d["venues"][0]["lat"])

    def test_distance_input_from_hospitality_output(self):
        """Agent 2's venue stubs flow into Agent 3's input without errors."""
        venue = VenueStub(name="Al Shallal", type="restaurant", price=75)
        inp = DistanceInput(
            venues=[venue],
            origin="Riyadh",
            destination="Jeddah",
            travel_mode="flight",
            trip_dates=TripDates(start="2026-06-01", end="2026-06-04"),
        )
        self.assertEqual(inp.destination, "Jeddah")
        self.assertEqual(inp.venues[0].name, "Al Shallal")

    def test_distance_output_structure(self):
        out = DistanceOutput(
            origin="Riyadh",
            destination="Jeddah",
            geolocated_venues=[
                GeolocatedVenue(name="Rosewood", type="hotel", lat=21.52, lng=39.17,
                                road_distance_km=0, drive_time_minutes=0)
            ],
            travel_costs=TravelCosts(
                flight=FlightPricing(origin="Riyadh", destination="Jeddah",
                                     price_one_way=350, price_round_trip=640,
                                     source="gemini_grounding"),
                car_rental=CarRentalPricing(city="Jeddah", price_per_day=120,
                                            source="fallback_estimate"),
            ),
        )
        d = out.model_dump()
        self.assertEqual(d["geolocated_venues"][0]["lat"], 21.52)
        self.assertEqual(d["travel_costs"]["flight"]["price_one_way"], 350)
        self.assertEqual(d["travel_costs"]["car_rental"]["price_per_day"], 120)


# ─── Tool Tests (Mocked) ──────────────────────────────────────────────────────

class TestLiveHospitalityTools(unittest.TestCase):

    @patch("safari.tools.live_hospitality._gemini_search_venues")
    def test_search_hotels_uses_gemini_first(self, mock_gemini):
        mock_gemini.return_value = [
            VenueStub(name="Hilton Jeddah", type="hotel", price=490, rating=4.5)
        ]
        from safari.tools.live_hospitality import search_hotels_live
        results = search_hotels_live(city="Jeddah", budget_per_night=600)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Hilton Jeddah")
        mock_gemini.assert_called_once()

    @patch("safari.tools.live_hospitality._gemini_search_venues", return_value=[])
    @patch("safari.tools.live_hospitality._ddg_search_venues")
    def test_search_hotels_falls_back_to_ddg(self, mock_ddg, mock_gemini):
        mock_ddg.return_value = [
            VenueStub(name="Budget Hotel", type="hotel", price=200, rating=3.5)
        ]
        from safari.tools.live_hospitality import search_hotels_live
        results = search_hotels_live(city="Jeddah", budget_per_night=600)
        self.assertEqual(results[0].name, "Budget Hotel")
        mock_ddg.assert_called_once()

    @patch("safari.tools.live_hospitality._gemini_search_venues", return_value=[])
    @patch("safari.tools.live_hospitality._ddg_search_venues", return_value=[])
    @patch("safari.tools.live_hospitality._fallback_db_venues")
    def test_search_hotels_falls_back_to_db(self, mock_db, mock_ddg, mock_gemini):
        mock_db.return_value = [
            VenueStub(name="DB Hotel", type="hotel", price=300, lat=21.48, lng=39.19)
        ]
        from safari.tools.live_hospitality import search_hotels_live
        results = search_hotels_live(city="Jeddah", budget_per_night=600)
        self.assertEqual(results[0].name, "DB Hotel")
        self.assertEqual(results[0].lat, 21.48)  # DB has coords
        mock_db.assert_called_once()


class TestLiveDistanceTools(unittest.TestCase):

    @patch("safari.tools.live_distance.geocode_nominatim")
    def test_geocode_nominatim_success(self, mock_nom):
        mock_nom.return_value = (21.5234, 39.1731)
        from safari.tools.live_distance import geocode_venues
        stubs = [VenueStub(name="Rosewood Jeddah", type="hotel", price=580)]
        result = geocode_venues(stubs, "Jeddah")
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].lat, 21.5234, places=3)
        self.assertEqual(result[0].geocode_source, "nominatim")

    @patch("safari.tools.live_distance.geocode_nominatim", return_value=None)
    @patch("safari.tools.live_distance.geocode_gemini")
    def test_geocode_falls_back_to_gemini(self, mock_gem, mock_nom):
        mock_gem.return_value = (21.5100, 39.1800)
        from safari.tools.live_distance import geocode_venues
        stubs = [VenueStub(name="Some Cafe", type="cafe", price=30)]
        result = geocode_venues(stubs, "Jeddah")
        self.assertEqual(result[0].geocode_source, "gemini")
        self.assertAlmostEqual(result[0].lat, 21.51, places=2)

    @patch("requests.get")
    def test_osrm_road_distance(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": "Ok",
            "routes": [{"distance": 12400, "duration": 1080}]  # 12.4km, 18min
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from safari.tools.live_distance import get_road_distance_osrm
        result = get_road_distance_osrm(21.48, 39.19, 21.52, 39.17)
        self.assertIsNotNone(result)
        self.assertEqual(result["distance_km"], 12.4)
        self.assertEqual(result["duration_minutes"], 18)
        self.assertEqual(result["source"], "osrm")

    @patch("requests.get", side_effect=Exception("Network error"))
    def test_road_distance_haversine_fallback(self, mock_get):
        from safari.tools.live_distance import get_road_distance
        result = get_road_distance(21.48, 39.19, 21.52, 39.17)
        self.assertIn("distance_km", result)
        self.assertEqual(result["source"], "haversine_corrected")

    @patch("safari.tools.live_distance.search_flight_prices", return_value=None)
    def test_flight_search_fallback_triggered(self, mock_live):
        from safari.tools.live_distance import search_flight_prices_fallback
        result = search_flight_prices_fallback("Riyadh", "Jeddah")
        self.assertIsInstance(result, FlightPricing)
        self.assertGreater(result.price_one_way, 0)
        self.assertEqual(result.source, "fallback_estimate")


# ─── Agent Integration Tests ──────────────────────────────────────────────────

class TestAgentHandoff(unittest.TestCase):

    @patch("safari.tools.live_hospitality.search_hotels_live")
    @patch("safari.tools.live_hospitality.search_restaurants_live")
    @patch("safari.tools.live_hospitality.search_cafes_live")
    def test_agent2_phase1_returns_no_coords(self, mock_cafes, mock_rests, mock_hotels):
        """Agent 2 must return venues with lat=None (coordinates to be filled by Agent 3)."""
        mock_hotels.return_value = [VenueStub(name="Hilton Jeddah", type="hotel", price=490, rating=4.5)]
        mock_rests.return_value = [VenueStub(name="Al Baik", type="restaurant", price=35, rating=4.8)]
        mock_cafes.return_value = []

        from safari.agent.worker_hospitality_live import HospitalityWorker
        agent2 = HospitalityWorker()
        result = agent2.phase1_scrape(HospitalityInput(city="Jeddah", budget_per_night=600))

        self.assertIsInstance(result, HospitalityOutput)
        for venue in result.venues:
            self.assertIsNone(venue.lat, f"{venue.name} should have lat=None from Agent 2")
            self.assertIsNone(venue.lng, f"{venue.name} should have lng=None from Agent 2")

    @patch("safari.tools.live_distance.geocode_nominatim")
    @patch("time.sleep")  # skip sleep in tests
    def test_agent3_phase1_fills_coords(self, mock_sleep, mock_nom):
        """Agent 3 must fill in lat/lng for every venue stub."""
        mock_nom.return_value = (21.5234, 39.1731)

        from safari.agent.worker_transport_live import TransportWorker
        agent3 = TransportWorker()
        stubs = [
            VenueStub(name="Hilton Jeddah", type="hotel", price=490),
            VenueStub(name="Al Baik", type="restaurant", price=35),
        ]
        geolocated = agent3.phase1_geolocate(stubs, "Jeddah")

        self.assertEqual(len(geolocated), 2)
        for v in geolocated:
            self.assertIsNotNone(v.lat)
            self.assertIsNotNone(v.lng)

    @patch("safari.tools.live_distance.search_flight_prices", return_value=None)
    @patch("safari.tools.live_distance.search_car_rental_prices", return_value=None)
    def test_agent3_phase2_uses_fallbacks(self, mock_car, mock_flight):
        """Agent 3 Phase 2 must always return a TravelCosts object, even if live search fails."""
        from safari.agent.worker_transport_live import TransportWorker
        agent3 = TransportWorker()
        costs = agent3.phase2_travel_costs(origin="Riyadh", destination="Jeddah", travel_mode="flight")

        self.assertIsNotNone(costs.flight)
        self.assertIsNotNone(costs.car_rental)
        self.assertGreater(costs.flight.price_one_way, 0)
        self.assertGreater(costs.car_rental.price_per_day, 0)

    @patch("safari.agent.worker_hospitality_live.search_hotels_live")
    @patch("safari.agent.worker_hospitality_live.search_restaurants_live")
    @patch("safari.agent.worker_hospitality_live.search_cafes_live")
    @patch("safari.tools.live_distance.geocode_nominatim")
    @patch("safari.tools.live_distance.search_flight_prices", return_value=None)
    @patch("safari.tools.live_distance.search_car_rental_prices", return_value=None)
    @patch("time.sleep")
    def test_full_two_phase_handoff(
        self, mock_sleep, mock_car, mock_flight,
        mock_nom, mock_cafes, mock_rests, mock_hotels
    ):
        """
        End-to-end schema contract test:
        Agent 2 Phase 1 output → Agent 3 Phase 1 input → Agent 3 Phase 2
        Verifies the full hand-off chain without network calls.
        """
        mock_hotels.return_value = [VenueStub(name="Hilton Jeddah", type="hotel", price=490, rating=4.5)]
        mock_rests.return_value = [VenueStub(name="Al Baik", type="restaurant", price=35)]
        mock_cafes.return_value = [VenueStub(name="Peet's Coffee", type="cafe", price=25)]
        mock_nom.return_value = (21.5234, 39.1731)

        from safari.agent.worker_hospitality_live import HospitalityWorker
        from safari.agent.worker_transport_live import TransportWorker

        # PHASE A: Agent 2
        agent2 = HospitalityWorker()
        hosp_out = agent2.phase1_scrape(HospitalityInput(city="Jeddah", budget_per_night=600))
        self.assertEqual(len(hosp_out.venues), 3)

        # Confirm no coords yet
        for v in hosp_out.venues:
            self.assertIsNone(v.lat)

        # PHASE B: Agent 3 geolocate
        agent3 = TransportWorker()
        geolocated = agent3.phase1_geolocate(hosp_out.venues, "Jeddah")
        self.assertEqual(len(geolocated), 3)

        # Confirm coords are filled
        for v in geolocated:
            self.assertIsNotNone(v.lat)
            self.assertIsNotNone(v.lng)

        # PHASE C: Agent 3 travel costs
        costs = agent3.phase2_travel_costs("Riyadh", "Jeddah", "flight")
        self.assertIsNotNone(costs.flight)
        self.assertIsNotNone(costs.car_rental)

        print("\n[PASS] Full two-phase hand-off test passed!")
        print(f"   Hotels: {[v.name for v in geolocated if v.type=='hotel']}")
        print(f"   Flight: {costs.flight.price_one_way} SAR ({costs.flight.source})")
        print(f"   Car rental: {costs.car_rental.price_per_day} SAR/day ({costs.car_rental.source})")


# ─── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  Safari Live Agent Test Suite")
    print("=" * 60)
    unittest.main(verbosity=2)
