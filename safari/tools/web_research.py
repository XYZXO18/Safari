"""
Web Research Tool
=================
Discovers real-time travel intelligence from the open web and social media.

Uses Gemini's Google Search grounding to pull:
  - 🐦 Social media buzz (X/Twitter, Instagram, TikTok, Reddit)
  - 🍽️ Trending restaurants & cafés from foodie accounts
  - 📸 Hidden gems recommended by local influencers
  - 🌤️ Current weather / travel advisories
  - 💸 Real-time price intelligence (hotel rates, fuel prices)

Returns structured WebResearchResult with categorized insights that
get injected into the agent's planning pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from google import genai
from google.genai import types

def get_ddg_results(query: str, max_results: int = 5) -> str:
    """Fetch search results from DuckDuckGo."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return "\n".join([f"Source: {r.get('title', '')} - {r.get('body', '')}" for r in results])
    except Exception as e:
        print(f"DDG Search failed: {e}")
        return ""


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class SocialMediaPost:
    """A single social media finding relevant to the destination."""

    platform: str              # x/twitter | instagram | tiktok | reddit | blog
    author: str                # username or account name
    content: str               # summary of the post / recommendation
    category: str              # restaurant | attraction | tip | warning | hidden_gem
    relevance_score: float     # 0.0 – 1.0 how useful this is for the traveler
    url: str = ""              # link if available
    likes: int = 0             # engagement metric
    posted_date: str = ""      # approximate date

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "author": self.author,
            "content": self.content,
            "category": self.category,
            "relevance_score": self.relevance_score,
            "url": self.url,
            "likes": self.likes,
            "posted_date": self.posted_date,
        }


@dataclass
class TrendingSpot:
    """A trending place discovered from online research."""

    name: str
    category: str              # restaurant | cafe | attraction | nightlife | shopping
    description: str
    price_range: str           # $ | $$ | $$$ | $$$$
    estimated_cost_sar: float
    rating: float = 0.0        # out of 5
    source: str = ""           # where this was found
    lat: Optional[float] = None
    lng: Optional[float] = None
    social_buzz: str = ""      # why it's trending
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "price_range": self.price_range,
            "estimated_cost_sar": self.estimated_cost_sar,
            "rating": self.rating,
            "source": self.source,
            "lat": self.lat,
            "lng": self.lng,
            "social_buzz": self.social_buzz,
            "tags": self.tags,
        }


@dataclass
class LocalInsight:
    """A practical tip or insight from online sources."""

    tip: str
    category: str              # money_saving | safety | culture | weather | transport
    source: str                # platform or site name
    confidence: str = "high"   # high | medium | low

    def to_dict(self) -> dict:
        return {
            "tip": self.tip,
            "category": self.category,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class WebResearchResult:
    """Complete result of web + social media research for a destination."""

    city: str
    research_date: str
    social_posts: List[SocialMediaPost] = field(default_factory=list)
    trending_spots: List[TrendingSpot] = field(default_factory=list)
    local_insights: List[LocalInsight] = field(default_factory=list)
    weather_summary: str = ""
    scan_successful: bool = False

    @property
    def has_data(self) -> bool:
        return bool(self.social_posts or self.trending_spots or self.local_insights)

    @property
    def summary(self) -> str:
        lines = [
            f"🌐 Web & Social Media Research — {self.city}",
            f"   Researched on: {self.research_date}",
            "",
        ]

        if self.weather_summary:
            lines.append(f"   🌤️ Weather: {self.weather_summary}")
            lines.append("")

        if self.social_posts:
            lines.append(f"   📱 Social Media Buzz ({len(self.social_posts)} posts found):")
            for post in self.social_posts[:5]:
                platform_icon = {
                    "x/twitter": "🐦", "instagram": "📸",
                    "tiktok": "🎵", "reddit": "🔴", "blog": "📝"
                }.get(post.platform, "🌐")
                lines.append(f"      {platform_icon} @{post.author}: {post.content[:80]}...")
            lines.append("")

        if self.trending_spots:
            lines.append(f"   🔥 Trending Spots ({len(self.trending_spots)} found):")
            for spot in self.trending_spots[:5]:
                stars = "⭐" * int(spot.rating) if spot.rating else ""
                lines.append(f"      • {spot.name} ({spot.category}) {stars}")
                lines.append(f"        {spot.description[:60]}...")
                if spot.social_buzz:
                    lines.append(f"        📱 Trending because: {spot.social_buzz[:50]}")
            lines.append("")

        if self.local_insights:
            lines.append(f"   💡 Local Tips ({len(self.local_insights)} insights):")
            for tip in self.local_insights[:5]:
                lines.append(f"      • {tip.tip}")
            lines.append("")

        if not self.has_data:
            lines.append("   ℹ️ No additional online data found.")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "research_date": self.research_date,
            "social_posts": [p.to_dict() for p in self.social_posts],
            "trending_spots": [s.to_dict() for s in self.trending_spots],
            "local_insights": [t.to_dict() for t in self.local_insights],
            "weather_summary": self.weather_summary,
            "scan_successful": self.scan_successful,
        }


# ─── Social Media Research ───────────────────────────────────────────────────

def _search_social_media(city: str, interests: str = "") -> List[SocialMediaPost]:
    """
    Use Gemini's Google Search grounding to discover social media posts
    about a destination — trending food spots, hidden gems, local recommendations.
    """
    from config import GEMINI_API_KEY, USE_LOCAL_AI, OLLAMA_URL, OLLAMA_MODEL

    if not USE_LOCAL_AI and not GEMINI_API_KEY:
        return []

    try:
        if USE_LOCAL_AI:
            pass
        else:
            client = genai.Client(api_key=GEMINI_API_KEY)

        interests_str = f" Focus especially on posts about: {interests}." if interests else ""

        prompt = (
            f"Search the web for recent social media posts, tweets, Instagram reels, "
            f"TikTok recommendations, and Reddit discussions about traveling to "
            f"{city}, Saudi Arabia.{interests_str} "
            f"Look for posts from platforms like x.com (Twitter), instagram.com, "
            f"tiktok.com, reddit.com/r/saudiarabia, and travel blogs. "
            f"Find posts about: trending restaurants, hidden gems, must-visit spots, "
            f"local food recommendations, nightlife, unique experiences, and travel tips. "
            f"Return ONLY a raw JSON array of up to 8 most relevant posts "
            f"with this exact structure per item: "
            f'{{"platform": "x/twitter|instagram|tiktok|reddit|blog", '
            f'"author": "username", "content": "summary of what they said (1-2 sentences)", '
            f'"category": "restaurant|attraction|tip|warning|hidden_gem", '
            f'"relevance_score": 0.85, "url": "link if available", '
            f'"likes": 0, "posted_date": "approximate date"}}'
            f"\nIf no relevant posts are found, return an empty array: []"
        )
        if USE_LOCAL_AI:
            import requests
            search_query = f"recent social media posts travel tips hidden gems {city} Saudi Arabia"
            search_context = get_ddg_results(search_query, max_results=8)
            prompt_with_context = f"Based on these live web search results:\n{search_context}\n\n{prompt}"
            
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt_with_context,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3}
            }
            res = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
            res.raise_for_status()
            text = res.json()["response"].strip()
        else:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
        text = text.strip()
        start_idx = text.find('[')
        end_idx = text.rfind(']')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx+1]
        data = json.loads(text)

        if isinstance(data, dict):
            data = data.get("posts", data.get("results", [data]))

        posts = []
        for item in data[:8]:
            posts.append(SocialMediaPost(
                platform=item.get("platform", "unknown"),
                author=item.get("author", "anonymous"),
                content=item.get("content", ""),
                category=item.get("category", "tip"),
                relevance_score=float(item.get("relevance_score", 0.5)),
                url=item.get("url", ""),
                likes=int(item.get("likes", 0)),
                posted_date=item.get("posted_date", ""),
            ))

        return posts

    except Exception as e:
        print(f"Social media search failed: {e}")
        return []


# ─── Trending Spots Research ────────────────────────────────────────────────

def _search_trending_spots(city: str, interests: str = "") -> List[TrendingSpot]:
    """
    Use Gemini's Google Search grounding to discover currently trending
    restaurants, cafés, attractions, and experiences in a city.
    """
    from config import GEMINI_API_KEY, USE_LOCAL_AI, OLLAMA_URL, OLLAMA_MODEL

    if not USE_LOCAL_AI and not GEMINI_API_KEY:
        return []

    try:
        if USE_LOCAL_AI:
            pass
        else:
            client = genai.Client(api_key=GEMINI_API_KEY)

        interests_str = f" The traveler is especially interested in: {interests}." if interests else ""

        from config import CITY_COORDS
        city_coords = CITY_COORDS.get(city.lower(), {"lat": 24.7, "lng": 46.7})
        lat_ex = city_coords["lat"]
        lng_ex = city_coords["lng"]

        prompt = (
            f"Search the web for the most trending and highly-rated restaurants, cafés, "
            f"attractions, nightlife spots, and unique experiences in {city}, Saudi Arabia "
            f"right now.{interests_str} "
            f"Check Google Maps reviews, Tripadvisor, Zomato, HungerStation, Foursquare, "
            f"local food bloggers, and social media recommendations. "
            f"Return ONLY a raw JSON array of up to 8 trending spots "
            f"with this exact structure per item: "
            f'{{"name": "place name", "category": "restaurant|cafe|attraction|nightlife|shopping", '
            f'"description": "what makes it special (1-2 sentences)", '
            f'"price_range": "$|$$|$$$|$$$$", "estimated_cost_sar": 80, '
            f'"rating": 4.5, "source": "where found", '
            f'"lat": {lat_ex}, "lng": {lng_ex}, '
            f'"social_buzz": "why it is trending right now", '
            f'"tags": ["tag1", "tag2"]}}'
            f"\nIMPORTANT: Provide accurate lat/lng coordinates for {city}. Do not just copy the example coordinates."
            f"\nIf no spots are found, return an empty array: []"
        )
        if USE_LOCAL_AI:
            import requests
            search_query = f"trending restaurants attractions nightlife {city} Saudi Arabia {interests}"
            search_context = get_ddg_results(search_query, max_results=8)
            prompt_with_context = f"Based on these live web search results:\n{search_context}\n\n{prompt}"
            
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt_with_context,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3}
            }
            res = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
            res.raise_for_status()
            text = res.json()["response"].strip()
        else:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
        text = text.strip()
        start_idx = text.find('[')
        end_idx = text.rfind(']')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx+1]
        data = json.loads(text)

        if isinstance(data, dict):
            data = data.get("spots", data.get("results", data.get("places", [data])))

        spots = []
        for item in data[:8]:
            spots.append(TrendingSpot(
                name=item.get("name", "Unknown"),
                category=item.get("category", "attraction"),
                description=item.get("description", ""),
                price_range=item.get("price_range", "$$"),
                estimated_cost_sar=float(item.get("estimated_cost_sar", 50)),
                rating=float(item.get("rating", 0)),
                source=item.get("source", "web"),
                lat=item.get("lat"),
                lng=item.get("lng"),
                social_buzz=item.get("social_buzz", ""),
                tags=item.get("tags", []),
            ))

        return spots

    except Exception as e:
        print(f"Trending spots search failed: {e}")
        return []


# ─── Local Insights Research ────────────────────────────────────────────────

def _search_local_insights(city: str) -> tuple[List[LocalInsight], str]:
    """
    Use Gemini's Google Search grounding to discover practical travel tips,
    weather info, and local insights from the web.
    """
    from config import GEMINI_API_KEY, USE_LOCAL_AI, OLLAMA_URL, OLLAMA_MODEL

    if not USE_LOCAL_AI and not GEMINI_API_KEY:
        return [], ""

    try:
        if USE_LOCAL_AI:
            pass
        else:
            client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = (
            f"Search the web for current practical travel tips and information about "
            f"visiting {city}, Saudi Arabia. Include: "
            f"1) Current weather conditions and what to pack, "
            f"2) Money-saving tips from travelers and locals, "
            f"3) Safety tips or travel advisories, "
            f"4) Cultural etiquette and local customs to know, "
            f"5) Best transportation options within the city. "
            f"Check travel blogs, Reddit, Lonely Planet, TripAdvisor forums. "
            f"Return ONLY a raw JSON object with this exact structure: "
            f'{{"weather_summary": "current conditions in 1 sentence", '
            f'"tips": [{{"tip": "practical advice (1 sentence)", '
            f'"category": "money_saving|safety|culture|weather|transport", '
            f'"source": "where found", "confidence": "high|medium|low"}}]}}'
        )
        if USE_LOCAL_AI:
            import requests
            search_query = f"current weather safety money saving travel tips transport {city} Saudi Arabia"
            search_context = get_ddg_results(search_query, max_results=8)
            prompt_with_context = f"Based on these live web search results:\n{search_context}\n\n{prompt}"
            
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt_with_context,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3}
            }
            res = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=60)
            res.raise_for_status()
            text = res.json()["response"].strip()
        else:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            text = response.text.strip()
        text = text.strip()
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx+1]
        data = json.loads(text)

        weather = data.get("weather_summary", "")
        tips_data = data.get("tips", [])

        insights = []
        for item in tips_data[:8]:
            insights.append(LocalInsight(
                tip=item.get("tip", ""),
                category=item.get("category", "tip"),
                source=item.get("source", "web"),
                confidence=item.get("confidence", "medium"),
            ))

        return insights, weather

    except Exception as e:
        print(f"Local insights search failed: {e}")
        return [], ""


# ─── Public API ──────────────────────────────────────────────────────────────

def research_destination(
    city: str,
    interests: str = "",
    include_social: bool = True,
    include_spots: bool = True,
    include_insights: bool = True,
) -> WebResearchResult:
    """
    Perform comprehensive web + social media research for a travel destination.

    Runs up to 3 parallel-style searches using Gemini Google Search grounding:
      1. Social media posts (X, Instagram, TikTok, Reddit)
      2. Trending restaurants, cafés, and attractions
      3. Local tips, weather, and practical insights

    Parameters
    ----------
    city : str
        The destination city (e.g., 'Jeddah', 'Riyadh').
    interests : str
        Comma-separated interests for personalized results.
    include_social : bool
        Whether to search social media (default True).
    include_spots : bool
        Whether to search for trending spots (default True).
    include_insights : bool
        Whether to search for local insights (default True).

    Returns
    -------
    WebResearchResult
        Comprehensive research data with social posts, spots, and tips.

    Examples
    --------
    >>> result = research_destination("Jeddah", interests="seafood, diving")
    >>> result.has_data
    True
    >>> len(result.trending_spots)
    5
    """
    from datetime import date

    social_posts = []
    trending_spots = []
    local_insights = []
    weather = ""

    # ── Search 1: Social media buzz ──
    if include_social:
        social_posts = _search_social_media(city, interests)

    # ── Search 2: Trending spots ──
    if include_spots:
        trending_spots = _search_trending_spots(city, interests)

    # ── Search 3: Local insights + weather ──
    if include_insights:
        local_insights, weather = _search_local_insights(city)

    scan_ok = bool(social_posts or trending_spots or local_insights)

    return WebResearchResult(
        city=city,
        research_date=date.today().isoformat(),
        social_posts=social_posts,
        trending_spots=trending_spots,
        local_insights=local_insights,
        weather_summary=weather,
        scan_successful=scan_ok,
    )
