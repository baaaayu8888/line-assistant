#!/bin/bash
# Cloud Run デプロイスクリプト
# 使い方: bash setup/deploy.sh

set -e

PROJECT_ID=""
REGION="asia-northeast1"
SERVICE_NAME="line-assistant"

echo "=== LINE Assistant Cloud Run デプロイ ==="

# gcloud確認
if ! command -v gcloud &> /dev/null; then
    echo ""
    echo "gcloud CLI が見つかりません。以下からインストールしてください:"
    echo "https://cloud.google.com/sdk/docs/install"
    echo ""
    echo "Mac の場合:"
    echo "  brew install --cask google-cloud-sdk"
    exit 1
fi

# プロジェクト設定
echo ""
read -p "Google Cloud プロジェクトID: " PROJECT_ID
read -p "新規作成しますか？ (y/n): " CREATE_NEW

if [ "$CREATE_NEW" = "y" ]; then
    gcloud projects create "$PROJECT_ID"
    echo "プロジェクトを作成しました: $PROJECT_ID"
    echo ""
    echo "⚠️  Cloud Run のデプロイには課金の有効化が必要です（無料枠内で使用可能）"
    echo "以下のURLで課金を有効化してください:"
    echo "https://console.cloud.google.com/billing/projects/$PROJECT_ID"
    read -p "課金を有効化したら Enter を押してください..."
fi

gcloud config set project "$PROJECT_ID"

# API有効化
echo ""
echo "必要なAPIを有効化中..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    calendar-json.googleapis.com \
    --project "$PROJECT_ID"

# 環境変数の確認
echo ""
echo "環境変数を設定します。.env.example を参考に入力してください。"
echo ""
read -p "GROQ_API_KEY: " GROQ_API_KEY
read -p "NTFY_CHANNEL: " NTFY_CHANNEL
read -p "SUPABASE_URL: " SUPABASE_URL
read -p "SUPABASE_KEY: " SUPABASE_KEY
read -p "LINE_CHANNEL_SECRET: " LINE_CHANNEL_SECRET
read -p "LINE_CHANNEL_ACCESS_TOKEN: " LINE_CHANNEL_ACCESS_TOKEN
read -p "GOOGLE_CLIENT_ID: " GOOGLE_CLIENT_ID
read -p "GOOGLE_CLIENT_SECRET: " GOOGLE_CLIENT_SECRET
read -p "GOOGLE_REFRESH_TOKEN: " GOOGLE_REFRESH_TOKEN
CALENDAR_ID="${CALENDAR_ID:-nakashibakogyo@gmail.com}"
read -p "CALENDAR_ID ($CALENDAR_ID): " INPUT_CALENDAR_ID
CALENDAR_ID="${INPUT_CALENDAR_ID:-$CALENDAR_ID}"

# リポジトリのルートに移動
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# デプロイ
echo ""
echo "Cloud Run にデプロイ中..."
gcloud run deploy "$SERVICE_NAME" \
    --source . \
    --region "$REGION" \
    --allow-unauthenticated \
    --set-env-vars "GROQ_API_KEY=$GROQ_API_KEY,NTFY_CHANNEL=$NTFY_CHANNEL,SUPABASE_URL=$SUPABASE_URL,SUPABASE_KEY=$SUPABASE_KEY,LINE_CHANNEL_SECRET=$LINE_CHANNEL_SECRET,LINE_CHANNEL_ACCESS_TOKEN=$LINE_CHANNEL_ACCESS_TOKEN,GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID,GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET,GOOGLE_REFRESH_TOKEN=$GOOGLE_REFRESH_TOKEN,CALENDAR_ID=$CALENDAR_ID" \
    --project "$PROJECT_ID"

# デプロイ後のURL取得
echo ""
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format="value(status.url)")

echo "✅ デプロイ完了！"
echo ""
echo "サービスURL: $SERVICE_URL"
echo ""
echo "=== 次のステップ ==="
echo "LINE Developers の Webhook URL に以下を設定してください:"
echo "$SERVICE_URL/line-webhook"
echo ""
echo "LINE Developers: https://developers.line.biz/"
