
from safari.tools.transport import calculate_transport_costs

try:
    print("Testing bus mode with dist=0...")
    # This should trigger the division by zero
    res = calculate_transport_costs(mode="bus", origin="riyadh", destination="city")
    print("Result:", res)
except Exception as e:
    import traceback
    traceback.print_exc()
