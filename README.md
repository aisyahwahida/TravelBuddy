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
| Frontend  | S3 static website | `http://travelbuddy-frontend-1781322896.s3-website-us-east-1.amazonaws.com` |
| Backend   | EC2 t3.small (Amazon Linux 2023) | `http://34.205.234.211:8000` |
| Sessions  | DynamoDB table `travelbuddy-sessions` | us-east-1 |

> **What gets wiped when the Academy account resets:**
> - EC2 instance and Elastic IP — backend goes offline, new IP needed
> - S3 bucket — frontend URL changes, new bucket needed
> - DynamoDB table — all backend sessions lost
>
> **What survives:**
> - Browser localStorage — the session history panel in the UI still works (saved in the user's browser, not AWS)
>
> If the backend is unreachable or the frontend shows "Load failed", follow the "Rebuilding from scratch" section below.

---

### Every time you start a new lab session

Each time you start the AWS Academy Learner Lab the credentials rotate. The EC2 instance also stops and must be restarted.

**Step 1 — start the lab** in the Academy LMS (Canvas). Wait for the green dot.

**Step 2 — get the new credentials** from the lab page: click **AWS Details → Show**. Note the `AccessKey` and `SecretKey`.

**Step 3 — update your local `.env`** (repo root) with the new keys:
```
AWS_ACCESS_KEY_ID=<new key>
AWS_SECRET_ACCESS_KEY=<new secret>
```

**Step 4 — start the EC2 instance** from the Academy sandbox terminal:
```bash
aws ec2 start-instances --instance-ids <instance-id>
aws ec2 wait instance-running --instance-ids <instance-id>
```

> To find the instance ID: `aws ec2 describe-instances --query "Reservations[*].Instances[*].[InstanceId,State.Name]" --output text`

**Step 5 — push new credentials to EC2** from your Mac terminal:
```bash
ssh -i /tmp/travelbuddy-key.pem ec2-user@34.205.234.211 "bash ~/refresh_creds.sh <NewAccessKey> <NewSecretKey>"
```

> **If `/tmp/travelbuddy-key.pem` is missing** (Mac rebooted), click **Download PEM** on the Academy lab page, then:
> ```bash
> mv ~/Downloads/labsuser.pem /tmp/travelbuddy-key.pem
> chmod 400 /tmp/travelbuddy-key.pem
> ```

---

### Deploying backend changes

```bash
# From the repo root on your Mac:
zip -r /tmp/backend_v2.zip backend/app backend/requirements.txt \
  -x "backend/app/__pycache__/*" "backend/app/**/__pycache__/*" "backend/app/data/embedding_cache.pkl"

# SCP directly to EC2 (bypass S3):
source .env
scp -i $EC2_KEY /tmp/backend_v2.zip ec2-user@$EC2_HOST:~/backend_v2.zip

# Also upload the embedding cache (speeds up search — without it first request is very slow):
scp -i $EC2_KEY backend/app/data/embedding_cache.pkl ec2-user@$EC2_HOST:~/backend/app/data/embedding_cache.pkl

# Then on EC2:
ssh -i /tmp/travelbuddy-key.pem ec2-user@34.205.234.211
sudo systemctl stop travelbuddy
rm -rf ~/backend_old ~/backend_new && mkdir ~/backend_new
unzip -q ~/backend_v2.zip -d ~/backend_new
mv ~/backend ~/backend_old && mv ~/backend_new/backend ~/backend 2>/dev/null || mv ~/backend_new/* ~/backend/
sudo chown -R ec2-user:ec2-user ~/backend
# Recreate the credentials file (it lives inside the backend folder):
bash ~/refresh_creds.sh <AccessKey> <SecretKey>
sudo systemctl start travelbuddy
```

### Deploying frontend changes

```bash
# From frontend/ on your Mac:
npm run build

source ../.env
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3 sync dist/ s3://$S3_BUCKET/ --exclude "*.html" \
  --cache-control "public, max-age=31536000, immutable"

AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3 cp dist/index.html s3://$S3_BUCKET/index.html \
  --cache-control "no-cache, no-store, must-revalidate"
```

---

### Rebuilding from scratch (new Academy account)

If the EC2 instance or S3 bucket no longer exists (account reset), follow these steps from the **Academy sandbox terminal**.

**Step 1 — create a security group:**
```bash
SG_ID=$(aws ec2 create-security-group --group-name travelbuddy-sg --description "TravelBuddy backend" --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 8000 --cidr 0.0.0.0/0
```

**Step 2 — launch the instance:**
```bash
AMI_ID=$(aws ec2 describe-images --owners amazon --filters "Name=name,Values=al2023-ami-*-x86_64" "Name=state,Values=available" --query "sort_by(Images, &CreationDate)[-1].ImageId" --output text)
INSTANCE_ID=$(aws ec2 run-instances --image-id $AMI_ID --instance-type t3.small --key-name vockey --security-group-ids $SG_ID --count 1 --query "Instances[0].InstanceId" --output text)
aws ec2 wait instance-running --instance-ids $INSTANCE_ID
echo "Instance: $INSTANCE_ID"
```

**Step 3 — allocate an Elastic IP:**
```bash
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id $INSTANCE_ID --allocation-id $ALLOC_ID
aws ec2 describe-addresses --allocation-ids $ALLOC_ID --query "Addresses[0].PublicIp" --output text
```

**Step 4 — expand the root volume to 24 GB** (from your Mac terminal, replace `vol-xxx` with the actual volume ID):
```bash
source .env
VOLUME_ID=$(AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws ec2 describe-instances --instance-ids $INSTANCE_ID \
  --query "Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId" --output text)
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws ec2 modify-volume --volume-id $VOLUME_ID --size 24
# Then SSH into the instance and run:
# sudo growpart /dev/xvda 1 && sudo xfs_growfs /
```

**Step 5 — download the PEM key** from the Academy lab page → save as `/tmp/travelbuddy-key.pem`:
```bash
mv ~/Downloads/labsuser.pem /tmp/travelbuddy-key.pem && chmod 400 /tmp/travelbuddy-key.pem
```

**Step 6 — update `.env` and `frontend/.env`** with the new IP:
```
# .env
EC2_HOST=<new-ip>

# frontend/.env
VITE_API_BASE=http://<new-ip>:8000/api
```

**Step 7 — install backend** (from Mac terminal):
```bash
source .env
scp -i $EC2_KEY /tmp/backend_v2.zip ec2-user@$EC2_HOST:~/backend_v2.zip
ssh -i $EC2_KEY ec2-user@$EC2_HOST "
  sudo dnf install -y python3.11 python3.11-pip unzip &&
  mkdir -p ~/backend && unzip -q ~/backend_v2.zip -d ~/backend_tmp &&
  mv ~/backend_tmp/backend/* ~/backend/ 2>/dev/null || mv ~/backend_tmp/* ~/backend/ &&
  mkdir -p ~/pip_tmp &&
  TMPDIR=~/pip_tmp pip3.11 install -r ~/backend/requirements.txt
"

# Upload the embedding cache (pre-computed — makes search fast):
scp -i $EC2_KEY backend/app/data/embedding_cache.pkl ec2-user@$EC2_HOST:~/backend/app/data/embedding_cache.pkl
```

**Step 8 — write credentials and set up systemd:**
```bash
ssh -i $EC2_KEY ec2-user@$EC2_HOST "
cat > ~/backend/.aws_env << EOF
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION=us-east-1
SESSION_TABLE=travelbuddy-sessions
EOF

sudo tee /etc/systemd/system/travelbuddy.service > /dev/null << 'SVC'
[Unit]
Description=TravelBuddy FastAPI Backend
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/backend
EnvironmentFile=/home/ec2-user/backend/.aws_env
ExecStart=/usr/bin/python3.11 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVC

sudo systemctl daemon-reload && sudo systemctl enable travelbuddy && sudo systemctl start travelbuddy

cat > ~/refresh_creds.sh << 'SCRIPT'
#!/bin/bash
KEY=\$1; SECRET=\$2
cat > /home/ec2-user/backend/.aws_env << ENVEOF
AWS_ACCESS_KEY_ID=\$KEY
AWS_SECRET_ACCESS_KEY=\$SECRET
AWS_DEFAULT_REGION=us-east-1
SESSION_TABLE=travelbuddy-sessions
ENVEOF
sudo systemctl restart travelbuddy
echo 'Credentials updated and service restarted.'
SCRIPT
chmod +x ~/refresh_creds.sh
"
```

**Step 9 — create S3 bucket and deploy frontend:**
```bash
source .env
NEW_BUCKET="travelbuddy-frontend-$(date +%s)"
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3 mb s3://$NEW_BUCKET --region us-east-1
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3api put-public-access-block --bucket $NEW_BUCKET \
  --public-access-block-configuration "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3 website s3://$NEW_BUCKET --index-document index.html --error-document index.html
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3api put-bucket-policy --bucket $NEW_BUCKET \
  --policy "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"PublicRead\",\"Effect\":\"Allow\",\"Principal\":\"*\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::$NEW_BUCKET/*\"}]}"

# Update S3_BUCKET in .env, then build and deploy:
# S3_BUCKET=<new-bucket-name>
cd frontend && npm run build
source ../.env
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3 sync dist/ s3://$S3_BUCKET/ --exclude "*.html" --cache-control "public, max-age=31536000, immutable"
AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=us-east-1 \
  aws s3 cp dist/index.html s3://$S3_BUCKET/index.html --cache-control "no-cache, no-store, must-revalidate"
```

Frontend URL: `http://<new-bucket>.s3-website-us-east-1.amazonaws.com`

## Next Integrations

- Add embeddings + vector search for a larger recommendation base
- Add a Google Maps JavaScript API key if you want multi-marker native Google Maps instead of embed-based maps
- Use the scoring rubric in `docs/evaluation-plan.md` to compare LLM-only, basic RAG, and personalized RAG results
