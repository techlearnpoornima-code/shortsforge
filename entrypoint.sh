#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  ShortsForge AI — Production Entrypoint
#  Runs inside the Cloud Run Job container.
#  Fetches secrets from GCP Secret Manager → env vars + files,
#  then executes the LangGraph pipeline.
# ─────────────────────────────────────────────────────────────

set -euo pipefail

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎬  ShortsForge AI — Container Starting"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Helper: fetch a secret or abort with a clear message ─────
fetch_secret() {
  local secret_name="$1"
  local value
  value=$(gcloud secrets versions access latest --secret="$secret_name" 2>&1) || {
    echo "❌  Failed to fetch secret: $secret_name"
    echo "    Make sure the secret exists and the service account has secretmanager.secretAccessor role."
    exit 1
  }
  echo "$value"
}

# ── 1. Fetch API key secrets into environment variables ──────
echo "🔐  Fetching API keys from Secret Manager..."

export GOOGLE_API_KEY
GOOGLE_API_KEY=$(fetch_secret "GOOGLE_API_KEY")
echo "   ✓ GOOGLE_API_KEY loaded"

# ── 2. Write YouTube credential files to disk ────────────────
echo "🔐  Fetching YouTube credentials from Secret Manager..."

fetch_secret "YOUTUBE_CLIENT_SECRETS" > /app/client_secrets.json
echo "   ✓ client_secrets.json written"

fetch_secret "YOUTUBE_TOKEN" > /app/youtube_token.pickle
echo "   ✓ youtube_token.pickle written"

export YOUTUBE_CLIENT_SECRETS_FILE=/app/client_secrets.json

# ── 3. Set pipeline config ────────────────────────────────────
export DRY_RUN="${DRY_RUN:-false}"
export POST_TIMES="${POST_TIMES:-11:00,19:00}"

echo ""
echo "⚙️   Config:"
echo "   DRY_RUN  = $DRY_RUN"
echo "   THEME    = ${THEME_HINT:-none}"
echo "   COUNT    = ${VIDEO_COUNT:-1}"
echo ""

# ── 4. Run the pipeline ───────────────────────────────────────
echo "🚀  Launching LangGraph pipeline..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python main.py \
  ${THEME_HINT:+--theme "$THEME_HINT"} \
  ${VIDEO_COUNT:+--count "$VIDEO_COUNT"} \
  ${DRY_RUN:+$([ "$DRY_RUN" = "true" ] && echo "--dry-run")}

EXIT_CODE=$?

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $EXIT_CODE -eq 0 ]; then
  echo "  ✅  Pipeline completed successfully"
else
  echo "  ❌  Pipeline exited with code $EXIT_CODE"
fi
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit $EXIT_CODE
