from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

GOOGLE_PLACES_PATH = Path(__file__).resolve().parents[1] / "data" / "google_places.json"


def _norm(value: str) -> str:
    return " ".join(value.lower().strip().split())


@lru_cache(maxsize=1)
def permanently_closed_place_keys() -> set[tuple[str, str]]:
    if not GOOGLE_PLACES_PATH.exists():
        return set()

    try:
        payload = json.loads(GOOGLE_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    places = payload.get("places", []) if isinstance(payload, dict) else []
    closed: set[tuple[str, str]] = set()
    for place in places:
        if place.get("business_status") != "CLOSED_PERMANENTLY":
            continue
        city = _norm(str(place.get("city", "")))
        for name_field in ("name", "display_name"):
            name = _norm(str(place.get(name_field, "")))
            if name and city:
                closed.add((name, city))
    return closed


@lru_cache(maxsize=1)
def permanently_closed_place_names() -> set[str]:
    return {name for name, _ in permanently_closed_place_keys()}


def is_permanently_closed_place(name: str, city: str) -> bool:
    return (_norm(name), _norm(city)) in permanently_closed_place_keys()


def scrub_permanently_closed_names(text: str) -> str:
    cleaned = text
    for name in sorted(permanently_closed_place_names(), key=len, reverse=True):
        if name:
            cleaned = re.sub(re.escape(name), "[removed closed place]", cleaned, flags=re.IGNORECASE)
    return cleaned
