# 🧭 Safari — Budget-First AI Travel Planner

**Math first. Adventure second. Regrets never.**

Safari is an AI travel agent that reverse-engineers trips from financial constraints. Give it your budget, travel mode, destination, and duration — it does the math, allocates every riyal, and hands you a realistic day-by-day itinerary.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) Add your Gemini API key for LLM-generated itineraries
#    Edit .env and set: GEMINI_API_KEY=your_key_here

# 3. Run Safari
python main.py "I have 3000 Riyals, driving my car to the coast for 4 days"
```

## How It Works

```
User Input → Parse → Calculate Transport → Allocate Budget → Suggest Activities → Generate Itinerary
```

1. **Input Parser** extracts budget, travel mode, destination, and days from natural language
2. **Transport Calculator** estimates fuel/ticket costs using lookup tables
3. **Budget Allocator** splits the remainder: 40% lodging, 30% food, 20% activities, 10% buffer
4. **Activity Suggester** picks destination-appropriate activities within budget
5. **Agent Brain** (optional LLM) weaves the numbers into a natural-language itinerary

## Example Queries

```bash
python main.py "I have 3000 Riyals, driving my car to the coast for 4 days"
python main.py "Budget is 5000 SAR, flying to Abha for 5 days from Jeddah"
python main.py "I got 2000 riyals, driving my SUV to the desert for 3 days"
python main.py "I have $1500, taking the train to Medina for 3 days"
```

## Project Structure

```
Safari/
├── main.py                  # Entry point
├── config.py                # Constants, routes, prices, destinations
├── requirements.txt
├── .env                     # API key (gitignored)
└── safari/
    ├── input_parser.py      # NLP extraction → TripRequest
    ├── tools/
    │   ├── transport.py     # Fuel/ticket cost calculator
    │   ├── budget.py        # Budget allocator (40/30/20/10 split)
    │   └── activities.py    # Activity suggester
    ├── agent/
    │   ├── brain.py         # Orchestration + LLM integration
    │   └── prompts.py       # System & user prompts
    └── output/
        └── formatter.py     # Rich terminal + JSON output
```

## LLM Integration

Safari works in two modes:

- **Without API key**: Uses a template-based fallback to generate clean itineraries from the calculated data
- **With Gemini API key**: Generates rich, personality-driven itineraries using Google Gemini

Set your key in `.env`:
```
GEMINI_API_KEY=your_gemini_api_key_here
```

## Supported Destinations

| Vibe | Cities | Activities |
|------|--------|------------|
| 🏖️ Coast | Jeddah, Yanbu, Umluj, Al Lith | Diving, beach camping, seafood |
| ⛰️ Mountains | Abha, Al Baha, Taif | Hiking, cable cars, honey tasting |
| 🏜️ Desert | Al-Ula, Edge of the World | Stargazing, dune bashing, ruins |
| 🏙️ City | Riyadh, Jeddah, Dammam | Shopping, dining, nightlife |

## License

Built with 💛 by Anti Gravity for Safari.
