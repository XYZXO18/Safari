"""
Output Formatter
================
Renders Safari's results as rich terminal output.
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.text import Text

from safari.tools.transport import TransportEstimate
from safari.tools.budget import BudgetBreakdown
from safari.tools.activities import ActivityPlan
from safari.tools.event_scanner import EventScanResult


console = Console(force_terminal=True)


def _build_budget_table(breakdown: BudgetBreakdown) -> Table:
    """Build a rich Table for the budget breakdown."""
    sym = breakdown.currency

    table = Table(
        title="💰 Budget Breakdown",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        title_style="bold yellow",
    )
    table.add_column("Category", style="bold")
    table.add_column("Total", justify="right", style="green")
    table.add_column("Per Day", justify="right", style="green")
    table.add_column("Share", justify="right", style="dim")

    table.add_row(
        "🚗 Transport (round-trip)",
        f"{breakdown.transport_cost:.0f} {sym}",
        "—",
        "—",
    )
    table.add_row("", "", "", "", end_section=True)

    remaining = breakdown.remaining_budget
    categories = [
        ("🏨 Lodging", breakdown.lodging_total, breakdown.lodging_per_day, "40%"),
        ("🍽️  Food", breakdown.food_total, breakdown.food_per_day, "30%"),
        ("🎯 Activities", breakdown.activities_total, breakdown.activities_per_day, "20%"),
        ("🛡️  Buffer", breakdown.buffer_total, breakdown.buffer_per_day, "10%"),
    ]

    for name, total, per_day, share in categories:
        table.add_row(name, f"{total:.0f} {sym}", f"{per_day:.0f} {sym}", share)

    table.add_row("", "", "", "", end_section=True)
    table.add_row(
        "📊 TOTAL",
        f"[bold]{breakdown.total_budget:.0f} {sym}[/bold]",
        "",
        "100%",
        style="bold",
    )

    return table


def print_itinerary(
    transport: TransportEstimate,
    breakdown: BudgetBreakdown,
    activities: ActivityPlan,
    llm_response: Optional[str] = None,
    event_scan: Optional[EventScanResult] = None,
) -> None:
    """Print the complete Safari itinerary to the terminal."""

    # Header
    console.print()
    console.print(
        Panel(
            Text("🧭 S A F A R I", style="bold yellow", justify="center"),
            subtitle="Budget-First Travel Planner",
            border_style="yellow",
            padding=(1, 4),
        )
    )
    console.print()

    # Transport info
    console.print(
        Panel(
            transport.summary,
            title="🚗 Transport Estimate",
            border_style="blue",
        )
    )
    console.print()

    # Budget table
    table = _build_budget_table(breakdown)
    console.print(table)
    console.print()

    # Warnings
    if breakdown.warnings:
        for w in breakdown.warnings:
            console.print(f"  ⚠️  [yellow]{w}[/yellow]")
        console.print()

    # Live Events
    if event_scan and event_scan.has_events:
        console.print(
            Panel(
                event_scan.summary,
                title="🎭 Live Events Discovered",
                border_style="red",
            )
        )
        console.print()

    # Activities
    console.print(
        Panel(activities.summary, title="🎯 Activity Plan", border_style="magenta")
    )
    console.print()

    # LLM-generated itinerary
    if llm_response:
        console.print(Panel(
            Markdown(llm_response),
            title="🧭 Safari's Full Itinerary",
            border_style="green",
            padding=(1, 2),
        ))
    console.print()


def format_itinerary(
    transport: TransportEstimate,
    breakdown: BudgetBreakdown,
    activities: ActivityPlan,
    llm_response: Optional[str] = None,
) -> dict:
    """Return structured JSON-serializable output."""
    result = {
        "transport": {
            "mode": transport.mode,
            "origin": transport.origin,
            "destination": transport.destination,
            "distance_km": transport.distance_km,
            "cost_one_way": transport.cost_one_way,
            "cost_round_trip": transport.cost_round_trip,
            "currency": transport.currency,
        },
        "budget": {
            "total": breakdown.total_budget,
            "transport": breakdown.transport_cost,
            "remaining": breakdown.remaining_budget,
            "days": breakdown.days,
            "lodging": {"total": breakdown.lodging_total, "per_day": breakdown.lodging_per_day},
            "food": {"total": breakdown.food_total, "per_day": breakdown.food_per_day},
            "activities": {"total": breakdown.activities_total, "per_day": breakdown.activities_per_day},
            "buffer": {"total": breakdown.buffer_total, "per_day": breakdown.buffer_per_day},
            "currency": breakdown.currency,
            "is_feasible": breakdown.is_feasible,
            "warnings": breakdown.warnings,
        },
        "activities": {
            "destination": activities.destination,
            "vibe": activities.vibe,
            "recommended_city": activities.recommended_city,
            "daily_plan": activities.daily_activities,
        },
    }
    if llm_response:
        result["itinerary_text"] = llm_response
    return result
