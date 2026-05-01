import json
import random

def jitter_data(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    key = list(data.keys())[0]
    items = data[key]
    
    for item in items:
        if "lat" in item and "lng" in item:
            # Add between -0.04 and 0.04 to lat/lng (roughly 4-5km radius)
            item["lat"] += random.uniform(-0.04, 0.04)
            item["lng"] += random.uniform(-0.04, 0.04)
            
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

jitter_data('data/hotels.json')
jitter_data('data/restaurants.json')
print("Jitter applied!")
