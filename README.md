# ShortsForge 🎬

An autonomous AI pipeline that generates, validates, and uploads viral YouTube Shorts — fully hands-free. Built on LangGraph, Gemini 2.5 Flash, and Veo 3.

---

## How it works

```
pick_universe
      │
generate_content ◄─────────────┐
      │                         │ (retry up to 3x)
      ▼                         │
compliance_check ───────────────┘
      │
      ├── PASS ──► generate_video ──┐
      │        └► build_youtube_meta─┤
      │                              ▼
      ├── FAIL ──► fix_content     upload_youtube
      │                │                │
      │                └──► compliance_check
      │
      └── LEARN ──► update_rules ──► compliance_check
```

Every node is a pure function `(PipelineState) → dict`. LangGraph merges partial state updates and handles the routing logic between nodes.

---

## Project structure

```
shortsforge/
└── graph/
    ├── nodes.py               # All 7 LangGraph nodes + Gemini calls
    ├── pipeline.py            # Graph assembly + compile
    ├── state.py               # PipelineState TypedDict
    ├── edges.py               # Conditional routing functions
    ├── universes.py           # Content universe definitions + burnout tracker
    ├── compliance_supervisor.py  # AI-powered compliance evaluator
    └── parser.py              # JSON parse + repair utilities
```

---

## Nodes

| # | Node | What it does |
|---|------|-------------|
| 0 | `pick_universe` | Gemini picks the best universe, character, and scenario for a mass global audience |
| 1 | `generate_content` | Gemini generates the full content package — script, veo prompt, YouTube metadata |
| 2 | `compliance_check` | AI supervisor evaluates content against trademark, parody, and YouTube policy rules |
| 3 | `fix_content` | Gemini fixes specific compliance failures using supervisor feedback |
| 3.5 | `update_compliance_rules` | Learns patterns from repeated failures, extends the blacklist at runtime |
| 4 | `generate_video` | Veo 3.1 generates the 8-second animated short (parallel branch A) |
| 5 | `build_youtube_meta` | Validates and enriches YouTube title, description, tags (parallel branch B) |
| 6 | `upload_youtube` | Uploads the video via YouTube Data API v3 and posts a pinned comment |

---

## Content universes

| Universe | Weight | Best for |
|----------|--------|----------|
| `animals_human_problems` | 30 | Universal — zero cultural knowledge needed |
| `sports_athletes` | 25 | Cricket, football/soccer, global athletics |
| `pop_culture` | 20 | Fictional characters in absurd everyday situations |
| `office_workplace` | 15 | Relatable corporate comedy |
| `historical_figures` | 10 | Only when the joke needs zero historical knowledge |

Weights are used by the burnout-aware universe selector. The same universe cannot appear 3 times in a row, and recently used characters and scenarios go on cooldown automatically.

---

## Setup

### 1. Install dependencies

```bash
pip install langgraph google-genai google-auth-oauthlib google-api-python-client
```

### 2. Environment variables

```bash
# Required
GOOGLE_API_KEY=your_gemini_api_key

# YouTube upload
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json   # default
YOUTUBE_CHANNEL_URL=https://youtube.com/@YourChannel

# Video model (optional — defaults to veo-3.1-fast-generate-preview)
VIDEO_GENERATION_MODEL=veo-3.1-generate-preview

# Cloud deployment (optional — see Cloud Deployment section)
YOUTUBE_TOKEN_SECRET=projects/YOUR_PROJECT/secrets/youtube-token/versions/latest
```

### 3. YouTube OAuth (first run only)

Download your OAuth 2.0 client secrets from [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials and save as `client_secrets.json`.

On first run, a browser window will open for authorization. The token is saved to `youtube_token.pickle` and auto-refreshes on all subsequent runs.

Make sure `http://localhost:8081/` is registered as an authorized redirect URI in your OAuth client.

---

## Running the pipeline

```python
from graph.pipeline import build_pipeline

pipeline = build_pipeline()

result = pipeline.invoke({
    "theme_hint": "",   # optional — e.g. "cricket" or "cats"
    "dry_run": False,   # True = skip actual YouTube upload
    "logs": [],
    "pipeline_status": "running",
    "content_attempts": 0,
    "compliance_fix_attempts": 0,
    "fix_history": [],
})

print(result["youtube_url"])
```

### Dry run (no upload)

```python
result = pipeline.invoke({
    "theme_hint": "",
    "dry_run": True,
    "logs": [],
    "pipeline_status": "running",
    "content_attempts": 0,
    "compliance_fix_attempts": 0,
    "fix_history": [],
})
```

---

## Compliance system

Every generated content package passes through two layers of compliance:

**Layer 1 — AI Supervisor** (`ComplianceSupervisor.evaluate()`): Gemini evaluates the full content package against 6 rules — trademark violations, real people named, family-friendly, original audio, structural completeness (3-second hook, 8-second loop, CTA overlay), and parody safety. Returns a structured verdict with score, failures, warnings, and suggestions.

**Layer 2 — Hard blacklist scan** (`_scan_blacklist()`): Context-aware word-boundary scan against a curated list of trademarked names. Uses safe-context patterns to avoid false positives — `"frozen data"` and `"sonic boom"` are not flagged, but `"The Hulk smashes"` is.

Scores: 90–100 = pass, 70–89 = warnings only, 0–69 = fail (triggers fix or abort).

If content fails twice, the `update_compliance_rules` node analyses the failure history, learns patterns, and extends the blacklist at runtime before retrying.

---

## Gemini calls

All structured Gemini calls use `response_schema` for constrained JSON decoding — the model cannot produce truncated output, markdown fences, or missing fields.

| Call | Schema | Token budget |
|------|--------|-------------|
| `pick_universe` | `SCHEMA_PICK_UNIVERSE` | 8192 |
| `generate_content` | `SCHEMA_CONTENT_PACKAGE` | 8192 |
| `fix_content` | `SCHEMA_CONTENT_PACKAGE` | 8192 |
| `update_compliance_rules` | `SCHEMA_LEARNING` | 8192 |
| `compliance_supervisor.evaluate()` | `_VERDICT_SCHEMA` | 4096 |

---

## Output files

```
output/
├── videos/
│   └── {title}_{timestamp}.mp4      # generated video
└── metadata/
    └── {title}_{timestamp}.json     # full content package + final metadata
```

The burnout tracker is saved to `output/burnout_tracker.json` and persists across runs to prevent repeated characters, scenarios, and universes.

---

## Cloud deployment

For automated cloud runs, store the YouTube OAuth token in GCP Secret Manager instead of a local pickle file.

**Step 1 — Complete OAuth once locally:**
```bash
python -c "from graph.pipeline import build_pipeline; build_pipeline().invoke({'theme_hint':'','dry_run':True,'logs':[],'pipeline_status':'running','content_attempts':0,'compliance_fix_attempts':0,'fix_history':[]})"
```

**Step 2 — Upload token to Secret Manager:**
```bash
gcloud secrets create youtube-token --data-file=youtube_token.pickle
```

**Step 3 — Set env var in your cloud environment:**
```bash
YOUTUBE_TOKEN_SECRET=projects/YOUR_PROJECT_ID/secrets/youtube-token/versions/latest
```

The pipeline will load the token from Secret Manager on startup. The token auto-refreshes silently — no browser interaction needed after the initial setup.
