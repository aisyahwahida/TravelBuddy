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

## AWS Deployment (Academy Learner Lab)

The production deployment runs on:

| Component | Service | Address |
|-----------|---------|---------|
| Frontend  | S3 static website | `http://travelbuddy-frontend-705715.s3-website-us-east-1.amazonaws.com` |
| Backend   | EC2 t3.small (Amazon Linux 2023) | `http://44.206.85.114:8000` |
| Sessions  | DynamoDB table `travelbuddy-sessions` | us-east-1 |

### Starting a new lab session

Each time you start the AWS Academy Learner Lab the credentials rotate. You need to push the new credentials to EC2 so DynamoDB keeps working.

**Step 1 — get credentials from the Academy lab page** (AccessKey + SecretKey shown when the lab is running).

**Step 2 — open your Mac terminal** and run:

```bash
ssh -i /tmp/travelbuddy-key.pem ec2-user@44.206.85.114
bash ~/refresh_creds.sh <NewAccessKey> <NewSecretKey>
```

That updates `/home/ec2-user/backend/.aws_env` and restarts the backend service automatically.

> **If `/tmp/travelbuddy-key.pem` is missing** (Mac rebooted), re-download the key from the Academy lab page and save it to `/tmp/travelbuddy-key.pem`, then run `chmod 400 /tmp/travelbuddy-key.pem`.

If you skip the credential refresh the backend still works — it falls back to local JSON file sessions on EC2. DynamoDB just won't receive new session data until credentials are refreshed.

### Deploying backend changes

```bash
# From the repo root on your Mac:
cd backend
zip -r /tmp/backend_v2.zip app requirements.txt -x "app/__pycache__/*" "app/**/__pycache__/*" "app/data/embedding_cache.pkl"

AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> AWS_DEFAULT_REGION=us-east-1 \
  aws s3 cp /tmp/backend_v2.zip s3://travelbuddy-frontend-705715/deploys/backend_v2.zip

# Then on EC2:
ssh -i /tmp/travelbuddy-key.pem ec2-user@44.206.85.114
aws s3 cp s3://travelbuddy-frontend-705715/deploys/backend_v2.zip ~/backend_v2.zip
sudo systemctl stop travelbuddy
cd ~ && rm -rf backend_new && mkdir backend_new && unzip -q backend_v2.zip -d backend_new
rm -rf backend_old && mv backend backend_old && mv backend_new backend
sudo chown -R ec2-user:ec2-user ~/backend
# Recreate the credentials file (it lives inside the backend folder)
bash ~/refresh_creds.sh <AccessKey> <SecretKey>
```

### Deploying frontend changes

```bash
# From frontend/:
npm run build

AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> AWS_DEFAULT_REGION=us-east-1 \
  aws s3 sync dist/ s3://travelbuddy-frontend-705715/ --delete \
  --cache-control "public, max-age=31536000, immutable" --exclude "*.html"

AWS_ACCESS_KEY_ID=<key> AWS_SECRET_ACCESS_KEY=<secret> AWS_DEFAULT_REGION=us-east-1 \
  aws s3 cp dist/index.html s3://travelbuddy-frontend-705715/index.html \
  --cache-control "no-cache, no-store, must-revalidate"
```

## Next Integrations

- Add embeddings + vector search for a larger recommendation base
- Add a Google Maps JavaScript API key if you want multi-marker native Google Maps instead of embed-based maps
- Use the scoring rubric in `docs/evaluation-plan.md` to compare LLM-only, basic RAG, and personalized RAG results
