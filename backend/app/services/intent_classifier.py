from __future__ import annotations

import re


INTENT_KEYWORDS = {
    "itinerary": [
        "itinerary",
        "plan",
        "schedule",
        "trip",
        "day",
        "days",
        "weekend",
        "route",
    ],
    "place_recommendation": [
        "recommend",
        "suggest",
        "places",
        "spots",
        "where should i go",
        "things to do",
    ],
    "food_recommendation": [
        "food",
        "restaurant",
        "restaurants",
        "lunch",
        "dinner",
        "eat",
        "cafe",
        "coffee",
        "bistro",
        "brasserie",
        "ramen",
        "pho",
        "sushi",
    ],
    "budget_plan": ["cheap", "budget", "affordable", "free", "low cost", "under"],
    "romantic_plan": ["romantic", "date", "anniversary", "honeymoon", "couple"],
    "quiet_plan": ["quiet", "calm", "peaceful", "slow", "relaxed", "not crowded"],
    "family_trip": ["family", "kids", "children", "teen", "stroller"],
    "nightlife_plan": ["nightlife", "bar", "bars", "club", "clubs", "drinks", "cocktail"],
    "museum_plan": ["museum", "museums", "gallery", "art", "exhibition"],
    "walking_route": ["walk", "walking", "wander", "stroll", "on foot"],
    "shopping_plan": [
        "shopping",
        "shop",
        "souvenir",
        "souvenirs",
        "vintage",
        "thrift",
        "boutique",
        "luxury",
    ],
    "must_go_plan": [
        "first time",
        "first-time",
        "must go",
        "must-go",
        "must see",
        "must-see",
        "iconic",
        "famous",
        "eiffel",
        "louvre",
        "landmark",
    ],
    "rainy_day_plan": ["rain", "rainy", "indoor", "inside", "bad weather"],
    "general_travel_advice": ["advice", "tips", "how", "safe", "avoid", "transport"],
}


def classify_user_intents(message: str) -> list[str]:
    lowered = message.lower()
    intents = [
        intent
        for intent, keywords in INTENT_KEYWORDS.items()
        if any(_contains_term(lowered, keyword) for keyword in keywords)
    ]

    if not intents:
        if any(term in lowered for term in ["fun", "nice", "cool", "local"]):
            intents = ["itinerary", "place_recommendation"]
        else:
            intents = ["itinerary"]

    if "food_recommendation" in intents and "itinerary" not in intents:
        if any(term in lowered for term in ["day", "days", "route", "plan"]):
            intents.insert(0, "itinerary")

    return list(dict.fromkeys(intents))


def has_must_go_intent(intents: list[str]) -> bool:
    return "must_go_plan" in intents


def _contains_term(message: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in message
    return bool(re.search(rf"\b{re.escape(term)}\b", message))
