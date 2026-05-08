
from app import app
from flask import json

with app.test_client() as client:
    resp = client.post("/api/plan", json={
        "budget": 3000,
        "travel_mode": "flight",
        "destination": "makkah",
        "days": 3,
        "origin": "riyadh"
    })
    print("STATUS:", resp.status_code)
    data = resp.get_json()
    if "error" in data:
        print("ERROR:", data["error"])
    else:
        print("Transport Insight:", data.get("transport", {}).get("insight"))
        print("Events:", data.get("events", {}).get("scan_source"))
        if data.get("events"):
            for e in data["events"]["events"]:
                print(f" - {e['name']} at {e['lat']}, {e['lng']}")
        print("Flight pricing source:", data.get("transport", {}).get("breakdown"))
        if "transport" in data and "details" in data["transport"]:
            print(data["transport"]["details"])
