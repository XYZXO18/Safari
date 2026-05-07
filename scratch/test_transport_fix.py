
import math
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from safari.agent.worker_transport import TransportWorker

def test_transport_none():
    worker = TransportWorker()
    req = {
        "action": "plan_timeline",
        "origin": "riyadh",
        "destination": "coast",
        "daily_activities": {
            "1": [
                {"name": "No Loc", "lat": None, "lng": None}
            ]
        },
        "hotel": {"name": "Test Hotel", "lat": None, "lng": None},
        "travel_mode": "car"
    }
    
    try:
        res = worker.process_request(req)
        print("Success!")
        print(f"Timeline Days: {len(res.get('timeline', {}))}")
        print(f"Total Cost: {res.get('total_transit_cost')}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_transport_none()
