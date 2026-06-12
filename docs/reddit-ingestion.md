# Reddit Ingestion

TravelBuddy can ingest local recommendations from Reddit communities through the Reddit Data API using PRAW. This is intentionally an API-based workflow instead of browser HTML scraping.

## Why API-Based

- Reddit requires API access to follow its developer and data API terms.
- PRAW handles OAuth, subreddit search, submissions, comments, and rate behavior more reliably than page scraping.
- The app caches extracted places locally so normal chat requests stay fast.

## Required Environment Variables

```powershell
$env:LUXIA_API_KEY="your_luxia_api_key"
$env:REDDIT_CLIENT_ID="your_reddit_app_client_id"
$env:REDDIT_CLIENT_SECRET="your_reddit_app_client_secret"
$env:REDDIT_USER_AGENT="travelbuddy-france-local-recs/0.1 by your_reddit_username"
```

Create a Reddit app at:

```text
https://www.reddit.com/prefs/apps
```

For local development, a script app is the simplest option.

## No Reddit API Option: Manual Snippets

If you do not have Reddit API credentials, do not scrape the subreddit page automatically. Instead, manually copy useful post/comment text into:

```text
backend/app/data/manual_reddit_snippets.json
```

Example:

```json
{
  "snippets": [
    {
      "id": "expats_1",
      "kind": "manual",
      "subreddit": "Expats_In_France",
      "title": "Best small cities to live in France?",
      "text": "Paste the Reddit post or comment text here...",
      "permalink": "https://www.reddit.com/r/Expats_In_France/comments/...",
      "score": 0,
      "query": "manual recommendations"
    }
  ]
}
```

Then run:

```powershell
python -m app.services.reddit_ingestion --mode manual
```

This uses Luxia to extract named France places from your manually supplied Reddit content and saves them into `reddit_places.json`.

## No Reddit API Option: Public Thread URLs

You can also ingest public Reddit thread URLs through Reddit's JSON endpoint:

```powershell
python -m app.services.reddit_ingestion --mode urls --max-snippets 180 --comments-per-thread 45
```

Or pass your own comma-separated thread URLs:

```powershell
python -m app.services.reddit_ingestion --mode urls --urls "https://www.reddit.com/r/ParisTravelGuide/comments/..."
```

The importer now refuses to overwrite an existing dataset when Reddit returns zero snippets or zero places, which protects `reddit_places.json` from temporary Reddit rate limits.

## No Reddit API Option: Public Search

The public-search mode discovers matching Reddit threads first, then ingests the thread URLs:

```powershell
python -m app.services.reddit_ingestion --mode public-search --subreddits ParisTravelGuide,paris,Lyon,nicefrance,Expats_In_France --max-threads 45 --max-snippets 350 --posts-per-query 5 --comments-per-thread 35
```

If Reddit returns HTTP `429 Too Many Requests`, wait before retrying or use a smaller run. The script will keep the existing JSON instead of replacing it with an empty dataset.

For the subreddit you sent:

```text
https://www.reddit.com/r/Expats_In_France/
```

Open it in your browser, search within the subreddit for terms like `restaurant`, `market`, `where to live`, `neighborhood`, `cafe`, `hidden gem`, `Lyon`, `Paris`, `Marseille`, then copy specific useful post/comment text into the JSON file.

## Refresh 500 Raw Reddit Snippets From The CLI

Run from `backend/`:

```powershell
python -m app.services.reddit_ingestion --mode dataset --max-snippets 500 --posts-per-query 25 --comments-per-post 15 --time-filter all
```

This writes individual Reddit posts/comments to:

```text
backend/app/data/reddit_raw_snippets.json
```

Then it extracts candidate France places into:

```text
backend/app/data/reddit_places.json
```

The raw JSON includes `kind`, `subreddit`, `title`, `text`, `score`, `permalink`, `parent_permalink`, `created_utc`, and the query that found the snippet.

## Smaller Legacy Refresh From The CLI

Run from `backend/`:

```powershell
python -m app.services.reddit_ingestion --subreddits france,paris,AskFrance --limit-per-query 5 --comment-limit 8
```

This writes:

```text
backend/app/data/reddit_places.json
```

## Reddit Recommendations Verified With Google Maps

If you want Reddit only for discovering recommended place names, then Google Maps for the practical details, run:

```powershell
python -m app.services.reddit_google_pipeline --subreddits france,paris,AskFrance --limit-per-query 5 --comment-limit 8 --google-limit 20
```

This refreshes:

- `backend/app/data/reddit_places.json` for Reddit-discovered recommendations.
- `backend/app/data/google_places.json` for Google Maps rating, opening hours, map link, and price level.

## Refresh Through The API

With FastAPI running:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/reddit/refresh
```

For the 500-snippet dataset mode:

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/reddit/refresh-dataset?max_snippets=500&posts_per_query=25&comments_per_post=15&time_filter=all"
```

Check cache status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/reddit/status
```

## How It Works

1. Search selected subreddits for restaurant and local-place queries.
2. Pull each matching submission and a bounded number of top comments.
3. Ask Luxia to extract named France places only.
4. Save deduplicated `Place` objects into the local cache.
5. Merge cached Reddit places into the normal retrieval pipeline.

## Practical Notes

- Keep limits small during development to avoid unnecessary API usage.
- Do not store private user data.
- Treat Reddit-derived places as suggestions, not verified venue records.
- Coordinates are estimated for map display and should be verified before production use.
