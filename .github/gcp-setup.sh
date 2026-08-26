#!/usr/bin/env bash
#
# One-time setup for the GitHub Actions -> Cloud Run deploy path.
#
#   bash .github/gcp-setup.sh
#
# Creates a deploy service account scoped to this repo and wires it to GitHub
# via Workload Identity Federation, so no service-account key is ever created,
# downloaded, or stored in GitHub. CI receives a short-lived credential minted
# per run.
#
# Safe to re-run: every step tolerates already existing.
set -euo pipefail

PROJECT="${PROJECT:-antibody-hackathon-2026}"
REPO="${REPO:-aniket-3001/pf-sahi-hai}"
POOL="${POOL:-github}"
PROVIDER="${PROVIDER:-github-provider}"
# Keeps its original name: this is an infrastructure identity that
# already exists and holds the role grants. Renaming it would mean a
# new account, new bindings and a new GitHub secret, for nothing a
# user ever sees.
SA_ID="${SA_ID:-vested-deployer}"

# Repos that share this pool's provider. The provider is shared with Antibody,
# so its condition must list both -- dropping one would break that pipeline.
ALLOWED_REPOS="${ALLOWED_REPOS:-aniket-3001/Antibody aniket-3001/pf-sahi-hai}"

SA="${SA_ID}@${PROJECT}.iam.gserviceaccount.com"
NUM="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"

echo "project $PROJECT ($NUM)"
echo "repo    $REPO"
echo "sa      $SA"
echo

# 1. Deploy service account, separate from any other repo's, so this repo's CI
#    cannot deploy another project's service.
echo "==> service account"
gcloud iam service-accounts create "$SA_ID" \
  --display-name="GitHub Actions deployer (PF Sahi Hai)" \
  --project="$PROJECT" 2>/dev/null || echo "    exists"

# 2. Roles required by `gcloud run deploy --source`: it uploads the source,
#    triggers a Cloud Build, pushes the image, then updates the service.
echo "==> roles"
for R in \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.admin \
  roles/storage.admin \
  roles/iam.serviceAccountUser \
  roles/serviceusage.serviceUsageConsumer
do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role="$R" \
    --condition=None --quiet >/dev/null
  echo "    $R"
done

# 3. Restrict the provider to known repos. Without this condition ANY GitHub
#    Actions workflow on GitHub could request a token from this provider.
echo "==> provider condition"
COND=""
for r in $ALLOWED_REPOS; do
  [ -n "$COND" ] && COND="$COND || "
  COND="${COND}assertion.repository=='${r}'"
done
echo "    $COND"
gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" \
  --location=global --workload-identity-pool="$POOL" \
  --project="$PROJECT" \
  --attribute-condition="$COND" --quiet

# 4. Let only this repo impersonate this service account. This binding, not the
#    provider condition, is the boundary that keeps the two repos apart.
echo "==> impersonation binding"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --project="$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${NUM}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --quiet >/dev/null
echo "    $REPO -> $SA"

PROVIDER_PATH="projects/${NUM}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"

echo
echo "==> GitHub secrets"
if command -v gh >/dev/null 2>&1; then
  gh secret set GCP_PROJECT      --repo "$REPO" --body "$PROJECT"
  gh secret set GCP_DEPLOY_SA    --repo "$REPO" --body "$SA"
  gh secret set GCP_WIF_PROVIDER --repo "$REPO" --body "$PROVIDER_PATH"
  echo "    set GCP_PROJECT, GCP_DEPLOY_SA, GCP_WIF_PROVIDER"
else
  echo "    gh not found -- set these three by hand:"
  echo "    GCP_PROJECT      $PROJECT"
  echo "    GCP_DEPLOY_SA    $SA"
  echo "    GCP_WIF_PROVIDER $PROVIDER_PATH"
fi

echo
echo "done. push to main to trigger the pipeline."
