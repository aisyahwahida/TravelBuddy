from __future__ import annotations

import math
import re
from collections import Counter

from app.schemas.travel import TravelIntent


SYNONYMS = {
    "fun": ["activity", "lively", "interesting", "experience"],
    "calm": ["quiet", "peaceful", "relaxed", "slow"],
    "quiet": ["calm", "peaceful", "hidden", "local"],
    "romantic": ["date", "couple", "sunset", "view", "wine"],
    "kids": ["family", "children", "zoo", "park", "aquarium"],
    "rain": ["indoor", "museum", "gallery", "covered"],
    "rainy": ["indoor", "museum", "gallery", "covered"],
    "cheap": ["budget", "affordable", "free"],
    "budget": ["cheap", "affordable", "free"],
    "iconic": ["must_go", "landmark", "famous", "classic"],
    "first": ["must_go", "iconic", "classic"],
    "shopping": ["shop", "boutique", "souvenir", "vintage"],
    "food": ["restaurant", "market", "cafe", "bistro"],
    "walk": ["walking", "wander", "stroll", "route"],
}


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def expand_tokens(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(SYNONYMS.get(token, []))
    return expanded


def query_text(intent: TravelIntent, original_query: str = "") -> str:
    parts = [
        original_query,
        intent.destination,
        intent.budget,
        intent.mood,
        intent.travel_style,
        intent.group_type,
        intent.food_preference,
        intent.indoor_outdoor,
        intent.time_of_day,
        intent.transportation,
        " ".join(intent.request_intents),
        " ".join(intent.interests),
        " ".join(intent.avoid),
    ]
    return " ".join(part for part in parts if part)


def place_text(place: dict) -> str:
    parts = [
        place.get("name", ""),
        place.get("city", ""),
        place.get("neighborhood", ""),
        place.get("category", ""),
        place.get("reason", ""),
        place.get("local_tip", ""),
        place.get("price_label", ""),
        place.get("source_type", ""),
        " ".join(place.get("tags", [])),
        " ".join(place.get("opening_hours", [])),
    ]
    return " ".join(part for part in parts if part)


def cosine_similarity(left_text: str, right_text: str) -> float:
    left = Counter(expand_tokens(tokenize(left_text)))
    right = Counter(expand_tokens(tokenize(right_text)))
    if not left or not right:
        return 0.0

    dot = sum(value * right.get(token, 0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def semantic_scores(
    places: list[dict],
    intent: TravelIntent,
    original_query: str = "",
) -> dict[tuple[str, str], float]:
    text = query_text(intent, original_query)
    return {
        (place.get("name", "").lower(), place.get("city", "").lower()): cosine_similarity(
            text,
            place_text(place),
        )
        for place in places
    }
