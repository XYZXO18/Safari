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
GEMINI_MODEL = "gemini-2.5-flash"

# Local AI Configuration (Ollama) — used as fallback when Gemini is unavailable.
# The new safari/ai_client.py handles the priority: Gemini first → Ollama fallback.
# USE_LOCAL_AI is kept for backward compatibility with modules not yet migrated.
USE_LOCAL_AI = os.getenv("USE_LOCAL_AI", "True").lower() in ("true", "1", "yes")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

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
# Fuel efficiency by vehicle type (km per liter — used in cost calculations)
# Based on real-world Saudi highway driving figures
VEHICLE_KM_PER_LITER = {
    "sedan":   13.0,   # e.g. Toyota Camry, Hyundai Sonata
    "suv":     10.0,   # e.g. Toyota Prado, Hyundai Tucson
    "truck":    8.0,   # e.g. Toyota Hilux, Ford F-150 4x4 (desert-spec)
    "4x4":      8.0,   # alias for truck
    "default": 12.0,   # generic passenger car
}

# Legacy alias kept for backward-compat (liters per 100 km — NOT used in fuel.py)
FUEL_CONSUMPTION = {
    "sedan": 7.7,   # ≈ 13 km/L
    "suv":  10.0,   # ≈ 10 km/L
    "truck": 12.5,  # ≈ 8  km/L
    "default": 8.3, # ≈ 12 km/L
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
# All distances verified against Google Maps Saudi Arabia road routes
ROUTES = {
    # ── Riyadh departures ────────────────────────────────────────────────────
    ("riyadh", "jeddah"):        950,
    ("riyadh", "dammam"):        400,
    ("riyadh", "abha"):          950,
    ("riyadh", "al-ula"):       1100,   # ✅ ~1,100 km via Hail highway
    ("riyadh", "yanbu"):        1050,
    ("riyadh", "taif"):          800,
    ("riyadh", "medina"):        850,
    ("riyadh", "tabuk"):        1300,
    ("riyadh", "hail"):          670,
    ("riyadh", "edge of the world"): 100,  # Day-trip distance west of Riyadh
    ("riyadh", "empty quarter fringe"): 650,

    # ── Jeddah departures ───────────────────────────────────────────────────
    ("jeddah", "taif"):          170,
    ("jeddah", "yanbu"):         325,
    ("jeddah", "medina"):        420,
    ("jeddah", "abha"):          600,
    ("jeddah", "al-ula"):        600,   # via Medina

    # ── Eastern Region ──────────────────────────────────────────────────────
    ("dammam", "al-ahsa"):       150,
    ("dammam", "jubail"):         90,

    # ── Vibe-based defaults (used when only a vibe name is given) ───────────
    ("riyadh", "the coast"):     500,
    ("riyadh", "coast"):         500,
    ("default", "coast"):        500,
    ("default", "mountains"):    700,
    ("default", "desert"):      1100,   # ✅ Fixed: Al-Ula is the flagship desert dest
    ("default", "city"):           0,
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
            "Historical downtown walking tour",
            "Marina promenade stroll",
            "Visit coastal landmarks",
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
            "Nature reserve walking trail",
            "Historic fort exploration",
            "Valley viewpoint hike",
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
            "Oasis heritage walking tour",
            "Ancient tombs sightseeing",
            "Desert canyon hike",
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
            "City center landmark walk",
            "National museum visit",
            "Historical palaces walking tour",
            "Modern architecture sightseeing",
        ],
        "avg_hotel_sar": 450,
        "avg_meal_sar": 75,
    },
}

# ─── City → Vibe resolver ────────────────────────────────────────────────────
# Used when the user picks a specific city instead of a vibe category.
CITY_TO_VIBE = {
    "jeddah":   "coast",
    "yanbu":    "coast",
    "umluj":    "coast",
    "al lith":  "coast",
    "abha":     "mountains",
    "taif":     "mountains",
    "al baha":  "mountains",
    "al-ula":   "desert",
    "riyadh":   "city",
    "dammam":   "city",
    "medina":   "city",
    "madinah":  "city",
    "makkah":   "city",
    "tabuk":    "desert",
    "hail":     "desert",
}

# ─── City Coordinates (lat, lng) ─────────────────────────────────────────────
# ─── Airport Mapping ────────────────────────────────────────────────────────
# Maps every known city to the nearest airport city.
# Cities that ARE airports map to themselves (distance 0).
# Cities without a direct airport map to the nearest hub.
AIRPORTS = {
    # ── Cities with their own commercial airport ──────────────────────────────
    "riyadh":   {"airport_city": "riyadh",  "iata": "RUH", "name": "King Khalid Intl",           "km_to_airport": 0},
    "jeddah":   {"airport_city": "jeddah",  "iata": "JED", "name": "King Abdulaziz Intl",         "km_to_airport": 0},
    "dammam":   {"airport_city": "dammam",  "iata": "DMM", "name": "King Fahd Intl",              "km_to_airport": 0},
    "abha":     {"airport_city": "abha",    "iata": "AHB", "name": "Abha Regional Airport",       "km_to_airport": 0},
    "al-ula":   {"airport_city": "al-ula",  "iata": "ULH", "name": "Prince Abdul Majeed Airport", "km_to_airport": 0},
    "yanbu":    {"airport_city": "yanbu",   "iata": "YNB", "name": "Prince Abdul Mohsen Airport", "km_to_airport": 0},
    "taif":     {"airport_city": "taif",    "iata": "TIF", "name": "Taif Regional Airport",       "km_to_airport": 0},
    "medina":   {"airport_city": "medina",  "iata": "MED", "name": "Prince Mohammad bin Abdulaziz Airport", "km_to_airport": 0},
    "tabuk":    {"airport_city": "tabuk",   "iata": "TUU", "name": "Tabuk Regional Airport",      "km_to_airport": 0},
    # ── Cities without a direct airport — nearest hub ─────────────────────────
    "makkah":   {"airport_city": "jeddah",  "iata": "JED", "name": "King Abdulaziz Intl (nearest)", "km_to_airport": 85},
    "umluj":    {"airport_city": "yanbu",   "iata": "YNB", "name": "Prince Abdul Mohsen Airport (nearest)", "km_to_airport": 170},
    "al baha":  {"airport_city": "taif",    "iata": "TIF", "name": "Taif Regional Airport (nearest)", "km_to_airport": 100},
    "al lith":  {"airport_city": "jeddah",  "iata": "JED", "name": "King Abdulaziz Intl (nearest)", "km_to_airport": 145},
    "jubail":   {"airport_city": "dammam",  "iata": "DMM", "name": "King Fahd Intl (nearest)",    "km_to_airport": 100},
    "al-ahsa":  {"airport_city": "dammam",  "iata": "DMM", "name": "King Fahd Intl (nearest)",    "km_to_airport": 155},
    # ── Vibe defaults → nearest hub ──────────────────────────────────────────
    "coast":     {"airport_city": "jeddah",  "iata": "JED", "name": "King Abdulaziz Intl",        "km_to_airport": 0},
    "mountains": {"airport_city": "abha",    "iata": "AHB", "name": "Abha Regional Airport",      "km_to_airport": 0},
    "desert":    {"airport_city": "al-ula",  "iata": "ULH", "name": "Prince Abdul Majeed Airport","km_to_airport": 0},
    "city":      {"airport_city": "riyadh",  "iata": "RUH", "name": "King Khalid Intl",           "km_to_airport": 0},
}

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
