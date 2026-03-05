# ShortsForge AI — Installation & Setup Guide

## What This Is

A fully automated YouTube Shorts pipeline built on LangGraph.

Every day at 11 AM and 7 PM IST, it:
1. **Picks** a trending content idea across 5 universes (pop culture, sports, history, animals, office)
2. **Generates** a complete script + Veo prompt using Gemini 2.0 Flash
3. **Checks compliance** — trademark scan, parody rules, family-friendly gate
4. **Renders** an 8-second Pixar-style animated Short using Veo 3
5. **Uploads** to YouTube with optimised metadata and pins a comment

**One API key** (Google) powers everything: Gemini + Veo + YouTube.

---

## Project Structure

```
shortsforge_langgraph/
├── main.py                    # CLI entry point + scheduler
├── requirements.txt           # Python dependencies
├── pytest.ini                 # Test configuration
├── .env.example               # Environment variable template
│
├── graph/                     # LangGraph pipeline
│   ├── __init__.py
│   ├── state.py               # Shared PipelineState TypedDict
│   ├── universes.py           # 5 content universes + burnout tracker
│   ├── nodes.py               # All 7 pipeline nodes (Gemini + Veo + YouTube)
│   ├── edges.py               # Conditional routing logic
│   └── pipeline.py            # LangGraph graph assembly
│
├── tests/                     # 122 test cases
│   ├── conftest.py            # Shared fixtures (VALID_CONTENT, base_state)
│   ├── test_universes.py      # Burnout tracker + universe selection (49 tests)
│   ├── test_nodes.py          # Node logic, compliance, trademark scan (39 tests)
│   ├── test_edges.py          # Routing logic boundary tests (20 tests)
│   └── test_integration.py    # Full pipeline runs, retry loops (14 tests)
│
├── Dockerfile                 # Production (Cloud Run Jobs)
├── Dockerfile.dev             # Local development
├── docker-compose.yml         # Local orchestration
├── entrypoint.sh              # Container startup — fetches secrets
└── deploy_gcp.sh              # One-command GCP deployment
```

---

## Prerequisites

| Requirement | Where to get it |
|---|---|
| Python 3.12+ | https://python.org |
| Google account | https://accounts.google.com |
| Google AI Studio API key | https://aistudio.google.com/app/apikey |
| YouTube channel | https://studio.youtube.com |
| GCP project (for production) | https://console.cloud.google.com |

> **Veo 3 access**: Requires Google AI Studio with Veo 3 enabled. As of 2026, this needs explicit access grant from Google. Apply at https://deepmind.google/technologies/veo/

---

## Option A — Local Setup (Recommended First)

### 1. Clone / extract the project

```bash
unzip shortsforge_langgraph.zip
cd shortsforge_langgraph
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
# Single key powers Gemini 2.0 Flash + Veo 3
GOOGLE_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Path to YouTube OAuth credentials (downloaded in step 5)
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json

# Post times (24h, IST)
POST_TIMES=11:00,19:00

# Set true to skip YouTube upload (safe for testing)
DRY_RUN=false
```

### 5. Set up YouTube OAuth

**a. Create OAuth credentials in Google Cloud Console**

1. Go to https://console.cloud.google.com
2. Create a new project (or use existing)
3. Enable the **YouTube Data API v3**:
   - APIs & Services → Library → search "YouTube Data API v3" → Enable
4. Create OAuth credentials:
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Desktop app**
   - Name: `ShortsForge`
   - Download the JSON → save as `client_secrets.json` in the project root
5. Add your YouTube account as a test user:
   - APIs & Services → OAuth consent screen → Test users → Add Users → add your Google email

**b. Run first-time authentication**

```bash
python main.py --dry-run
```

A browser window will open. Authorise with your YouTube account.
This creates `youtube_token.pickle` — keep it safe, it auto-refreshes.

### 6. Test the pipeline

```bash
# Dry run — generates content + video but skips YouTube upload
python main.py --dry-run

# With a theme hint
python main.py --dry-run --theme "office humor"

# See the graph structure
python main.py --visualise

# Generate 3 videos in sequence
python main.py --dry-run --count 3
```

### 7. Run the tests

```bash
pip install pytest
pytest                              # all 122 tests
pytest tests/test_universes.py -v   # burnout tracker tests only
pytest -k "trademark" -v            # trademark scan tests only
pytest tests/test_edges.py -v       # routing logic tests only
```

Expected output:
```
========================= 122 passed in 4.3s =========================
```

---

## Option B — Docker (Local)

```bash
# First-time auth (required before Docker — generates youtube_token.pickle)
python main.py --dry-run

# Build and run
docker compose up

# Run with custom theme
docker compose run pipeline python main.py --dry-run --theme "sports comedy"

# Scheduled mode (posts at POST_TIMES automatically)
docker compose --profile scheduled up
```

---

## Option C — GCP Production Deployment

### Prerequisites
- `gcloud` CLI installed and authenticated: `gcloud auth login`
- `youtube_token.pickle` generated locally (see Option A step 5b)
- `client_secrets.json` present

### Deploy

```bash
chmod +x deploy_gcp.sh
./deploy_gcp.sh
```

The script will prompt for your GCP Project ID, then:
1. Enable all required APIs
2. Create a service account with correct IAM roles
3. Upload `GOOGLE_API_KEY`, `YOUTUBE_CLIENT_SECRETS`, `YOUTUBE_TOKEN` to Secret Manager
4. Build the Docker image and deploy a Cloud Run Job
5. Create two Cloud Scheduler triggers: **11:00 AM IST** and **7:00 PM IST**

### Manually trigger a run

```bash
gcloud run jobs execute shortsforge --region asia-south1
```

### Watch live logs

```bash
gcloud run jobs executions logs tail shortsforge --region asia-south1
```

### Monthly GCP cost estimate

| Service | Cost |
|---|---|
| Cloud Run Jobs (2 runs/day × 5 min) | ~$3–5/month |
| Cloud Scheduler (3 jobs) | Free (< 3 jobs) |
| Secret Manager | ~$0.24/month |
| Artifact Registry | ~$0.05/month |
| **Total** | **~$4–6/month** |

---

## Content System

### 5 Universes

| Universe | Examples |
|---|---|
| 🎬 Pop Culture | "a giant rage-fuelled green superhero tries yoga" |
| ⚽ Sports | "a Portuguese footballer obsessed with mirrors tries cooking" |
| 🏛️ Historical Figures | "Napoleon Bonaparte discovers TikTok" |
| 🐾 Animals | "an anxious hamster has a Monday morning crisis" |
| 💼 Office | "the office printer develops abandonment issues" |

### Parody Rules (YouTube-safe)

- **Fictional characters** (superheroes, game characters): described vividly, no trademarked names
- **Real living people** (athletes, celebrities): parody descriptions only, never real name
- **Historical figures** (deceased 50+ years): real name allowed in clearly comedic context

### Burnout Tracker

Prevents repetition across 4 independent lists:

```json
{
  "used_titles":     [...last 100 titles],
  "used_scenarios":  [...last 90 scenario strings],
  "used_characters": [...last 90 character tags],
  "used_universes":  [...last 10 universe keys]
}
```

Same universe picked 3× in a row → hard-blocked until streak breaks.
Persists to `output/burnout_tracker.json` across container restarts.

---

## Pipeline Architecture

```
pick_universe
     │  (Gemini picks trending universe + character + scenario)
     ▼
generate_content ◄──────────────────────┐
     │  (Gemini writes full content pkg) │ retry (max 3)
     ▼                                   │
compliance_check ───────────────────────┘
     │ pass        │ fail
     │             ▼
     │        fix_content (max 2 attempts)
     │             │
     ▼ ┌───────────┴──────────┐
     │ ▼ PARALLEL             ▼
     │ generate_video    build_youtube_meta
     │      │                 │
     └──────┴────────┬────────┘
                     ▼
               upload_youtube
                     │
                    END
```

---

## CLI Reference

```bash
python main.py [OPTIONS]

Options:
  --theme TEXT     Theme hint for content generation (e.g. "office humor")
  --dry-run        Generate content + video but skip YouTube upload
  --count INT      Number of videos to generate in one run (default: 1)
  --schedule       Run on POST_TIMES schedule (daemon mode)
  --visualise      Print ASCII graph diagram and exit
```

---

## Troubleshooting

**`❌ GOOGLE_API_KEY not set`**
→ Copy `.env.example` to `.env` and add your key from https://aistudio.google.com

**`Veo quota exceeded`**
→ Veo 3 has rate limits. Wait 60 seconds and retry. For production, add retry logic.

**`youtube_token.pickle not found`**
→ Run `python main.py --dry-run` locally first to complete OAuth flow.

**`Compliance FAIL: trademark_violation`**
→ Gemini generated a trademarked name. The `fix_content` node will auto-fix it (up to 2 attempts). If it keeps failing, add the name to `TRADEMARK_BLACKLIST` in `nodes.py`.

**Tests failing with import errors**
→ Make sure you're running pytest from the project root: `cd shortsforge_langgraph && pytest`
