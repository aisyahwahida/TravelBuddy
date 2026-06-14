# TravelBuddy Hybrid RAG + Vector Search Pipeline

TravelBuddy uses a hybrid RAG pipeline for itinerary generation. The LLM is used to understand the user request, while the final itinerary is grounded in retrieved places from the project datasets.

## Runtime Flow

1. User prompt
2. Luxia / rule extractor converts the prompt into `TravelIntent`
3. Metadata filters narrow candidates by city, requested place type, budget, group type, closure status, and trip duration
4. Vector retrieval searches semantically relevant places from the filtered candidate pool
5. Travel reranker combines vector similarity with source quality, category match, ratings, duplicate control, and diversity
6. Planner builds day-by-day itinerary and route structure
7. Frontend renders cards, map route, sources, and PDF export

## Retrieval Design

The place dataset is treated as the RAG document collection. Each place is converted into searchable text using fields such as name, city, neighborhood, category, tags, reason, local tip, source type, and opening hours.

When embeddings are available, TravelBuddy embeds the user query and compares it with place embeddings using normalized inner product, which is equivalent to cosine similarity. If FAISS is installed during index building, the backend also writes a flat `IndexFlatIP` index. If FAISS or the embedding cache is unavailable, the system safely falls back to the existing TF-IDF-style cosine scoring.

## Why Flat FAISS First

The current dataset is small enough that exact flat vector search is practical and reliable. HNSW or other approximate nearest-neighbor methods are useful later if the dataset grows large enough that exact search becomes slow.

## Presentation Summary

TravelBuddy uses Luxia for intent extraction, RAG retrieval to ground recommendations in real travel datasets, vector search for semantic matching, and a custom travel reranker to enforce itinerary quality.
