"""
Safari Calculation Tools
========================
Deterministic, math-only tools that the agent calls before generating text.
No LLM calls happen inside these modules — pure arithmetic.

Also includes web research tools that use Gemini's Google Search grounding
to discover real-time data from the web and social media.
"""

from safari.tools.transport import calculate_transport_costs
from safari.tools.budget import budget_allocator
from safari.tools.activities import suggest_activities
from safari.tools.fuel import calculate_driving_cost
from safari.tools.event_scanner import find_live_events
from safari.tools.web_research import research_destination

__all__ = [
    "calculate_transport_costs",
    "budget_allocator",
    "suggest_activities",
    "calculate_driving_cost",
    "find_live_events",
    "research_destination",
]


