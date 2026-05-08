
from safari.tools.transport import calculate_transport_costs

try:
    # This should trigger the division by zero if my theory is correct
    # "city" as destination with "riyadh" as origin might return dist=0
    # and then fall through to the estimation logic.
    res = calculate_transport_costs(mode="flight", origin="riyadh", destination="city")
    print("Result:", res)
except Exception as e:
    import traceback
    traceback.print_exc()
