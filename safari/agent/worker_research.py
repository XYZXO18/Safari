"""
Worker 1 — Research & Events
===========================
Finds live events, trending spots, and builds daily activity plans.
"""

from typing import Optional, List, Dict, Any
from safari.tools.activities import suggest_activities, ActivityPlan
from safari.tools.event_scanner import find_live_events, EventScanResult
from safari.tools.web_research import research_destination, WebResearchResult
from config import DESTINATIONS

class ResearchWorker:
    """Agent 1: Handles activities, events, and web research."""
    
    def process_request(self, request: dict) -> dict:
        action = request.get("action")
        if action == "gather_activities_and_events":
            return self._gather(request)
        return {"error": "Unknown action"}
        
    def _gather(self, request: dict) -> dict:
        destination = request.get("destination")
        interests = request.get("interests")
        days = request.get("days")
        start_date = request.get("start_date")
        end_date = request.get("end_date")
        activities_per_day = request.get("activities_per_day", 0)
        currency = request.get("currency", "SAR")

        dest_key = destination.lower()
        vibe = None
        if dest_key in DESTINATIONS:
            vibe = dest_key
            dest_info = DESTINATIONS[dest_key]
        else:
            for k, info in DESTINATIONS.items():
                if any(destination.lower() == c.lower() for c in info.get("cities", [])):
                    vibe = k
                    dest_info = info
                    break
            if not vibe:
                vibe = "coast"
                dest_info = DESTINATIONS["coast"]

        cities = dest_info.get("cities", [])
        scan_city = cities[0] if cities else destination.title()

        # 1. Web Research
        web_research = research_destination(city=scan_city, interests=interests)
        
        # 2. Event Scan
        event_scan = find_live_events(
            location=scan_city,
            start_date=start_date,
            end_date=end_date,
            interests=interests,
            max_events=10,
        )

        # 3. Calculate adjusted budget
        event_cost_per_day = event_scan.total_event_cost / days if days > 0 else 0
        adjusted_budget = max(activities_per_day - event_cost_per_day, 0)

        # 4. Suggest Activities
        activities = suggest_activities(
            destination=destination,
            days=days,
            daily_activities_budget=adjusted_budget,
            currency=currency,
        )

        # 5. Inject events and trending spots
        if event_scan.has_events:
            self._inject_events(activities, event_scan, days)
        if web_research.trending_spots:
            self._inject_trending_spots(activities, web_research, days)

        return {
            "activities": activities,
            "event_scan": event_scan,
            "web_research": web_research,
            "scan_city": scan_city,
            "vibe": vibe,
            "dest_info": dest_info
        }

    def _inject_events(self, activities: ActivityPlan, event_scan: EventScanResult, days: int) -> None:
        for i, event in enumerate(event_scan.events):
            target_day = (i % days) + 1
            event_activity = {
                "id": f"evt_{i}_{event.name.replace(' ', '_').lower()[:10]}",
                "name": f"🎪 LIVE: {event.name}",
                "lat": event.lat,
                "lng": event.lng,
                "is_live_event": True,
                "cost": event.estimated_cost_sar,
                "venue": event.venue,
                "time": event.time,
                "description": event.description,
            }
            if target_day in activities.daily_activities:
                activities.daily_activities[target_day].insert(0, event_activity)
            else:
                activities.daily_activities[target_day] = [event_activity]

    def _inject_trending_spots(self, activities: ActivityPlan, research: WebResearchResult, days: int) -> None:
        import random
        from config import CITY_COORDS
        city_coords = CITY_COORDS.get(activities.recommended_city.lower(), {"lat": 24.7, "lng": 46.7})
        for i, spot in enumerate(research.trending_spots[:days * 2]):
            target_day = (i % days) + 1
            spot_activity = {
                "id": f"trend_{i}_{spot.name.replace(' ', '_').lower()[:10]}",
                "name": f"🔥 TRENDING: {spot.name}",
                "lat": spot.lat or (city_coords["lat"] + random.uniform(-0.05, 0.05)),
                "lng": spot.lng or (city_coords["lng"] + random.uniform(-0.05, 0.05)),
                "is_trending_spot": True,
                "cost": spot.estimated_cost_sar,
                "category": spot.category,
                "description": spot.description,
                "social_buzz": spot.social_buzz,
                "rating": spot.rating,
                "price_range": spot.price_range,
                "tags": spot.tags,
                "source": spot.source,
            }
            if target_day in activities.daily_activities:
                insert_pos = 0
                for idx, act in enumerate(activities.daily_activities[target_day]):
                    if isinstance(act, dict) and act.get("is_live_event"):
                        insert_pos = idx + 1
                    else:
                        break
                activities.daily_activities[target_day].insert(insert_pos, spot_activity)
            else:
                activities.daily_activities[target_day] = [spot_activity]
