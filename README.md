# TravelBuddy France

TravelBuddy France is a starter monorepo for an AI travel assistant focused on France. It combines a FastAPI backend with a React + Vite frontend so travelers can chat, see recommended places on a map, and export itineraries as PDF.

## Project Structure

```text
backend/   FastAPI API, orchestration, retrieval, PDF export
frontend/  React chat UI, map panel, itinerary rendering
docs/      Product and architecture notes
```

## Why This Structure

The current design follows the flowchart:

1. User sends a travel request.
2. Frontend calls the backend API.
3. Backend extracts travel intent and constraints.
4. Retrieval finds local-style recommendations and candidate places.
5. Planning assembles an explainable itinerary.
6. Frontend displays the chat plus map markers.
7. User can export the itinerary as PDF.

The implementation also reflects the project proposal by extracting budget,
mood, pace, and travel style; attaching Reddit or Google Maps evidence to
recommendations; and saving local development chat sessions for later review.

## Backend

The backend uses Luxia for AI planning. Set `LUXIA_API_KEY` in your environment
or local `.env` file. You can optionally set `LUXIA_BASE_URL`, `LUXIA_MODEL`,
and `LUXIA_TIMEOUT_SECONDS`; defaults are shown in `.env.example`.

```powershell
$env:LUXIA_API_KEY="your_luxia_api_key"
$env:LUXIA_MODEL="luxia3-llm-8b-0731"
```

For Reddit recommendation ingestion, also set:

```powershell
$env:REDDIT_CLIENT_ID="your_reddit_app_client_id"
$env:REDDIT_CLIENT_SECRET="your_reddit_app_client_secret"
$env:REDDIT_USER_AGENT="travelbuddy-france-local-recs/0.1 by your_reddit_username"
```

For Google Maps review references, set:

```powershell
$env:GOOGLE_MAPS_API_KEY="your_google_maps_platform_key"
```

If you cannot get a Google Maps API key, use OpenStreetMap instead:

```powershell
$env:OSM_USER_AGENT="travelbuddy-france-local-recs/0.1 by your_name"
```

Run from `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API docs:

- `http://127.0.0.1:8000/docs`

Session endpoints:

- `GET /api/sessions` lists saved local chat sessions.
- `GET /api/sessions/{session_id}` returns a saved session with chat turns and the latest itinerary.

Refresh Reddit-derived recommendations. This also uses Luxia to extract named
France places from Reddit text:

```powershell
python -m app.services.reddit_ingestion --mode dataset --max-snippets 500 --posts-per-query 25 --comments-per-post 15 --time-filter all
```

More details are in `docs/reddit-ingestion.md`.

Refresh Google Maps review references:

```powershell
python -m app.services.google_places --limit 3
```

More details are in `docs/google-places-sources.md`.

To use Reddit only for discovering recommended places, then Google Maps for
rating, opening hours, price level, and map links:

```powershell
python -m app.services.reddit_google_pipeline --subreddits france,paris,AskFrance --limit-per-query 5 --comment-limit 8 --google-limit 20
```

No-Google alternative: use Reddit for recommendations, then OpenStreetMap for
coordinates, map links, opening-hours tags, and price/fee tags when available:

```powershell
python -m app.services.reddit_osm_pipeline --subreddits france,paris,AskFrance --limit-per-query 5 --comment-limit 8 --osm-limit 20
```

More details are in `docs/openstreetmap-sources.md`.

Refresh official Paris Open Data events and activities:

```powershell
python -m app.services.open_data_sources --limit 50
```

For a focused activity/event dataset refresh:

```powershell
python -m app.services.open_data_sources --limit 50 --search "balade"
```

More details are in `docs/open-data-sources.md`.

Broaden the place dataset with OpenStreetMap POIs across major France cities:

```powershell
python -m app.services.osm_poi_ingestion --cities Paris,Lyon,Marseille,Nice,Bordeaux,Strasbourg,Lille --city-limit 120 --delay-seconds 2
```

More details are in `docs/osm-poi-ingestion.md`.

## Frontend

Run from `frontend/`:

```bash
npm install
npm run dev
```

App URL:

- `http://127.0.0.1:5173`

## Next Integrations

- Add embeddings + vector search for a larger recommendation base
- Add a Google Maps JavaScript API key if you want multi-marker native Google Maps instead of embed-based maps
- Move local JSON sessions to DynamoDB if deploying the proposal's AWS architecture
- Use the scoring rubric in `docs/evaluation-plan.md` to compare LLM-only, basic RAG, and personalized RAG results
