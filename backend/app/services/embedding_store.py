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
from app.services.place_identity import dedupe_place_dicts, place_identity_key
from app.services.place_exclusions import is_excluded_place
from app.services.semantic_retrieval import place_text, query_text

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "embedding_cache.pkl"
FAISS_INDEX_PATH = Path(__file__).resolve().parents[1] / "data" / "places_flat.index"
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

    return dedupe_place_dicts(
        [
            place
            for place in all_places
            if not is_excluded_place(
                str(place.get("name", "")),
                str(place.get("city", "")),
            )
        ]
    )


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
    embeddings = np.asarray(embeddings, dtype="float32")
    with open(CACHE_PATH, "wb") as fh:
        pickle.dump({"places": places, "embeddings": embeddings}, fh)
    print(f"Cache saved to {CACHE_PATH}")
    try:
        import faiss

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        faiss.write_index(index, str(FAISS_INDEX_PATH))
        print(f"FAISS flat index saved to {FAISS_INDEX_PATH}")
    except Exception as exc:
        print(f"FAISS index not written ({exc}); NumPy flat search fallback remains available.")


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
            (place_identity_key(p), p.get("city", "").lower()): np.asarray(cached_embs[i])
            for i, p in enumerate(cached_places)
        }

        result: dict[tuple[str, str], float] = {}
        for place in places:
            key = (place_identity_key(place), place.get("city", "").lower())
            place_emb = lookup.get(key)
            if place_emb is not None:
                result[key] = float(np.dot(query_emb, place_emb))
        return result
    except Exception:
        return {}


def search_semantic_candidates(
    candidates: list[dict],
    intent: TravelIntent,
    original_query: str = "",
    top_k: int = 120,
) -> list[dict]:
    """
    Return the most semantically relevant candidates from the embedding cache.

    This is an exact flat vector-search stage over the already metadata-filtered
    candidate set. It mirrors FAISS IndexFlatIP semantics by using normalized
    embeddings and inner product, with a lightweight NumPy fallback so the app
    still works when FAISS is not installed.
    """
    cache = _get_cache()
    if cache is None or not candidates:
        return []

    try:
        model = _get_model()
        query_emb = np.asarray(
            model.encode(query_text(intent, original_query), normalize_embeddings=True),
            dtype="float32",
        )
        cached_places: list[dict] = cache["places"]
        cached_embs = np.asarray(cache["embeddings"], dtype="float32")
        index_lookup: dict[tuple[str, str], int] = {
            (place_identity_key(p), p.get("city", "").lower()): i
            for i, p in enumerate(cached_places)
        }

        searchable: list[tuple[dict, int]] = []
        seen: set[tuple[str, str]] = set()
        for place in candidates:
            key = (place_identity_key(place), place.get("city", "").lower())
            if key in seen:
                continue
            index = index_lookup.get(key)
            if index is None:
                continue
            searchable.append((place, index))
            seen.add(key)

        if not searchable:
            return []

        matrix = np.asarray([cached_embs[index] for _, index in searchable], dtype="float32")
        scores = matrix @ query_emb
        order = np.argsort(scores)[::-1][: max(1, top_k)]
        return [searchable[int(i)][0] for i in order]
    except Exception:
        return []


if __name__ == "__main__":
    build()
