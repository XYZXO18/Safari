
import json
from typing import Dict, Any
from safari.agent.prompts import FIXER_SYSTEM_PROMPT
from safari.ai_client import generate_json
from config import CITY_COORDS

class FixerWorker:
    """
    The 'Fixer' Agent: Its whole job is to repair or provide fallback data 
    when other workers (Hospitality, Transport, Research) fail.
    """
    
    def process_request(self, original_request: Dict[str, Any], error_msg: str, worker_type: str) -> Dict[str, Any]:
        print(f"🛠️ [Fixer Agent] Attempting to repair {worker_type} failure: {error_msg}")
        
        prompt = f"""
        The {worker_type} failed with error: "{error_msg}"
        Original Request: {json.dumps(original_request, indent=2)}
        
        Provide a REPAIR response that mimics a successful {worker_type} output.
        - If it's a Transport failure: Provide a basic timeline with inter-city and local legs using CITY_COORDS defaults.
        - If it's a Hospitality failure: Provide 2-3 fictional but realistic hotels/restaurants matching the budget.
        - If it's a Research failure: Provide 3-5 popular landmarks for the city.
        
        Respond ONLY with a valid JSON object.
        """
        
        try:
            # Try cloud AI for high-quality repair, fallback to simple logic if even AI fails
            resp = generate_json(prompt, system=FIXER_SYSTEM_PROMPT)
            return resp
        except Exception as e:
            print(f"❌ [Fixer Agent] AI repair failed: {e}. Falling back to hardcoded defaults.")
            return self._hardcoded_fallback(original_request, worker_type)

    def _hardcoded_fallback(self, req: Dict[str, Any], worker_type: str) -> Dict[str, Any]:
        city = req.get("city", "riyadh").lower()
        coords = CITY_COORDS.get(city, {"lat": 24.7, "lng": 46.7})
        
        if worker_type == "Transport":
            return {
                "action": "plan_timeline",
                "status": "success",
                "timeline": {
                    "1": {"legs": [], "day_cost": 50, "recommendation": "Using default transport due to tool error."}
                },
                "total_transit_cost": 50,
                "simulation_routes": {"1": [{"name": city.title(), "lat": coords["lat"], "lng": coords["lng"], "type": "origin"}]},
                "full_trip_dataset": [],
                "inter_city_travel_time_str": "4h (Est)"
            }
        elif worker_type == "Hospitality":
            return {
                "hotels": [
                    {"id": "fix_1", "name": f"Comfort Stay {city.title()}", "stars": 4, "lat": coords["lat"] + 0.01, "lng": coords["lng"] + 0.01, "best_deal": {"final_price_sar": 350, "discount_percent": 10, "base_price_sar": 388}}
                ],
                "restaurants": [
                    {"name": f"Local Kitchen {city.title()}", "rating": 4.5, "available_tables": 5, "total_tables": 20}
                ]
            }
        return {}
