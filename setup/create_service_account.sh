#!/bin/bash
# Google Cloud サービスアカウント作成スクリプト
# 使い方: bash setup/create_service_account.sh
#
# 事前準備:
#   1. https://console.cloud.google.com/ でプロジェクト作成
#   2. 課金を有効化（無料枠内OK、カード登録必須）
#   3. gcloud CLI インストール: brew install --cask google-cloud-sdk
#   4. gcloud auth login  ← ブラウザで認証（1回だけ）

set -e

read -p "Google Cloud プロジェクトID: " PROJECT_ID

gcloud config set project "$PROJECT_ID"

# 必要なAPIを有効化
echo "APIを有効化中..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com

# サービスアカウント作成
SA_NAME="line-assistant-sa"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "サービスアカウントを作成中..."
gcloud iam service-accounts create "$SA_NAME" \
    --display-name="LINE Assistant Deploy" \
    --project "$PROJECT_ID" 2>/dev/null || echo "（既存のサービスアカウントを使用）"

# 必要な権限を付与
echo "権限を付与中..."
for ROLE in \
    "roles/run.admin" \
    "roles/cloudbuild.builds.editor" \
    "roles/artifactregistry.admin" \
    "roles/iam.serviceAccountUser" \
    "roles/storage.admin"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$ROLE" \
        --quiet
done

# キーファイルをダウンロード
KEY_FILE="setup/gcp-sa-key.json"
echo "サービスアカウントキーを生成中..."
gcloud iam service-accounts keys create "$KEY_FILE" \
    --iam-account="$SA_EMAIL" \
    --project "$PROJECT_ID"

echo ""
echo "✅ 完了！"
echo ""
echo "=== GitHub Secrets に設定するもの ==="
echo ""
echo "GCP_PROJECT_ID = $PROJECT_ID"
echo "GCP_SA_KEY     = $(cat $KEY_FILE | tr -d '\n')"
echo ""
echo "その他の secrets は .env.example を参照してください"
echo ""
echo "⚠️  $KEY_FILE は機密情報です。GitHubにpushしないでください（.gitignoreに追加済み）"
