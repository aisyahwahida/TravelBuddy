import re
from datetime import datetime, timedelta

from app.schemas.travel import TravelIntent
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
    currency_match = re.search(r"([$€£]\s?\d+|\d+\s?(?:eur|euro|euros|usd|dollars))", lowered)
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


def extract_travel_intent(message: str) -> TravelIntent:
    lowered = message.lower()

    destination = next(
        (
            "France" if city == "france" else city.title()
            for city in KNOWN_DESTINATIONS
            if _contains_term(lowered, city)
        ),
        "Paris",
    )

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
    interests = list(dict.fromkeys(interests))
    duration_days = 1
    for days in range(1, 15):
        if f"{days} day" in lowered or f"{days}-day" in lowered:
            duration_days = days
            break
    if "weekend" in lowered and duration_days == 1:
        duration_days = 2

    if "slow" in lowered or "relaxed" in lowered:
        pace = "slow"
    elif "fast" in lowered or "packed" in lowered:
        pace = "fast"
    else:
        pace = "balanced"

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
    avoid = [] if must_go_request else [item for item in KNOWN_AVOIDS if item in lowered]

    intent = TravelIntent(
        destination=destination,
        duration_days=duration_days,
        interests=interests or default_mixed_interests,
        avoid=avoid if must_go_request else (avoid or ["tourist traps"]),
        pace=pace,
        visit_day=_extract_visit_day(message),
        budget=_extract_budget(message),
        mood=_extract_mood(message),
        travel_style=_extract_travel_style(message),
    )
    return enrich_preferences(message, intent)
