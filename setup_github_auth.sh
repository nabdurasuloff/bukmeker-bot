#!/usr/bin/env bash
# GitHub Actions -> Google Cloud kalitsiz ulanish (Workload Identity Federation).
# Google Cloud Shell'da bir marta ishga tushiring (matnni nusxalab joylang).
# Loyihadagi mavjud resurslarga tegmaydi: faqat yangi service account, pool va ruxsatlar qo'shadi.
set -e

PROJECT_ID="bilyard-klub"
REPO="nabdurasuloff/bukmeker-bot"
SA_NAME="bukmeker-deploy"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
POOL="github"
PROVIDER="bukmeker-provider"

gcloud config set project "$PROJECT_ID" >/dev/null
PN=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "1/6 API'lar..."
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  cloudresourcemanager.googleapis.com cloudfunctions.googleapis.com cloudbuild.googleapis.com \
  run.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com \
  firestore.googleapis.com firebase.googleapis.com >/dev/null

echo "2/6 Service account..."
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="Bukmeker bot deploy (GitHub)"

echo "3/6 Rollar..."
for R in roles/editor roles/cloudfunctions.admin roles/iam.serviceAccountUser roles/firebase.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" \
    --role="$R" --condition=None -q >/dev/null
done

echo "4/6 Identity pool va provider..."
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global \
  --workload-identity-pool="$POOL" >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global \
    --workload-identity-pool="$POOL" --display-name="Bukmeker bot" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository=='${REPO}'"

echo "5/6 GitHub ruxsati..."
gcloud iam service-accounts add-iam-policy-binding "$SA" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PN}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  -q >/dev/null

echo "6/6 Firestore..."
if gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  echo "   Firestore bor, tegilmadi."
else
  gcloud firestore databases create --database="(default)" --location=europe-west1 --type=firestore-native
fi

echo
echo "✅ Tayyor! WIF_PROVIDER secret'iga FAQAT shu qatorni kiriting:"
echo "projects/${PN}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
