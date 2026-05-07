"""
Orchestrator Agent — Live Web Edition
=======================================
Shows the updated plan_trip() two-phase hand-off between:
  Agent 2 (HospitalityWorker Live) → Agent 3 (TransportWorker Live)

This file shows only the modified section of the Orchestrator.
Drop-in replacement for the relevant block in orchestrator_agent.py.

TWO-PHASE PATTERN:
  Phase A: Agent 2 scrapes venue NAMES + PRICES (no coordinates)
  Phase B: Agent 3 geolocates those venues → fills lat/lng
  Phase C: Agent 3 fetches live flight + car rental prices
  Phase D: Orchestrator merges all data into master JSON → LLM
"""

from __future__ import annotations

import logging
from typing import List, Optional

from safari.agent.schemas import (
    HospitalityInput, HospitalityOutput,
    DistanceInput, DistanceOutput,
    VenueStub, TripDates,
)
from safari.agent.worker_hospitality_live import HospitalityWorker
from safari.agent.worker_transport_live import TransportWorker

logger = logging.getLogger(__name__)


def plan_trip_live(
    orchestrator,           # The existing OrchestratorAgent instance
    request,                # TripRequest from input_parser
    research_res: dict,     # Already collected from Worker 1 (unchanged)
    transport_est,          # Already calculated from calculate_transport_costs()
    breakdown,              # Already calculated from budget_allocator()
) -> dict:
    """
    Updated plan_trip() block — the live two-phase Agent 2 ↔ Agent 3 hand-off.

    This replaces lines 87-156 in the existing orchestrator_agent.py.
    Agent 1 (Research) output is passed in unchanged.

    Returns merged hospitality + logistics JSON dict ready for LLM synthesis.
    """

    # ── Resolve city name from vibe ─────────────────────────────────────────
    from config import DESTINATIONS
    vibe = research_res.get("vibe", "coast")
    dest_info = research_res.get("dest_info", DESTINATIONS.get(vibe, {}))
    cities = dest_info.get("cities", [request.destination.title()])
    scan_city = cities[0]  # Primary city, e.g. "Jeddah"

    agent2 = HospitalityWorker()
    agent3 = TransportWorker()

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE A — Agent 2: Scrape real venue names + prices (NO coordinates)
    # ═══════════════════════════════════════════════════════════════════════
    from rich.console import Console
    console = Console(force_terminal=True)
    console.print(
        "  [bold yellow]🏨 Orchestrator → Agent 2 (Hospitality): "
        "Live web scrape for venues...[/bold yellow]"
    )

    hospitality_input = HospitalityInput(
        city=scan_city,
        budget_per_night=breakdown.lodging_per_day,
        currency=request.currency,
        interests=request.interests.split(",") if request.interests else [],
        allergens=getattr(request, "allergens", []),
        max_results=6,
    )

    phase_a: HospitalityOutput = agent2.phase1_scrape(hospitality_input)

    # Budget filter: remove hotels that are over budget
    venue_stubs: List[VenueStub] = []
    for v in phase_a.venues:
        if v.type == "hotel" and v.price > breakdown.lodging_per_day * 1.3:
            logger.debug(f"Dropping {v.name} (price {v.price} > budget {breakdown.lodging_per_day})")
            continue
        venue_stubs.append(v)

    console.print(
        f"  [dim]↳ Agent 2 found {len([v for v in venue_stubs if v.type=='hotel'])} hotels, "
        f"{len([v for v in venue_stubs if v.type=='restaurant'])} restaurants, "
        f"{len([v for v in venue_stubs if v.type=='cafe'])} cafes "
        f"[{phase_a.data_source}][/dim]"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE B — Agent 3: Geolocate Agent 2's venues (fill lat/lng)
    # ═══════════════════════════════════════════════════════════════════════
    console.print(
        "  [bold blue]📍 Orchestrator → Agent 3 (Logistics): "
        "Geolocating venues...[/bold blue]"
    )

    geolocated_venues = agent3.phase1_geolocate(venue_stubs, scan_city)

    # Merge coordinates back into venue stubs
    coord_map = {v.name: (v.lat, v.lng) for v in geolocated_venues}
    for stub in venue_stubs:
        if stub.name in coord_map:
            stub.lat, stub.lng = coord_map[stub.name]

    console.print(
        f"  [dim]↳ Agent 3 geolocated {len(geolocated_venues)} venues "
        f"(sources: {list({v.geocode_source for v in geolocated_venues})})[/dim]"
    )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE C — Agent 3: Live flight + car rental prices
    # ═══════════════════════════════════════════════════════════════════════
    console.print(
        "  [bold blue]✈️  Orchestrator → Agent 3 (Logistics): "
        "Live travel prices...[/bold blue]"
    )

    travel_costs = agent3.phase2_travel_costs(
        origin=request.origin,
        destination=scan_city,
        travel_mode=request.travel_mode,
        trip_dates={"start": request.start_date, "end": request.end_date},
        days=request.days,
    )

    if travel_costs.flight:
        console.print(
            f"  [dim]↳ Flight: {travel_costs.flight.price_one_way} {travel_costs.flight.currency} "
            f"one-way ({travel_costs.flight.airline or 'Unknown'}) "
            f"[{travel_costs.flight.source}][/dim]"
        )
    if travel_costs.car_rental:
        console.print(
            f"  [dim]↳ Car rental: {travel_costs.car_rental.price_per_day} {travel_costs.car_rental.currency}/day "
            f"({travel_costs.car_rental.company or 'Unknown'}) "
            f"[{travel_costs.car_rental.source}][/dim]"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE D — Agent 3: Daily timeline (existing logic, now with real coords)
    # ═══════════════════════════════════════════════════════════════════════
    console.print(
        "  [bold blue]🗺️  Orchestrator → Agent 3 (Logistics): "
        "Building daily route timeline...[/bold blue]"
    )

    activities = research_res["activities"]

    # Best hotel from live data (has real coords now)
    live_hotels = [v for v in venue_stubs if v.type == "hotel" and v.lat and v.lng]
    best_hotel_coords = (
        {"name": live_hotels[0].name, "lat": live_hotels[0].lat, "lng": live_hotels[0].lng}
        if live_hotels else
        {"name": "Hotel", "lat": 0, "lng": 0}
    )

    timeline_res = agent3.process_request({
        "action": "plan_timeline",
        "daily_activities": activities.daily_activities,
        "hotel": best_hotel_coords,
        "travel_mode": request.travel_mode,
        "origin": request.origin,
        "destination": scan_city,
        "vehicle_type": request.vehicle_type,
    })

    activities.timeline = timeline_res.get("timeline", {})
    activities.total_transit_cost = timeline_res.get("total_transit_cost", 0)

    # ═══════════════════════════════════════════════════════════════════════
    # ASSEMBLE MASTER HOSPITALITY DICT (same structure as before for LLM)
    # ═══════════════════════════════════════════════════════════════════════
    hotels_out = [v.model_dump() for v in venue_stubs if v.type == "hotel"]
    restaurants_out = [v.model_dump() for v in venue_stubs if v.type == "restaurant"]
    cafes_out = [v.model_dump() for v in venue_stubs if v.type == "cafe"]

    hospitality_data = {
        "hotels": hotels_out,
        "restaurants": restaurants_out,
        "cafes": cafes_out,
        "travel_costs": travel_costs.model_dump(),
        "hospitality_summary_text": (
            f"Found {len(hotels_out)} real hotels "
            f"(avg {sum(h['price'] for h in hotels_out)/max(len(hotels_out),1):.0f} {request.currency}/night), "
            f"{len(restaurants_out)} restaurants, and {len(cafes_out)} cafes in {scan_city}. "
            + (
                f"Cheapest flight: {travel_costs.flight.price_one_way} {travel_costs.flight.currency} one-way. "
                if travel_costs.flight else ""
            )
            + (
                f"Car rental available from {travel_costs.car_rental.price_per_day} {travel_costs.car_rental.currency}/day."
                if travel_costs.car_rental else ""
            )
        ),
        "data_sources": list({v.geocode_source for v in geolocated_venues}),
        "warnings": phase_a.warnings,
    }

    return hospitality_data, timeline_res, activities
