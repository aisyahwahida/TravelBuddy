from __future__ import annotations

import argparse
import json

from app.services.osm_places import refresh_osm_places
from app.services.reddit_ingestion import DEFAULT_SUBREDDITS, refresh_reddit_places


def refresh_reddit_then_osm(
    subreddits: list[str] | None = None,
    limit_per_query: int = 5,
    comment_limit: int = 8,
    osm_limit: int | None = None,
) -> dict:
    reddit_result = refresh_reddit_places(
        subreddits=subreddits or DEFAULT_SUBREDDITS,
        limit_per_query=limit_per_query,
        comment_limit=comment_limit,
    )
    osm_result = refresh_osm_places(limit=osm_limit)
    return {
        "reddit": reddit_result,
        "openstreetmap": osm_result,
        "note": (
            "Reddit was used to discover recommended places. OpenStreetMap "
            "Nominatim was then used to look up coordinates, map links, opening "
            "hours, and price/fee tags when available."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Reddit recommendations, then verify them with OpenStreetMap."
    )
    parser.add_argument("--subreddits", default=",".join(DEFAULT_SUBREDDITS))
    parser.add_argument("--limit-per-query", type=int, default=5)
    parser.add_argument("--comment-limit", type=int, default=8)
    parser.add_argument("--osm-limit", type=int, default=None)
    args = parser.parse_args()

    result = refresh_reddit_then_osm(
        subreddits=[item.strip() for item in args.subreddits.split(",") if item.strip()],
        limit_per_query=args.limit_per_query,
        comment_limit=args.comment_limit,
        osm_limit=args.osm_limit,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
