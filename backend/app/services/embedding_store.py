"""
Pre-compute and cache sentence embeddings for all places.

Build the cache (run once after changing place data):
    python -m app.services.embedding_store
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from app.schemas.travel import TravelIntent
from app.services.semantic_retrieval import place_text, query_text

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "embedding_cache.pkl"
_MODEL_NAME = "all-MiniLM-L6-v2"

_model: "SentenceTransformer | None" = None
_cache: dict | None = None


def _get_model() -> "SentenceTransformer":
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _get_cache() -> dict | None:
    global _cache
    if _cache is None and CACHE_PATH.exists():
        with open(CACHE_PATH, "rb") as fh:
            _cache = pickle.load(fh)
    return _cache


def _load_all_place_dicts() -> list[dict]:
    from app.data.france_places import FRANCE_PLACES

    data_dir = Path(__file__).resolve().parents[1] / "data"
    all_places: list[dict] = list(FRANCE_PLACES)

    for fname in (
        "reddit_places.json",
        "open_data_places.json",
        "osm_poi_places.json",
        "france_must_go_places.json",
    ):
        path = data_dir / fname
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = payload.get("places", []) if isinstance(payload, dict) else payload
        if isinstance(items, list):
            all_places.extend(items)

    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for place in all_places:
        key = (place.get("name", "").lower(), place.get("city", "").lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(place)
    return unique


def build() -> None:
    """Pre-compute embeddings for all places and write disk cache."""
    model = _get_model()
    places = _load_all_place_dicts()
    print(f"Building embeddings for {len(places)} places with {_MODEL_NAME}...")
    texts = [place_text(p) for p in places]
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=32,
    )
    with open(CACHE_PATH, "wb") as fh:
        pickle.dump({"places": places, "embeddings": embeddings}, fh)
    print(f"Cache saved to {CACHE_PATH}")


def get_semantic_scores(
    places: list[dict],
    intent: TravelIntent,
    original_query: str = "",
) -> dict[tuple[str, str], float]:
    """Cosine similarity scores using real embeddings. Returns {} if cache absent."""
    cache = _get_cache()
    if cache is None:
        return {}

    try:
        model = _get_model()
        text = query_text(intent, original_query)
        query_emb = model.encode(text, normalize_embeddings=True)

        cached_places: list[dict] = cache["places"]
        cached_embs: np.ndarray = cache["embeddings"]
        lookup: dict[tuple[str, str], np.ndarray] = {
            (p.get("name", "").lower(), p.get("city", "").lower()): cached_embs[i]
            for i, p in enumerate(cached_places)
        }

        result: dict[tuple[str, str], float] = {}
        for place in places:
            key = (place.get("name", "").lower(), place.get("city", "").lower())
            place_emb = lookup.get(key)
            if place_emb is not None:
                result[key] = float(np.dot(query_emb, place_emb))
        return result
    except Exception:
        return {}


if __name__ == "__main__":
    build()
