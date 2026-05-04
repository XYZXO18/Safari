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
from safari.agent.worker_hospitality import HospitalityWorker
from safari.agent.worker_transport import TransportWorker

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

        self._step_log("✅", f"Budget: {request.budget} | Mode: {request.travel_mode} | Dest: {request.destination} | Days: {request.days}")

        # Initial Orchestrator math
        transport_est = calculate_transport_costs(request.travel_mode, request.origin, request.destination, request.vehicle_type)
        breakdown = budget_allocator(request.budget, transport_est.cost_round_trip, request.days, request.currency)

        # DELEGATE TO Worker 1: RESEARCH
        console.print("\n  [bold magenta]🛠️ Orchestrator Agent → Worker 1 (Research): Gather activities & events...[/bold magenta]")
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

        # DELEGATE TO Worker 2: HOSPITALITY
        console.print("  [bold yellow]🏨 Orchestrator Agent → Worker 2 (Hospitality): Fetch hotels & restaurants...[/bold yellow]")
        hospitality_res = self.worker_2.process_request({
            "action": "search_hotels",
            "vibe": vibe
        })
        hotels = hospitality_res.get("hotels", [])
        
        rest_res = self.worker_2.process_request({
            "action": "search_restaurants",
            "vibe": vibe,
            "allergens": getattr(request, 'allergens', [])
        })
        restaurants = rest_res.get("restaurants", [])

        # Filter hotels strictly by budget logic
        budget_hotels = []
        for h in hotels:
            if not h.get("has_availability"): continue
            affordable = [r for r in h.get("rooms", []) if r["final_price_sar"] <= breakdown.lodging_per_day * 1.2]
            if affordable:
                best = max(affordable, key=lambda r: r["discount_percent"])
                h["best_deal"] = best
                budget_hotels.append(h)
        budget_hotels.sort(key=lambda h: h["best_deal"]["discount_percent"], reverse=True)
        restaurants.sort(key=lambda r: r.get("rating", 0), reverse=True)

        hospitality_data = {
            "hotels": budget_hotels[:5],
            "restaurants": restaurants[:5],
            "hospitality_summary_text": f"Found {len(budget_hotels)} affordable hotels and {len(restaurants)} high-rated restaurants."
        }

        # DELEGATE TO Worker 3: TRANSPORT
        console.print("  [bold blue]🚗 Orchestrator Agent → Worker 3 (Transport): Calculate daily routes...[/bold blue]")
        best_hotel_coords = {"name": budget_hotels[0]["name"], "lat": budget_hotels[0]["lat"], "lng": budget_hotels[0]["lng"]} if budget_hotels else activities.hotel
        
        timeline_res = self.worker_3.process_request({
            "action": "plan_timeline",
            "daily_activities": activities.daily_activities,
            "hotel": best_hotel_coords,
            "travel_mode": request.travel_mode
        })
        activities.timeline = timeline_res.get("timeline", {})
        activities.total_transit_cost = timeline_res.get("total_transit_cost", 0)
        
        comparison = self.worker_3.process_request({
            "action": "compare_modes",
            "origin": request.origin,
            "destination": request.destination
        })

        # Master generation phase
        console.print("  [bold green]✅ All 3 Workers have reported back. Orchestrator generating itinerary...[/bold green]")
        
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
