"""
Gemini API Call Logger
======================
Prints a clear, timestamped line every time any part of the app
calls the Gemini API — showing which agent/tool triggered it and why.

Import and use:
    from safari.gemini_log import log_gemini

    log_gemini("Agent 3 · Transport", "geocoding 'Four Seasons Hotel'")
    # → [14:32:05] 🔷 GEMINI #3  | Agent 3 · Transport  → geocoding 'Four Seasons Hotel'
"""

from datetime import datetime

_call_count = 0


def log_gemini(caller: str, purpose: str) -> None:
    """Print a single line announcing a Gemini API call."""
    global _call_count
    _call_count += 1
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] \U0001f537 GEMINI #{_call_count:<3} | {caller:<35} -> {purpose}")


def reset_counter() -> None:
    """Reset the per-session call counter (useful in tests)."""
    global _call_count
    _call_count = 0
