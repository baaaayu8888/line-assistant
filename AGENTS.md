# AGENTS.md — line-assistant

このファイルは Codex / Claude などの AI エージェントが本リポジトリをレビュー・改修するときに
最初に読むガイドです。「全システムを Codex のダブルチェックに回す」ための起点として用意しています。

## このプロジェクトは何か

中芝悠太（大阪・施工業）向けの個人用ツール。FastAPI 1 ファイル（`main.py`）で動く
**スケジュール登録 Bot**。LINE に施工予定を送ると、内容を抽出して Google カレンダーに
色分け登録する。Cloud Run（本番）で稼働。

> 旧「LINE 自動返信アシスタント」機能（MacroDroid→ntfy→コピーの返信案生成、履歴解析、
> 連絡先プロフィール等）はアーカイブ済みのため **2026-06 に削除**した。現存するのは
> スケジュール系のみ。

- 本番 URL: `https://line-assistant-ncpnpxg3hq-an.a.run.app`
- 言語/FW: Python 3.11 / FastAPI / httpx（同期 SDK は使わず REST 直叩き）
- データ: Supabase（`contacts` テーブルにトークン・色設定・LINE ユーザー名を保存）
- AI: Anthropic Claude Haiku（`claude-haiku-4-5-20251001`）を REST で呼び出し

## システム（機能）一覧

| # | システム | 入口 | 主な関数 |
|---|---------|------|---------|
| 1 | スケジュール Bot（LINE 受信→予定抽出→カレンダー登録） | `POST /line-webhook` | `line_webhook`, `detect_intent`, `extract_schedule`, `register_calendar_event`, `calc_end_time` |
| 2 | AI 抽出基盤（意図判定・予定抽出） | — | `ask_claude` |
| 3 | Google リフレッシュトークン管理（要 ADMIN_TOKEN） | `GET/POST /save-token` | `save_token_*`, `get_google_access_token` |
| 4 | ユーザー別カレンダー色設定（要 ADMIN_TOKEN） | `GET/POST /set-user-color` | `set_user_color_*`, `get_calendar_color` |
| 5 | 稼働確認 | `GET /` | `root` |

管理用エンドポイント（`/save-token`, `/set-user-color`）は `ADMIN_TOKEN` ゲートで保護。
`?key=<ADMIN_TOKEN>` を付けて開く。未設定時は fail-closed（常に 401）。

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
