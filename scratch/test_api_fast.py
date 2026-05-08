
from app import app
from flask import json
import os

# mock out ollama
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
    print("DESTINATION USED:", data.get("transport", {}).get("destination"))
    print("Transport Insight:", data.get("transport", {}).get("insight"))
    print("Transport Details:", data.get("transport", {}).get("details", {}))
    if data.get("events"):
        for e in data["events"].get("events", []):
            print(f" - {e['name']} at {e['lat']}, {e['lng']}")
