import unittest

import numpy as np

from app.schemas.travel import TravelIntent
from app.services import embedding_store


class _FakeModel:
    def encode(self, text: str, normalize_embeddings: bool = False):
        return np.asarray([1.0, 0.0], dtype="float32")


class EmbeddingStoreTests(unittest.TestCase):
    def test_search_semantic_candidates_orders_by_vector_similarity(self) -> None:
        old_cache = embedding_store._cache
        old_model = embedding_store._model
        try:
            candidates = [
                {"name": "Exact Match", "city": "Paris", "category": "museum"},
                {"name": "Weak Match", "city": "Paris", "category": "park"},
                {"name": "Middle Match", "city": "Paris", "category": "cafe"},
            ]
            embedding_store._cache = {
                "places": candidates,
                "embeddings": np.asarray(
                    [
                        [1.0, 0.0],
                        [0.0, 1.0],
                        [0.6, 0.8],
                    ],
                    dtype="float32",
                ),
            }
            embedding_store._model = _FakeModel()

            intent = TravelIntent(destination="Paris", interests=["museum"])
            result = embedding_store.search_semantic_candidates(candidates, intent, top_k=2)

            self.assertEqual([place["name"] for place in result], ["Exact Match", "Middle Match"])
        finally:
            embedding_store._cache = old_cache
            embedding_store._model = old_model


if __name__ == "__main__":
    unittest.main()
