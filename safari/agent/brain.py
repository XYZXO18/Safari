"""
Safari Agent Brain
==================
The main orchestration engine. Runs deterministic calculations first,
then feeds verified numbers to the LLM for natural language generation.

Workflow:
1. Parse user input → TripRequest
2. calculate_transport_costs() → TransportEstimate
3. budget_allocator() → BudgetBreakdown
4. suggest_activities() → ActivityPlan
5. LLM generates itinerary from verified data
6. Format and return structured output
"""

from __future__ import annotations

import sys
from typing import Optional

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL
from safari.input_parser import TripRequest, parse_user_input
from safari.tools.transport import calculate_transport_costs, TransportEstimate
from safari.tools.budget import budget_allocator, BudgetBreakdown
from safari.tools.activities import suggest_activities, ActivityPlan
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

    def _step_log(self, emoji: str, message: str) -> None:
        """Print a styled step indicator."""
        console.print(f"  {emoji} [dim]{message}[/dim]")

    def run_calculations(self, request: TripRequest) -> tuple[TransportEstimate, BudgetBreakdown, ActivityPlan]:
        """
        Run all deterministic calculations for a trip request.
        No LLM calls — pure math.

        Returns
        -------
        tuple of (TransportEstimate, BudgetBreakdown, ActivityPlan)
        """
        # Step 1: Transport
        self._step_log("🚗", "Calculating transport costs...")
        transport = calculate_transport_costs(
            mode=request.travel_mode,
            origin=request.origin,
            destination=request.destination,
            vehicle_type=request.vehicle_type,
        )

        # Step 2: Budget allocation
        self._step_log("💰", "Allocating budget across categories...")
        breakdown = budget_allocator(
            total_budget=request.budget,
            transport_cost=transport.cost_round_trip,
            days=request.days,
            currency=request.currency,
        )

        # Step 3: Activity suggestions
        self._step_log("🎯", "Selecting activities within budget...")
        activities = suggest_activities(
            destination=request.destination,
            days=request.days,
            daily_activities_budget=breakdown.activities_per_day,
            currency=request.currency,
        )

        return transport, breakdown, activities

    def _generate_itinerary_text(
        self,
        request: TripRequest,
        transport: TransportEstimate,
        breakdown: BudgetBreakdown,
        activities: ActivityPlan,
    ) -> str:
        """Call the LLM to generate a natural-language itinerary."""
        if not self.client:
            return self._fallback_itinerary(request, transport, breakdown, activities)

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
            lodging_per_day=breakdown.lodging_per_day,
            food_per_day=breakdown.food_per_day,
            buffer_total=breakdown.buffer_total,
            currency=breakdown.currency,
        )

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
            return self._fallback_itinerary(request, transport, breakdown, activities)

    def _fallback_itinerary(
        self,
        request: TripRequest,
        transport: TransportEstimate,
        breakdown: BudgetBreakdown,
        activities: ActivityPlan,
    ) -> str:
        """Generate a template-based itinerary when LLM is unavailable."""
        sym = breakdown.currency
        lines = [
            f"### 🧭 Safari Trip Plan: {activities.recommended_city}",
            f"**{request.days} days | {request.travel_mode.title()} | "
            f"Budget: {request.budget:.0f} {sym}**",
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
            "---",
            "",
            "#### 📅 Day-by-Day Itinerary",
            "",
        ]

        for day in range(1, request.days + 1):
            day_acts = activities.daily_activities.get(day, [])
            lines.append(f"**Day {day}:**")
            if day == 1:
                lines.append(f"- 🚗 Depart {request.origin.title()} → {activities.recommended_city}")
            lines.append(f"- 🏨 Accommodation: ~{breakdown.lodging_per_day:.0f} {sym}")
            lines.append(f"- 🍽️ Meals: ~{breakdown.food_per_day:.0f} {sym}")
            for act in day_acts:
                lines.append(f"- 🎯 {act}")
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

        # Step 2: Run calculations
        console.print("  [bold]⚙️  Running calculations...[/bold]")
        transport, breakdown, activities = self.run_calculations(request)
        console.print("  [green]✅ All calculations complete![/green]")
        console.print()

        # Step 3: Generate LLM itinerary
        llm_text = self._generate_itinerary_text(request, transport, breakdown, activities)

        # Step 4: Display
        print_itinerary(transport, breakdown, activities, llm_text)

        # Step 5: Return structured data
        return format_itinerary(transport, breakdown, activities, llm_text)
