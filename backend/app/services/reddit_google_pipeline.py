from __future__ import annotations

import argparse
import json

from app.services.google_places import refresh_google_places
from app.services.reddit_ingestion import DEFAULT_SUBREDDITS, refresh_reddit_places


def refresh_reddit_then_google(
    subreddits: list[str] | None = None,
    limit_per_query: int = 5,
    comment_limit: int = 8,
    google_limit: int | None = None,
) -> dict:
    reddit_result = refresh_reddit_places(
        subreddits=subreddits or DEFAULT_SUBREDDITS,
        limit_per_query=limit_per_query,
        comment_limit=comment_limit,
    )
    google_result = refresh_google_places(limit=google_limit, reddit_only=True)
    return {
        "reddit": reddit_result,
        "google": google_result,
        "note": (
            "Reddit was used to discover recommended places. Google Places was "
            "then used to verify map links, ratings, opening hours, and price levels."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Reddit recommendations, then verify them with Google Places."
    )
    parser.add_argument("--subreddits", default=",".join(DEFAULT_SUBREDDITS))
    parser.add_argument("--limit-per-query", type=int, default=5)
    parser.add_argument("--comment-limit", type=int, default=8)
    parser.add_argument("--google-limit", type=int, default=None)
    args = parser.parse_args()

    result = refresh_reddit_then_google(
        subreddits=[item.strip() for item in args.subreddits.split(",") if item.strip()],
        limit_per_query=args.limit_per_query,
        comment_limit=args.comment_limit,
        google_limit=args.google_limit,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
