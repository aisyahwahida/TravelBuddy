# TravelBuddy — TODO

## AWS Deployment

- [ ] **S3 — Frontend hosting**
  - Build React/Vite app (`npm run build`)
  - Create S3 bucket with static website hosting enabled
  - Upload `dist/` output to bucket
  - Set bucket policy for public read

- [ ] **S3 — Data file storage**
  - Upload `google_places.json` to S3
  - Upload `embedding_cache.pkl` to S3
  - Update backend to read these files from S3 instead of local disk

- [ ] **Elastic Beanstalk — Backend hosting**
  - Dockerize the FastAPI backend (`Dockerfile`)
  - Create Elastic Beanstalk application and environment (Docker platform)
  - Set environment variables (API keys, S3 bucket name)
  - Deploy and verify `/api/chat/stream` endpoint is reachable

- [ ] **DynamoDB — Session persistence**
  - Create `travelbuddy-sessions` table (PK: `session_id`)
  - Replace in-memory session dict in backend with DynamoDB read/write
  - Test that chat history survives page refresh and EB restarts

- [ ] **Wire frontend to deployed backend**
  - Update `VITE_API_BASE_URL` in frontend `.env` to point to EB URL
  - Rebuild and re-upload frontend to S3
  - Confirm end-to-end flow works on the deployed stack

---

## Features

- [x] Google Maps integration (map, markers, polyline)
- [x] Google Places photos in stop cards and detail panel
- [x] Map / Route / Transit tabs
- [x] SSE streaming responses
- [ ] (Optional) CloudFront CDN in front of S3 for faster frontend delivery
