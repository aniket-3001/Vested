#!/usr/bin/env bash
# Deploy PF Sahi Hai to Cloud Run. Builds remotely via Cloud Build - no local
# Docker daemon required.
set -euo pipefail

SERVICE="${SERVICE:-pf-sahi-hai}"
REGION="${REGION:-asia-south1}"          # Mumbai - closest to the users
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"

[ -z "$PROJECT" ] && { echo "No project set. Run: gcloud config set project YOUR_PROJECT"; exit 1; }

echo "Deploying $SERVICE to $REGION in $PROJECT"

gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --session-affinity \
  --timeout 120 \
  ${OPENAI_API_KEY:+--set-env-vars "OPENAI_API_KEY=${OPENAI_API_KEY}"}

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')
echo
echo "Live at: $URL"
echo "Health : $URL/status"
# routing can take a few seconds to propagate on a fresh revision
for i in 1 2 3 4 5 6 7 8 9 10; do
  code=$(curl -sS -o /tmp/pf-sahi-hai_health -w "%{http_code}" "$URL/status" || true)
  [ "$code" = "200" ] && { cat /tmp/pf-sahi-hai_health; echo; break; }
  sleep 3
done
[ "$code" = "200" ] || echo "WARNING: /status returned $code after retries"
