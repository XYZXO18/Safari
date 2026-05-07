"""Quick test of the Almosafer live scraper."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from safari.tools.almosafer import AlmosaferScraper

scraper = AlmosaferScraper()

print("=== URL Construction ===")
print("Hotel URL:", scraper.hotel_search_url("jeddah", "2026-05-15", "2026-05-18"))
print("Flight URL:", scraper.flight_search_url("riyadh", "jeddah", "2026-05-15"))

print("\n=== Live Hotel Scrape: Jeddah ===")
hotels = scraper.scrape_hotels("jeddah", "2026-05-15", "2026-05-18", max_results=5)
if hotels:
    for h in hotels:
        print(f"  {h['name']} | {h['stars']}stars | {h.get('price_per_night', 'N/A')} SAR/night | {h['source']}")
else:
    print("  No results — Almosafer may need JS rendering (blocked request).")
    print("  The scraper will return [] and the frontend will show a 'Check Almosafer' link.")

print("\n=== Live Flight Scrape: RUH->JED ===")
flights = scraper.scrape_flights("riyadh", "jeddah", "2026-05-15")
if flights:
    for f in flights:
        print(f"  {f['airline']} | {f.get('price_sar', 'N/A')} SAR | {f.get('duration', '?')}")
else:
    print("  No results.")
