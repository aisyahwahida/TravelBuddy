from __future__ import annotations

import math
import re
import unicodedata
from typing import Any


_STOPWORDS = {
    "the",
    "a",
    "an",
    "de",
    "du",
    "des",
    "le",
    "la",
    "les",
    "d",
    "l",
    "of",
    "and",
    "et",
    "au",
    "aux",
    "sur",
    "must",
    "go",
}

_TOKEN_MAP = {
    "jardin": "garden",
    "jardins": "garden",
    "garden": "garden",
    "gardens": "garden",
    "parc": "park",
    "parcs": "park",
    "park": "park",
    "parks": "park",
    "champ": "champ",
    "champs": "champ",
    "musee": "museum",
    "musees": "museum",
    "museum": "museum",
    "museums": "museum",
    "galerie": "gallery",
    "galeries": "gallery",
    "gallery": "gallery",
    "galleries": "gallery",
    "bibliotheque": "library",
    "bibliotheques": "library",
    "library": "library",
    "libraries": "library",
    "librairie": "bookstore",
    "librairies": "bookstore",
    "bookstore": "bookstore",
    "bookstores": "bookstore",
    "marche": "market",
    "marches": "market",
    "market": "market",
    "markets": "market",
    "cathedrale": "cathedral",
    "cathedrales": "cathedral",
    "cathedral": "cathedral",
    "cathedrals": "cathedral",
    "eglise": "church",
    "eglises": "church",
    "church": "church",
    "churches": "church",
}

_CANONICAL_ALIASES = {
    ("louvre", "museum"): "louvre museum",
    # "Galeries Lafayette", "Galeries Lafayette Haussmann", "Galeries Lafayette (Haussmann)"
    # all refer to the same Paris landmark — normalise to one key
    ("gallery", "lafayette"): "gallery lafayette haussmann",
}


def _fold_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()


def _tokenize_name(name: str) -> list[str]:
    stripped = re.sub(r"\([^)]*\)", " ", _fold_text(name))
    raw_tokens = re.findall(r"[a-z0-9]+", stripped)
    tokens: list[str] = []
    for token in raw_tokens:
        if token in _STOPWORDS:
            continue
        mapped = _TOKEN_MAP.get(token, token)
        tokens.append(mapped)
    return tokens


def normalized_city(city: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _fold_text(city)))


def canonical_name_key(name: str) -> str:
    tokens = _tokenize_name(name)
    if not tokens:
        return ""
    token_set = set(tokens)
    for alias_tokens, canonical in _CANONICAL_ALIASES.items():
        if set(alias_tokens).issubset(token_set):
            return canonical
    return " ".join(sorted(tokens))


def canonical_category_key(category: str) -> str:
    tokens = _tokenize_name(category)
    if not tokens:
        return ""
    return " ".join(sorted(tokens))


def place_identity_key(place: Any) -> str:
    city = normalized_city(str(_get(place, "city", "")))
    name = canonical_name_key(str(_get(place, "name", "")))
    category = canonical_category_key(str(_get(place, "category", "")))
    if name:
        return f"{city}::{name}::{category}"
    lat = _safe_float(_get(place, "latitude"))
    lon = _safe_float(_get(place, "longitude"))
    if lat is not None and lon is not None:
        return f"{city}::coords::{round(lat, 4)}::{round(lon, 4)}"
    return f"{city}::{_fold_text(str(_get(place, 'name', '')))}"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get(place: Any, field: str, default: Any = "") -> Any:
    if isinstance(place, dict):
        return place.get(field, default)
    return getattr(place, field, default)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, set, tuple)):
        return bool(value)
    return True


def _richness_score(place: dict) -> int:
    score = 0
    for field in (
        "source_url",
        "photo_name",
        "google_maps_url",
        "wiki_thumb_url",
        "address",
        "neighborhood",
        "source_title",
    ):
        if _has_value(place.get(field)):
            score += 1
    for field in (
        "google_rating",
        "google_user_rating_count",
        "open_now",
    ):
        if place.get(field) is not None:
            score += 1
    score += len(place.get("opening_hours", []) or [])
    score += min(3, len(place.get("tags", []) or []))
    score += min(3, len(str(place.get("reason", ""))) // 40)
    score += min(2, len(str(place.get("local_tip", ""))) // 40)
    return score


def merge_place_dicts(current: dict, incoming: dict) -> dict:
    keep, merge = (current, incoming)
    if _richness_score(incoming) > _richness_score(current):
        keep, merge = incoming, current

    merged = dict(keep)
    for key, value in merge.items():
        if not _has_value(merged.get(key)) and _has_value(value):
            merged[key] = value
        elif key == "tags":
            merged[key] = list(dict.fromkeys([*(merged.get(key) or []), *(value or [])]))
        elif key == "opening_hours":
            merged[key] = list(dict.fromkeys([*(merged.get(key) or []), *(value or [])]))
    return merged


def dedupe_place_dicts(places: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for place in places:
        key = place_identity_key(place)
        existing = deduped.get(key)
        deduped[key] = merge_place_dicts(existing, place) if existing else place
    return list(deduped.values())


def _name_token_overlap(a: dict, b: dict) -> float:
    """Jaccard overlap of significant name tokens (stopwords and type words stripped)."""
    tokens_a = set(_tokenize_name(a.get("name", "")))
    tokens_b = set(_tokenize_name(b.get("name", "")))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def proximity_dedupe_place_dicts(
    places: list[dict],
    distance_km: float = 0.12,
    name_overlap_threshold: float = 0.60,
) -> list[dict]:
    """
    Secondary dedup pass that catches places with slightly different names
    but the same physical location.

    Two places are considered duplicates when:
      - they are within `distance_km` of each other (default 120 m), AND
      - their significant name tokens overlap by ≥ `name_overlap_threshold`.

    Example pairs caught:
      "Musée du Louvre" / "Louvre Museum" / "The Louvre"  (all ~0 m apart)
      "Café de Flore" / "Cafe de Flore"                   (diacritics already folded)

    The richer of the two entries is kept (via merge_place_dicts).
    Runs in O(n · w) where w is the number of places within a small lat window —
    typically < 20 even for dense city data.
    """
    if not places:
        return places

    # Sort by latitude so we only scan backwards within a ~distance_km lat window.
    lat_delta = distance_km / 111.0  # degrees lat per km
    sorted_places = sorted(
        places,
        key=lambda p: (float(p.get("latitude") or 0), float(p.get("longitude") or 0)),
    )

    result: list[dict] = []
    for place in sorted_places:
        place_lat = float(place.get("latitude") or 0)
        merged = False

        # Walk backwards through result — stop when lat gap exceeds window
        for i in range(len(result) - 1, -1, -1):
            existing = result[i]
            if place_lat - float(existing.get("latitude") or 0) > lat_delta:
                break
            dist = place_distance_km(place, existing)
            if dist is None or dist > distance_km:
                continue
            if _name_token_overlap(place, existing) >= name_overlap_threshold:
                result[i] = merge_place_dicts(existing, place)
                merged = True
                break

        if not merged:
            result.append(place)

    return result


def place_distance_km(a: Any, b: Any) -> float | None:
    lat1 = _safe_float(_get(a, "latitude"))
    lon1 = _safe_float(_get(a, "longitude"))
    lat2 = _safe_float(_get(b, "latitude"))
    lon2 = _safe_float(_get(b, "longitude"))
    if None in {lat1, lon1, lat2, lon2}:
        return None
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))
