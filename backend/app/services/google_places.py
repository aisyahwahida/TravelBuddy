import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

from dotenv import load_dotenv

from app.data.france_places import FRANCE_PLACES
from app.services.retriever import REDDIT_PLACES_PATH

load_dotenv()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "google_places.json"
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


def _api_key() -> str:
    key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
    if not key:
        raise RuntimeError("Set GOOGLE_MAPS_API_KEY or GOOGLE_PLACES_API_KEY first.")
    return key


def _load_reddit_places() -> list[dict]:
    if not REDDIT_PLACES_PATH.exists():
        return []

    try:
        payload = json.loads(REDDIT_PLACES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        return payload.get("places", [])
    if isinstance(payload, list):
        return payload
    return []


def _candidate_places(reddit_only: bool = False) -> list[dict]:
    reddit_places = _load_reddit_places()
    if reddit_only:
        places = reddit_places
    else:
        places = [*FRANCE_PLACES, *reddit_places]
    deduped: dict[str, dict] = {}
    for place in places:
        key = f"{place.get('name', '').lower()}::{place.get('city', '').lower()}"
        deduped[key] = place
    return list(deduped.values())


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


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
        "textQuery": f"{place.get('name', '')} {place.get('city', '')} France",
        "languageCode": "en",
        "regionCode": "FR",
        "pageSize": 1,
    }
    data = _post_json(TEXT_SEARCH_URL, payload, headers)
    matches = data.get("places", [])
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
    }


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
    DATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"place_count": len(enriched), "output_path": str(DATA_PATH)}


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
