"""Quick sanity check for distance + vehicle-type fixes."""
from safari.tools.fuel import calculate_driving_cost
from safari.tools.transport import calculate_transport_costs

SEP = "=" * 60

print(SEP)
print("1. Distance fix: Riyadh -> desert vibe (should be ~1100 km)")
t = calculate_transport_costs("car", "riyadh", "desert", vehicle_type="truck")
print(f"   Distance      : {t.distance_km} km  (expected ~1100)")
print(f"   Round-trip    : {t.cost_round_trip} SAR")
print(f"   Breakdown     : {t.breakdown}")
print()

print(SEP)
print("2. Vehicle type fix: truck vs sedan vs default on 1100 km")
for vt, label in [("truck", "4x4 Truck (8 km/L)"), ("sedan", "Sedan (13 km/L)"), ("default", "Default (12 km/L)")]:
    r = calculate_driving_cost(1100, vehicle_type=vt)
    print(f"   {label:25s}: {r['cost_round_trip']:.1f} SAR  @ {r['km_per_liter']} km/L")
print()

print(SEP)
print("3. Direct city: Riyadh -> Al-Ula with 4x4")
t2 = calculate_transport_costs("car", "riyadh", "al-ula", vehicle_type="4x4")
print(f"   Distance      : {t2.distance_km} km  (expected 1100)")
print(f"   Round-trip    : {t2.cost_round_trip} SAR")
print(f"   Breakdown     : {t2.breakdown}")
