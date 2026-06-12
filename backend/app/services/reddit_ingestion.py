import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.schemas.travel import Place
from app.services.luxia_client import LuxiaClient, extract_json_object

load_dotenv()

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "reddit_places.json"
RAW_SNIPPETS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "reddit_raw_snippets.json"
)
MANUAL_SNIPPETS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "manual_reddit_snippets.json"
)
DEFAULT_SUBREDDITS = ["france", "paris", "AskFrance"]
DEFAULT_PUBLIC_SEARCH_SUBREDDITS = [
    "ParisTravelGuide",
    "paris",
    "AskFrance",
    "france",
    "Lyon",
    "nicefrance",
    "Expats_In_France",
]
DEFAULT_QUERIES = [
    "cafe local Paris pas touristique",
    "coffee shop Paris local",
    "meilleur cafe Paris habitants",
    "cafe tranquille Paris",
    "bon cafe Lyon local",
    "bon cafe Marseille local",
    "bon cafe Bordeaux local",
    "restaurant local Paris pas touristique",
    "bon restaurant Paris habitants",
    "adresse locale Paris",
    "ou manger Paris pas touristique",
    "restaurant Lyon local",
    "restaurant Marseille local",
    "restaurant Bordeaux local",
    "endroit sympa France pas touristique",
    "non touristy Paris",
    "local neighborhood Paris",
    "where locals eat Paris",
    "hidden gems Paris",
    "marche Paris locals",
    "ou manger Paris pas touristique",
    "sortir a Paris ce weekend",
    "quartiers sympas Paris locaux",
    "marches de quartier Paris",
    "balade Paris insolite",
    "restaurant de quartier Paris",
    "restaurant asiatique Paris pas touristique",
    "cantine japonaise Paris",
    "ou manger coreen Paris",
    "pho Paris quartier",
    "shopping Paris souvenirs",
    "affordable shopping Paris",
    "vintage thrift shopping Paris",
    "luxury shopping Paris",
    "boutiques locales Lyon",
    "souvenirs Nice",
]
DEFAULT_PUBLIC_SEARCH_QUERIES = [
    "local restaurants Paris",
    "affordable restaurants Paris local favorites",
    "where locals eat Paris",
    "non touristy Paris",
    "hidden gems Paris",
    "local neighborhood Paris",
    "Paris cafes local",
    "best cafes Paris",
    "coffee shops Paris",
    "free museums Paris",
    "small museums Paris",
    "markets Paris locals",
    "shopping Paris souvenirs",
    "affordable Paris souvenirs",
    "vintage thrift shopping Paris",
    "best affordable shopping Paris",
    "luxury shopping Paris",
    "things to do Paris local",
    "local restaurants Lyon",
    "souvenirs Lyon",
    "local boutiques Lyon",
    "things to do Lyon local",
    "restaurants Nice local",
    "souvenirs Nice",
    "things to do Nice local",
    "Marseille local restaurants",
    "Marseille hidden gems",
    "Bordeaux local restaurants",
    "Strasbourg local restaurants",
    "Lille local restaurants",
]
DEFAULT_REDDIT_THREAD_URLS = [
    "https://www.reddit.com/r/ParisTravelGuide/comments/1t8cvl8/affordable_paris_souvenirs/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1l5ue90/must_have_stuff_to_buy_in_paris/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1r7n5ac/must_buys_in_paris/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1m5hoba/paris_off_the_tourist_path_july_2025/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1isb6sm/vintage_thrift_shopping/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1jbx0nw/best_places_to_thrift/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1jqsz51/secondhand_shopping_areas_that_arent_outrageously_expensive/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1p8xcn7/best_and_affordable_shopping_in_paris/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1qgm4tp/tips_for_buying_souvenirs_in_paris/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1rrtcc0/special_souvenir/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1ry8w6n/iconic_stores_that_are_mustvisits_in_paris_for_a/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1tmh5mr/something_fun/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1t6g09f/best_paris_keepsake/",
    "https://www.reddit.com/r/ParisTravelGuide/comments/1t8cep4/french_product_recommendations/",
    "https://www.reddit.com/r/nicefrance/comments/1satop5/cheap_souvenirs/",
    "https://www.reddit.com/r/Lyon/comments/1ft6tkg/local_boutiques_and_stores/",
    "https://www.reddit.com/r/Lyon/comments/1cypn9p/boutique_cadeaux/",
    "https://www.reddit.com/r/Lyon/comments/vpp2qr/souvenirs_de_lyon/",
    "https://www.reddit.com/r/Lyon/comments/1lb59j4/lyon_in_48_hours_what_should_we_see_and_avoid/",
]
CITY_CENTER_COORDS = {
    "paris": (48.8566, 2.3522),
    "lyon": (45.7640, 4.8357),
    "marseille": (43.2965, 5.3698),
    "nice": (43.7102, 7.2620),
    "bordeaux": (44.8378, -0.5792),
    "strasbourg": (48.5734, 7.7521),
    "lille": (50.6292, 3.0573),
}
PLACE_STRING_FIELDS = [
    "neighborhood",
    "address",
    "map_source",
    "map_url",
    "price_label",
    "google_maps_url",
    "google_price_level",
    "google_price_label",
    "business_status",
    "open_status_label",
    "source_title",
    "source_url",
]


class RedditSnippet(BaseModel):
    id: str = ""
    kind: str = "post"
    subreddit: str
    title: str
    text: str
    score: int
    permalink: str
    parent_permalink: str = ""
    created_utc: float | None = None
    query: str = ""


class RedditExtraction(BaseModel):
    places: list[Place] = Field(default_factory=list)


def _reddit_client():
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "travelbuddy-france-local-recs/0.1 by local-dev",
    )

    if not client_id or not client_secret:
        raise RuntimeError(
            "Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT first."
        )

    import praw

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def collect_reddit_snippets(
    subreddits: list[str],
    queries: list[str],
    limit_per_query: int,
    comment_limit: int,
) -> list[RedditSnippet]:
    reddit = _reddit_client()
    snippets: list[RedditSnippet] = []
    seen: set[str] = set()

    for subreddit_name in subreddits:
        subreddit = reddit.subreddit(subreddit_name)
        for query in queries:
            for submission in subreddit.search(
                query,
                sort="relevance",
                time_filter="year",
                limit=limit_per_query,
            ):
                if submission.id in seen:
                    continue
                seen.add(submission.id)

                comment_texts: list[str] = []
                submission.comments.replace_more(limit=0)
                for comment in list(submission.comments)[:comment_limit]:
                    body = getattr(comment, "body", "")
                    if body and body not in ("[deleted]", "[removed]"):
                        comment_texts.append(body[:1200])

                text_parts = [submission.selftext or "", *comment_texts]
                snippets.append(
                    RedditSnippet(
                        id=submission.id,
                        kind="post_bundle",
                        subreddit=subreddit_name,
                        title=submission.title,
                        text="\n\n".join(part for part in text_parts if part)[:6000],
                        score=int(submission.score or 0),
                        permalink=f"https://www.reddit.com{submission.permalink}",
                        created_utc=float(submission.created_utc or 0),
                        query=query,
                    )
                )

    return snippets


def _valid_text(text: str) -> bool:
    return bool(text and text not in {"[deleted]", "[removed]"} and len(text.strip()) >= 25)


def _append_unique_snippet(
    snippets: list[RedditSnippet],
    seen: set[str],
    snippet: RedditSnippet,
    max_snippets: int,
) -> bool:
    if snippet.id in seen or not _valid_text(snippet.text):
        return False
    seen.add(snippet.id)
    snippets.append(snippet)
    return len(snippets) >= max_snippets


def _submission_comments(submission, comment_limit: int) -> Iterable:
    submission.comments.replace_more(limit=0)
    return list(submission.comments.list())[:comment_limit]


def collect_reddit_raw_snippets(
    subreddits: list[str],
    queries: list[str],
    max_snippets: int = 500,
    posts_per_query: int = 25,
    comments_per_post: int = 15,
    time_filter: str = "all",
) -> list[RedditSnippet]:
    reddit = _reddit_client()
    snippets: list[RedditSnippet] = []
    seen: set[str] = set()

    for subreddit_name in subreddits:
        subreddit = reddit.subreddit(subreddit_name)
        for query in queries:
            for submission in subreddit.search(
                query,
                sort="relevance",
                time_filter=time_filter,
                limit=posts_per_query,
            ):
                post_permalink = f"https://www.reddit.com{submission.permalink}"
                post_text = "\n\n".join(
                    part
                    for part in [submission.title, submission.selftext or ""]
                    if part
                )
                reached_limit = _append_unique_snippet(
                    snippets,
                    seen,
                    RedditSnippet(
                        id=f"post_{submission.id}",
                        kind="post",
                        subreddit=subreddit_name,
                        title=submission.title,
                        text=post_text[:2500],
                        score=int(submission.score or 0),
                        permalink=post_permalink,
                        created_utc=float(submission.created_utc or 0),
                        query=query,
                    ),
                    max_snippets,
                )
                if reached_limit:
                    return snippets

                for comment in _submission_comments(submission, comments_per_post):
                    body = getattr(comment, "body", "")
                    reached_limit = _append_unique_snippet(
                        snippets,
                        seen,
                        RedditSnippet(
                            id=f"comment_{comment.id}",
                            kind="comment",
                            subreddit=subreddit_name,
                            title=submission.title,
                            text=body[:2500],
                            score=int(getattr(comment, "score", 0) or 0),
                            permalink=f"https://www.reddit.com{comment.permalink}",
                            parent_permalink=post_permalink,
                            created_utc=float(getattr(comment, "created_utc", 0) or 0),
                            query=query,
                        ),
                        max_snippets,
                    )
                    if reached_limit:
                        return snippets

    return snippets


def _reddit_json_url(url: str) -> str:
    clean_url = url.split("?")[0].rstrip("/")
    return f"{clean_url}.json?limit=500"


def _flatten_reddit_comments(children: list[dict]) -> Iterable[dict]:
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {})
        yield data
        replies = data.get("replies")
        if isinstance(replies, dict):
            nested = replies.get("data", {}).get("children", [])
            yield from _flatten_reddit_comments(nested)


def collect_public_thread_snippets(
    urls: list[str],
    max_snippets: int = 500,
    comments_per_thread: int = 80,
    request_delay_seconds: float = 1.5,
) -> list[RedditSnippet]:
    snippets: list[RedditSnippet] = []
    seen: set[str] = set()
    user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "travelbuddy-france-local-recs/0.1 by local-dev",
    )

    for url in urls:
        if len(snippets) >= max_snippets:
            break
        request = urllib.request.Request(
            _reddit_json_url(url),
            headers={"User-Agent": user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError):
            continue

        if not isinstance(payload, list) or len(payload) < 2:
            continue

        post_data = payload[0].get("data", {}).get("children", [{}])[0].get("data", {})
        subreddit = post_data.get("subreddit", "reddit")
        title = post_data.get("title", "Reddit recommendation thread")
        post_permalink = f"https://www.reddit.com{post_data.get('permalink', '')}" or url
        post_text = "\n\n".join(
            part for part in [title, post_data.get("selftext", "")] if part
        )
        if _append_unique_snippet(
            snippets,
            seen,
            RedditSnippet(
                id=f"public_post_{post_data.get('id', len(snippets))}",
                kind="post",
                subreddit=subreddit,
                title=title,
                text=post_text[:2500],
                score=int(post_data.get("score", 0) or 0),
                permalink=post_permalink,
                created_utc=float(post_data.get("created_utc", 0) or 0),
                query="public_thread_url",
            ),
            max_snippets,
        ):
            break

        comments = payload[1].get("data", {}).get("children", [])
        for index, comment_data in enumerate(_flatten_reddit_comments(comments)):
            if index >= comments_per_thread or len(snippets) >= max_snippets:
                break
            body = comment_data.get("body", "")
            comment_permalink = comment_data.get("permalink", "")
            _append_unique_snippet(
                snippets,
                seen,
                RedditSnippet(
                    id=f"public_comment_{comment_data.get('id', len(snippets))}",
                    kind="comment",
                    subreddit=subreddit,
                    title=title,
                    text=body[:2500],
                    score=int(comment_data.get("score", 0) or 0),
                    permalink=(
                        f"https://www.reddit.com{comment_permalink}"
                        if comment_permalink
                        else post_permalink
                    ),
                    parent_permalink=post_permalink,
                    created_utc=float(comment_data.get("created_utc", 0) or 0),
                    query="public_thread_url",
                ),
                max_snippets,
            )
        time.sleep(request_delay_seconds)

    return snippets


def discover_public_reddit_thread_urls(
    subreddits: list[str],
    queries: list[str],
    posts_per_query: int = 8,
    time_filter: str = "all",
    request_delay_seconds: float = 1.0,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    user_agent = os.getenv(
        "REDDIT_USER_AGENT",
        "travelbuddy-france-local-recs/0.1 by local-dev",
    )

    for subreddit in subreddits:
        for query in queries:
            search_url = (
                f"https://www.reddit.com/r/{subreddit}/search.json?"
                + urllib.parse.urlencode(
                    {
                        "q": query,
                        "restrict_sr": "1",
                        "sort": "relevance",
                        "t": time_filter,
                        "limit": posts_per_query,
                    }
                )
            )
            request = urllib.request.Request(
                search_url,
                headers={"User-Agent": user_agent},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, json.JSONDecodeError):
                continue

            for child in payload.get("data", {}).get("children", []):
                permalink = child.get("data", {}).get("permalink", "")
                if not permalink:
                    continue
                url = f"https://www.reddit.com{permalink}"
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
            time.sleep(request_delay_seconds)

    return urls


def _extract_places_batch(client: LuxiaClient, snippets: list[RedditSnippet]) -> list[Place]:
    system_prompt = (
        "Extract France place recommendations from Reddit snippets. "
        "Only include named places that appear to be genuine recommendations from users. "
        "Include restaurants, cafes, markets, neighborhoods, museums, parks, viewpoints, "
        "bookstores, shopping streets, boutiques, department stores, pharmacies, food gift "
        "shops, vintage/thrift/flea markets, souvenir shops, malls, and local activity spots. "
        "Avoid vague recommendations, private addresses, hotels unless clearly recommended as "
        "a public place to visit, and generic city names by themselves. "
        "Use ASCII text. Estimate coordinates only for clearly named places in France. "
        "Set source_type to reddit, source_title to the Reddit post title, and source_url to "
        "the Reddit permalink that supported it. Use tags that preserve user intent such as "
        "shopping, souvenirs, affordable, luxury, vintage, local, cafes, restaurants, museum, "
        "parks, market, nightlife, or family. Return only valid JSON."
    )
    raw_response = client.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "snippets": [snippet.model_dump() for snippet in snippets],
                        "required_schema": RedditExtraction.model_json_schema(),
                        "required_output": "Return unique Place objects only.",
                    }
                ),
            },
        ],
        temperature=0.0,
        max_tokens=2200,
    )

    payload = extract_json_object(raw_response)
    for place in payload.get("places", []):
        duration = int(place.get("estimated_duration_minutes") or 60)
        place["estimated_duration_minutes"] = max(15, min(duration, 360))
        confidence = float(place.get("confidence") or 0.8)
        place["confidence"] = max(0, min(confidence, 1))
        city = str(place.get("city") or "Paris").lower()
        fallback_latitude, fallback_longitude = CITY_CENTER_COORDS.get(
            city, CITY_CENTER_COORDS["paris"]
        )
        place["latitude"] = place.get("latitude") or fallback_latitude
        place["longitude"] = place.get("longitude") or fallback_longitude
        for field in PLACE_STRING_FIELDS:
            if place.get(field) is None:
                place[field] = ""
        if not isinstance(place.get("tags"), list):
            place["tags"] = []
        if not isinstance(place.get("opening_hours"), list):
            place["opening_hours"] = []

    return RedditExtraction.model_validate(payload).places


def extract_places_with_luxia(snippets: list[RedditSnippet]) -> list[Place]:
    if not snippets:
        return []

    client = LuxiaClient()
    if not client.is_configured:
        raise RuntimeError("LUXIA_API_KEY is required to extract Reddit places.")

    deduped: dict[str, Place] = {}
    batch_size = int(os.getenv("REDDIT_EXTRACT_BATCH_SIZE", "35"))
    for start in range(0, len(snippets), batch_size):
        batch = snippets[start : start + batch_size]
        for place in _extract_places_batch(client, batch):
            key = f"{place.name.lower()}::{place.city.lower()}"
            place.source_type = "reddit"
            if not place.source_title:
                place.source_title = "Reddit recommendation thread"
            place.tags = list(dict.fromkeys([*place.tags, place.city.lower(), "reddit"]))
            if not place.google_maps_url:
                place.google_maps_url = (
                    "https://www.google.com/maps/search/?api=1"
                    f"&query={place.latitude},{place.longitude}"
                )
            deduped[key] = place

    return list(deduped.values())


def _load_existing_reddit_places() -> list[Place]:
    if not DATA_PATH.exists():
        return []
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    raw_places = payload.get("places", []) if isinstance(payload, dict) else []
    return [Place.model_validate(place) for place in raw_places]


def save_reddit_places(
    places: list[Place],
    snippets: list[RedditSnippet],
    merge_existing: bool = True,
) -> Path:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not places and DATA_PATH.exists():
        raise RuntimeError(
            "No Reddit places were extracted; keeping existing reddit_places.json."
        )
    existing_places = _load_existing_reddit_places() if merge_existing else []
    deduped: dict[str, Place] = {}
    for place in [*existing_places, *places]:
        key = f"{place.name.strip().lower()}::{place.city.strip().lower()}"
        deduped[key] = place
    merged_places = list(deduped.values())
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Incremental Reddit extraction from API/public Reddit JSON",
        "snippet_count": len(snippets),
        "previous_place_count": len(existing_places),
        "new_extracted_place_count": len(places),
        "place_count": len(merged_places),
        "places": [place.model_dump() for place in merged_places],
    }
    DATA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return DATA_PATH


def save_raw_snippets(snippets: list[RedditSnippet]) -> Path:
    RAW_SNIPPETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not snippets and RAW_SNIPPETS_PATH.exists():
        raise RuntimeError(
            "No Reddit snippets were collected; keeping existing reddit_raw_snippets.json."
        )
    existing_snippets: list[RedditSnippet] = []
    if RAW_SNIPPETS_PATH.exists():
        existing_payload = json.loads(RAW_SNIPPETS_PATH.read_text(encoding="utf-8"))
        existing_items = (
            existing_payload.get("snippets", [])
            if isinstance(existing_payload, dict)
            else []
        )
        existing_snippets = [
            RedditSnippet.model_validate(item)
            for item in existing_items
            if isinstance(item, dict)
        ]
    deduped: dict[str, RedditSnippet] = {}
    for snippet in [*existing_snippets, *snippets]:
        deduped[snippet.id] = snippet
    merged_snippets = list(deduped.values())
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Incremental Reddit snippets from API/public Reddit JSON/PullPush",
        "snippet_count": len(merged_snippets),
        "previous_snippet_count": len(existing_snippets),
        "new_snippet_count": len(snippets),
        "post_count": sum(1 for snippet in merged_snippets if snippet.kind == "post"),
        "comment_count": sum(1 for snippet in merged_snippets if snippet.kind == "comment"),
        "snippets": [snippet.model_dump() for snippet in merged_snippets],
    }
    RAW_SNIPPETS_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return RAW_SNIPPETS_PATH


def load_manual_reddit_snippets(path: Path = MANUAL_SNIPPETS_PATH) -> list[RedditSnippet]:
    if not path.exists():
        raise RuntimeError(f"Manual Reddit snippet file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_items = payload.get("snippets", []) if isinstance(payload, dict) else payload
    snippets: list[RedditSnippet] = []
    for index, item in enumerate(raw_items, start=1):
        text = item.get("text", "")
        if not _valid_text(text):
            continue
        permalink = item.get("permalink", item.get("url", ""))
        snippets.append(
            RedditSnippet(
                id=item.get("id", f"manual_{index}"),
                kind=item.get("kind", "manual"),
                subreddit=item.get("subreddit", "manual"),
                title=item.get("title", "Manual Reddit snippet"),
                text=text[:2500],
                score=int(item.get("score", 0) or 0),
                permalink=permalink,
                parent_permalink=item.get("parent_permalink", ""),
                created_utc=item.get("created_utc"),
                query=item.get("query", "manual"),
            )
        )
    return snippets


def refresh_reddit_places(
    subreddits: list[str] | None = None,
    queries: list[str] | None = None,
    limit_per_query: int = 5,
    comment_limit: int = 8,
) -> dict:
    snippets = collect_reddit_snippets(
        subreddits=subreddits or DEFAULT_SUBREDDITS,
        queries=queries or DEFAULT_QUERIES,
        limit_per_query=limit_per_query,
        comment_limit=comment_limit,
    )
    places = extract_places_with_luxia(snippets)
    output_path = save_reddit_places(places, snippets)
    return {
        "snippet_count": len(snippets),
        "place_count": len(places),
        "output_path": str(output_path),
    }


def refresh_reddit_dataset(
    subreddits: list[str] | None = None,
    queries: list[str] | None = None,
    max_snippets: int = 500,
    posts_per_query: int = 25,
    comments_per_post: int = 15,
    time_filter: str = "all",
) -> dict:
    snippets = collect_reddit_raw_snippets(
        subreddits=subreddits or DEFAULT_SUBREDDITS,
        queries=queries or DEFAULT_QUERIES,
        max_snippets=max_snippets,
        posts_per_query=posts_per_query,
        comments_per_post=comments_per_post,
        time_filter=time_filter,
    )
    raw_output_path = save_raw_snippets(snippets)
    places = extract_places_with_luxia(snippets)
    places_output_path = save_reddit_places(places, snippets)
    return {
        "snippet_count": len(snippets),
        "post_count": sum(1 for snippet in snippets if snippet.kind == "post"),
        "comment_count": sum(1 for snippet in snippets if snippet.kind == "comment"),
        "place_count": len(places),
        "raw_output_path": str(raw_output_path),
        "places_output_path": str(places_output_path),
    }


def refresh_manual_reddit_places(path: Path = MANUAL_SNIPPETS_PATH) -> dict:
    snippets = load_manual_reddit_snippets(path)
    raw_output_path = save_raw_snippets(snippets)
    places = extract_places_with_luxia(snippets)
    places_output_path = save_reddit_places(places, snippets)
    return {
        "snippet_count": len(snippets),
        "place_count": len(places),
        "raw_output_path": str(raw_output_path),
        "places_output_path": str(places_output_path),
        "manual_input_path": str(path),
    }


def refresh_public_thread_reddit_places(
    urls: list[str] | None = None,
    max_snippets: int = 500,
    comments_per_thread: int = 80,
    request_delay_seconds: float = 1.5,
) -> dict:
    snippets = collect_public_thread_snippets(
        urls=urls or DEFAULT_REDDIT_THREAD_URLS,
        max_snippets=max_snippets,
        comments_per_thread=comments_per_thread,
        request_delay_seconds=request_delay_seconds,
    )
    raw_output_path = save_raw_snippets(snippets)
    places = extract_places_with_luxia(snippets)
    places_output_path = save_reddit_places(places, snippets)
    return {
        "snippet_count": len(snippets),
        "post_count": sum(1 for snippet in snippets if snippet.kind == "post"),
        "comment_count": sum(1 for snippet in snippets if snippet.kind == "comment"),
        "place_count": len(places),
        "raw_output_path": str(raw_output_path),
        "places_output_path": str(places_output_path),
        "url_count": len(urls or DEFAULT_REDDIT_THREAD_URLS),
    }


def refresh_public_search_reddit_places(
    subreddits: list[str] | None = None,
    queries: list[str] | None = None,
    max_threads: int = 40,
    max_snippets: int = 500,
    posts_per_query: int = 8,
    comments_per_thread: int = 40,
    time_filter: str = "all",
    request_delay_seconds: float = 1.5,
) -> dict:
    urls = discover_public_reddit_thread_urls(
        subreddits=subreddits or DEFAULT_PUBLIC_SEARCH_SUBREDDITS,
        queries=queries or DEFAULT_PUBLIC_SEARCH_QUERIES,
        posts_per_query=posts_per_query,
        time_filter=time_filter,
        request_delay_seconds=request_delay_seconds,
    )[:max_threads]
    result = refresh_public_thread_reddit_places(
        urls=urls,
        max_snippets=max_snippets,
        comments_per_thread=comments_per_thread,
        request_delay_seconds=request_delay_seconds,
    )
    return {**result, "discovered_thread_count": len(urls)}


def _pullpush_request(endpoint: str, params: dict) -> list[dict]:
    url = (
        f"https://api.pullpush.io/reddit/search/{endpoint}/?"
        + urllib.parse.urlencode(params)
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "travelbuddy-france-local-recs/0.1"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("data", []) if isinstance(payload, dict) else []


def collect_pullpush_snippets(
    subreddits: list[str],
    queries: list[str],
    max_posts: int = 100,
    max_comments: int = 100,
    posts_per_query: int = 5,
    comments_per_query: int = 5,
    request_delay_seconds: float = 2.0,
) -> list[RedditSnippet]:
    snippets: list[RedditSnippet] = []
    seen: set[str] = set()
    post_count = 0
    comment_count = 0

    def add(snippet: RedditSnippet) -> None:
        if snippet.id in seen or not _valid_text(snippet.text):
            return
        seen.add(snippet.id)
        snippets.append(snippet)

    for subreddit in subreddits:
        for query in queries:
            if post_count < max_posts:
                try:
                    submissions = _pullpush_request(
                        "submission",
                        {
                            "subreddit": subreddit,
                            "q": query,
                            "size": min(posts_per_query, max_posts - post_count),
                            "sort": "desc",
                            "sort_type": "score",
                        },
                    )
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    submissions = []
                for submission in submissions:
                    permalink = submission.get("permalink", "")
                    title = submission.get("title", "Reddit recommendation post")
                    text = "\n\n".join(
                        part
                        for part in [title, submission.get("selftext", "")]
                        if part and part not in {"[deleted]", "[removed]"}
                    )
                    add(
                        RedditSnippet(
                            id=f"pullpush_post_{submission.get('id', len(snippets))}",
                            kind="post",
                            subreddit=subreddit,
                            title=title,
                            text=text[:2500],
                            score=int(submission.get("score", 0) or 0),
                            permalink=(
                                f"https://www.reddit.com{permalink}"
                                if permalink.startswith("/")
                                else permalink
                            ),
                            created_utc=float(submission.get("created_utc", 0) or 0),
                            query=query,
                        )
                    )
                    post_count += 1
                    if post_count >= max_posts:
                        break
                time.sleep(request_delay_seconds)

            if comment_count < max_comments:
                try:
                    comments = _pullpush_request(
                        "comment",
                        {
                            "subreddit": subreddit,
                            "q": query,
                            "size": min(comments_per_query, max_comments - comment_count),
                            "sort": "desc",
                            "sort_type": "score",
                        },
                    )
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    comments = []
                for comment in comments:
                    body = comment.get("body", "")
                    permalink = comment.get("permalink", "")
                    add(
                        RedditSnippet(
                            id=f"pullpush_comment_{comment.get('id', len(snippets))}",
                            kind="comment",
                            subreddit=subreddit,
                            title=comment.get("link_title", "Reddit recommendation comment"),
                            text=body[:2500],
                            score=int(comment.get("score", 0) or 0),
                            permalink=(
                                f"https://www.reddit.com{permalink}"
                                if permalink.startswith("/")
                                else permalink
                            ),
                            created_utc=float(comment.get("created_utc", 0) or 0),
                            query=query,
                        )
                    )
                    comment_count += 1
                    if comment_count >= max_comments:
                        break
                time.sleep(request_delay_seconds)

            if post_count >= max_posts and comment_count >= max_comments:
                return snippets

    return snippets


def refresh_pullpush_reddit_places(
    subreddits: list[str] | None = None,
    queries: list[str] | None = None,
    max_posts: int = 100,
    max_comments: int = 100,
    posts_per_query: int = 5,
    comments_per_query: int = 5,
    request_delay_seconds: float = 2.0,
    raw_only: bool = False,
) -> dict:
    snippets = collect_pullpush_snippets(
        subreddits=subreddits or DEFAULT_PUBLIC_SEARCH_SUBREDDITS,
        queries=queries or DEFAULT_PUBLIC_SEARCH_QUERIES,
        max_posts=max_posts,
        max_comments=max_comments,
        posts_per_query=posts_per_query,
        comments_per_query=comments_per_query,
        request_delay_seconds=request_delay_seconds,
    )
    raw_output_path = save_raw_snippets(snippets)
    if raw_only:
        return {
            "snippet_count": len(snippets),
            "post_count": sum(1 for snippet in snippets if snippet.kind == "post"),
            "comment_count": sum(1 for snippet in snippets if snippet.kind == "comment"),
            "raw_output_path": str(raw_output_path),
            "places_output_path": "",
            "place_count": 0,
            "raw_only": True,
        }
    places = extract_places_with_luxia(snippets)
    places_output_path = save_reddit_places(places, snippets)
    return {
        "snippet_count": len(snippets),
        "post_count": sum(1 for snippet in snippets if snippet.kind == "post"),
        "comment_count": sum(1 for snippet in snippets if snippet.kind == "comment"),
        "place_count": len(places),
        "raw_output_path": str(raw_output_path),
        "places_output_path": str(places_output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Reddit-derived France places.")
    parser.add_argument("--subreddits", default=",".join(DEFAULT_SUBREDDITS))
    parser.add_argument(
        "--queries",
        default="",
        help="Optional comma-separated search queries. Defaults to the built-in France travel queries.",
    )
    parser.add_argument(
        "--mode",
        choices=["legacy", "dataset", "manual", "urls", "public-search", "pullpush"],
        default="dataset",
        help="dataset stores individual posts/comments; legacy stores bundled post snippets.",
    )
    parser.add_argument(
        "--manual-file",
        default=str(MANUAL_SNIPPETS_PATH),
        help="Path to manual Reddit snippets JSON when --mode manual is used.",
    )
    parser.add_argument("--max-snippets", type=int, default=500)
    parser.add_argument("--posts-per-query", type=int, default=25)
    parser.add_argument("--limit-per-query", type=int, default=5)
    parser.add_argument("--comment-limit", type=int, default=8)
    parser.add_argument("--comments-per-post", type=int, default=15)
    parser.add_argument("--comments-per-thread", type=int, default=80)
    parser.add_argument("--time-filter", default="all")
    parser.add_argument("--max-threads", type=int, default=40)
    parser.add_argument("--max-posts", type=int, default=100)
    parser.add_argument("--max-comments", type=int, default=100)
    parser.add_argument("--request-delay-seconds", type=float, default=1.5)
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument(
        "--urls",
        default="",
        help="Comma-separated Reddit thread URLs when --mode urls is used.",
    )
    args = parser.parse_args()

    subreddits = [item.strip() for item in args.subreddits.split(",") if item.strip()]
    queries = [item.strip() for item in args.queries.split(",") if item.strip()]
    if args.mode == "manual":
        result = refresh_manual_reddit_places(Path(args.manual_file))
    elif args.mode == "pullpush":
        result = refresh_pullpush_reddit_places(
            subreddits=subreddits or None,
            queries=queries or None,
            max_posts=args.max_posts,
            max_comments=args.max_comments,
            posts_per_query=args.posts_per_query,
            comments_per_query=args.comments_per_post,
            request_delay_seconds=args.request_delay_seconds,
            raw_only=args.raw_only,
        )
    elif args.mode == "public-search":
        result = refresh_public_search_reddit_places(
            subreddits=subreddits or None,
            queries=queries or None,
            max_threads=args.max_threads,
            max_snippets=args.max_snippets,
            posts_per_query=args.posts_per_query,
            comments_per_thread=args.comments_per_thread,
            time_filter=args.time_filter,
            request_delay_seconds=args.request_delay_seconds,
        )
    elif args.mode == "urls":
        urls = [item.strip() for item in args.urls.split(",") if item.strip()]
        result = refresh_public_thread_reddit_places(
            urls=urls or None,
            max_snippets=args.max_snippets,
            comments_per_thread=args.comments_per_thread,
            request_delay_seconds=args.request_delay_seconds,
        )
    elif args.mode == "legacy":
        result = refresh_reddit_places(
            subreddits=subreddits,
            limit_per_query=args.limit_per_query,
            comment_limit=args.comment_limit,
        )
    else:
        result = refresh_reddit_dataset(
            subreddits=subreddits,
            max_snippets=args.max_snippets,
            posts_per_query=args.posts_per_query,
            comments_per_post=args.comments_per_post,
            time_filter=args.time_filter,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
