import requests
import json

payload = {
    "origin": "Riyadh",
    "destination": "coast",
    "budget": 5000,
    "days": 3,
    "travel_mode": "drive",
    "vehicle_type": "SUV",
    "interests": "beach"
}

try:
    res = requests.post("http://localhost:5000/api/plan", json=payload, timeout=60)
    data = res.json()
    paths = data.get("paths", [])
    if paths:
        sim_routes = paths[0].get("simulation_routes", {})
        print("Keys in simulation_routes:", sim_routes.keys())
        if sim_routes:
            print("First point of day 1:", sim_routes.get("1", [])[0])
        else:
            print("simulation_routes is EMPTY!")
            
        print("Timeline keys:", paths[0].get("timeline", {}).keys())
    else:
        print("No paths returned.")
except Exception as e:
    print("Error:", e)
