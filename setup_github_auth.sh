#!/usr/bin/env bash
# GitHub Actions -> Google Cloud kalitsiz ulanish (Workload Identity Federation).
# Google Cloud Shell'da bir marta ishga tushiring (matnni nusxalab joylang).
set -e

PROJECT_ID="bukmeker-bot"
REPO="nabdurasuloff/bukmeker-bot"
SA="bukmeker-bot@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github"
PROVIDER="github-provider"

gcloud config set project "$PROJECT_ID" >/dev/null
PN=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
echo "Loyiha raqami: $PN"

echo "1/5 Kerakli API'lar yoqilmoqda..."
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  cloudresourcemanager.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com \
  run.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com \
  firestore.googleapis.com firebase.googleapis.com >/dev/null

echo "2/5 Service account rollari..."
for R in roles/editor roles/cloudfunctions.admin roles/iam.serviceAccountUser roles/firebase.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" \
    --role="$R" --condition=None -q >/dev/null
done

echo "3/5 Identity pool..."
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub"

echo "4/5 GitHub provider (faqat $REPO uchun)..."
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global \
  --workload-identity-pool="$POOL" >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global \
    --workload-identity-pool="$POOL" --display-name="GitHub Actions" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository=='${REPO}'"

echo "5/5 GitHub'ga service account'dan foydalanish ruxsati..."
gcloud iam service-accounts add-iam-policy-binding "$SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PN}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  -q >/dev/null

echo
echo "✅ Tayyor! GitHub'da WIF_PROVIDER secret'iga quyidagini kiriting:"
echo
echo "projects/${PN}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
