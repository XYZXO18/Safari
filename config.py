"""
Safari Configuration
====================
Central configuration for the Safari travel agent.
Loads environment variables and defines system-wide constants.
Supports worldwide destinations with land-border car-travel validation.
"""

import json
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

# Car rental daily rate in SAR (approximate) by country
CAR_RENTAL_DAILY_RATE_SAR = {
    "saudi arabia": 120,
    "united arab emirates": 150,
    "qatar": 130,
    "oman": 110,
    "jordan": 100,
    "egypt": 80,
    "morocco": 90,
    "france": 200,
    "germany": 190,
    "italy": 185,
    "spain": 175,
    "united kingdom": 210,
    "switzerland": 230,
    "netherlands": 180,
    "austria": 180,
    "belgium": 175,
    "portugal": 160,
    "greece": 155,
    "croatia": 150,
    "czechia": 140,
    "sweden": 195,
    "norway": 210,
    "denmark": 195,
    "united states": 220,
    "canada": 210,
    "mexico": 130,
    "japan": 200,
    "south korea": 185,
    "china": 160,
    "india": 90,
    "thailand": 110,
    "indonesia": 100,
    "malaysia": 105,
    "singapore": 190,
    "australia": 195,
    "new zealand": 185,
    "south africa": 115,
    "kenya": 100,
    "tanzania": 100,
    "brazil": 130,
    "argentina": 110,
    "colombia": 100,
    "peru": 95,
    "chile": 115,
    "default": 120,
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

# ─── Country → Best tourist/capital city (used when user searches by country) ─
COUNTRY_TO_DEFAULT_CITY: dict = {
    # Europe
    "austria": "vienna",
    "belgium": "brussels",
    "croatia": "dubrovnik",
    "czechia": "prague",
    "czech republic": "prague",
    "denmark": "copenhagen",
    "france": "paris",
    "germany": "berlin",
    "greece": "athens",
    "iceland": "reykjavik",
    "ireland": "dublin",
    "italy": "rome",
    "netherlands": "amsterdam",
    "norway": "oslo",
    "portugal": "lisbon",
    "spain": "madrid",
    "sweden": "stockholm",
    "switzerland": "zurich",
    "united kingdom": "london",
    "uk": "london",
    "england": "london",
    # Asia
    "china": "beijing",
    "india": "new delhi",
    "indonesia": "bali",
    "japan": "tokyo",
    "malaysia": "kuala lumpur",
    "maldives": "malé",
    "philippines": "manila",
    "singapore": "singapore",
    "south korea": "seoul",
    "korea": "seoul",
    "sri lanka": "colombo",
    "thailand": "bangkok",
    "vietnam": "hanoi",
    # Middle East & Africa
    "egypt": "cairo",
    "jordan": "amman",
    "kenya": "nairobi",
    "mauritius": "port louis",
    "morocco": "marrakech",
    "oman": "muscat",
    "qatar": "doha",
    "saudi arabia": "riyadh",
    "seychelles": "victoria",
    "south africa": "cape town",
    "tanzania": "zanzibar",
    "uae": "dubai",
    "united arab emirates": "dubai",
    # Americas
    "canada": "toronto",
    "costa rica": "san josé",
    "cuba": "havana",
    "dominican republic": "punta cana",
    "jamaica": "montego bay",
    "mexico": "mexico city",
    "panama": "panama city",
    "usa": "new york",
    "united states": "new york",
    "us": "new york",
    "america": "new york",
    "argentina": "buenos aires",
    "brazil": "rio de janeiro",
    "chile": "santiago",
    "colombia": "cartagena",
    "ecuador": "quito",
    "peru": "cusco",
    # Oceania
    "australia": "sydney",
    "fiji": "nadi",
    "new zealand": "queenstown",
}

# ─── Worldwide Geography: City → Country ─────────────────────────────────────
CITY_TO_COUNTRY: dict = {
    # Saudi Arabia
    "riyadh": "saudi arabia", "jeddah": "saudi arabia", "dammam": "saudi arabia",
    "abha": "saudi arabia", "al-ula": "saudi arabia", "alula": "saudi arabia",
    "yanbu": "saudi arabia", "taif": "saudi arabia", "medina": "saudi arabia",
    "madinah": "saudi arabia", "makkah": "saudi arabia", "tabuk": "saudi arabia",
    "hail": "saudi arabia", "umluj": "saudi arabia", "al lith": "saudi arabia",
    "al baha": "saudi arabia", "jubail": "saudi arabia", "al-ahsa": "saudi arabia",
    "edge of the world": "saudi arabia", "empty quarter fringe": "saudi arabia",
    # Europe
    "vienna": "austria", "salzburg": "austria", "innsbruck": "austria",
    "brussels": "belgium", "bruges": "belgium", "antwerp": "belgium",
    "dubrovnik": "croatia", "split": "croatia", "zagreb": "croatia",
    "prague": "czechia", "brno": "czechia", "český krumlov": "czechia",
    "copenhagen": "denmark", "aarhus": "denmark",
    "paris": "france", "nice": "france", "lyon": "france", "bordeaux": "france",
    "berlin": "germany", "munich": "germany", "frankfurt": "germany", "hamburg": "germany",
    "athens": "greece", "santorini": "greece", "mykonos": "greece", "crete": "greece",
    "reykjavik": "iceland", "akureyri": "iceland",
    "dublin": "ireland", "galway": "ireland", "cork": "ireland",
    "rome": "italy", "florence": "italy", "venice": "italy", "milan": "italy", "naples": "italy",
    "amsterdam": "netherlands", "rotterdam": "netherlands", "utrecht": "netherlands",
    "oslo": "norway", "bergen": "norway", "tromsø": "norway",
    "lisbon": "portugal", "porto": "portugal", "faro": "portugal",
    "madrid": "spain", "barcelona": "spain", "seville": "spain", "valencia": "spain",
    "stockholm": "sweden", "gothenburg": "sweden",
    "zurich": "switzerland", "geneva": "switzerland", "lucerne": "switzerland", "bern": "switzerland",
    "london": "united kingdom", "edinburgh": "united kingdom",
    "manchester": "united kingdom", "bath": "united kingdom",
    # Asia
    "beijing": "china", "shanghai": "china", "xi'an": "china",
    "new delhi": "india", "mumbai": "india", "jaipur": "india", "goa": "india",
    "bali": "indonesia", "jakarta": "indonesia", "yogyakarta": "indonesia",
    "tokyo": "japan", "kyoto": "japan", "osaka": "japan", "sapporo": "japan",
    "kuala lumpur": "malaysia", "penang": "malaysia", "langkawi": "malaysia",
    "malé": "maldives",
    "manila": "philippines", "cebu": "philippines", "palawan": "philippines",
    "singapore": "singapore",
    "seoul": "south korea", "busan": "south korea", "jeju island": "south korea",
    "colombo": "sri lanka", "kandy": "sri lanka", "galle": "sri lanka",
    "bangkok": "thailand", "phuket": "thailand", "chiang mai": "thailand",
    "hanoi": "vietnam", "ho chi minh city": "vietnam", "da nang": "vietnam",
    # Middle East & Africa
    "cairo": "egypt", "luxor": "egypt", "sharm el sheikh": "egypt",
    "amman": "jordan", "petra": "jordan", "aqaba": "jordan",
    "nairobi": "kenya", "mombasa": "kenya",
    "port louis": "mauritius",
    "marrakech": "morocco", "casablanca": "morocco", "fes": "morocco", "chefchaouen": "morocco",
    "muscat": "oman", "salalah": "oman",
    "doha": "qatar",
    "cape town": "south africa", "johannesburg": "south africa", "durban": "south africa",
    "dar es salaam": "tanzania", "zanzibar": "tanzania", "arusha": "tanzania",
    "dubai": "united arab emirates", "abu dhabi": "united arab emirates",
    "victoria": "seychelles",
    # Americas
    "toronto": "canada", "vancouver": "canada", "montreal": "canada", "banff": "canada",
    "san josé": "costa rica", "liberia": "costa rica", "tamarindo": "costa rica",
    "havana": "cuba", "varadero": "cuba",
    "punta cana": "dominican republic", "santo domingo": "dominican republic",
    "montego bay": "jamaica", "kingston": "jamaica",
    "mexico city": "mexico", "cancún": "mexico", "cancun": "mexico",
    "são paulo": "brazil", "sao paulo": "brazil",
    "rio de janeiro": "brazil",
    "buenos aires": "argentina",
    "valparaíso": "chile", "valparaiso": "chile",
    "tulum": "mexico", "oaxaca": "mexico",
    "panama city": "panama",
    "new york": "united states", "los angeles": "united states", "miami": "united states",
    "chicago": "united states", "las vegas": "united states",
    "buenos aires": "argentina", "mendoza": "argentina",
    "rio de janeiro": "brazil", "são paulo": "brazil", "salvador": "brazil",
    "santiago": "chile", "valparaíso": "chile",
    "bogotá": "colombia", "bogota": "colombia",
    "medellín": "colombia", "medellin": "colombia", "cartagena": "colombia",
    "quito": "ecuador", "guayaquil": "ecuador",
    "lima": "peru", "cusco": "peru", "arequipa": "peru",
    # Oceania
    "sydney": "australia", "melbourne": "australia", "brisbane": "australia", "perth": "australia",
    "nadi": "fiji", "suva": "fiji",
    "auckland": "new zealand", "wellington": "new zealand", "queenstown": "new zealand",
}

# Countries that share direct land borders (bilateral — both sides listed)
COUNTRY_BORDERS: dict = {
    "austria": {"germany", "switzerland", "czechia", "italy", "croatia", "slovenia", "hungary"},
    "belgium": {"france", "germany", "netherlands", "luxembourg"},
    "croatia": {"austria", "slovenia", "hungary", "serbia", "bosnia and herzegovina"},
    "czechia": {"austria", "germany", "poland", "slovakia"},
    "denmark": {"germany", "sweden"},
    "france": {"belgium", "germany", "switzerland", "italy", "spain", "luxembourg", "andorra"},
    "germany": {"austria", "belgium", "czechia", "denmark", "france", "netherlands", "switzerland", "poland"},
    "greece": {"bulgaria", "north macedonia", "albania", "turkey"},
    "iceland": set(),
    "ireland": {"united kingdom"},
    "italy": {"austria", "france", "switzerland", "slovenia"},
    "netherlands": {"belgium", "germany"},
    "norway": {"sweden", "finland", "russia"},
    "portugal": {"spain"},
    "spain": {"france", "portugal", "andorra"},
    "sweden": {"norway", "finland", "denmark"},
    "switzerland": {"austria", "france", "germany", "italy"},
    "united kingdom": {"ireland"},
    # Asia
    "china": {"russia", "mongolia", "kazakhstan", "india", "nepal", "myanmar", "laos", "vietnam", "north korea"},
    "india": {"china", "nepal", "bhutan", "bangladesh", "myanmar", "pakistan"},
    "indonesia": set(),
    "japan": set(),
    "malaysia": {"thailand", "singapore"},
    "maldives": set(),
    "philippines": set(),
    "singapore": {"malaysia"},
    "south korea": set(),
    "sri lanka": set(),
    "thailand": {"malaysia", "myanmar", "laos", "cambodia"},
    "vietnam": {"china", "laos", "cambodia"},
    # Middle East & Africa
    "egypt": {"libya", "sudan", "israel"},
    "jordan": {"saudi arabia", "iraq", "syria", "israel"},
    "kenya": {"tanzania", "uganda", "south sudan", "ethiopia", "somalia"},
    "mauritius": set(),
    "morocco": {"algeria", "mauritania"},
    "oman": {"saudi arabia", "united arab emirates", "yemen"},
    "qatar": {"saudi arabia"},
    "saudi arabia": {"jordan", "iraq", "kuwait", "united arab emirates", "oman", "yemen"},
    "seychelles": set(),
    "south africa": {"namibia", "botswana", "zimbabwe", "mozambique", "eswatini", "lesotho"},
    "tanzania": {"kenya", "uganda", "rwanda", "burundi", "zambia", "malawi", "mozambique"},
    "united arab emirates": {"saudi arabia", "oman"},
    # Americas
    "canada": {"united states"},
    "costa rica": {"panama", "nicaragua"},
    "cuba": set(),
    "dominican republic": {"haiti"},
    "jamaica": set(),
    "mexico": {"united states", "guatemala", "belize"},
    "panama": {"costa rica", "colombia"},
    "united states": {"canada", "mexico"},
    "argentina": {"chile", "bolivia", "paraguay", "uruguay", "brazil"},
    "brazil": {"argentina", "bolivia", "colombia", "ecuador", "peru", "paraguay", "uruguay", "venezuela", "guyana", "suriname"},
    "chile": {"argentina", "bolivia", "peru"},
    "colombia": {"brazil", "ecuador", "panama", "peru", "venezuela"},
    "ecuador": {"colombia", "peru"},
    "peru": {"brazil", "bolivia", "chile", "colombia", "ecuador"},
    # Oceania
    "australia": set(),
    "fiji": set(),
    "new zealand": set(),
}


def can_travel_by_car(origin_city: str, destination_city: str) -> tuple:
    """
    Returns (possible: bool, reason: str).
    Car is possible only if both cities are in the same country, or their
    countries share a direct land border.
    """
    o = origin_city.lower().strip()
    d = destination_city.lower().strip()

    origin_country = CITY_TO_COUNTRY.get(o)
    dest_country = CITY_TO_COUNTRY.get(d)

    if not origin_country or not dest_country:
        return True, "Countries unknown — car travel assumed possible."

    if origin_country == dest_country:
        return True, f"Both cities are in {origin_country.title()}."

    neighbors = COUNTRY_BORDERS.get(origin_country, set())
    if dest_country in neighbors:
        return True, f"{origin_country.title()} and {dest_country.title()} share a land border."

    return False, (
        f"Car travel is not possible: {origin_country.title()} and {dest_country.title()} "
        f"do not share a land border. Please choose flight, train, or bus instead."
    )


# ─── Auto-geocoding for unknown cities ───────────────────────────────────────

_EXTRA_COORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "city_coords.json")


def _fetch_coords_nominatim(city: str) -> dict:
    """Look up city coordinates from Nominatim (OpenStreetMap). Free, no key."""
    try:
        import requests as _req
        # Use country hint if we know it, otherwise search globally
        country = CITY_TO_COUNTRY.get(city.lower().strip(), "")
        query = f"{city}, {country}" if country else city
        resp = _req.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "SafariTravelApp/1.0"},
            timeout=10,
        )
        data = resp.json()
        if data:
            return {"lat": round(float(data[0]["lat"]), 4), "lng": round(float(data[0]["lon"]), 4)}
    except Exception as e:
        print(f"[GeoCache] Nominatim lookup failed for '{city}': {e}")
    return {}


class _AutoCoordDict(dict):
    """
    Dict that auto-fetches coordinates for unknown cities via Nominatim
    and persists them to data/city_coords.json so they are never re-fetched.
    All existing CITY_COORDS.get() / CITY_COORDS[city] calls work transparently.
    """

    def get(self, key, default=None):
        key = key.lower().strip() if isinstance(key, str) else key
        if super().__contains__(key):
            return super().__getitem__(key)
        fetched = self._resolve(key)
        if fetched:
            return fetched
        return default if default is not None else None

    def __missing__(self, key):
        key = key.lower().strip() if isinstance(key, str) else key
        fetched = self._resolve(key)
        return fetched if fetched else None

    def _resolve(self, key: str) -> dict:
        coords = _fetch_coords_nominatim(key)
        if coords:
            self[key] = coords
            try:
                extra = {}
                if os.path.exists(_EXTRA_COORDS_FILE):
                    with open(_EXTRA_COORDS_FILE, encoding="utf-8") as f:
                        extra = json.load(f)
                extra[key] = coords
                os.makedirs(os.path.dirname(_EXTRA_COORDS_FILE), exist_ok=True)
                with open(_EXTRA_COORDS_FILE, "w", encoding="utf-8") as f:
                    json.dump(extra, f, indent=2, ensure_ascii=False)
                print(f"[GeoCache] Auto-fetched and saved coords for '{key}': {coords}")
            except Exception as e:
                print(f"[GeoCache] Failed to persist coords for '{key}': {e}")
        return coords


CITY_COORDS = _AutoCoordDict({
    # Saudi Arabia
    "riyadh":   {"lat": 24.7136, "lng": 46.6753},
    "jeddah":   {"lat": 21.4858, "lng": 39.1925},
    "dammam":   {"lat": 26.4207, "lng": 50.0888},
    "abha":     {"lat": 18.2164, "lng": 42.5053},
    "al-ula":   {"lat": 26.6086, "lng": 37.9211},
    "alula":    {"lat": 26.6086, "lng": 37.9211},
    "yanbu":    {"lat": 24.0895, "lng": 38.0618},
    "taif":     {"lat": 21.2703, "lng": 40.4158},
    "medina":   {"lat": 24.4672, "lng": 39.6024},
    "madinah":  {"lat": 24.4672, "lng": 39.6024},
    "makkah":   {"lat": 21.3891, "lng": 39.8579},
    "tabuk":    {"lat": 28.3835, "lng": 36.5662},
    "hail":     {"lat": 27.5114, "lng": 41.7208},
    "umluj":    {"lat": 25.0542, "lng": 37.2639},
    "al lith":  {"lat": 20.1500, "lng": 40.2700},
    "al baha":  {"lat": 20.0000, "lng": 41.4667},
    "jubail":   {"lat": 27.0046, "lng": 49.6225},
    "al-ahsa":  {"lat": 25.3800, "lng": 49.5860},
    # Europe
    "vienna":       {"lat": 48.2082, "lng": 16.3738},
    "salzburg":     {"lat": 47.8095, "lng": 13.0550},
    "innsbruck":    {"lat": 47.2692, "lng": 11.4041},
    "brussels":     {"lat": 50.8503, "lng": 4.3517},
    "bruges":       {"lat": 51.2093, "lng": 3.2247},
    "antwerp":      {"lat": 51.2194, "lng": 4.4025},
    "dubrovnik":    {"lat": 42.6507, "lng": 18.0944},
    "split":        {"lat": 43.5081, "lng": 16.4402},
    "zagreb":       {"lat": 45.8150, "lng": 15.9819},
    "prague":       {"lat": 50.0755, "lng": 14.4378},
    "brno":         {"lat": 49.1951, "lng": 16.6068},
    "copenhagen":   {"lat": 55.6761, "lng": 12.5683},
    "paris":        {"lat": 48.8566, "lng": 2.3522},
    "nice":         {"lat": 43.7102, "lng": 7.2620},
    "lyon":         {"lat": 45.7640, "lng": 4.8357},
    "bordeaux":     {"lat": 44.8378, "lng": -0.5792},
    "berlin":       {"lat": 52.5200, "lng": 13.4050},
    "munich":       {"lat": 48.1351, "lng": 11.5820},
    "frankfurt":    {"lat": 50.1109, "lng": 8.6821},
    "hamburg":      {"lat": 53.5753, "lng": 10.0153},
    "athens":       {"lat": 37.9838, "lng": 23.7275},
    "santorini":    {"lat": 36.3932, "lng": 25.4615},
    "mykonos":      {"lat": 37.4467, "lng": 25.3289},
    "crete":        {"lat": 35.2401, "lng": 24.8093},
    "reykjavik":    {"lat": 64.1355, "lng": -21.8954},
    "dublin":       {"lat": 53.3498, "lng": -6.2603},
    "galway":       {"lat": 53.2707, "lng": -9.0568},
    "cork":         {"lat": 51.8985, "lng": -8.4756},
    "rome":         {"lat": 41.9028, "lng": 12.4964},
    "florence":     {"lat": 43.7696, "lng": 11.2558},
    "venice":       {"lat": 45.4408, "lng": 12.3155},
    "milan":        {"lat": 45.4642, "lng": 9.1900},
    "naples":       {"lat": 40.8518, "lng": 14.2681},
    "amsterdam":    {"lat": 52.3676, "lng": 4.9041},
    "rotterdam":    {"lat": 51.9244, "lng": 4.4777},
    "oslo":         {"lat": 59.9139, "lng": 10.7522},
    "bergen":       {"lat": 60.3913, "lng": 5.3221},
    "lisbon":       {"lat": 38.7223, "lng": -9.1393},
    "porto":        {"lat": 41.1579, "lng": -8.6291},
    "faro":         {"lat": 37.0194, "lng": -7.9322},
    "madrid":       {"lat": 40.4168, "lng": -3.7038},
    "barcelona":    {"lat": 41.3851, "lng": 2.1734},
    "seville":      {"lat": 37.3891, "lng": -5.9845},
    "valencia":     {"lat": 39.4699, "lng": -0.3763},
    "stockholm":    {"lat": 59.3293, "lng": 18.0686},
    "gothenburg":   {"lat": 57.7089, "lng": 11.9746},
    "zurich":       {"lat": 47.3769, "lng": 8.5417},
    "geneva":       {"lat": 46.2044, "lng": 6.1432},
    "lucerne":      {"lat": 47.0502, "lng": 8.3093},
    "bern":         {"lat": 46.9480, "lng": 7.4474},
    "london":       {"lat": 51.5074, "lng": -0.1278},
    "edinburgh":    {"lat": 55.9533, "lng": -3.1883},
    "manchester":   {"lat": 53.4808, "lng": -2.2426},
    "bath":         {"lat": 51.3811, "lng": -2.3590},
    # Asia
    "beijing":         {"lat": 39.9042, "lng": 116.4074},
    "shanghai":        {"lat": 31.2304, "lng": 121.4737},
    "xi'an":           {"lat": 34.3416, "lng": 108.9398},
    "new delhi":       {"lat": 28.6139, "lng": 77.2090},
    "mumbai":          {"lat": 19.0760, "lng": 72.8777},
    "jaipur":          {"lat": 26.9124, "lng": 75.7873},
    "goa":             {"lat": 15.2993, "lng": 74.1240},
    "bali":            {"lat": -8.3405, "lng": 115.0920},
    "jakarta":         {"lat": -6.2088, "lng": 106.8456},
    "yogyakarta":      {"lat": -7.7956, "lng": 110.3695},
    "tokyo":           {"lat": 35.6762, "lng": 139.6503},
    "kyoto":           {"lat": 35.0116, "lng": 135.7681},
    "osaka":           {"lat": 34.6937, "lng": 135.5023},
    "sapporo":         {"lat": 43.0618, "lng": 141.3545},
    "kuala lumpur":    {"lat": 3.1390, "lng": 101.6869},
    "penang":          {"lat": 5.4141, "lng": 100.3288},
    "langkawi":        {"lat": 6.3500, "lng": 99.8000},
    "malé":            {"lat": 4.1755, "lng": 73.5093},
    "manila":          {"lat": 14.5995, "lng": 120.9842},
    "cebu":            {"lat": 10.3157, "lng": 123.8854},
    "palawan":         {"lat": 9.8349, "lng": 118.7384},
    "singapore":       {"lat": 1.3521, "lng": 103.8198},
    "seoul":           {"lat": 37.5665, "lng": 126.9780},
    "busan":           {"lat": 35.1796, "lng": 129.0756},
    "jeju island":     {"lat": 33.4996, "lng": 126.5312},
    "colombo":         {"lat": 6.9271, "lng": 79.8612},
    "kandy":           {"lat": 7.2906, "lng": 80.6337},
    "galle":           {"lat": 6.0535, "lng": 80.2210},
    "bangkok":         {"lat": 13.7563, "lng": 100.5018},
    "phuket":          {"lat": 7.8804, "lng": 98.3923},
    "chiang mai":      {"lat": 18.7883, "lng": 98.9853},
    "hanoi":           {"lat": 21.0285, "lng": 105.8542},
    "ho chi minh city":{"lat": 10.8231, "lng": 106.6297},
    "da nang":         {"lat": 16.0544, "lng": 108.2022},
    # Middle East & Africa
    "cairo":           {"lat": 30.0444, "lng": 31.2357},
    "luxor":           {"lat": 25.6872, "lng": 32.6396},
    "sharm el sheikh": {"lat": 27.9158, "lng": 34.3300},
    "amman":           {"lat": 31.9454, "lng": 35.9284},
    "petra":           {"lat": 30.3285, "lng": 35.4444},
    "aqaba":           {"lat": 29.5269, "lng": 35.0078},
    "nairobi":         {"lat": -1.2921, "lng": 36.8219},
    "mombasa":         {"lat": -4.0435, "lng": 39.6682},
    "port louis":      {"lat": -20.1609, "lng": 57.4989},
    "marrakech":       {"lat": 31.6295, "lng": -7.9811},
    "casablanca":      {"lat": 33.5731, "lng": -7.5898},
    "fes":             {"lat": 34.0181, "lng": -5.0078},
    "chefchaouen":     {"lat": 35.1688, "lng": -5.2690},
    "muscat":          {"lat": 23.5880, "lng": 58.3829},
    "salalah":         {"lat": 17.0151, "lng": 54.0924},
    "doha":            {"lat": 25.2854, "lng": 51.5310},
    "cape town":       {"lat": -33.9249, "lng": 18.4241},
    "johannesburg":    {"lat": -26.2041, "lng": 28.0473},
    "durban":          {"lat": -29.8587, "lng": 31.0218},
    "dar es salaam":   {"lat": -6.7924, "lng": 39.2083},
    "zanzibar":        {"lat": -6.1659, "lng": 39.1989},
    "arusha":          {"lat": -3.3869, "lng": 36.6830},
    "dubai":           {"lat": 25.2048, "lng": 55.2708},
    "abu dhabi":       {"lat": 24.4539, "lng": 54.3773},
    "victoria":        {"lat": -4.6191, "lng": 55.4513},
    # Americas
    "toronto":         {"lat": 43.6532, "lng": -79.3832},
    "vancouver":       {"lat": 49.2827, "lng": -123.1207},
    "montreal":        {"lat": 45.5017, "lng": -73.5673},
    "banff":           {"lat": 51.1784, "lng": -115.5708},
    "san josé":        {"lat": 9.9281, "lng": -84.0907},
    "havana":          {"lat": 23.1136, "lng": -82.3666},
    "varadero":        {"lat": 23.1536, "lng": -81.2514},
    "punta cana":      {"lat": 18.5601, "lng": -68.3725},
    "santo domingo":   {"lat": 18.4861, "lng": -69.9312},
    "montego bay":     {"lat": 18.4762, "lng": -77.8939},
    "kingston":        {"lat": 17.9970, "lng": -76.7936},
    "mexico city":     {"lat": 19.4326, "lng": -99.1332},
    "cancún":          {"lat": 21.1619, "lng": -86.8515},
    "cancun":          {"lat": 21.1619, "lng": -86.8515},
    "tulum":           {"lat": 20.2114, "lng": -87.4654},
    "oaxaca":          {"lat": 17.0732, "lng": -96.7266},
    "panama city":     {"lat": 8.9936, "lng": -79.5197},
    "new york":        {"lat": 40.7128, "lng": -74.0060},
    "los angeles":     {"lat": 34.0522, "lng": -118.2437},
    "miami":           {"lat": 25.7617, "lng": -80.1918},
    "chicago":         {"lat": 41.8781, "lng": -87.6298},
    "las vegas":       {"lat": 36.1699, "lng": -115.1398},
    "buenos aires":    {"lat": -34.6037, "lng": -58.3816},
    "mendoza":         {"lat": -32.8908, "lng": -68.8272},
    "rio de janeiro":  {"lat": -22.9068, "lng": -43.1729},
    "são paulo":       {"lat": -23.5505, "lng": -46.6333},
    "salvador":        {"lat": -12.9714, "lng": -38.5014},
    "santiago":        {"lat": -33.4489, "lng": -70.6693},
    "valparaíso":      {"lat": -33.0472, "lng": -71.6127},
    "bogotá":          {"lat": 4.7110, "lng": -74.0721},
    "medellín":        {"lat": 6.2442, "lng": -75.5812},
    "cartagena":       {"lat": 10.3910, "lng": -75.4794},
    "quito":           {"lat": -0.1807, "lng": -78.4678},
    "guayaquil":       {"lat": -2.1894, "lng": -79.8891},
    "lima":            {"lat": -12.0464, "lng": -77.0428},
    "cusco":           {"lat": -13.5319, "lng": -71.9675},
    "arequipa":        {"lat": -16.4090, "lng": -71.5375},
    # Oceania
    "sydney":          {"lat": -33.8688, "lng": 151.2093},
    "melbourne":       {"lat": -37.8136, "lng": 144.9631},
    "brisbane":        {"lat": -27.4698, "lng": 153.0251},
    "perth":           {"lat": -31.9505, "lng": 115.8605},
    "nadi":            {"lat": -17.7765, "lng": 177.4356},
    "suva":            {"lat": -18.1248, "lng": 178.4501},
    "auckland":        {"lat": -36.8485, "lng": 174.7633},
    "wellington":      {"lat": -41.2865, "lng": 174.7762},
    "queenstown":      {"lat": -45.0312, "lng": 168.6626},
    # Vibe-based defaults (Saudi Arabia as base)
    "coast":     {"lat": 21.4858, "lng": 39.1925},
    "mountains": {"lat": 18.2164, "lng": 42.5053},
    "desert":    {"lat": 26.6086, "lng": 37.9211},
    "city":      {"lat": 24.7136, "lng": 46.6753},
})

# Merge any previously auto-fetched cities from persistent cache
try:
    if os.path.exists(_EXTRA_COORDS_FILE):
        with open(_EXTRA_COORDS_FILE, encoding="utf-8") as _f:
            for _k, _v in json.load(_f).items():
                if _k not in CITY_COORDS:
                    CITY_COORDS[_k] = _v
except Exception:
    pass
