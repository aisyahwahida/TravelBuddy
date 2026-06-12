from __future__ import annotations

import re

from app.schemas.travel import TravelIntent
from app.services.intent_classifier import classify_user_intents


FOOD_TERMS = {
    "asian": ["asian"],
    "japanese": ["japanese", "ramen", "sushi", "izakaya"],
    "korean": ["korean", "bbq"],
    "chinese": ["chinese", "sichuan", "noodles"],
    "vietnamese": ["vietnamese", "pho", "banh mi"],
    "thai": ["thai"],
    "french": ["french", "bistro", "brasserie", "wine bar"],
    "vegetarian": ["vegetarian", "vegan", "plant based"],
    "halal": ["halal"],
    "dessert": ["dessert", "pastry", "patisserie", "chocolate"],
}


def _first_matching_label(message: str, mapping: dict[str, list[str]]) -> str:
    lowered = message.lower()
    for label, terms in mapping.items():
        if any(_contains_term(lowered, term) for term in terms):
            return label
    return ""


def _contains_term(message: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in message
    return bool(re.search(rf"\b{re.escape(term)}\b", message))


def _extract_time_of_day(message: str) -> str:
    lowered = message.lower()
    for label, terms in {
        "morning": ["morning", "breakfast", "sunrise", "9am", "9 am"],
        "afternoon": ["afternoon", "lunch", "midday", "2pm", "2 pm"],
        "evening": ["evening", "dinner", "sunset", "night", "7pm", "7 pm"],
        "late night": ["late night", "after midnight"],
    }.items():
        if any(_contains_term(lowered, term) for term in terms):
            return label
    return ""


def _extract_indoor_outdoor(message: str) -> str:
    lowered = message.lower()
    indoor = any(_contains_term(lowered, term) for term in ["indoor", "inside", "rain", "rainy", "museum"])
    outdoor = any(_contains_term(lowered, term) for term in ["outdoor", "outside", "park", "walk", "garden"])
    if indoor and outdoor:
        return "mixed"
    if indoor:
        return "indoor"
    if outdoor:
        return "outdoor"
    return ""


def _extract_transportation(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if any(term in lowered for term in ["no walking", "can't walk", "cannot walk", "limited walking", "cannot walk much"]):
        return "transit or taxi", "limited walking"
    if any(term in lowered for term in ["walking only", "walk only", "on foot"]):
        return "walking", "walking preferred"
    if any(_contains_term(lowered, term) for term in ["metro", "subway", "train", "bus", "public transport"]):
        return "public transport", ""
    if any(term in lowered for term in ["taxi", "uber", "bolt"]):
        return "taxi or rideshare", ""
    return "", ""


def _extract_group_type(message: str, existing_style: str) -> str:
    lowered = message.lower()
    if any(term in lowered for term in ["solo", "alone", "by myself"]):
        return "solo"
    if any(term in lowered for term in ["couple", "partner", "date", "anniversary", "honeymoon"]):
        return "couple"
    if any(term in lowered for term in ["family", "kids", "children", "teen", "parents"]):
        return "family"
    if any(term in lowered for term in ["friends", "group"]):
        return "friends"
    return existing_style


def _build_assumptions(message: str, intent: TravelIntent) -> list[str]:
    lowered = message.lower()
    assumptions = []
    if not any(city.lower() in lowered for city in ["france", "paris", "lyon", "marseille", "nice", "bordeaux", "strasbourg", "lille"]):
        assumptions.append(f"Assumed {intent.destination} because no destination was specified.")
    if not re.search(r"\b\d+\s*(day|days|hour|hours)\b", lowered):
        assumptions.append(f"Assumed a {intent.duration_days}-day plan.")
    if not intent.budget:
        assumptions.append("Assumed a moderate budget.")
    if not intent.pace:
        assumptions.append("Assumed balanced pacing.")
    return assumptions


def _clarification_question(intent: TravelIntent, message: str) -> str:
    lowered = message.lower().strip()
    if len(lowered.split()) <= 4 and not intent.mood and not intent.budget:
        return "Do you want this to feel local/quiet, iconic/first-time, food-focused, or budget-friendly?"
    if intent.destination == "Paris" and "paris" not in lowered and "france" not in lowered:
        return "I assumed Paris; tell me if you want another French city."
    return ""


def enrich_preferences(message: str, intent: TravelIntent) -> TravelIntent:
    request_intents = classify_user_intents(message)
    food_preference = _first_matching_label(message, FOOD_TERMS)
    indoor_outdoor = _extract_indoor_outdoor(message)
    time_of_day = _extract_time_of_day(message)
    transportation, walking_constraints = _extract_transportation(message)
    group_type = _extract_group_type(message, intent.travel_style)
    assumptions = _build_assumptions(message, intent)

    return intent.model_copy(
        update={
            "request_intents": request_intents,
            "food_preference": food_preference,
            "indoor_outdoor": indoor_outdoor,
            "time_of_day": time_of_day,
            "transportation": transportation,
            "walking_constraints": walking_constraints,
            "group_type": group_type,
            "assumptions": assumptions,
            "clarification_question": _clarification_question(intent, message),
        }
    )
