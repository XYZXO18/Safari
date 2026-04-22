"""
Safari Configuration
====================
Central configuration for the Safari travel agent.
Loads environment variables and defines system-wide constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ─── Model Configuration ─────────────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.0-flash"

# ─── Currency & Locale ───────────────────────────────────────────────────────
DEFAULT_CURRENCY = "SAR"
CURRENCY_SYMBOLS = {
    "SAR": "﷼",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "د.إ",
    "EGP": "E£",
}

# ─── Budget Allocation Ratios ────────────────────────────────────────────────
# After subtracting transport, the remaining budget is split as follows:
BUDGET_RATIOS = {
    "lodging": 0.40,     # 40% → Accommodation
    "food": 0.30,        # 30% → Meals & drinks
    "activities": 0.20,  # 20% → Sightseeing, tours, entertainment
    "buffer": 0.10,      # 10% → Emergency / unexpected expenses
}

# ─── Transport Defaults ─────────────────────────────────────────────────────
# Average fuel consumption (liters per 100 km) by vehicle type
FUEL_CONSUMPTION = {
    "sedan": 8.0,
    "suv": 12.0,
    "truck": 15.0,
    "default": 10.0,
}

# Average fuel price per liter (SAR) by region
FUEL_PRICES_SAR = {
    "saudi_arabia": 2.18,
    "uae": 2.80,
    "egypt": 1.50,
    "jordan": 3.50,
    "default": 2.33,
}

# Rough estimates for non-driving transport (SAR per km)
TRANSPORT_RATES_PER_KM = {
    "flight": 0.45,   # Domestic budget airline estimate
    "train": 0.25,    # Rail estimate
    "bus": 0.15,      # Intercity bus estimate
}

# ─── Common Routes (one-way distances in km) ────────────────────────────────
ROUTES = {
    ("riyadh", "jeddah"): 950,
    ("riyadh", "dammam"): 400,
    ("riyadh", "abha"): 950,
    ("riyadh", "al-ula"): 1000,
    ("riyadh", "yanbu"): 1050,
    ("riyadh", "taif"): 800,
    ("jeddah", "taif"): 170,
    ("jeddah", "yanbu"): 325,
    ("jeddah", "medina"): 420,
    ("jeddah", "abha"): 600,
    ("dammam", "al-ahsa"): 150,
    ("dammam", "jubail"): 90,
    ("riyadh", "the coast"): 500,
    ("riyadh", "coast"): 500,
    ("default", "coast"): 500,
    ("default", "mountains"): 700,
    ("default", "desert"): 300,
}

# ─── Destination Metadata ───────────────────────────────────────────────────
DESTINATIONS = {
    "coast": {
        "cities": ["Jeddah", "Yanbu", "Al Lith", "Umluj"],
        "vibe": "Beach, diving, seafood, Red Sea sunsets",
        "activities": [
            "Snorkeling & diving",
            "Beach camping",
            "Seafood dinner by the shore",
            "Jet ski rental",
            "Corniche walk",
            "Fish market visit",
            "Sunset cruise",
        ],
        "avg_hotel_sar": 350,
        "avg_meal_sar": 60,
    },
    "mountains": {
        "cities": ["Abha", "Al Baha", "Taif"],
        "vibe": "Cool weather, green terraces, adventure, cable cars",
        "activities": [
            "Cable car ride",
            "Mountain hiking",
            "Visit hanging village",
            "Local honey tasting",
            "Flower garden tours",
            "Traditional village walk",
            "Cliff-edge café",
        ],
        "avg_hotel_sar": 300,
        "avg_meal_sar": 50,
    },
    "desert": {
        "cities": ["Al-Ula", "Edge of the World", "Empty Quarter fringe"],
        "vibe": "Stargazing, ancient ruins, off-road, solitude",
        "activities": [
            "Stargazing camp",
            "Off-road dune bashing",
            "Hegra ancient ruins tour",
            "Camel ride",
            "Desert bonfire dinner",
            "Sandboarding",
            "Elephant Rock visit",
        ],
        "avg_hotel_sar": 400,
        "avg_meal_sar": 55,
    },
    "city": {
        "cities": ["Riyadh", "Jeddah", "Dammam"],
        "vibe": "Urban exploration, nightlife, shopping, dining",
        "activities": [
            "Boulevard Riyadh City",
            "Historical Diriyah tour",
            "Fine dining experience",
            "Mall exploration",
            "Art gallery visit",
            "Rooftop café",
            "Local souq haggling",
        ],
        "avg_hotel_sar": 450,
        "avg_meal_sar": 75,
    },
}

# ─── City Coordinates (lat, lng) ─────────────────────────────────────────────
CITY_COORDS = {
    "riyadh":   {"lat": 24.7136, "lng": 46.6753},
    "jeddah":   {"lat": 21.4858, "lng": 39.1925},
    "dammam":   {"lat": 26.4207, "lng": 50.0888},
    "abha":     {"lat": 18.2164, "lng": 42.5053},
    "al-ula":   {"lat": 26.6086, "lng": 37.9211},
    "yanbu":    {"lat": 24.0895, "lng": 38.0618},
    "taif":     {"lat": 21.2703, "lng": 40.4158},
    "medina":   {"lat": 24.4672, "lng": 39.6024},
    "umluj":    {"lat": 25.0542, "lng": 37.2639},
    "al lith":  {"lat": 20.1500, "lng": 40.2700},
    "al baha":  {"lat": 20.0000, "lng": 41.4667},
    "jubail":   {"lat": 27.0046, "lng": 49.6225},
    "al-ahsa":  {"lat": 25.3800, "lng": 49.5860},
    # Vibe-based defaults
    "coast":     {"lat": 21.4858, "lng": 39.1925},
    "mountains": {"lat": 18.2164, "lng": 42.5053},
    "desert":    {"lat": 26.6086, "lng": 37.9211},
    "city":      {"lat": 24.7136, "lng": 46.6753},
}
