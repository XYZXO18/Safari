"""
Safari AI Client
=================
Unified AI interface that tries Google Gemini first,
then falls back to local Ollama if Gemini is unavailable.

Usage:
    from safari.ai_client import generate, generate_json

    # Simple text generation
    text = generate("What are the top places to visit in Jeddah?")

    # With system prompt
    text = generate("Plan a trip", system="You are a travel agent.")

    # JSON-structured response
    data = generate_json("List 3 cities", schema_hint='{"cities": [...]}')

    # Web-grounded generation (uses Gemini's Google Search tool)
    text = generate_with_search("Latest events in Riyadh 2026")
"""

import json
import requests
import time
from typing import Optional

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OLLAMA_URL,
    OLLAMA_MODEL,
)

# ─── Internal State ──────────────────────────────────────────────────────────

_gemini_client = None
_gemini_available = True   # Flip to False after repeated failures
_gemini_fail_count = 0
_MAX_GEMINI_FAILS = 3      # After 3 consecutive fails, stop trying Gemini

def _get_gemini_client():
    """Lazy-init the Gemini client. Returns None if no API key."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        return _gemini_client
    except Exception as e:
        print(f"[AI Client] Failed to init Gemini client: {e}")
        return None


def _reset_gemini():
    """Re-enable Gemini after it was disabled by failures."""
    global _gemini_available, _gemini_fail_count
    _gemini_available = True
    _gemini_fail_count = 0


def _record_gemini_failure():
    """Track consecutive Gemini failures; disable after threshold."""
    global _gemini_available, _gemini_fail_count
    _gemini_fail_count += 1
    if _gemini_fail_count >= _MAX_GEMINI_FAILS:
        _gemini_available = False
        print(f"[AI Client] ⚠️ Gemini disabled after {_MAX_GEMINI_FAILS} consecutive failures. Using Ollama only.")


# ─── Gemini Backend ─────────────────────────────────────────────────────────

def _call_gemini(
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
    use_search: bool = False,
    timeout: int = 60,
) -> Optional[str]:
    """Call Google Gemini API. Returns text or None on failure."""
    global _gemini_available

    if not _gemini_available:
        return None

    client = _get_gemini_client()
    if not client:
        return None

    try:
        from google.genai import types

        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        if system:
            config_kwargs["system_instruction"] = system

        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        tools = []
        if use_search:
            tools.append({"google_search": {}})

        if tools:
            config_kwargs["tools"] = tools

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        text = response.text
        if text:
            _reset_gemini()  # Gemini worked → reset failure counter
            return text.strip()
        return None

    except Exception as e:
        print(f"[AI Client] Gemini failed: {e}")
        _record_gemini_failure()
        return None


# ─── Ollama Backend ──────────────────────────────────────────────────────────

def _call_ollama(
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    json_mode: bool = False,
    timeout: int = 120,
) -> Optional[str]:
    """Call local Ollama API. Returns text or None on failure."""
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }

        if system:
            payload["system"] = system

        if json_mode:
            payload["format"] = "json"

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()

        text = response.json().get("response", "")
        return text.strip() if text else None

    except Exception as e:
        print(f"[AI Client] Ollama failed: {e}")
        return None


# ─── Public API ──────────────────────────────────────────────────────────────

def generate(
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 60,
) -> str:
    """
    Generate text using AI. Tries Gemini first, falls back to Ollama.

    Args:
        prompt:      The user prompt / question.
        system:      Optional system prompt.
        temperature: Creativity (0.0 = deterministic, 1.0 = creative).
        max_tokens:  Maximum output length.
        timeout:     Request timeout in seconds.

    Returns:
        Generated text string.
    """
    # Try Gemini first
    result = _call_gemini(
        prompt=prompt,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if result:
        return result

    # Fallback to Ollama
    print("[AI Client] Falling back to Ollama...")
    result = _call_ollama(
        prompt=prompt,
        system=system,
        temperature=temperature,
        timeout=timeout,
    )
    if result:
        return result

    return "AI generation failed on both Gemini and Ollama."


def generate_json(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
    timeout: int = 60,
) -> dict:
    """
    Generate a JSON response. Tries Gemini (with JSON mime type) first,
    falls back to Ollama (with format: json).

    Returns:
        Parsed dict, or empty dict on failure.
    """
    # Try Gemini
    text = _call_gemini(
        prompt=prompt,
        system=system,
        temperature=temperature,
        json_mode=True,
        timeout=timeout,
    )
    if text:
        try:
            return _parse_json(text)
        except Exception:
            pass

    # Fallback to Ollama
    print("[AI Client] JSON fallback to Ollama...")
    text = _call_ollama(
        prompt=prompt,
        system=system,
        temperature=temperature,
        json_mode=True,
        timeout=timeout,
    )
    if text:
        try:
            return _parse_json(text)
        except Exception:
            pass

    return {}


def generate_with_search(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    """
    Generate with web search grounding.
    Gemini uses Google Search tool. Ollama fallback uses DuckDuckGo + prompt injection.

    Returns:
        Generated text string.
    """
    # Try Gemini with Google Search
    result = _call_gemini(
        prompt=prompt,
        system=system,
        temperature=temperature,
        use_search=True,
        json_mode=json_mode,
        timeout=timeout,
    )
    if result:
        return result

    # Fallback: DuckDuckGo search + Ollama
    print("[AI Client] Search fallback: DDG + Ollama...")
    search_context = _ddg_search(prompt)
    enriched_prompt = f"Based on these web search results:\n{search_context}\n\n{prompt}" if search_context else prompt

    result = _call_ollama(
        prompt=enriched_prompt,
        system=system,
        temperature=temperature,
        json_mode=json_mode,
        timeout=timeout,
    )
    if result:
        return result

    return "AI search generation failed on both Gemini and Ollama."


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Extract and parse JSON from text that might contain markdown fences."""
    text = text.strip()

    # Remove markdown JSON fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Find JSON object boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]

    return json.loads(text)


def _ddg_search(query: str, max_results: int = 5) -> str:
    """Fetch search results from DuckDuckGo for Ollama fallback."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return "\n".join(
                [f"Source: {r.get('title', '')} - {r.get('body', '')}" for r in results]
            )
    except Exception as e:
        print(f"[AI Client] DDG search failed: {e}")
        return ""


def get_provider_status() -> dict:
    """
    Check which AI providers are currently available.
    Useful for diagnostics and the frontend status display.
    """
    gemini_ok = False
    ollama_ok = False

    # Check Gemini
    if GEMINI_API_KEY and _gemini_available:
        try:
            client = _get_gemini_client()
            if client:
                gemini_ok = True
        except Exception:
            pass

    # Check Ollama
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "gemini": {
            "available": gemini_ok,
            "model": GEMINI_MODEL,
            "api_key_set": bool(GEMINI_API_KEY),
            "fail_count": _gemini_fail_count,
            "disabled": not _gemini_available,
        },
        "ollama": {
            "available": ollama_ok,
            "url": OLLAMA_URL,
            "model": OLLAMA_MODEL,
        },
        "primary": "gemini" if gemini_ok else "ollama",
    }
