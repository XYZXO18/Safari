import sqlite3
import json
import os
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "safari_cache.db")

def get_db_connection():
    """Create a database connection to the SQLite database."""
    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with required tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Events table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        name TEXT NOT NULL,
        event_date TEXT NOT NULL, -- Date the event happens
        time TEXT,
        estimated_cost_sar REAL,
        category TEXT,
        description TEXT,
        venue TEXT,
        lat REAL,
        lng REAL,
        source TEXT,
        date_added TEXT NOT NULL, -- When we added it to our DB
        UNIQUE(city, name, event_date)
    )
    ''')
    
    # Web research cache table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS web_research_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        research_date TEXT NOT NULL,
        data_json TEXT NOT NULL,
        UNIQUE(city, research_date)
    )
    ''')

    # Hospitality table (Hotels and Restaurants)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS hospitality (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT NOT NULL,
        type TEXT NOT NULL, -- 'hotel', 'restaurant', 'cafe'
        name TEXT NOT NULL,
        price REAL,
        rating REAL,
        stars INTEGER, -- For hotels
        empty_rooms INTEGER, -- For hotels
        cuisine TEXT, -- For restaurants/cafes
        total_tables INTEGER, -- For restaurants/cafes
        available_tables INTEGER, -- For restaurants/cafes
        lat REAL,
        lng REAL,
        last_randomized TEXT,
        UNIQUE(city, type, name)
    )
    ''')
    
    conn.commit()
    conn.close()

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
    # Note: This simple comparison works for ISO dates (YYYY-MM-DD)
    cursor.execute('''
    SELECT * FROM events 
    WHERE city = ? AND event_date >= ? AND event_date <= ?
    ''', (city.lower(), start_date, end_date))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_web_research(city, research_data):
    """Save web research results for a city for the current day."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO web_research_cache (city, research_date, data_json)
        VALUES (?, ?, ?)
        ''', (
            city.lower(),
            date.today().isoformat(),
            json.dumps(research_data)
        ))
        conn.commit()
    except Exception as e:
        print(f"Error saving web research: {e}")
    finally:
        conn.close()

def get_cached_web_research(city):
    """Retrieve cached web research for today."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT data_json FROM web_research_cache 
    WHERE city = ? AND research_date = ?
    ''', (city.lower(), date.today().isoformat()))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row['data_json'])
    return None

def create_snapshot():
    """Create a backup snapshot of the database."""
    import shutil
    if os.path.exists(DB_PATH):
        snapshot_name = f"{DB_PATH}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        shutil.copy2(DB_PATH, snapshot_name)
        return snapshot_name
    return None


# Initialize on import
init_db()

def randomize_hospitality(city, force=False):
    """Randomize prices and empty rooms if enough time has passed (e.g., 4 hours)."""
    import random
    from datetime import timedelta
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now()
    
    # Check if city has any hospitality data
    cursor.execute('SELECT last_randomized FROM hospitality WHERE city = ? LIMIT 1', (city.lower(),))
    row = cursor.fetchone()
    
    should_randomize = force
    if row:
        last_rand_str = row['last_randomized']
        if last_rand_str:
            last_rand = datetime.fromisoformat(last_rand_str)
            if now - last_rand > timedelta(hours=4):
                should_randomize = True
    else:
        # Seed the database if empty for this city
        seed_hospitality(city)
        should_randomize = True
        
    if should_randomize:
        cursor.execute('SELECT id, type, price FROM hospitality WHERE city = ?', (city.lower(),))
        items = cursor.fetchall()
        
        for item in items:
            # Randomize price +/- 20%
            new_price = item['price'] * random.uniform(0.8, 1.2)
            # Randomize rooms (1 to 20)
            new_rooms = random.randint(1, 20) if item['type'] == 'hotel' else 0
            
            cursor.execute('''
            UPDATE hospitality SET price = ?, empty_rooms = ?, last_randomized = ?
            WHERE id = ?
            ''', (round(new_price, 2), new_rooms, now.isoformat(), item['id']))
            
        conn.commit()
    
    conn.close()

def seed_hospitality(city):
    """Seed initial data for a city if it doesn't exist."""
    import random
    
    # Sample names for variety
    hotel_names = ["Luxe Palace", "Desert Rose Inn", "Skyline Suites", "The Oasis", "Heritage House", "Royal Palms"]
    rest_names = ["Zaman Flavors", "Al-Najd Grill", "The Red Sea Catch", "Modern Mezze", "Kabsah Kingdom"]
    cafe_names = ["Mocha Dunes", "Saffron Sip", "Date & Bean", "Cloud Cafe"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Simple coordinate jitter around center of city
    # In a real app, we'd use real data, but for this demo we'll use base coords
    from config import CITY_COORDS
    base = CITY_COORDS.get(city.lower(), {"lat": 24.7, "lng": 46.7})
    
    for name in hotel_names:
        cursor.execute('INSERT OR IGNORE INTO hospitality (city, type, name, price, rating, stars, empty_rooms, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (city.lower(), 'hotel', f"{city.title()} {name}", random.randint(200, 800), round(random.uniform(3.5, 5.0), 1), random.randint(3, 5), random.randint(5, 25), 
                       base['lat'] + random.uniform(-0.05, 0.05), base['lng'] + random.uniform(-0.05, 0.05)))
        
    for name in rest_names:
        total_tables = random.randint(10, 30)
        cursor.execute('INSERT OR IGNORE INTO hospitality (city, type, name, price, rating, cuisine, total_tables, available_tables, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (city.lower(), 'restaurant', f"{city.title()} {name}", random.randint(40, 150), round(random.uniform(3.5, 5.0), 1), 
                       random.choice(["Arabic", "International", "Seafood", "Steakhouse"]), total_tables, random.randint(2, total_tables),
                       base['lat'] + random.uniform(-0.05, 0.05), base['lng'] + random.uniform(-0.05, 0.05)))

    for name in cafe_names:
        total_tables = random.randint(5, 15)
        cursor.execute('INSERT OR IGNORE INTO hospitality (city, type, name, price, rating, cuisine, total_tables, available_tables, lat, lng) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                      (city.lower(), 'cafe', f"{city.title()} {name}", random.randint(15, 45), round(random.uniform(4.0, 5.0), 1),
                       "Cafe & Sweets", total_tables, random.randint(1, total_tables),
                       base['lat'] + random.uniform(-0.05, 0.05), base['lng'] + random.uniform(-0.05, 0.05)))
        
    conn.commit()
    conn.close()

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

def get_hospitality(city, type=None):
    """Retrieve hospitality items for a city."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if type:
        cursor.execute('SELECT * FROM hospitality WHERE city = ? AND type = ?', (city.lower(), type))
    else:
        cursor.execute('SELECT * FROM hospitality WHERE city = ?', (city.lower(),))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_cached_web_research(city):
    """Retrieve cached research for a city."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data_json FROM web_research_cache WHERE city = ?', (city.lower(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row['data_json'])
    return None

def save_web_research(city, data):
    """Save research data to cache."""
    conn = get_db_connection()
    cursor = conn.cursor()
    from datetime import date
    cursor.execute('''
    INSERT OR REPLACE INTO web_research_cache (city, research_date, data_json)
    VALUES (?, ?, ?)
    ''', (city.lower(), date.today().isoformat(), json.dumps(data)))
    conn.commit()
    conn.close()
