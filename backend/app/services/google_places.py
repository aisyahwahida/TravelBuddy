from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

import requests
from dotenv import load_dotenv

from app.data.france_places import FRANCE_PLACES
from app.schemas.travel import LocationAnchor
from app.services.luxia_client import LuxiaClient, extract_json_object
from app.services.place_identity import dedupe_place_dicts, place_identity_key
from app.services.place_exclusions import is_excluded_place
from app.services.retriever import REDDIT_PLACES_PATH

load_dotenv()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "google_places.json"
OPEN_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "open_data_places.json"
MUST_GO_PATH = Path(__file__).resolve().parents[1] / "data" / "france_must_go_places.json"
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_META_IMAGE_PATTERNS = [
    re.compile(
        r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
        re.IGNORECASE,
    ),
]
_translation_cache: dict[str, str] = {}


def _api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY or GOOGLE_PLACES_API_KEY first.")
    return key


def _load_places(path: Path) -> list[dict]:
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        return payload.get("places", [])
    if isinstance(payload, list):
        return payload
    return []


def _load_reddit_places() -> list[dict]:
    return _load_places(REDDIT_PLACES_PATH)


def _candidate_places(reddit_only: bool = False) -> list[dict]:
    reddit_places = _load_reddit_places()
    if reddit_only:
        places = reddit_places
    else:
        places = [
            *FRANCE_PLACES,
            *reddit_places,
            *_load_places(OPEN_DATA_PATH),
            *_load_places(MUST_GO_PATH),
        ]
    filtered: list[dict] = []
    for place in places:
        if is_excluded_place(
            str(place.get("name", "")),
            str(place.get("city", "")),
        ):
            continue
        filtered.append(place)
    return dedupe_place_dicts(filtered)


def _candidate_keys(reddit_only: bool = False) -> set[str]:
    return {
        place_identity_key(place)
        for place in _candidate_places(reddit_only=reddit_only)
    }


def _load_google_cache() -> dict:
    if not DATA_PATH.exists():
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Google Places API Text Search reviews",
            "reddit_only": False,
            "place_count": 0,
            "places": [],
        }

    try:
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Google Places API Text Search reviews",
            "reddit_only": False,
            "place_count": 0,
            "places": [],
        }
    if isinstance(payload, dict):
        payload.setdefault("places", [])
        return payload
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Google Places API Text Search reviews",
        "reddit_only": False,
        "place_count": 0,
        "places": payload if isinstance(payload, list) else [],
    }


def _save_google_cache(payload: dict) -> dict:
    payload["places"] = [
        place
        for place in payload.get("places", [])
        if not is_excluded_place(
            str(place.get("name", "")),
            str(place.get("city", "")),
        )
    ]
    payload["place_count"] = len(payload.get("places", []))
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    DATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"place_count": payload["place_count"], "output_path": str(DATA_PATH)}


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _search_text_places(text_query: str, language_code: str = "en") -> list[dict]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": _api_key(),
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,places.location,"
            "places.rating,places.userRatingCount,places.googleMapsUri,places.reviews,"
            "places.businessStatus,places.currentOpeningHours,places.regularOpeningHours,"
            "places.priceLevel,places.photos"
        ),
    }
    payload = {
        "textQuery": text_query,
        "languageCode": language_code,
        "regionCode": "FR",
        "pageSize": 1,
    }
    data = _post_json(TEXT_SEARCH_URL, payload, headers)
    return data.get("places", [])


def _fetch_wiki_thumbnail(name: str) -> str:
    """Return the Wikipedia thumbnail URL for a place name, or empty string."""
    if not name:
        return ""
    title = name.strip()
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}"
        resp = requests.get(url, timeout=5, headers={"User-Agent": "travelbuddy-france/0.1"})
        if resp.status_code == 200:
            data = resp.json()
            return data.get("thumbnail", {}).get("source", "")
    except Exception:
        pass
    return ""


def _translate_query_to_french(text_query: str) -> str:
    cached = _translation_cache.get(text_query)
    if cached is not None:
        return cached

    client = LuxiaClient()
    if not client.is_configured:
        _translation_cache[text_query] = ""
        return ""

    try:
        raw = client.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the travel place search query into natural French for a Google Maps place lookup. "
                        "Return only JSON like {\"translated_query\": \"...\"}. Keep place names precise."
                    ),
                },
                {"role": "user", "content": json.dumps({"query": text_query})},
            ],
            temperature=0.0,
            max_tokens=120,
            model_override="luxia3-llm-8b-0731",
        )
        translated = str(extract_json_object(raw).get("translated_query", "")).strip()
    except Exception:
        translated = ""

    _translation_cache[text_query] = translated
    return translated


def _review_text(review: dict) -> str:
    text = review.get("text")
    if isinstance(text, dict):
        return text.get("text", "")
    return ""


def _price_label(price_level: str) -> str:
    return {
        "PRICE_LEVEL_FREE": "Free",
        "PRICE_LEVEL_INEXPENSIVE": "Inexpensive",
        "PRICE_LEVEL_MODERATE": "Moderate",
        "PRICE_LEVEL_EXPENSIVE": "Expensive",
        "PRICE_LEVEL_VERY_EXPENSIVE": "Very expensive",
    }.get(price_level, "")


def fetch_google_place(place: dict) -> dict | None:
    base_query = f"{place.get('name', '')} {place.get('city', '')} France".strip()
    matches = _search_text_places(base_query, language_code="en")
    if not matches:
        matches = _search_text_places(base_query, language_code="fr")
    if not matches:
        translated_query = _translate_query_to_french(base_query)
        if translated_query and translated_query.lower() != base_query.lower():
            matches = _search_text_places(translated_query, language_code="fr")
    if not matches and place.get("name") and place.get("city"):
        compact_query = f"{place.get('name', '')} {place.get('city', '')}".strip()
        matches = _search_text_places(compact_query, language_code="fr")
    if not matches:
        return None

    match = matches[0]
    display_name = match.get("displayName", {}).get("text", place.get("name", ""))
    rating = match.get("rating")
    review_count = match.get("userRatingCount")
    price_level = match.get("priceLevel", "")
    current_hours = match.get("currentOpeningHours") or {}
    regular_hours = match.get("regularOpeningHours") or {}
    opening_hours = (
        current_hours.get("weekdayDescriptions")
        or regular_hours.get("weekdayDescriptions")
        or []
    )
    reviews = [
        {
            "author": review.get("authorAttribution", {}).get("displayName", ""),
            "rating": review.get("rating"),
            "text": _review_text(review)[:420],
        }
        for review in match.get("reviews", [])[:3]
    ]

    photos = match.get("photos", [])
    photo_name = photos[0].get("name", "") if photos else ""
    wiki_thumb_url = "" if photo_name else _fetch_wiki_thumbnail(place.get("name", ""))

    title_parts = ["Google Maps reviews"]
    if rating:
        title_parts.append(f"{rating:.1f} stars")
    if review_count:
        title_parts.append(f"{review_count} reviews")

    return {
        "name": place.get("name", ""),
        "city": place.get("city", ""),
        "place_id": match.get("id", ""),
        "display_name": display_name,
        "formatted_address": match.get("formattedAddress", ""),
        "rating": rating,
        "user_rating_count": review_count,
        "price_level": price_level,
        "price_label": _price_label(price_level),
        "business_status": match.get("businessStatus", ""),
        "opening_hours": opening_hours,
        "open_now": current_hours.get("openNow"),
        "google_maps_url": match.get("googleMapsUri", ""),
        "map_source": "Google Maps",
        "map_url": match.get("googleMapsUri", ""),
        "source_type": "google_maps",
        "source_title": " / ".join(title_parts),
        "source_url": match.get("googleMapsUri", ""),
        "reddit_source_title": place.get("source_title", ""),
        "reddit_source_url": place.get("source_url", ""),
        "reviews": reviews,
        "photo_name": photo_name,
        "wiki_thumb_url": wiki_thumb_url,
    }


def resolve_stay_location(stay_query: str, destination: str = "") -> LocationAnchor | None:
    query = " ".join(part for part in [stay_query.strip(), destination.strip(), "France"] if part).strip()
    if not query:
        return None

    matches = _search_text_places(query, language_code="en")
    if not matches:
        matches = _search_text_places(query, language_code="fr")
    if not matches:
        translated = _translate_query_to_french(query)
        if translated and translated.lower() != query.lower():
            matches = _search_text_places(translated, language_code="fr")
    if not matches:
        return None

    match = matches[0]
    location = match.get("location") or {}
    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is None or lon is None:
        return None

    return LocationAnchor(
        name=match.get("displayName", {}).get("text", stay_query.strip()) or stay_query.strip(),
        city=destination,
        address=match.get("formattedAddress", ""),
        latitude=float(lat),
        longitude=float(lon),
        google_maps_url=match.get("googleMapsUri", ""),
    )


def refresh_google_places(limit: int | None = None, reddit_only: bool = False) -> dict:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    enriched: list[dict] = []
    candidates = _candidate_places(reddit_only=reddit_only)
    if limit:
        candidates = candidates[:limit]

    for place in candidates:
        match = fetch_google_place(place)
        if match:
            enriched.append(match)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": (
            "Google Places API Text Search for Reddit recommendations"
            if reddit_only
            else "Google Places API Text Search reviews"
        ),
        "reddit_only": reddit_only,
        "place_count": len(enriched),
        "places": enriched,
    }
    return _save_google_cache(payload)


def backfill_google_place_photos(
    limit: int | None = None,
    reddit_only: bool = False,
) -> dict:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = _load_google_cache()
    cached_places = payload.get("places", [])
    candidate_keys = _candidate_keys(reddit_only=reddit_only)
    by_key = {
        f"{place.get('name', '').lower()}::{place.get('city', '').lower()}": place
        for place in cached_places
        if f"{place.get('name', '').lower()}::{place.get('city', '').lower()}" in candidate_keys
        and not is_excluded_place(
            str(place.get("name", "")),
            str(place.get("city", "")),
        )
    }

    candidates = _candidate_places(reddit_only=reddit_only)
    pending = []
    for place in candidates:
        key = f"{place.get('name', '').lower()}::{place.get('city', '').lower()}"
        cached = by_key.get(key)
        if cached and cached.get("photo_name"):
            continue
        pending.append(place)

    if limit:
        pending = pending[:limit]

    updated = 0
    added = 0
    for place in pending:
        key = f"{place.get('name', '').lower()}::{place.get('city', '').lower()}"
        match = fetch_google_place(place)
        if not match:
            continue
        if key in by_key:
            merged = {**by_key[key], **match}
            if merged.get("photo_name") and not by_key[key].get("photo_name"):
                updated += 1
            by_key[key] = merged
        else:
            by_key[key] = match
            added += 1

    payload["places"] = list(by_key.values())
    save_result = _save_google_cache(payload)
    return {
        **save_result,
        "checked": len(pending),
        "updated_photo_count": updated,
        "added_place_count": added,
    }


def resolve_source_image(source_url: str) -> str:
    if not source_url:
        return ""

    try:
        response = requests.get(
            source_url,
            timeout=10,
            headers={"User-Agent": "travelbuddy-france/0.1"},
        )
        response.raise_for_status()
    except Exception:
        return ""

    html = response.text
    for pattern in _META_IMAGE_PATTERNS:
        match = pattern.search(html)
        if match:
            return match.group(1).strip()
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Google Maps review sources.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--reddit-only",
        action="store_true",
        help="Only search Google Maps for places extracted from Reddit.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            refresh_google_places(limit=args.limit, reddit_only=args.reddit_only),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
