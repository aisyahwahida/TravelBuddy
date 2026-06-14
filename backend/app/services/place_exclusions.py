from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

EXCLUDED_PLACES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "excluded_places.json"
)


def _norm(value: str) -> str:
    return " ".join(value.lower().strip().split())


@lru_cache(maxsize=1)
def excluded_place_keys() -> set[tuple[str, str]]:
    if not EXCLUDED_PLACES_PATH.exists():
        return set()

    try:
        payload = json.loads(EXCLUDED_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    places = payload.get("places", []) if isinstance(payload, dict) else payload
    keys: set[tuple[str, str]] = set()
    for place in places:
        name = _norm(str(place.get("name", "")))
        city = _norm(str(place.get("city", "")))
        if name and city:
            keys.add((name, city))
    return keys


def is_excluded_place(name: str, city: str) -> bool:
    return (_norm(name), _norm(city)) in excluded_place_keys()
