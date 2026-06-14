from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from app.schemas.travel import TravelIntent
from app.services.luxia_client import LuxiaClient, extract_json_object
from app.services.preference_extractor import enrich_preferences


KNOWN_DESTINATIONS = [
    "france",
    "paris",
    "lyon",
    "marseille",
    "nice",
    "bordeaux",
    "strasbourg",
    "lille",
]

KNOWN_INTERESTS = [
    "food",
    "lunch",
    "dinner",
    "eat",
    "bar",
    "bars",
    "nightlife",
    "romantic",
    "family",
    "kids",
    "mixed",
    "markets",
    "market",
    "bookstores",
    "quiet",
    "cafe",
    "cafes",
    "coffee",
    "coffee shops",
    "free",
    "museum",
    "museums",
    "walks",
    "art",
    "wine",
    "history",
    "event",
    "events",
    "activity",
    "activities",
    "exhibition",
    "exhibitions",
    "concert",
    "concerts",
    "park",
    "parks",
    "library",
    "libraries",
    "weekend",
    "things to do",
    "first time",
    "first-time",
    "must go",
    "must-go",
    "must see",
    "must-see",
    "iconic",
    "famous",
    "classic",
    "landmark",
    "landmarks",
    "tourist attraction",
    "tourist attractions",
    "eiffel",
    "louvre",
    "shopping",
    "shop",
    "shops",
    "souvenir",
    "souvenirs",
    "gift",
    "gifts",
    "affordable shopping",
    "vintage",
    "thrift",
    "thrifting",
    "friperie",
    "flea market",
    "antiques",
    "luxury",
    "high-end",
    "high end",
    "brand",
    "brands",
    "designer",
    "fashion",
    "department store",
    "mall",
    "boutique",
    "boutiques",
    "skincare",
    "cosmetics",
    "pharmacy",
    "asian",
    "japanese",
    "korean",
    "chinese",
    "thai",
    "vietnamese",
    "ramen",
    "sushi",
    "pho",
    "restaurant",
    "restaurants",
    "french",
    "bistro",
    "brasserie",
]

KNOWN_AVOIDS = [
    "tourist traps",
    "crowds",
    "overpriced restaurants",
    "famous landmarks",
    "landmarks",
]

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
}


class HybridIntentHint(BaseModel):
    destination: str = ""
    duration_days: int | None = Field(default=None, ge=1, le=14)
    request_intents: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    pace: str = ""
    visit_day: str = ""
    budget: str = ""
    mood: str = ""
    travel_style: str = ""
    group_type: str = ""
    food_preference: str = ""
    indoor_outdoor: str = ""
    time_of_day: str = ""
    transportation: str = ""
    walking_constraints: str = ""
    stay_location: str = ""


def _contains_term(message: str, term: str) -> bool:
    if " " in term or "-" in term:
        return term in message
    return bool(re.search(rf"\b{re.escape(term)}\b", message))


def _extract_visit_day(message: str) -> str:
    lowered = message.lower()
    today = datetime.now()

    if "tomorrow" in lowered:
        return (today + timedelta(days=1)).strftime("%A")
    if "today" in lowered:
        return today.strftime("%A")

    for weekday in WEEKDAYS:
        if weekday in lowered:
            return weekday.title()

    return ""


def _extract_budget(message: str) -> str:
    lowered = message.lower()
    currency_match = re.search(r"([$€£]\s?\d+|\d+\s?(?:eur|euro|euros|usd|dollars|pounds))", lowered)
    if currency_match:
        return currency_match.group(0)
    if any(term in lowered for term in ["cheap", "budget", "low cost", "free", "affordable"]):
        return "budget"
    if any(term in lowered for term in ["mid range", "mid-range", "moderate"]):
        return "mid-range"
    if any(term in lowered for term in ["luxury", "high-end", "high end", "expensive", "splurge"]):
        return "luxury"
    return ""


def _extract_mood(message: str) -> str:
    lowered = message.lower()
    mood_terms = [
        ("quiet", ["quiet", "calm", "peaceful"]),
        ("relaxed", ["relaxed", "slow", "chill", "easy"]),
        ("romantic", ["romantic", "date", "couple"]),
        ("adventurous", ["adventure", "adventurous", "hidden"]),
        ("foodie", ["foodie", "food", "restaurant", "cafe", "coffee"]),
        ("cultural", ["culture", "cultural", "museum", "art", "history"]),
    ]
    for mood, terms in mood_terms:
        if any(term in lowered for term in terms):
            return mood
    return ""


def _extract_travel_style(message: str) -> str:
    lowered = message.lower()
    if any(term in lowered for term in ["solo", "alone", "by myself"]):
        return "solo"
    if any(term in lowered for term in ["couple", "partner", "girlfriend", "boyfriend", "wife", "husband"]):
        return "couple"
    if any(term in lowered for term in ["family", "kids", "children"]):
        return "family"
    if any(term in lowered for term in ["friends", "group"]):
        return "friends"
    if any(term in lowered for term in ["local", "not touristy", "non touristy", "hidden gem"]):
        return "local-first"
    if "slow travel" in lowered:
        return "slow travel"
    return ""


def _classify_user_type(
    message: str,
    interests: list[str],
    group_type: str,
    travel_style: str,
) -> str:
    lowered = message.lower()
    interests_set = {i.lower() for i in interests}

    food_terms = {
        "restaurant", "restaurants", "food", "lunch", "dinner", "eat",
        "bistro", "brasserie", "wine", "foodie", "cafes", "cafe", "coffee",
        "french food", "cuisine",
    }
    if len(food_terms.intersection(interests_set)) >= 2 or "food trip" in lowered:
        return "food_traveler"

    if (
        any(term in lowered for term in ["family", "kids", "children", "kid"])
        or "family" in group_type.lower()
    ):
        return "family_trip"

    if any(term in lowered for term in [
        "like a local", "local-style", "local style", "hidden gem", "hidden gems",
        "off the beaten", "not touristy", "non-touristy", "avoid tourist",
        "local experience",
    ]):
        return "local_resident"

    if any(term in lowered for term in [
        "been before", "returning", "second time", "been to paris",
        "already been", "know paris", "visited before", "been there",
        "visited paris", "been to france",
    ]):
        return "returning_visitor"

    if any(term in lowered for term in [
        "first time", "first-time", "first visit", "never been", "never visited",
        "must see", "must-see", "iconic", "must go", "must-go", "eiffel", "louvre",
    ]):
        return "first_time_visitor"

    if travel_style == "local-first":
        return "local_resident"

    # No strong signal — treat as a general/vague request
    return "general"


def _extract_stay_location(message: str) -> str:
    patterns = [
        r"\b(?:staying|stay|based|sleeping)\s+(?:at|in|near)\s+([A-Za-z0-9À-ÿ’’&.\- ]{2,80})",
        r"\b(?:hotel|hostel|airbnb|apartment)\s+(?:is|in|near|around)\s+([A-Za-z0-9À-ÿ'’&.\- ]{2,80})",
        r"\b(?:our|my)\s+(?:hotel|hostel|airbnb|apartment)\s+(?:is\s+)?(?:at|in|near)\s+([A-Za-z0-9À-ÿ'’&.\- ]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        value = re.split(r"[,\n.;]|(?:\band\b)|(?:\bwith\b)", match.group(1), maxsplit=1)[0].strip(" -?")
        value = re.sub(r"\s+for\s+\d+\s+days?\b.*$", "", value, flags=re.IGNORECASE).strip(" -?")
        if value:
            return value
    return ""


def _extract_stay_location(message: str) -> str:
    patterns = [
        r"\b(?:staying|stay|based|sleeping)\s+(?:at|in|near)\s+([^,\n.;]{2,80})",
        r"\b(?:hotel|hostel|airbnb|apartment)\s+(?:is|in|near|around)\s+([^,\n.;]{2,80})",
        r"\b(?:our|my)\s+(?:hotel|hostel|airbnb|apartment)\s+(?:is\s+)?(?:at|in|near)\s+([^,\n.;]{2,80})",
        r"\bfrom\s+(?:our|my)\s+(?:hotel|hostel|airbnb|apartment)\s+(?:at|in|near)\s+([^,\n.;]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        value = re.split(r"[,\n.;]|(?:\band\b)|(?:\bwith\b)", match.group(1), maxsplit=1)[0].strip(" -?")
        value = re.sub(r"\s+for\s+\d+\s+days?\b.*$", "", value, flags=re.IGNORECASE).strip(" -?")
        if value:
            return value
    return ""


def _extract_destination(message: str) -> str:
    lowered = message.lower()
    match = next(
        (
            "France" if city == "france" else city.title()
            for city in KNOWN_DESTINATIONS
            if _contains_term(lowered, city)
        ),
        "",
    )
    return match


def _extract_duration_days(message: str) -> int | None:
    lowered = message.lower()
    number_words = "|".join(NUMBER_WORDS)
    day_match = re.search(rf"\b(?P<count>\d+|{number_words})\s*[- ]?(day|days)\b", lowered)
    if day_match:
        raw = day_match.group("count")
        if raw.isdigit():
            return max(1, min(int(raw), 14))
        return NUMBER_WORDS.get(raw)

    week_match = re.search(rf"\b(?P<count>\d+|{number_words})\s*[- ]?(week|weeks)\b", lowered)
    if week_match:
        raw = week_match.group("count")
        count = int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw, 1)
        return max(1, min(count * 7, 14))

    if "weekend" in lowered:
        return 2

    return None


def _extract_interests(message: str) -> list[str]:
    lowered = message.lower()
    interests = [item for item in KNOWN_INTERESTS if _contains_term(lowered, item)]
    if any(
        term in lowered
        for term in [
            "first time",
            "first-time",
            "must go",
            "must-go",
            "must see",
            "must-see",
            "iconic",
            "famous",
            "classic",
            "landmark",
            "landmarks",
            "tourist attraction",
            "tourist attractions",
            "eiffel",
            "louvre",
        ]
    ):
        interests.extend(["must_go", "first_time", "iconic", "landmarks"])
    if "things to do" in lowered or "what to do" in lowered:
        interests.extend(["activity", "events", "museum", "parks", "walks"])
    if any(_contains_term(lowered, term) for term in ["rain", "rainy", "indoor", "inside"]):
        interests.extend(["museum", "shopping", "cafes"])
    if any(_contains_term(lowered, term) for term in ["romantic", "date", "couple", "sunset"]):
        interests.extend(["restaurant", "restaurants", "wine", "views", "parks"])
    if any(_contains_term(lowered, term) for term in ["family", "kids", "children"]):
        interests.extend(["parks", "museum", "activity"])
    if any(_contains_term(lowered, term) for term in ["lunch", "dinner", "eat"]):
        interests.append("restaurant")
    if "cafe" in interests or "coffee" in interests or "coffee shops" in interests:
        interests = [
            item
            for item in interests
            if item not in {"cafe", "cafes", "coffee", "coffee shops"}
        ]
        interests.append("cafes")
    return list(dict.fromkeys(interests))


def _extract_pace(message: str) -> str:
    lowered = message.lower()
    if "slow" in lowered or "relaxed" in lowered:
        return "slow"
    if "fast" in lowered or "packed" in lowered:
        return "fast"
    return "balanced"


def _extract_core_intent(message: str) -> TravelIntent:
    destination = _extract_destination(message) or "Paris"
    interests = _extract_interests(message)
    duration_days = _extract_duration_days(message) or 1

    default_mixed_interests = [
        "mixed",
        "walks",
        "museum",
        "parks",
        "cafes",
        "market",
        "restaurant",
    ]

    must_go_request = "must_go" in interests
    lowered = message.lower()
    avoid = [] if must_go_request else [item for item in KNOWN_AVOIDS if item in lowered]

    return TravelIntent(
        destination=destination,
        duration_days=duration_days,
        interests=interests or default_mixed_interests,
        avoid=avoid if must_go_request else (avoid or ["tourist traps"]),
        pace=_extract_pace(message),
        visit_day=_extract_visit_day(message),
        budget=_extract_budget(message),
        mood=_extract_mood(message),
        travel_style=_extract_travel_style(message),
        stay_location=_extract_stay_location(message),
    )


def _extract_with_luxia(message: str, rule_intent: TravelIntent) -> HybridIntentHint | None:
    client = LuxiaClient()
    if not client.is_configured:
        return None

    system_prompt = (
        "You extract structured travel intent from user prompts. "
        "Return only valid JSON. Preserve explicit facts exactly, especially destination, "
        "trip length, transport limitations, and budget. If a field is unknown, return an "
        "empty string, empty array, or null for duration_days. Do not invent constraints."
    )
    payload = {
        "message": message,
        "rule_based_intent": rule_intent.model_dump(),
        "allowed_destinations": [city.title() for city in KNOWN_DESTINATIONS if city != "france"]
        + ["France"],
        "json_schema": HybridIntentHint.model_json_schema(),
    }

    try:
        raw = client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=0.0,
            max_tokens=700,
            model_override="luxia3-llm-8b-0731",
        )
        return HybridIntentHint.model_validate(extract_json_object(raw))
    except Exception:
        return None


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([item for item in first + second if item]))


def _is_explicit_destination(message: str) -> bool:
    return bool(_extract_destination(message))


def _is_explicit_duration(message: str) -> bool:
    return _extract_duration_days(message) is not None


def _is_explicit_budget(message: str) -> bool:
    return bool(_extract_budget(message))


def _is_explicit_pace(message: str) -> bool:
    lowered = message.lower()
    return any(term in lowered for term in ["slow", "relaxed", "fast", "packed"])


def _merge_with_luxia(
    message: str,
    rule_intent: TravelIntent,
    luxia_hint: HybridIntentHint | None,
) -> TravelIntent:
    if luxia_hint is None:
        return rule_intent

    destination = rule_intent.destination
    if not _is_explicit_destination(message) and luxia_hint.destination:
        destination = luxia_hint.destination

    duration_days = rule_intent.duration_days
    if not _is_explicit_duration(message) and luxia_hint.duration_days:
        duration_days = luxia_hint.duration_days

    pace = rule_intent.pace
    if not _is_explicit_pace(message) and luxia_hint.pace:
        pace = luxia_hint.pace

    budget = rule_intent.budget
    if not _is_explicit_budget(message) and luxia_hint.budget:
        budget = luxia_hint.budget

    return rule_intent.model_copy(
        update={
            "destination": destination,
            "duration_days": duration_days,
            "interests": _merge_unique(rule_intent.interests, luxia_hint.interests),
            "avoid": _merge_unique(rule_intent.avoid, luxia_hint.avoid),
            "pace": pace,
            "visit_day": rule_intent.visit_day or luxia_hint.visit_day,
            "budget": budget,
            "mood": rule_intent.mood or luxia_hint.mood,
            "travel_style": rule_intent.travel_style or luxia_hint.travel_style,
            "group_type": luxia_hint.group_type,
            "food_preference": luxia_hint.food_preference,
            "indoor_outdoor": luxia_hint.indoor_outdoor,
            "time_of_day": luxia_hint.time_of_day,
            "transportation": luxia_hint.transportation,
            "walking_constraints": luxia_hint.walking_constraints,
            "stay_location": rule_intent.stay_location or luxia_hint.stay_location,
            "request_intents": _merge_unique(rule_intent.request_intents, luxia_hint.request_intents),
        }
    )


def extract_travel_intent(message: str) -> TravelIntent:
    rule_intent = enrich_preferences(message, _extract_core_intent(message))
    luxia_hint = _extract_with_luxia(message, rule_intent)
    merged = _merge_with_luxia(message, rule_intent, luxia_hint)
    merged = enrich_preferences(message, merged)
    user_type = _classify_user_type(
        message, merged.interests, merged.group_type, merged.travel_style
    )
    return merged.model_copy(update={
        "user_type": user_type,
        "first_time": user_type == "first_time_visitor",
    })
