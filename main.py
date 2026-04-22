"""
Safari — Main Entry Point
==========================
Initializes the Safari agent and runs a demo trip planning query.

Usage:
    python main.py                          # Run with default demo query
    python main.py "I have 5000 SAR..."     # Run with custom query

Environment:
    GEMINI_API_KEY=your_key_here            # Set in .env file or environment
"""

import sys
import os
import io

# ─── Force UTF-8 on Windows ──────────────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Ensure project root is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from safari.agent.brain import SafariAgent

console = Console(force_terminal=True)


# ─── Demo Queries ─────────────────────────────────────────────────────────────

DEMO_QUERIES = [
    "I have 3000 Riyals, driving my car to the coast for 4 days",
    "Budget is 5000 SAR, flying to Abha for 5 days from Jeddah",
    "I got 2000 riyals, driving my SUV to the desert for 3 days from Riyadh",
    "I have $1500, taking the train to Medina for 3 days",
]


def print_banner():
    """Print the Safari welcome banner."""
    banner = Text(justify="center")
    banner.append("🧭 ", style="bold yellow")
    banner.append("S A F A R I", style="bold yellow")
    banner.append("\n")
    banner.append("Budget-First AI Travel Planner", style="dim italic")
    banner.append("\n\n")
    banner.append("Math first. Adventure second. Regrets never.", style="italic cyan")

    console.print()
    console.print(Panel(
        banner,
        border_style="yellow",
        padding=(1, 6),
    ))
    console.print()


def main():
    """Run Safari with a demo query or user-provided input."""

    print_banner()

    # Get query from command line args or use the first demo query
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        console.print("[dim]No query provided. Running demo...[/dim]")
        console.print(f"[dim]Tip: python main.py \"your trip description\"[/dim]")
        console.print()
        query = DEMO_QUERIES[0]

    # Initialize the agent
    agent = SafariAgent()

    # Plan the trip
    result = agent.plan_trip(query)

    # Summary
    if "error" not in result:
        console.print()
        console.print("[bold green]✅ Trip planning complete![/bold green]")
        console.print("[dim]The structured data is also available as a Python dict for API integration.[/dim]")
    else:
        console.print(f"\n[bold red]❌ Planning failed: {result['error']}[/bold red]")

    return result


if __name__ == "__main__":
    main()
