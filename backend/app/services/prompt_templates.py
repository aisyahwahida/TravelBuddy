from __future__ import annotations

from app.schemas.travel import TravelIntent


PROMPT_TEMPLATES = {
    "itinerary": (
        "Build a timed itinerary with 09:00 start, lunch, afternoon route logic, "
        "dinner, assumptions, evidence, and alternatives."
    ),
    "place_recommendation": (
        "Recommend a concise list of places with reasons, best timing, map logic, "
        "source evidence, and alternatives."
    ),
    "food_recommendation": (
        "Prioritize food stops matching cuisine/budget, include lunch/dinner timing, "
        "and explain why each place fits."
    ),
    "budget_plan": (
        "Minimize cost, prefer free/affordable stops, markets, parks, and budget meals. "
        "Include rough cost estimates."
    ),
    "romantic_plan": (
        "Prefer scenic, slower, atmospheric stops, sunset timing, and dinner options."
    ),
    "family_trip": (
        "Prefer kid-friendly pacing, shorter transfers, parks, interactive museums, "
        "and practical meal breaks."
    ),
    "rainy_day_plan": (
        "Prefer indoor museums, galleries, covered passages, cafes, shopping, and "
        "short wet-weather transfers."
    ),
    "walking_route": (
        "Keep stops geographically sensible, state walking/transit logic, and avoid "
        "long jumps unless necessary."
    ),
    "must_go_plan": (
        "Use iconic first-time France sights, but keep lunch and dinner in the route."
    ),
}


def template_guidance(intent: TravelIntent) -> str:
    templates = [
        PROMPT_TEMPLATES[item]
        for item in intent.request_intents
        if item in PROMPT_TEMPLATES
    ]
    if not templates:
        templates = [PROMPT_TEMPLATES["itinerary"]]
    return "\n".join(f"- {template}" for template in templates)
