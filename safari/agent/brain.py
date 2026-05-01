"""
Safari Agent Brain (Agent 1 — Research & Planning)
===================================================
The main orchestration engine. Runs deterministic calculations first,
then feeds verified numbers to the LLM for natural language generation.

Multi-Agent Workflow:
1. Parse user input → TripRequest
2. calculate_transport_costs() → TransportEstimate
3. Agent 1 → Agent 3 (Transport): Compare transport modes
4. budget_allocator() → BudgetBreakdown
5. Agent 1 → Agent 2 (Hospitality): Get hotels & restaurants
6. find_live_events() → EventScanResult
7. suggest_activities() → ActivityPlan (with events injected)
8. LLM generates itinerary from ALL agents' verified data
9. Format and return structured output
"""

from __future__ import annotations

import sys
from typing import Optional

from google import genai
from google.genai import types
import requests

from config import GEMINI_API_KEY, GEMINI_MODEL, USE_LOCAL_AI, OLLAMA_URL, OLLAMA_MODEL
from safari.input_parser import TripRequest, parse_user_input
from safari.tools.transport import calculate_transport_costs, TransportEstimate
from safari.tools.budget import budget_allocator, BudgetBreakdown
from safari.tools.activities import suggest_activities, ActivityPlan
from safari.tools.event_scanner import find_live_events, EventScanResult
from safari.tools.web_research import research_destination, WebResearchResult
from safari.agent.prompts import SAFARI_SYSTEM_PROMPT, ITINERARY_USER_PROMPT
from safari.output.formatter import print_itinerary, format_itinerary

from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live

console = Console(force_terminal=True)


class SafariAgent:
    """
    The Safari travel planning agent.

    Orchestrates deterministic calculation tools and LLM generation
    to produce budget-constrained travel itineraries.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Safari with a Gemini API key.

        Parameters
        ----------
        api_key : str, optional
            Google Gemini API key. Falls back to GEMINI_API_KEY from config.
        """
        self.use_local = USE_LOCAL_AI
        self.ollama_url = OLLAMA_URL
        self.ollama_model = OLLAMA_MODEL

        # Initialize the multi-agent orchestrator
        from safari.agent.orchestrator import AgentOrchestrator
        self.orchestrator = AgentOrchestrator()

        if not self.use_local:
            key = api_key or GEMINI_API_KEY
            if not key:
                console.print(
                    "[bold red]❌ No GEMINI_API_KEY found![/bold red]\n"
                    "Set it in a .env file or pass it directly.\n"
                    "Safari will run calculations but skip LLM generation."
                )
                self.client = None
            else:
                self.client = genai.Client(api_key=key)
            self.model = GEMINI_MODEL
        else:
            self.client = None
            self.model = self.ollama_model
            console.print(f"  [cyan]🧠 Using local AI agent ({self.ollama_model})[/cyan]")

    def _step_log(self, emoji: str, message: str) -> None:
        """Print a styled step indicator."""
        console.print(f"  {emoji} [dim]{message}[/dim]")

    def run_calculations(self, request: TripRequest) -> tuple:
        """
        Run all deterministic calculations for a trip request.
        Now includes multi-agent communication with Agent 2 & Agent 3.

        Returns
        -------
        tuple of (TransportEstimate, BudgetBreakdown, ActivityPlan, EventScanResult, WebResearchResult, dict)
            The last element is hospitality_data from Agent 2.
        """
        # Step 1: Transport (Agent 1 internal)
        self._step_log("🚗", "Calculating transport costs...")
        transport = calculate_transport_costs(
            mode=request.travel_mode,
            origin=request.origin,
            destination=request.destination,
            vehicle_type=request.vehicle_type,
        )

        # Step 2: Agent 1 → Agent 3 (Transport comparison)
        self._step_log("🔄", "Agent 1 → Agent 3: Comparing transport options...")
        transport_comparison = self.orchestrator.get_transport_comparison(
            origin=request.origin,
            destination=request.destination,
        )

        # Step 3: Budget allocation
        self._step_log("💰", "Allocating budget across categories...")
        breakdown = budget_allocator(
            total_budget=request.budget,
            transport_cost=transport.cost_round_trip,
            days=request.days,
            currency=request.currency,
        )

        # Step 4: Agent 1 → Agent 2 (Hospitality) — hotels & restaurants
        self._step_log("🔄", "Agent 1 → Agent 2: Requesting hotel & restaurant data...")
        from config import DESTINATIONS
        
        # Determine the correct vibe key ("coast", "mountains", "desert", "city")
        vibe = None
        dest_key = request.destination.lower()
        if dest_key in DESTINATIONS:
            vibe = dest_key
            dest_info = DESTINATIONS[dest_key]
        else:
            for k, info in DESTINATIONS.items():
                if any(request.destination.lower() == c.lower() for c in info.get("cities", [])):
                    vibe = k
                    dest_info = info
                    break
            if not vibe:
                vibe = "coast"
                dest_info = DESTINATIONS["coast"]

        hospitality_data = self.orchestrator.get_hospitality_for_trip(
            destination=request.destination,
            vibe=vibe,
            budget_lodging_per_day=breakdown.lodging_per_day,
            budget_food_per_day=breakdown.food_per_day,
            days=request.days,
            allergens=getattr(request, 'allergens', None),
        )

        # Step 5: Web + Social Media Research
        self._step_log("🌐", "Researching online data & social media...")
        cities = dest_info.get("cities", [])
        scan_city = cities[0] if cities else request.destination.title()

        web_research = research_destination(
            city=scan_city,
            interests=request.interests,
        )

        if web_research.has_data:
            social_count = len(web_research.social_posts)
            spots_count = len(web_research.trending_spots)
            tips_count = len(web_research.local_insights)
            self._step_log("📱", f"Found {social_count} social posts, "
                                  f"{spots_count} trending spots, "
                                  f"{tips_count} local tips")
        else:
            self._step_log("📭", "No additional online data found.")

        # Step 6: Scan for live events
        self._step_log("🎭", "Scanning for live events & festivals...")
        event_scan = find_live_events(
            location=scan_city,
            start_date=request.start_date,
            end_date=request.end_date,
            interests=request.interests,
            max_events=10,
        )

        if event_scan.has_events:
            self._step_log("🎪", f"Found {len(event_scan.events)} live events! "
                                  f"(Total cost: {event_scan.total_event_cost:.0f} {request.currency})")
        else:
            self._step_log("📭", "No live events found for these dates.")

        # Step 7: Calculate adjusted activities budget (deduct event costs)
        event_cost_per_day = event_scan.total_event_cost / request.days if request.days > 0 else 0
        adjusted_activities_budget = max(breakdown.activities_per_day - event_cost_per_day, 0)

        # Step 8: Activity suggestions (with reduced budget if events consume some)
        self._step_log("🎯", "Selecting activities within budget...")
        activities = suggest_activities(
            destination=request.destination,
            days=request.days,
            daily_activities_budget=adjusted_activities_budget,
            currency=request.currency,
        )

        # Step 9: Inject live events into the activity plan
        if event_scan.has_events:
            self._inject_events(activities, event_scan, request.days)

        # Step 10: Inject trending spots from web research into activities
        if web_research.trending_spots:
            self._inject_trending_spots(activities, web_research, request.days)

        # Step 11: Route the daily activities using Agent 3 (Transport)
        self._step_log("🗺️", "Agent 1 → Agent 3: Calculating daily transit routes and costs...")
        from safari.agent.orchestrator import AgentOrchestrator
        orchestrator = AgentOrchestrator()
        
        hotel_data = activities.hotel
        if hospitality_data and hospitality_data.get("hotels"):
            # Use the best hospitality agent hotel for routing if available
            best_hotel = hospitality_data["hotels"][0]
            hotel_data = {"name": best_hotel.get("name"), "lat": best_hotel.get("lat"), "lng": best_hotel.get("lng")}

        timeline_req = {
            "action": "plan_timeline",
            "daily_activities": activities.daily_activities,
            "hotel": hotel_data,
            "travel_mode": request.travel_mode
        }
        
        timeline_res = orchestrator.send_to_agent("Agent 3 (Transport)", timeline_req)
        activities.timeline = timeline_res.get("timeline", {})
        activities.total_transit_cost = timeline_res.get("total_transit_cost", 0)

        return transport, breakdown, activities, event_scan, web_research, hospitality_data

    def _inject_events(self, activities: ActivityPlan, event_scan: EventScanResult, days: int) -> None:
        """
        Inject discovered live events into the activity plan's daily schedule.
        Spreads events across days, prioritizing earlier days for time-sensitive events.
        """
        for i, event in enumerate(event_scan.events):
            # Assign each event to a different day if possible
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

            if target_day in activities.daily_activities:
                # Insert at the beginning — live events get priority
                activities.daily_activities[target_day].insert(0, event_activity)
            else:
                activities.daily_activities[target_day] = [event_activity]

    def _inject_trending_spots(self, activities: ActivityPlan, research: WebResearchResult, days: int) -> None:
        """
        Inject top trending spots from web/social media research into the activity plan.
        Adds them as special 'social_pick' items so the UI can highlight them.
        """
        import random
        from config import CITY_COORDS

        city_coords = CITY_COORDS.get(activities.recommended_city.lower(), {"lat": 24.7, "lng": 46.7})

        for i, spot in enumerate(research.trending_spots[:days * 2]):
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

            if target_day in activities.daily_activities:
                # Add trending spots after live events but before regular activities
                insert_pos = 0
                for idx, act in enumerate(activities.daily_activities[target_day]):
                    if isinstance(act, dict) and act.get("is_live_event"):
                        insert_pos = idx + 1
                    else:
                        break
                activities.daily_activities[target_day].insert(insert_pos, spot_activity)
            else:
                activities.daily_activities[target_day] = [spot_activity]

    def _generate_itinerary_text(
        self,
        request: TripRequest,
        transport: TransportEstimate,
        breakdown: BudgetBreakdown,
        activities: ActivityPlan,
        event_scan: EventScanResult = None,
        web_research: WebResearchResult = None,
        hospitality_data: dict = None,
    ) -> str:
        """Call the LLM to generate a natural-language itinerary."""
        if not self.use_local and not self.client:
            return self._fallback_itinerary(request, transport, breakdown, activities, event_scan, web_research)

        events_section = ""
        if event_scan and event_scan.has_events:
            events_section = (
                f"\n## 🎭 Live Events Discovered\n"
                f"{event_scan.summary}\n\n"
                f"**IMPORTANT:** These live events have been injected into the daily plan. "
                f"Highlight them as exciting, unique experiences. Their costs ({event_scan.total_event_cost:.0f} SAR total) "
                f"come from the Activities budget.\n"
            )

        research_section = ""
        if web_research and web_research.has_data:
            research_section = (
                f"\n## 🌐 Online & Social Media Research\n"
                f"{web_research.summary}\n\n"
                f"**IMPORTANT:** Use these social media discoveries and trending spots to make "
                f"personalized, hyper-local recommendations. Mention specific restaurants, "
                f"hidden gems, and tips discovered from real social media posts. "
                f"Reference the social media sources when recommending a spot (e.g., "
                f"'trending on Instagram' or 'recommended by local food bloggers').\n"
            )

        # Hospitality section from Agent 2
        hospitality_section = ""
        if hospitality_data and hospitality_data.get("hospitality_summary_text"):
            hospitality_section = (
                f"\n{hospitality_data['hospitality_summary_text']}\n\n"
                f"**IMPORTANT:** Agent 2 (Hospitality) has provided these hotel and restaurant "
                f"recommendations from our database. Use the EXACT hotel names, prices, and "
                f"discount percentages above when suggesting accommodation. Recommend the "
                f"restaurants with their signature dishes for meal planning. "
                f"Mention the dynamic discounts as a money-saving tip.\n"
            )

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
            events_section=events_section,
            research_section=research_section,
            hospitality_section=hospitality_section,
            lodging_per_day=breakdown.lodging_per_day,
            food_per_day=breakdown.food_per_day,
            buffer_total=breakdown.buffer_total,
            currency=breakdown.currency,
            start_date=request.start_date,
            end_date=request.end_date,
        )

        if self.use_local:
            self._step_log("🧠", f"Generating itinerary with local AI ({self.ollama_model})...")
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
                console.print(f"  [yellow]⚠️  Local LLM call failed: {e}[/yellow]")
                console.print("  [dim]Falling back to template-based output...[/dim]")
                return self._fallback_itinerary(request, transport, breakdown, activities, event_scan, web_research)
        else:
            self._step_log("🧠", "Generating itinerary with Gemini...")

            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SAFARI_SYSTEM_PROMPT,
                        temperature=0.7,
                        max_output_tokens=4096,
                    ),
                )
                return response.text
            except Exception as e:
                console.print(f"  [yellow]⚠️  LLM call failed: {e}[/yellow]")
                console.print("  [dim]Falling back to template-based output...[/dim]")
                return self._fallback_itinerary(request, transport, breakdown, activities, event_scan, web_research)

    def _fallback_itinerary(
        self,
        request: TripRequest,
        transport: TransportEstimate,
        breakdown: BudgetBreakdown,
        activities: ActivityPlan,
        event_scan: EventScanResult = None,
        web_research: WebResearchResult = None,
    ) -> str:
        """Generate a template-based itinerary when LLM is unavailable."""
        sym = breakdown.currency
        lines = [
            f"### 🧭 Safari Trip Plan: {activities.recommended_city}",
            f"**{request.days} days | {request.travel_mode.title()} | "
            f"Budget: {request.budget:.0f} {sym}**",
            f"**📅 {request.start_date} → {request.end_date}**",
            "",
            "---",
            "",
            "#### 💰 Budget Breakdown",
            f"- Total Budget: **{request.budget:.0f} {sym}**",
            f"- Transport (round-trip): **{transport.cost_round_trip:.0f} {sym}**",
            f"- Remaining: **{breakdown.remaining_budget:.0f} {sym}**",
            f"  - 🏨 Lodging: {breakdown.lodging_per_day:.0f} {sym}/day ({breakdown.lodging_total:.0f} total)",
            f"  - 🍽️ Food: {breakdown.food_per_day:.0f} {sym}/day ({breakdown.food_total:.0f} total)",
            f"  - 🎯 Activities: {breakdown.activities_per_day:.0f} {sym}/day ({breakdown.activities_total:.0f} total)",
            f"  - 🛡️ Buffer: {breakdown.buffer_per_day:.0f} {sym}/day ({breakdown.buffer_total:.0f} total)",
            "",
        ]

        # Show live events section if events were found
        if event_scan and event_scan.has_events:
            lines.extend([
                "---",
                "",
                "#### 🎭 Live Events Happening During Your Trip!",
                "",
            ])
            for ev in event_scan.events:
                lines.append(f"- 🎪 **{ev.name}** — {ev.date}")
                if ev.venue:
                    lines.append(f"  📍 {ev.venue}")
                if ev.description:
                    lines.append(f"  _{ev.description}_")
                lines.append(f"  💰 ~{ev.estimated_cost_sar:.0f} {sym}")
                lines.append("")
            lines.append(f"Total event costs: **{event_scan.total_event_cost:.0f} {sym}** (from Activities budget)")

        # Show social media & web research section
        if web_research and web_research.has_data:
            lines.extend([
                "",
                "---",
                "",
                "#### 🌐 Online & Social Media Discoveries",
                "",
            ])

            if web_research.weather_summary:
                lines.append(f"🌤️ **Weather:** {web_research.weather_summary}")
                lines.append("")

            if web_research.social_posts:
                lines.append("**📱 Social Media Buzz:**")
                platform_icons = {
                    "x/twitter": "🐦", "instagram": "📸",
                    "tiktok": "🎵", "reddit": "🔴", "blog": "📝"
                }
                for post in web_research.social_posts[:5]:
                    icon = platform_icons.get(post.platform, "🌐")
                    lines.append(f"- {icon} **@{post.author}**: {post.content}")
                lines.append("")

            if web_research.trending_spots:
                lines.append("**🔥 Trending Spots:**")
                for spot in web_research.trending_spots[:5]:
                    stars = "⭐" * int(spot.rating) if spot.rating else ""
                    lines.append(f"- **{spot.name}** ({spot.category}) {stars}")
                    lines.append(f"  _{spot.description}_")
                    if spot.social_buzz:
                        lines.append(f"  📱 {spot.social_buzz}")
                    lines.append(f"  💰 ~{spot.estimated_cost_sar:.0f} {sym}")
                lines.append("")

            if web_research.local_insights:
                lines.append("**💡 Local Tips from the Web:**")
                for tip in web_research.local_insights[:5]:
                    lines.append(f"- {tip.tip} _(source: {tip.source})_")
                lines.append("")
            lines.append("")

        lines.extend([
            "---",
            "",
            "#### 📅 Day-by-Day Itinerary",
            "",
        ])

        for day in range(1, request.days + 1):
            day_acts = activities.daily_activities.get(day, [])
            lines.append(f"**Day {day}:**")
            if day == 1:
                lines.append(f"- 🚗 Depart {request.origin.title()} → {activities.recommended_city}")
            lines.append(f"- 🏨 Accommodation: ~{breakdown.lodging_per_day:.0f} {sym}")
            lines.append(f"- 🍽️ Meals: ~{breakdown.food_per_day:.0f} {sym}")
            for act in day_acts:
                act_name = act.get("name", act) if isinstance(act, dict) else act
                is_event = act.get("is_live_event", False) if isinstance(act, dict) else False
                is_trending = act.get("is_trending_spot", False) if isinstance(act, dict) else False
                if is_event:
                    prefix = "🎪"
                elif is_trending:
                    prefix = "🔥"
                else:
                    prefix = "🎯"
                lines.append(f"- {prefix} {act_name}")
            if day == request.days:
                lines.append(f"- 🚗 Return to {request.origin.title()}")
            lines.append("")

        lines.extend([
            "---",
            "",
            f"#### 🛡️ Emergency Buffer: {breakdown.buffer_total:.0f} {sym}",
            "Keep this aside for unexpected expenses, fuel price spikes, or spontaneous stops.",
        ])

        return "\n".join(lines)

    def plan_trip(self, user_input: str) -> dict:
        """
        Main entry point: parse input → calculate → generate → format.

        Parameters
        ----------
        user_input : str
            Raw natural-language trip request.

        Returns
        -------
        dict
            Structured itinerary data (JSON-serializable).
        """
        console.print()
        console.print(Panel(
            f"[italic]\"{user_input}\"[/italic]",
            title="📥 User Request",
            border_style="cyan",
        ))
        console.print()

        # Step 1: Parse
        self._step_log("📥", "Parsing your request...")
        try:
            request = parse_user_input(user_input)
        except ValueError as e:
            console.print(f"  [red]❌ Could not parse input: {e}[/red]")
            return {"error": str(e)}

        self._step_log("✅", f"Budget: {request.budget:.0f} {request.currency} | "
                             f"Mode: {request.travel_mode} | "
                             f"Dest: {request.destination} | "
                             f"Days: {request.days}")
        console.print()

        # Step 2: Run calculations (including multi-agent coordination)
        console.print("  [bold]⚙️  Running calculations & multi-agent coordination...[/bold]")
        transport, breakdown, activities, event_scan, web_research, hospitality_data = self.run_calculations(request)
        console.print("  [green]✅ All agents responded — calculations complete![/green]")
        console.print()

        # Step 3: Generate LLM itinerary (with ALL agents' data)
        llm_text = self._generate_itinerary_text(
            request, transport, breakdown, activities,
            event_scan, web_research, hospitality_data,
        )

        # Step 4: Display
        print_itinerary(transport, breakdown, activities, llm_text, event_scan)

        # Step 5: Return structured data
        result = format_itinerary(transport, breakdown, activities, llm_text)
        if event_scan and event_scan.has_events:
            result["events"] = event_scan.to_dict()
        if web_research and web_research.has_data:
            result["web_research"] = web_research.to_dict()
        # Include Agent 2 hospitality data & inter-agent communication log
        if hospitality_data:
            result["hospitality"] = {
                "hotels": hospitality_data.get("hotels", []),
                "restaurants": hospitality_data.get("restaurants", []),
                "agent_comms": self.orchestrator.get_communication_log(),
            }
        return result
