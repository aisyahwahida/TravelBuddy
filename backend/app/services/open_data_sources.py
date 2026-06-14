from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from re import sub
from urllib import parse, request

from dotenv import load_dotenv

load_dotenv()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "open_data_places.json"
PARIS_OPEN_DATA_BASE = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets"
PARIS_EVENTS_DATASET = "que-faire-a-paris-"


def _get_json(url: str) -> dict:
    req = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": os.getenv("OPEN_DATA_USER_AGENT", "travelbuddy-france/0.1"),
        },
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    return sub(r"\s+", " ", sub(r"<[^>]+>", " ", unescape(value))).strip()


def _price_label(record: dict) -> str:
    price_type = (record.get("price_type") or "").lower()
    price_detail = record.get("price_detail") or ""
    if price_type == "gratuit":
        return "Free"
    if price_detail:
        return price_detail
    if price_type:
        return price_type
    return ""


def _lat_lon(record: dict) -> tuple[float, float] | None:
    lat_lon = record.get("lat_lon") or {}
    lat = lat_lon.get("lat")
    lon = lat_lon.get("lon")
    if lat in (None, 0, 0.0) or lon in (None, 0, 0.0):
        return None
    return float(lat), float(lon)


def _tags(record: dict) -> list[str]:
    raw_tags = [
        record.get("qfap_tags"),
        record.get("universe_tags"),
        record.get("group"),
        record.get("audience"),
    ]
    tags = ["paris", "event", "activity", "official", "open data"]
    for raw_tag in raw_tags:
        if not raw_tag:
            continue
        for tag in str(raw_tag).replace(";", ",").split(","):
            cleaned = tag.strip().lower()
            if cleaned:
                tags.append(cleaned)
    if (record.get("price_type") or "").lower() == "gratuit":
        tags.append("free")
    return list(dict.fromkeys(tags))


def _record_to_place(record: dict) -> dict | None:
    coordinates = _lat_lon(record)
    if coordinates is None:
        return None
    latitude, longitude = coordinates

    title = record.get("title") or record.get("title_event") or "Paris event"
    url = record.get("url") or record.get("contact_url") or record.get("access_link") or ""
    address_name = record.get("address_name") or record.get("contact_organisation_name") or ""
    address_city = record.get("address_city") or "Paris"
    lead_text = _strip_html(record.get("lead_text") or record.get("description"))
    date_text = record.get("date_description") or record.get("date_start") or ""
    price_label = _price_label(record)

    return {
        "name": title,
        "city": "Paris" if address_city.lower() in {"paris", ""} else address_city,
        "neighborhood": address_name,
        "address": ", ".join(
            part
            for part in [
                address_name,
                record.get("address_street") or "",
                record.get("address_zipcode") or "",
                address_city,
            ]
            if part
        ),
        "category": "event or activity",
        "reason": lead_text[:260] or "Official Paris open-data event or activity.",
        "local_tip": (
            "Check the official event page for latest schedule and reservation details."
        ),
        "tourist_trap_risk": "low",
        "best_time": date_text,
        "estimated_duration_minutes": 90,
        "latitude": latitude,
        "longitude": longitude,
        "map_source": "Paris Open Data",
        "map_url": url,
        "price_label": price_label,
        "google_maps_url": f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=18/{latitude}/{longitude}",
        "business_status": "",
        "opening_hours": [date_text] if date_text else [],
        "open_now": None,
        "tags": _tags(record),
        "source_type": "official_open_data",
        "source_title": "Que Faire a Paris? official open-data agenda",
        "source_url": url,
        "confidence": 0.9,
    }


def fetch_paris_events(limit: int = 50, search: str = "") -> list[dict]:
    params = {
        "limit": str(limit),
        "order_by": "updated_at desc",
    }
    if search:
        params["where"] = f"search(title, \"{search}\") or search(lead_text, \"{search}\")"

    url = (
        f"{PARIS_OPEN_DATA_BASE}/{PARIS_EVENTS_DATASET}/records?"
        f"{parse.urlencode(params)}"
    )
    data = _get_json(url)
    places = []
    for record in data.get("results", []):
        place = _record_to_place(record)
        if place:
            places.append(place)
    return places


def refresh_open_data_places(limit: int = 50, search: str = "") -> dict:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    places = fetch_paris_events(limit=limit, search=search)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Paris Open Data - Que Faire a Paris?",
        "place_count": len(places),
        "places": places,
    }
    DATA_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return {"place_count": len(places), "output_path": str(DATA_PATH)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh official open-data places.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--search", default="")
    args = parser.parse_args()
    print(json.dumps(refresh_open_data_places(limit=args.limit, search=args.search), indent=2))


if __name__ == "__main__":
    main()
