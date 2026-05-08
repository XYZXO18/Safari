"""
Orchestrator Agent
============
The main entry point. Coordinates the 3 Workers (Research, Hospitality, Transport)
and uses the LLM to generate the final output.
"""

import time
import requests
from typing import List, Dict

from config import OLLAMA_URL, OLLAMA_MODEL, USE_LOCAL_AI, GEMINI_API_KEY, GEMINI_MODEL
from safari.input_parser import TripRequest, parse_user_input
from safari.tools.transport import calculate_transport_costs
from safari.tools.budget import budget_allocator
from safari.agent.prompts import SAFARI_SYSTEM_PROMPT, ITINERARY_USER_PROMPT
from safari.output.formatter import print_itinerary, format_itinerary

from safari.agent.worker_research import ResearchWorker
from safari.agent.worker_hospitality_live import HospitalityWorker
from safari.agent.worker_transport_live import TransportWorker

from rich.console import Console
from rich.panel import Panel

console = Console(force_terminal=True)

class OrchestratorAgent:
    def __init__(self):
        self.use_local = USE_LOCAL_AI
        self.ollama_url = OLLAMA_URL
        self.ollama_model = OLLAMA_MODEL

        console.print("[bold cyan]Initializing Orchestrator Agent...[/bold cyan]")
        self.worker_1 = ResearchWorker()
        self.worker_2 = HospitalityWorker()
        self.worker_3 = TransportWorker()
        console.print("  [dim]↳ Initialized Worker 1 (Research)[/dim]")
        console.print("  [dim]↳ Initialized Worker 2 (Hospitality)[/dim]")
        console.print("  [dim]↳ Initialized Worker 3 (Transport)[/dim]")

        if not self.use_local:
            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.model = GEMINI_MODEL
        else:
            self.client = None
            self.model = self.ollama_model

    def _step_log(self, emoji: str, message: str) -> None:
        console.print(f"  {emoji} [dim]{message}[/dim]")

    def plan_trip(self, user_input: str) -> dict:
        console.print()
        console.print(Panel(f"[italic]\"{user_input}\"[/italic]", title="📥 User Request", border_style="cyan"))

        # Step 1: Parse
        self._step_log("📥", "Orchestrator Agent: Parsing request...")
        try:
            request = parse_user_input(user_input)
        except ValueError as e:
            return {"error": str(e)}

        if request.suggest_budget:
            self._step_log("💡", "No budget provided. Safari will suggest a mid-range budget based on live data.")
        
        self._step_log("✅", f"Budget: {'[Suggesting...]' if request.suggest_budget else request.budget} | Mode: {request.travel_mode} | Dest: {request.destination} | Days: {request.days} | Rent Car: {request.rent_car}")

        # Initial Orchestrator math
        # Use the raw city name (if captured) for more accurate transport/border checks
        transport_dest = request.destination_city if request.destination_city else request.destination
        transport_est = calculate_transport_costs(request.travel_mode, request.origin, transport_dest, request.vehicle_type)

        # Determine car rental daily rate if requested
        car_rental_daily = 0.0
        if request.rent_car:
            from config import CAR_RENTAL_DAILY_RATE_SAR, CITY_TO_COUNTRY
            dest_lookup = request.destination_city if request.destination_city else request.destination
            dest_country = CITY_TO_COUNTRY.get(dest_lookup.lower(), "")
            car_rental_daily = CAR_RENTAL_DAILY_RATE_SAR.get(dest_country, CAR_RENTAL_DAILY_RATE_SAR["default"])
            self._step_log("🚗", f"Car rental included: ~{car_rental_daily:.0f} SAR/day x {request.days} days = {car_rental_daily * request.days:.0f} SAR")

        breakdown = budget_allocator(
            request.budget,
            transport_est.cost_round_trip,
            request.days,
            request.currency,
            car_rental_daily_rate=car_rental_daily,
        )
        
        # If budget was suggested, update the request object so LLM prompts use the new values
        if request.suggest_budget:
            request.budget = breakdown.total_budget
            self._step_log("💰", f"Calculated suggested budget: {request.budget:.0f} {request.currency}")

        # DELEGATE TO Worker 1: RESEARCH
        console.print("\n  [bold magenta][R] Orchestrator Agent -> Worker 1 (Research): Gather activities & events...[/bold magenta]")
        research_res = self.worker_1.process_request({
            "action": "gather_activities_and_events",
            "destination": request.destination,
            "interests": request.interests,
            "days": request.days,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "activities_per_day": breakdown.activities_per_day,
            "currency": request.currency
        })
        activities = research_res["activities"]
        event_scan = research_res["event_scan"]
        web_research = research_res["web_research"]
        vibe = research_res["vibe"]

        # ─── Worker 2 & 3: Hospitality & Transport (LIVE WEB) ───────────────────
        from safari.agent.schemas import HospitalityInput
        
        console.print("[bold yellow][H] [Agent 2] Searching live web for hotels/restaurants...[/bold yellow]")
        hosp_input = HospitalityInput(
            city=activities.recommended_city,
            budget_per_night=breakdown.lodging_per_day,
            currency=request.currency,
            interests=request.interests.split(",") if request.interests else []
        )
        
        # Phase 1: Scrape
        hosp_output = self.worker_2.phase1_scrape(hosp_input)
        venues = hosp_output.venues
        
        # Phase 2: Geolocate (Agent 3)
        console.print("[bold cyan][T] [Agent 3] Resolving coordinates for live venues...[/bold cyan]")
        geolocated = self.worker_3.phase1_geolocate(venues, activities.recommended_city)
        
        # Update venues with coords
        hotels = [v.model_dump() for v in geolocated if v.type == 'hotel']
        restaurants = [v.model_dump() for v in geolocated if v.type == 'restaurant']
        hospitality_data = {
            "hotels": hotels, 
            "restaurants": restaurants,
            "hospitality_summary_text": f"Found {len(hotels)} affordable hotels and {len(restaurants)} high-rated restaurants."
        }
        
        # Determine hotel reference point
        if hotels:
            best = hotels[0]
            best_hotel_coords = {"name": best["name"], "lat": best["lat"], "lng": best["lng"]}
        else:
            best_hotel_coords = activities.hotel

        # Phase 3: Travel Costs (Agent 3)
        console.print("[bold blue][F] [Agent 3] Searching live travel pricing...[/bold blue]")
        travel_costs = self.worker_3.phase2_travel_costs(
            origin=request.origin,
            destination=activities.recommended_city,
            travel_mode=request.travel_mode,
            days=request.days
        )
        hospitality_data["travel_costs"] = travel_costs.model_dump()

        console.print("[bold magenta][M] [Agent 3] Planning timeline and routing...[/bold magenta]")
        timeline_res = self.worker_3.process_request({
            "action": "plan_timeline",
            "daily_activities": activities.daily_activities,
            "hotel": best_hotel_coords,
            "travel_mode": request.travel_mode,
            "vehicle_type": request.vehicle_type,
            "origin": request.origin,
            "destination": request.destination,
        })
        activities.timeline = timeline_res.get("timeline", {})
        activities.total_transit_cost = timeline_res.get("total_transit_cost", 0)
        
        comparison = self.worker_3.process_request({
            "action": "compare_modes",
            "origin": request.origin,
            "destination": request.destination
        })

        # Master generation phase
        console.print("  [bold green][V] All 3 Workers have reported back. Orchestrator generating itinerary...[/bold green]")
        
        llm_text = self._generate_itinerary_text(request, transport_est, breakdown, activities, event_scan, web_research, hospitality_data)

        # Output formatting
        result = format_itinerary(transport_est, breakdown, activities, llm_text)
        if event_scan and event_scan.has_events:
            result["events"] = event_scan.to_dict()
        if web_research and web_research.has_data:
            result["web_research"] = web_research.to_dict()
        if hospitality_data:
            result["hospitality"] = {
                "hotels": hospitality_data["hotels"],
                "restaurants": hospitality_data["restaurants"]
            }

        return result

    def _generate_itinerary_text(self, request, transport, breakdown, activities, event_scan, web_research, hospitality_data) -> str:
        if not self.use_local and not self.client:
            return "Fallback itinerary: LLM disabled."

        user_prompt = ITINERARY_USER_PROMPT.format(
            origin=request.origin.title(),
            destination=request.destination.title(),
            vibe=activities.vibe,
            days=request.days,
            travel_mode=request.travel_mode.title(),
            recommended_city=activities.recommended_city,
            transport_summary=transport.summary,
            budget_summary=breakdown.summary,
            activities_summary=activities.summary,
            events_section=event_scan.summary if event_scan and event_scan.has_events else "",
            research_section=web_research.summary if web_research and web_research.has_data else "",
            hospitality_section=hospitality_data["hospitality_summary_text"],
            lodging_per_day=breakdown.lodging_per_day,
            food_per_day=breakdown.food_per_day,
            buffer_total=breakdown.buffer_total,
            currency=breakdown.currency,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        if self.use_local:
            try:
                payload = {
                    "model": self.ollama_model,
                    "prompt": user_prompt,
                    "system": SAFARI_SYSTEM_PROMPT,
                    "stream": False,
                    "options": {"temperature": 0.7, "num_ctx": 4096}
                }
                response = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=120)
                response.raise_for_status()
                return response.json()["response"]
            except Exception as e:
                return f"LLM error: {e}"
        else:
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config={"system_instruction": SAFARI_SYSTEM_PROMPT, "temperature": 0.7, "max_output_tokens": 4096},
                )
                return response.text
            except Exception as e:
                return f"LLM error: {e}"
