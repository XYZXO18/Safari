import sqlite3
import json
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "safari_cache.db")

def get_db_connection():
    """Create a database connection to the SQLite database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with required tables."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        name TEXT NOT NULL,
        event_date TEXT NOT NULL,
        time TEXT,
        estimated_cost_sar REAL,
        category TEXT,
        description TEXT,
        venue TEXT,
        lat REAL,
        lng REAL,
        source TEXT,
        date_added TEXT NOT NULL,
        UNIQUE(city, name, event_date)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS web_research_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        research_date TEXT NOT NULL,
        data_json TEXT NOT NULL,
        UNIQUE(city, research_date)
    )
    ''')

    # Hospitality table — hotels stored with name+location only (no price).
    # Live prices come from Almosafer on every search.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS hospitality (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        type TEXT NOT NULL,           -- 'hotel', 'restaurant', 'cafe'
        name TEXT NOT NULL,
        price REAL,                   -- NULL for hotels (price is live)
        rating REAL,
        stars INTEGER,
        empty_rooms INTEGER,
        cuisine TEXT,
        total_tables INTEGER,
        available_tables INTEGER,
        lat REAL,
        lng REAL,
        last_randomized TEXT,
        UNIQUE(city, type, name)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS public_transit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL UNIQUE,
        data_json TEXT NOT NULL,
        date_added TEXT NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS inter_city_transport (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        origin TEXT NOT NULL,
        destination TEXT NOT NULL,
        mode TEXT NOT NULL,
        data_json TEXT NOT NULL,
        date_added TEXT NOT NULL,
        UNIQUE(origin, destination, mode)
    )
    ''')

    conn.commit()
    conn.close()

# Initialize on import
init_db()


# ─── Event helpers ────────────────────────────────────────────────────────────

def save_event(city, event_data):
    """Save a single event to the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO events
        (city, name, event_date, time, estimated_cost_sar, category, description, venue, lat, lng, source, date_added)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            city.lower(),
            event_data['name'],
            event_data['date'],
            event_data.get('time'),
            event_data.get('estimated_cost_sar', 0),
            event_data.get('category'),
            event_data.get('description'),
            event_data.get('venue'),
            event_data.get('lat'),
            event_data.get('lng'),
            event_data.get('source', 'web_search'),
            date.today().isoformat()
        ))
        conn.commit()
    except Exception as e:
        print(f"Error saving event: {e}")
    finally:
        conn.close()


def get_cached_events(city, start_date, end_date):
    """Retrieve events for a city within a date range."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT * FROM events
    WHERE city = ? AND event_date >= ? AND event_date <= ?
    ''', (city.lower(), start_date, end_date))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_any_events_for_city(city: str, limit: int = 20) -> list:
    """Return all stored events for a city regardless of date (fallback when web search fails)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM events WHERE city = ? ORDER BY date_added DESC LIMIT ?',
        (city.lower(), limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ─── Web research cache ───────────────────────────────────────────────────────

def save_web_research(city, data):
    """Save research data to cache."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO web_research_cache (city, research_date, data_json)
    VALUES (?, ?, ?)
    ''', (city.lower(), date.today().isoformat(), json.dumps(data)))
    conn.commit()
    conn.close()


def get_cached_web_research(city):
    """Retrieve cached research for a city (today only)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT data_json FROM web_research_cache WHERE city = ? AND research_date = ?',
        (city.lower(), date.today().isoformat())
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row['data_json'])
    return None


# ─── Snapshot ────────────────────────────────────────────────────────────────

def create_snapshot():
    """Create a backup snapshot of the database."""
    import shutil
    if os.path.exists(DB_PATH):
        snapshot_name = f"{DB_PATH}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        shutil.copy2(DB_PATH, snapshot_name)
        return snapshot_name
    return None


# ─── Hotel helpers (Almosafer-based) ─────────────────────────────────────────

def upsert_hotel_static(city: str, name: str, lat: float, lng: float,
                        stars: int = 4) -> int:
    """
    Insert a newly discovered hotel into the DB (name + location only, NO price).
    Price is always fetched live from Almosafer at search time.
    Returns the row id (or -1 on error).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO hospitality (city, type, name, stars, lat, lng)
            VALUES (?, 'hotel', ?, ?, ?, ?)
        ''', (city.lower(), name, stars, lat, lng))
        conn.commit()
        cursor.execute(
            'SELECT id FROM hospitality WHERE city=? AND type="hotel" AND name=?',
            (city.lower(), name)
        )
        row = cursor.fetchone()
        return row['id'] if row else -1
    except Exception as e:
        print(f"Error upserting hotel: {e}")
        return -1
    finally:
        conn.close()


def get_hotel_count(city: str) -> int:
    """Return the number of hotels stored for a city."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT COUNT(*) as cnt FROM hospitality WHERE city=? AND type="hotel"',
        (city.lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return row['cnt'] if row else 0


def get_known_hotels(city: str, limit: int = 20) -> list:
    """Return stored hotels for a city (name + location, no price)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM hospitality WHERE city=? AND type="hotel" ORDER BY id LIMIT ?',
        (city.lower(), limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── General hospitality helpers ─────────────────────────────────────────────

def upsert_restaurant_static(
    city: str, name: str, venue_type: str,
    price: float = 80.0, rating: float = 4.0,
    lat: float = 24.7, lng: float = 46.7,
) -> None:
    """Persist a live-fetched restaurant/cafe stub to the DB (INSERT OR IGNORE)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO hospitality (city, type, name, price, rating, lat, lng)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (city.lower(), venue_type, name, price, rating, lat, lng))
        conn.commit()
    except Exception as e:
        print(f"Error upserting venue: {e}")
    finally:
        conn.close()


def get_restaurant_count(city: str) -> int:
    """Return number of restaurants + cafes stored for a city."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT COUNT(*) as cnt FROM hospitality WHERE city=? AND type IN ("restaurant","cafe")',
        (city.lower(),)
    )
    row = cursor.fetchone()
    conn.close()
    return row['cnt'] if row else 0


def get_hospitality(city, type=None):
    """Retrieve hospitality items for a city."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if type:
        cursor.execute(
            'SELECT * FROM hospitality WHERE city = ? AND type = ?',
            (city.lower(), type)
        )
    else:
        cursor.execute('SELECT * FROM hospitality WHERE city = ?', (city.lower(),))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def book_hotel(hotel_id):
    """Decrease empty_rooms count by 1 for the given hotel."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE hospitality SET empty_rooms = MAX(0, empty_rooms - 1) WHERE id = ? AND type = "hotel"',
        (hotel_id,)
    )
    conn.commit()
    conn.close()


# ─── Public Transit Cache ─────────────────────────────────────────────────────

def save_public_transit(city: str, data: list) -> None:
    """Cache public transit options for a city (valid 7 days — prices rarely change)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO public_transit (city, data_json, date_added) VALUES (?, ?, ?)',
        (city.lower(), json.dumps(data), date.today().isoformat())
    )
    conn.commit()
    conn.close()


def get_public_transit(city: str, max_age_days: int = 7) -> list:
    """Return cached public transit for city if within max_age_days, else empty list."""
    from datetime import timedelta
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
    cursor.execute(
        'SELECT data_json FROM public_transit WHERE city = ? AND date_added >= ?',
        (city.lower(), cutoff)
    )
    row = cursor.fetchone()
    conn.close()
    return json.loads(row['data_json']) if row else []


# ─── Inter-city Transport Cache ───────────────────────────────────────────────

def save_inter_city_transport(origin: str, destination: str, mode: str, data: dict) -> None:
    """Cache flight/bus/train search results for a route (valid 1 day)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO inter_city_transport (origin, destination, mode, data_json, date_added) VALUES (?, ?, ?, ?, ?)',
        (origin.lower(), destination.lower(), mode.lower(), json.dumps(data), date.today().isoformat())
    )
    conn.commit()
    conn.close()


def get_inter_city_transport(origin: str, destination: str, mode: str, max_age_days: int = 1) -> dict:
    """Return cached transport data for a route if within max_age_days, else empty dict."""
    from datetime import timedelta
    conn = get_db_connection()
    cursor = conn.cursor()
    cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
    cursor.execute(
        'SELECT data_json FROM inter_city_transport WHERE origin=? AND destination=? AND mode=? AND date_added >= ?',
        (origin.lower(), destination.lower(), mode.lower(), cutoff)
    )
    row = cursor.fetchone()
    conn.close()
    return json.loads(row['data_json']) if row else {}
