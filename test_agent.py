import sys
import os
import io

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from safari.agent.brain import SafariAgent

def main():
    agent = SafariAgent()
    result = agent.plan_trip("I have 5000 SAR and want to drive to the coast from Riyadh for 3 days.")
    print("\n--- Final Result Keys ---")
    print(result.keys())
    if "hospitality" in result:
        print("\nHospitality Hotels:")
        for h in result["hospitality"]["hotels"]:
            print(f"- {h['name']} ({h['city']})")
        print("\nHospitality Restaurants:")
        for r in result["hospitality"]["restaurants"]:
            print(f"- {r['name']} ({r['city']})")

if __name__ == "__main__":
    main()
