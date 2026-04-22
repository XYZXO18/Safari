"""
Safari Calculation Tools
========================
Deterministic, math-only tools that the agent calls before generating text.
No LLM calls happen inside these modules — pure arithmetic.
"""

from safari.tools.transport import calculate_transport_costs
from safari.tools.budget import budget_allocator
from safari.tools.activities import suggest_activities

__all__ = [
    "calculate_transport_costs",
    "budget_allocator",
    "suggest_activities",
]
