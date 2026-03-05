#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  ShortsForge AI — GCP Deployment Script
#  Automates the full Google Cloud setup:
#    1. Enable APIs
#    2. Create service account + grant permissions
#    3. Upload secrets to Secret Manager
#    4. Build & deploy Cloud Run Job
#    5. Create Cloud Scheduler jobs (11:00 + 19:00 IST)
#
#  Usage:
#    chmod +x deploy_gcp.sh
#    ./deploy_gcp.sh
# ─────────────────────────────────────────────────────────────

set -euo pipefail

# ── CONFIG — edit these ───────────────────────────────────────
PROJECT_ID=""                         # Your GCP project ID
REGION="asia-south1"                  # Mumbai (closest to Bengaluru)
JOB_NAME="shortsforge"
SA_NAME="shortsforge-sa"
MORNING_SCHEDULE="30 5 * * *"         # 11:00 IST = 05:30 UTC
EVENING_SCHEDULE="30 13 * * *"        # 19:00 IST = 13:30 UTC
# ─────────────────────────────────────────────────────────────

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}▸${RESET} $1"; }
ok()   { echo -e "${GREEN}✓${RESET} $1"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $1"; }
fail() { echo -e "${RED}✗${RESET} $1"; exit 1; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║      🎬  ShortsForge AI — GCP Deployment            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── Validate config ───────────────────────────────────────────
if [ -z "$PROJECT_ID" ]; then
  echo -n "Enter your GCP Project ID: "
  read -r PROJECT_ID
fi
[ -z "$PROJECT_ID" ] && fail "PROJECT_ID is required"

# Check required files exist
[ ! -f ".env" ]                  && fail ".env file not found. Copy .env.example → .env and fill in your keys."
[ ! -f "client_secrets.json" ]   && fail "client_secrets.json not found. Download from Google Cloud Console."
[ ! -f "youtube_token.pickle" ]  && fail "youtube_token.pickle not found. Run: python main.py --dry-run  to generate it locally first."

# ── Set GCP project ───────────────────────────────────────────
log "Setting GCP project to: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"
ok "Project set"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# ── Step 1: Enable APIs ───────────────────────────────────────
echo ""
echo -e "${BOLD}[1/5] Enabling GCP APIs...${RESET}"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  --quiet
ok "All APIs enabled"

# ── Step 2: Create service account ───────────────────────────
echo ""
echo -e "${BOLD}[2/5] Setting up Service Account...${RESET}"

if gcloud iam service-accounts describe "$SA_EMAIL" &>/dev/null; then
  warn "Service account already exists: $SA_EMAIL"
else
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="ShortsForge Service Account" \
    --quiet
  ok "Service account created: $SA_EMAIL"
fi

# Grant Cloud Run invoker role (needed for Scheduler → Cloud Run)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --quiet

ok "Roles granted to service account"

# ── Step 3: Upload secrets ────────────────────────────────────
echo ""
echo -e "${BOLD}[3/5] Uploading secrets to Secret Manager...${RESET}"

# Load .env and extract values
source .env

upload_secret() {
  local name="$1"
  local value="$2"
  if gcloud secrets describe "$name" &>/dev/null; then
    echo "$value" | gcloud secrets versions add "$name" --data-file=- --quiet
    ok "Updated secret: $name"
  else
    echo "$value" | gcloud secrets create "$name" \
      --data-file=- --replication-policy=automatic --quiet
    ok "Created secret: $name"
  fi
  # Grant access to service account
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet
}

upload_secret "GOOGLE_API_KEY"    "$GOOGLE_API_KEY"

# Upload file-based secrets
upload_file_secret() {
  local name="$1"
  local file="$2"
  if gcloud secrets describe "$name" &>/dev/null; then
    gcloud secrets versions add "$name" --data-file="$file" --quiet
    ok "Updated secret: $name (from $file)"
  else
    gcloud secrets create "$name" \
      --data-file="$file" --replication-policy=automatic --quiet
    ok "Created secret: $name (from $file)"
  fi
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet
}

upload_file_secret "YOUTUBE_CLIENT_SECRETS" "client_secrets.json"
upload_file_secret "YOUTUBE_TOKEN"          "youtube_token.pickle"

# ── Step 4: Deploy Cloud Run Job ──────────────────────────────
echo ""
echo -e "${BOLD}[4/5] Building & deploying Cloud Run Job...${RESET}"
log "This will take 2-4 minutes (building Docker image)..."

gcloud run jobs deploy "$JOB_NAME" \
  --source . \
  --region "$REGION" \
  --memory 2Gi \
  --cpu 2 \
  --task-timeout 3600 \
  --max-retries 1 \
  --service-account "$SA_EMAIL" \
  --set-env-vars "DRY_RUN=false,VIDEO_COUNT=1" \
  --quiet

ok "Cloud Run Job deployed: $JOB_NAME"

# ── Step 5: Create Cloud Scheduler jobs ──────────────────────
echo ""
echo -e "${BOLD}[5/5] Creating Cloud Scheduler jobs...${RESET}"

JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

create_or_update_scheduler() {
  local sched_name="$1"
  local schedule="$2"
  local description="$3"

  if gcloud scheduler jobs describe "$sched_name" --location "$REGION" &>/dev/null; then
    gcloud scheduler jobs update http "$sched_name" \
      --location "$REGION" \
      --schedule "$schedule" \
      --time-zone "Asia/Kolkata" \
      --uri "$JOB_URI" \
      --http-method POST \
      --oauth-service-account-email "$SA_EMAIL" \
      --quiet
    ok "Updated scheduler: $sched_name ($description)"
  else
    gcloud scheduler jobs create http "$sched_name" \
      --location "$REGION" \
      --schedule "$schedule" \
      --time-zone "Asia/Kolkata" \
      --description "$description" \
      --uri "$JOB_URI" \
      --http-method POST \
      --oauth-service-account-email "$SA_EMAIL" \
      --quiet
    ok "Created scheduler: $sched_name ($description)"
  fi
}

create_or_update_scheduler \
  "${JOB_NAME}-morning" \
  "$MORNING_SCHEDULE" \
  "ShortsForge 11:00 AM IST post"

create_or_update_scheduler \
  "${JOB_NAME}-evening" \
  "$EVENING_SCHEDULE" \
  "ShortsForge 7:00 PM IST post"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅  Deployment Complete!                            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo "  Cloud Run Job:  https://console.cloud.google.com/run/jobs?project=${PROJECT_ID}"
echo "  Scheduler:      https://console.cloud.google.com/cloudscheduler?project=${PROJECT_ID}"
echo "  Logs:           https://console.cloud.google.com/logs?project=${PROJECT_ID}"
echo ""
echo -e "${BOLD}Test it now:${RESET}"
echo "  gcloud run jobs execute $JOB_NAME --region $REGION"
echo ""
echo -e "${BOLD}Watch live logs:${RESET}"
echo "  gcloud run jobs executions logs tail $JOB_NAME --region $REGION"
echo ""
