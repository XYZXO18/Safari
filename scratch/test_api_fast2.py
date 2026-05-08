from app import app
from flask import json
import os

os.environ["USE_LOCAL_AI"] = "false"

with app.test_client() as client:
    resp = client.post("/api/plan", json={
        "budget": 3000,
        "travel_mode": "flight",
        "destination": "makkah",
        "days": 3,
        "origin": "riyadh"
    })
    data = resp.get_json()
    print("Transport destination:", data.get("transport", {}).get("destination"))
    print("Events location:", data.get("events", {}).get("scan_city"))
    if "events" in data and "events" in data["events"]:
        for e in data["events"]["events"]:
            print(f" - {e['name']} at {e['lat']}, {e['lng']}")
    print("Insight:", data.get("transport", {}).get("insight"))
