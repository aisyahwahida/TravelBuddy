from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse, request

from dotenv import load_dotenv

from app.services.retriever import REDDIT_PLACES_PATH

load_dotenv()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "osm_places.json"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "travelbuddy-france-local-recs/0.1"


def _user_agent() -> str:
    return os.getenv("OSM_USER_AGENT") or os.getenv("NOMINATIM_USER_AGENT") or DEFAULT_USER_AGENT


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


def _osm_url(osm_type: str, osm_id: int | str, latitude: float, longitude: float) -> str:
    if osm_type and osm_id:
        return f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
    return f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=18/{latitude}/{longitude}"


def _price_label(extratags: dict) -> str:
    for key in ("price", "charge", "fee", "fee:conditional"):
        value = extratags.get(key)
        if value:
            if key == "fee" and value == "no":
                return "Free"
            if key == "fee" and value == "yes":
                return "Fee may apply"
            return str(value)
    return ""


def _category(result: dict, fallback: dict) -> str:
    result_type = result.get("type", "")
    result_class = result.get("class", "")
    if result_type:
        return result_type.replace("_", " ")
    if result_class:
        return result_class.replace("_", " ")
    return fallback.get("category", "place")


def _search_nominatim(place: dict) -> dict | None:
    params = {
        "q": f"{place.get('name', '')} {place.get('city', '')} France",
        "format": "jsonv2",
        "addressdetails": "1",
        "extratags": "1",
        "namedetails": "1",
        "limit": "1",
        "countrycodes": "fr",
    }
    url = f"{NOMINATIM_SEARCH_URL}?{parse.urlencode(params)}"
    req = request.Request(
        url,
        headers={
            "User-Agent": _user_agent(),
            "Accept": "application/json",
        },
    )
    with request.urlopen(req, timeout=20) as response:
        matches = json.loads(response.read().decode("utf-8"))

    if not matches:
        return None

    result = matches[0]
    extratags = result.get("extratags") or {}
    address = result.get("address") or {}
    latitude = float(result.get("lat") or place.get("latitude") or 0)
    longitude = float(result.get("lon") or place.get("longitude") or 0)
    osm_type = result.get("osm_type", "")
    osm_id = result.get("osm_id", "")
    source_url = _osm_url(osm_type, osm_id, latitude, longitude)
    opening_hours = extratags.get("opening_hours", "")
    price_label = _price_label(extratags)

    return {
        "name": place.get("name", result.get("name", "")),
        "display_name": result.get("display_name", ""),
        "city": place.get("city") or address.get("city") or address.get("town") or "Paris",
        "neighborhood": place.get("neighborhood") or address.get("suburb", ""),
        "category": _category(result, place),
        "latitude": latitude,
        "longitude": longitude,
        "map_source": "OpenStreetMap",
        "map_url": source_url,
        "price_label": price_label,
        "opening_hours": [opening_hours] if opening_hours else [],
        "open_now": None,
        "business_status": "",
        "source_type": "openstreetmap",
        "source_title": "OpenStreetMap place details",
        "source_url": source_url,
        "website": extratags.get("website") or extratags.get("contact:website", ""),
        "phone": extratags.get("phone") or extratags.get("contact:phone", ""),
        "reddit_source_title": place.get("source_title", ""),
        "reddit_source_url": place.get("source_url", ""),
        "raw_extratags": extratags,
    }


def refresh_osm_places(limit: int | None = None, delay_seconds: float = 1.1) -> dict:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidates = _load_reddit_places()
    if limit:
        candidates = candidates[:limit]

    enriched: list[dict] = []
    for index, place in enumerate(candidates):
        match = _search_nominatim(place)
        if match:
            enriched.append(match)
        if index < len(candidates) - 1:
            time.sleep(delay_seconds)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap Nominatim search for Reddit recommendations",
        "place_count": len(enriched),
        "places": enriched,
    }
    DATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"place_count": len(enriched), "output_path": str(DATA_PATH)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh OpenStreetMap details for Reddit-derived France places."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay-seconds", type=float, default=1.1)
    args = parser.parse_args()
    print(
        json.dumps(
            refresh_osm_places(limit=args.limit, delay_seconds=args.delay_seconds),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
