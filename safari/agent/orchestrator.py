"""
Safari Agent Orchestrator
==========================
Coordinates all 3 agents to produce a unified travel plan.

Agent 1 (Research & Planning) → existing SafariAgent brain
Agent 2 (Hospitality & Venue) → hotel/restaurant data + dynamic pricing
Agent 3 (Transport)           → route calculation + cost comparison

The Orchestrator is the "conductor" — it routes requests between agents
and combines their outputs into a complete itinerary.
"""

from __future__ import annotations

import json
import time
from typing import Optional, List
from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from safari.agent.hospitality_agent import HospitalityAgent
from safari.agent.transport_agent import TransportAgent

console = Console()


@dataclass
class AgentMessage:
    """A message passed between agents."""
    from_agent: str
    to_agent: str
    action: str
    payload: dict
    timestamp: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "action": self.action,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class AgentOrchestrator:
    """
    Master coordinator for the Safari multi-agent system.

    Routes messages between agents and produces unified results.
    Records all inter-agent communication for transparency.
    """

    def __init__(self):
        self.hospitality_agent = HospitalityAgent()
        self.transport_agent = TransportAgent()
        self.message_log: List[AgentMessage] = []

    def _log_message(self, msg: AgentMessage):
        """Record an inter-agent message."""
        self.message_log.append(msg)
        console.print(
            f"  [dim cyan]📨 {msg.from_agent} → {msg.to_agent}[/dim cyan] "
            f"[dim]({msg.action})[/dim]"
        )

    def _send_to_hospitality(self, action: str, payload: dict, sender: str = "Orchestrator") -> dict:
        """Send a request to Agent 2 (Hospitality)."""
        msg = AgentMessage(
            from_agent=sender,
            to_agent="Agent 2 (Hospitality)",
            action=action,
            payload=payload,
        )
        self._log_message(msg)

        request = {"action": action, **payload}
        response = self.hospitality_agent.process_request(request)

        # Log response
        reply = AgentMessage(
            from_agent="Agent 2 (Hospitality)",
            to_agent=sender,
            action=f"{action}_response",
            payload={"status": "success" if "error" not in response else "error"},
        )
        self._log_message(reply)

        return response

    def _send_to_transport(self, action: str, payload: dict, sender: str = "Orchestrator") -> dict:
        """Send a request to Agent 3 (Transport)."""
        msg = AgentMessage(
            from_agent=sender,
            to_agent="Agent 3 (Transport)",
            action=action,
            payload=payload,
        )
        self._log_message(msg)

        request = {"action": action, **payload}
        response = self.transport_agent.process_request(request)

        reply = AgentMessage(
            from_agent="Agent 3 (Transport)",
            to_agent=sender,
            action=f"{action}_response",
            payload={"status": response.get("status", "success")},
        )
        self._log_message(reply)

        return response

    def get_hospitality_for_trip(
        self,
        destination: str,
        vibe: str,
        budget_lodging_per_day: float,
        budget_food_per_day: float,
        days: int,
        allergens: Optional[List[str]] = None,
    ) -> dict:
        """
        Called by Agent 1 during trip planning.
        Asks Agent 2 for hotel + restaurant recommendations matching the budget.

        Returns a structured dict with:
        - recommended_hotels: sorted by best value (discount + availability)
        - recommended_restaurants: sorted by rating
        - hospitality_summary: text for the LLM prompt
        """
        console.print()
        console.print("  [bold magenta]🏨 Agent 1 → Agent 2: Requesting hospitality data...[/bold magenta]")

        # Ask Agent 2 for hotel data
        hotel_data = self._send_to_hospitality(
            action="search_hotels",
            payload={"vibe": vibe},
            sender="Agent 1 (Research & Planning)",
        )

        # Ask Agent 2 for restaurant data
        restaurant_data = self._send_to_hospitality(
            action="search_restaurants",
            payload={"vibe": vibe, "allergens": allergens or []},
            sender="Agent 1 (Research & Planning)",
        )

        hotels = hotel_data.get("hotels", [])
        restaurants = restaurant_data.get("restaurants", [])

        # Filter hotels within budget
        budget_hotels = []
        for h in hotels:
            if not h.get("has_availability"):
                continue
            affordable_rooms = [
                r for r in h.get("rooms", [])
                if r["available"] > 0 and r["final_price_sar"] <= budget_lodging_per_day * 1.2
            ]
            if affordable_rooms:
                h["affordable_rooms"] = affordable_rooms
                # Best deal = room with highest discount
                best = max(affordable_rooms, key=lambda r: r["discount_percent"])
                h["best_deal"] = best
                budget_hotels.append(h)

        # Sort by best discount first
        budget_hotels.sort(key=lambda h: h["best_deal"]["discount_percent"], reverse=True)

        # Sort restaurants by rating
        restaurants.sort(key=lambda r: r.get("rating", 0), reverse=True)

        # Build the text summary for Agent 1's LLM prompt
        summary_lines = []
        summary_lines.append("## 🏨 Hotel Recommendations (from Agent 2)")
        if budget_hotels:
            for h in budget_hotels[:5]:
                bd = h["best_deal"]
                summary_lines.append(
                    f"- **{h['name']}** ({h['city']}, {h['stars']}★) — "
                    f"{bd['room_type']} room: ~~{bd['base_price_sar']} SAR~~ → "
                    f"**{bd['final_price_sar']:.0f} SAR/night** "
                    f"({bd['discount_percent']}% off, {bd['available']} rooms left)"
                )
        else:
            summary_lines.append("- No hotels found within lodging budget.")

        summary_lines.append("\n## 🍽️ Restaurant Recommendations (from Agent 2)")
        for r in restaurants[:5]:
            sig = ", ".join(r.get("top_dishes", [])[:3])
            disc = f" | 🔥 {r['discount_percent']}% off" if r.get("discount_percent", 0) > 0 else ""
            avail = f"{r['available_tables']}/{r['total_tables']} tables free"
            summary_lines.append(
                f"- **{r['name']}** ({r['city']}) — {r['cuisine']} ★{r['rating']} | "
                f"Signature: {sig} | {avail}{disc}"
            )

        hospitality_text = "\n".join(summary_lines)

        # Print a nice table for the console
        self._print_hospitality_summary(budget_hotels, restaurants)

        console.print(f"  [green]✅ Agent 2 responded: {len(budget_hotels)} hotels, {len(restaurants)} restaurants[/green]")

        return {
            "hotels": budget_hotels[:5],
            "restaurants": restaurants[:5],
            "all_hotels_count": len(hotels),
            "budget_hotels_count": len(budget_hotels),
            "restaurants_count": len(restaurants),
            "hospitality_summary_text": hospitality_text,
        }

    def get_transport_comparison(
        self,
        origin: str,
        destination: str,
    ) -> dict:
        """
        Called by Agent 1 to get transport options from Agent 3.
        """
        console.print("  [bold blue]🚗 Agent 1 → Agent 3: Comparing transport modes...[/bold blue]")

        comparison = self._send_to_transport(
            action="compare_modes",
            payload={"origin": origin, "destination": destination},
            sender="Agent 1 (Research & Planning)",
        )

        console.print(f"  [green]✅ Agent 3 responded: cheapest is {comparison.get('cheapest', '?')}[/green]")
        return comparison

    def get_communication_log(self) -> List[dict]:
        """Get the full inter-agent communication log."""
        return [m.to_dict() for m in self.message_log]

    def _print_hospitality_summary(self, hotels: list, restaurants: list):
        """Print a rich table of hospitality results."""
        if hotels:
            table = Table(title="🏨 Hotels Within Budget", border_style="dim")
            table.add_column("Hotel", style="bold")
            table.add_column("City")
            table.add_column("Stars")
            table.add_column("Best Room")
            table.add_column("Price", style="green")
            table.add_column("Discount", style="cyan")
            for h in hotels[:5]:
                bd = h["best_deal"]
                table.add_row(
                    h["name"], h["city"],
                    "★" * h["stars"],
                    bd["room_type"],
                    f"{bd['final_price_sar']:.0f} SAR",
                    f"-{bd['discount_percent']}%",
                )
            console.print(table)

        if restaurants:
            table = Table(title="🍽️ Top Restaurants", border_style="dim")
            table.add_column("Restaurant", style="bold")
            table.add_column("City")
            table.add_column("Cuisine")
            table.add_column("Rating", style="yellow")
            table.add_column("Tables Free", style="green")
            for r in restaurants[:5]:
                table.add_row(
                    r["name"], r["city"],
                    r["cuisine"],
                    f"★ {r['rating']}",
                    f"{r['available_tables']}/{r['total_tables']}",
                )
            console.print(table)
