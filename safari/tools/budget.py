"""
Budget Allocator
================
Subtracts transport costs from the total budget, then splits the remainder
into category allocations using configurable ratios.

Default split (post-transport):
- 40% → Lodging
- 30% → Food
- 20% → Activities
- 10% → Buffer / emergency
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from config import BUDGET_RATIOS


@dataclass
class BudgetBreakdown:
    """Detailed budget allocation result."""

    total_budget: float
    transport_cost: float
    remaining_budget: float
    days: int
    currency: str = "SAR"

    # Car rental (separate from inter-city transport)
    car_rental_total: float = 0.0
    car_rental_per_day: float = 0.0

    # Category totals (for the entire trip)
    lodging_total: float = 0.0
    food_total: float = 0.0
    activities_total: float = 0.0
    buffer_total: float = 0.0

    # Category per-day amounts
    lodging_per_day: float = 0.0
    food_per_day: float = 0.0
    activities_per_day: float = 0.0
    buffer_per_day: float = 0.0

    # Allocation ratios used
    ratios: Dict[str, float] = field(default_factory=lambda: dict(BUDGET_RATIOS))

    # Feasibility and Status
    is_feasible: bool = True
    is_suggested: bool = False
    warnings: list = field(default_factory=list)

    @property
    def summary(self) -> str:
        sym = self.currency
        title = "💰 Budget Breakdown" if not self.is_suggested else "💡 Suggested Budget (Estimated)"
        lines = [
            f"{title} ({self.days} days)",
            f"{'─' * 45}",
            f"  Total Budget:        {self.total_budget:>8.0f} {sym}",
            f"  Transport (round):   {self.transport_cost:>8.0f} {sym}",
        ]
        if self.car_rental_total > 0:
            lines.append(f"  🚗 Car Rental:       {self.car_rental_total:>8.0f} {sym}  ({self.car_rental_per_day:.0f}/day)")
        lines += [
            f"  ────────────────────────────────────",
            f"  Remaining:           {self.remaining_budget:>8.0f} {sym}",
            f"",
            f"  Category           Total    /Day",
            f"  ─────────────────────────────────",
            f"  🏨 Lodging:       {self.lodging_total:>6.0f}    {self.lodging_per_day:>6.0f} {sym}",
            f"  🍽️  Food:          {self.food_total:>6.0f}    {self.food_per_day:>6.0f} {sym}",
            f"  🎯 Activities:    {self.activities_total:>6.0f}    {self.activities_per_day:>6.0f} {sym}",
            f"  🛡️  Buffer:        {self.buffer_total:>6.0f}    {self.buffer_per_day:>6.0f} {sym}",
        ]
        if self.warnings:
            lines.append("")
            for w in self.warnings:
                lines.append(f"  ⚠️  {w}")

        return "\n".join(lines)


def budget_allocator(
    total_budget: float,
    transport_cost: float,
    days: int,
    currency: str = "SAR",
    custom_ratios: Dict[str, float] | None = None,
    car_rental_daily_rate: float = 0.0,
    adults: int = 1,
    children: int = 0,
    has_own_lodging: bool = False,
) -> BudgetBreakdown:
    """
    Allocate budget across categories after subtracting transport and car rental.

    Parameters
    ----------
    total_budget : float
        The user's total trip budget.
    transport_cost : float
        Round-trip inter-city transport cost (already calculated).
    days : int
        Number of trip days.
    currency : str
        Currency code for display.
    custom_ratios : dict, optional
        Override default ratios. Keys: 'lodging', 'food', 'activities', 'buffer'.
    car_rental_daily_rate : float
        Daily car rental cost. If > 0, total rental (days × rate) is deducted
        from the budget before category allocation.

    Returns
    -------
    BudgetBreakdown
        Complete allocation with totals, per-day amounts, and feasibility flags.

    Examples
    --------
    >>> result = budget_allocator(3000, 400, 4)
    >>> result.remaining_budget
    2600.0
    >>> result = budget_allocator(3000, 400, 4, car_rental_daily_rate=120)
    >>> result.remaining_budget  # 3000 - 400 transport - 480 rental
    2120.0
    """

    ratios = custom_ratios if custom_ratios else dict(BUDGET_RATIOS)

    # Validate ratios sum to ~1.0
    ratio_sum = sum(ratios.values())
    if abs(ratio_sum - 1.0) > 0.01:
        raise ValueError(f"Budget ratios must sum to 1.0, got {ratio_sum:.2f}")

    days = max(days, 1)  # guard against zero

    car_rental_total = round(car_rental_daily_rate * days, 2) if car_rental_daily_rate > 0 else 0.0
    total_deducted = transport_cost + car_rental_total
    remaining = total_budget - total_deducted
    warnings = []

    # Feasibility check
    is_feasible = True
    is_suggested = False
    
    if total_budget <= 0:
        # SUGGESTED MODE: Calculate a mid-range budget
        is_suggested = True
        
        # Target daily spend for non-transport categories (Lodging, Food, Activities, Buffer)
        # 1000 SAR/day is a solid mid-range estimate for Saudi Arabia
        TARGET_DAILY_SPEND = 1000.0
        
        remaining = TARGET_DAILY_SPEND * days
        total_budget = remaining + transport_cost + car_rental_total
    elif remaining <= 0:
        is_feasible = False
        warnings.append("Transport and rental costs exceed total budget!")
        remaining = 0

    if remaining > 0 and (remaining / days) < 100:
        warnings.append(
            f"Very tight budget: only {remaining / days:.0f} {currency}/day after transport."
        )

    # Allocate
    lodging_total = remaining * ratios.get("lodging", 0.40)
    food_base = remaining * ratios.get("food", 0.30)
    activities_total = remaining * ratios.get("activities", 0.20)
    buffer_total = remaining * ratios.get("buffer", 0.10)

    # Per-person food scaling: baseline allocation assumed 1 adult.
    # Each additional adult costs 1×, each child costs 0.75×.
    adults = max(int(adults), 1)
    children = max(int(children), 0)
    people_factor = adults + 0.75 * children
    food_total = food_base * people_factor

    # User already has lodging arranged → zero it out and redistribute
    # the freed allocation back into the buffer so the budget summary stays consistent.
    if has_own_lodging:
        buffer_total += lodging_total
        lodging_total = 0.0

    return BudgetBreakdown(
        total_budget=total_budget,
        transport_cost=transport_cost,
        remaining_budget=remaining,
        days=days,
        currency=currency,
        car_rental_total=car_rental_total,
        car_rental_per_day=round(car_rental_daily_rate, 2),
        lodging_total=round(lodging_total, 2),
        food_total=round(food_total, 2),
        activities_total=round(activities_total, 2),
        buffer_total=round(buffer_total, 2),
        lodging_per_day=round(lodging_total / days, 2) if days > 0 else 0,
        food_per_day=round(food_total / days, 2) if days > 0 else 0,
        activities_per_day=round(activities_total / days, 2) if days > 0 else 0,
        buffer_per_day=round(buffer_total / days, 2) if days > 0 else 0,
        ratios=ratios,
        is_feasible=is_feasible,
        is_suggested=is_suggested,
        warnings=warnings,
    )
