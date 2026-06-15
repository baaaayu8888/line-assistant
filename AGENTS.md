# AGENTS.md — line-assistant

このファイルは Codex / Claude などの AI エージェントが本リポジトリをレビュー・改修するときに
最初に読むガイドです。「全システムを Codex のダブルチェックに回す」ための起点として用意しています。

## このプロジェクトは何か

中芝悠太（大阪・施工業）向けの個人用 LINE アシスタント。FastAPI 1 ファイル（`main.py`）に
複数の機能が同居しており、Cloud Run（本番）/ Render（予備）で動く。

- 本番 URL: `https://line-assistant-ncpnpxg3hq-an.a.run.app`
- 言語/FW: Python 3.11 / FastAPI / httpx（同期 SDK は使わず REST 直叩き）
- データ: Supabase（`contacts`, `conversations`, `corrections` テーブル）
- AI: Anthropic Claude Haiku（`claude-haiku-4-5-20251001`）を REST で呼び出し
- 通知: ntfy.sh（返信案をスマホへプッシュ）

## システム（機能）一覧

`main.py` 内に同居している「システム」は実質これだけある。レビュー時はこの単位で見ると漏れない。

| # | システム | 入口 | 主な関数 |
|---|---------|------|---------|
| 1 | LINE Bot 本体（受信→意図判定→AI返信 or 予定登録） | `POST /line-webhook` | `line_webhook` |
| 2 | MacroDroid 通知連携（通知文→返信案→ntfy） | `POST /webhook` | `receive_message`, `_receive_message_inner` |
| 3 | AI 返信生成（敬語/関西弁の自動切替） | — | `ask_claude`, `detect_intent` |
| 4 | 予定抽出→Google カレンダー登録（色ルール付き） | — | `extract_schedule`, `register_calendar_event`, `calc_end_time` |
| 5 | 返信案ビューア／コピー | `GET /latest`, `GET /copy` | `latest_page`, `copy_page` |
| 6 | フィードバック学習（修正履歴の蓄積） | `POST /feedback` | `save_feedback` |
| 7 | LINE 履歴アップロード解析→プロフィール生成 | `GET /upload`, `POST /analyze` | `upload_page`, `analyze_history` |
| 8 | 連絡先プロフィール管理 | `GET /contacts`, `POST /set_profile` | `contacts_page`, `set_profile` |
| 9 | ユーザー別カレンダー色設定 | `GET/POST /set-user-color` | `set_user_color_page`, `set_user_color` |
| 10 | Google リフレッシュトークン管理 | `GET/POST /save-token` | `save_token_*`, `get_google_access_token` |
| 11 | デバッグ系 | `GET /debug-auth`, `GET /test-ai`, `GET /` | — |

デプロイ基盤: `.github/workflows/deploy.yml`（main push で Cloud Run）, `setup/deploy.sh`,
`Dockerfile`, `render.yaml`。

## 動かし方 / チェック方法

```bash
pip install -r requirements.txt
# 必須 env: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY（.env.example 参照）
uvicorn main:app --host 0.0.0.0 --port 8080
```

- 構文チェック: `python -m py_compile main.py`
- 簡易疎通: `GET /`（稼働確認）, `GET /test-ai`（Claude 呼び出し確認）
- テストは現状なし。追加するなら `pytest` + httpx の `ASGITransport` でエンドポイント単体が書ける。

## レビューで重点的に見てほしい観点（ダブルチェックの軸）

1. **認証・公開範囲**: Cloud Run は `--allow-unauthenticated`。各エンドポイントが無認証で
   叩けてよいか。特に秘匿情報・個人情報・状態変更を伴うものは要注意。
2. **シークレット漏洩**: トークン・鍵・個人情報がレスポンスやログに出ていないか。
3. **入力の信頼性**: 外部から来る `message` / `filename` / クエリ文字列を HTML/JS に
   そのまま埋めていないか（XSS）。
4. **外部 API 失敗時の挙動**: Claude / Google / Supabase / ntfy のエラー・タイムアウト・
   ステータス未チェック箇所。
5. **時刻・日付ロジック**: `calc_end_time` の日跨ぎ、タイムゾーン、`extract_schedule` の
   JSON 抽出失敗。
6. **コスト/濫用**: 無認証エンドポイントから AI 呼び出しを誘発できる経路。

既知の指摘候補は `docs/CODEX_REVIEW_CHECKLIST.md` にまとめてある。Codex はそれを潰す形で
レビューすると効率がよい。

## ルール

- `main.py` の既存スタイル（コメントは日本語、httpx で REST 直叩き）に合わせる。
- シークレットをコード・コミットに含めない（`.env` は gitignore 済み）。
- 破壊的変更・大規模リファクタは事前に相談。
