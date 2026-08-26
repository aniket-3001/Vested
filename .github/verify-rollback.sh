#!/usr/bin/env bash
#
# Prove the rollback path in deploy.yml actually works.
#
# The workflow's "Roll back on failed verification" step has never executed. An
# untested recovery path is not a safety net; it is a belief about one. This
# script exercises it against a THROWAWAY service, so a bug in the rollback is
# found here rather than during a real bad deploy of the live demo.
#
# It deliberately does not touch the `pf-sahi-hai` service. Testing a rollback by
# breaking production is how you find out your rollback is broken.
#
# What it does:
#   1. deploys a known-good revision of a scratch service
#   2. deploys a revision that is guaranteed to fail /status
#   3. runs the same update-traffic command deploy.yml runs
#   4. asserts traffic returned to the good revision and /status is 200
#   5. deletes the scratch service
#
# Usage:  bash .github/verify-rollback.sh
# Requires: gcloud, authenticated, with the same permissions the CI SA holds.

set -euo pipefail

SERVICE="${SERVICE:-pf-sahi-hai-rollback-test}"
REGION="${REGION:-asia-south1}"
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"

if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  echo "No project set. Pass PROJECT=... or run: gcloud config set project ..." >&2
  exit 2
fi

if [ "$SERVICE" = "pf-sahi-hai" ]; then
  echo "Refusing to run against the live service. This test breaks what it deploys." >&2
  exit 2
fi

say()  { printf '\n=== %s\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

cleanup() {
  say "cleaning up $SERVICE"
  gcloud run services delete "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --quiet >/dev/null 2>&1 || true
}
trap cleanup EXIT

say "project $PROJECT · region $REGION · scratch service $SERVICE"

# --- 1. a revision that works ------------------------------------------------
say "deploying the good revision"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --project "$PROJECT" \
  --allow-unauthenticated --max-instances 1 --quiet >/dev/null

GOOD=$(gcloud run services describe "$SERVICE" --region "$REGION" \
        --project "$PROJECT" --format='value(status.traffic[0].revisionName)')
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" \
        --project "$PROJECT" --format='value(status.url)')
[ -n "$GOOD" ] || fail "no serving revision after the first deploy"
echo "good revision: $GOOD"

code=$(curl -sS -o /dev/null -w '%{http_code}' "$URL/status" || true)
[ "$code" = "200" ] || fail "the good revision is not healthy (HTTP $code)"
echo "/status on the good revision: 200"

# --- 2. a revision that cannot serve -----------------------------------------
# PORT is what Cloud Run expects the container to listen on. Pointing the app at
# a different port produces a revision that deploys and then fails to serve,
# which is the failure mode the rollback exists for.
say "deploying a revision that will fail /status"
gcloud run deploy "$SERVICE" \
  --source . --region "$REGION" --project "$PROJECT" \
  --allow-unauthenticated --max-instances 1 \
  --set-env-vars=PORT=9999 --quiet >/dev/null 2>&1 || true

BAD=$(gcloud run services describe "$SERVICE" --region "$REGION" \
       --project "$PROJECT" --format='value(status.traffic[0].revisionName)')
echo "now serving: $BAD"

if [ "$BAD" = "$GOOD" ]; then
  echo "NOTE: Cloud Run refused to promote the broken revision, so traffic never"
  echo "moved. That is a stronger guarantee than the rollback and this test has"
  echo "nothing left to prove. The rollback step remains unexercised."
  exit 0
fi

code=$(curl -sS -o /dev/null -w '%{http_code}' "$URL/status" || true)
[ "$code" != "200" ] || fail "the broken revision is serving 200 - fixture is wrong"
echo "/status on the broken revision: $code (as intended)"

# --- 3. the exact command deploy.yml runs ------------------------------------
say "rolling back to $GOOD"
gcloud run services update-traffic "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --to-revisions "$GOOD=100" --quiet >/dev/null

# --- 4. assert we are actually back ------------------------------------------
NOW=$(gcloud run services describe "$SERVICE" --region "$REGION" \
       --project "$PROJECT" --format='value(status.traffic[0].revisionName)')
[ "$NOW" = "$GOOD" ] || fail "traffic is on $NOW, expected $GOOD"

for i in $(seq 1 10); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' "$URL/status" || true)
  [ "$code" = "200" ] && break
  echo "attempt $i: HTTP $code"
  sleep 3
done
[ "$code" = "200" ] || fail "/status is $code after rollback"

say "PASS - rollback restored $GOOD and /status is 200"
