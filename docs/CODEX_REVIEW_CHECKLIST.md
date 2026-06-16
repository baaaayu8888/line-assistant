# Codex ダブルチェック用チェックリスト & 先行レビュー

目的: 中芝悠太が作ってきた全システム（`main.py` 1 ファイルに同居）を Codex に
ダブルチェックさせるための、(A) システム別チェックリストと (B) Claude による先行レビュー結果。

Codex への渡し方（どれでも可）:
- このリポジトリ全体を Codex（CLI / クラウド）に渡し「`AGENTS.md` と本ファイルを読んで、
  各システムを順にレビューし、指摘を裏取りして修正案を出して」と指示。
- もしくは本ブランチの PR を OpenAI Codex の GitHub レビューに流す。

先行レビューは Claude による一次診断であり、確定不具合とは限らない。Codex 側で
**再現・裏取りしてから**対応すること（＝二重チェック）。

> **2026-06 更新**: 旧「LINE 自動返信アシスタント」機能（`/webhook`, `/latest`, `/copy`,
> `/feedback`, `/upload`, `/analyze`, `/set_profile`, `/contacts`, `/test-ai`, `/debug-auth`）は
> アーカイブ済みのため **削除済み**。それらに紐づく指摘（システム 2/5/6/7/8、🔴1/3 の一部、
> 🟡4/5）は **対象外**。現存は スケジュール Bot + `/save-token` + `/set-user-color` のみで、
> 管理エンドポイントは `ADMIN_TOKEN` ゲートで保護済み。
> **いま Codex に見てほしいのは下記の残課題**: 🔴2(save-token ゲートの妥当性) /
> 🟡6(calc_end_time 日跨ぎ) / 🟡7(HTTP ステータス未チェック) / ⚪8(設定残骸) /
> ⚪10(extract_schedule の貪欲マッチ) / `/set-user-color` ゲートの抜け道。

---

## A. システム別チェックリスト

### 1. LINE Bot 本体 `POST /line-webhook`
- [ ] 署名検証は `LINE_CHANNEL_SECRET` 未設定時にスキップされる。本番で必ず設定されているか。
- [ ] `events` ループ内で 1 件失敗しても他イベントを処理し続けるか（現状 try/except あり）。
- [ ] `reply_token` 空時の `send_line_reply` が安全か（早期 return あり）。
- [ ] 意図判定の誤分類（会話を schedule と誤認）時のユーザー影響。

### 2. MacroDroid 通知連携 `POST /webhook`
- [ ] 無認証で AI 呼び出し＋ntfy 送信を誘発できる（濫用・コスト）。制限の要否。
- [ ] `sender` / `message` をクエリ・ボディ両対応。優先順位は妥当か。
- [ ] ntfy トピックが推測可能だと第三者が返信案を購読できる（プライバシー）。

### 3. AI 返信生成 `ask_claude` / `detect_intent`
- [ ] `res.status_code` を見ずに `res.json()` している。429/5xx 時の挙動。
- [ ] リトライ・バックオフなし。一時障害でユーザーにエラー文が出る。
- [ ] プロンプトインジェクション（相手メッセージが system 指示を上書きしうる）。

### 4. 予定抽出→カレンダー登録
- [ ] `calc_end_time` の日跨ぎ（17時以降で `(h+2)%24` → 終了が開始より前になり得る）。
- [ ] `extract_schedule` の JSON 抽出失敗時は `{}` を返し、必須項目不足として弾けるか。
- [ ] タイムゾーン固定（+09:00）で問題ないか。

### 5. 返信案ビューア `GET /latest` / `GET /copy`
- [ ] `/latest` で `their_message` と `contact` が **未エスケープ**のまま HTML 挿入（XSS）。
- [ ] `/copy` の `text` クエリはエスケープ済みだが、全文公開 URL になる点（情報露出）。
- [ ] 無認証で全会話の返信案が閲覧できる。

### 6. フィードバック学習 `POST /feedback`
- [ ] `conv_id` の所有者チェックなし（任意 ID を更新可能）。
- [ ] `actual_reply != suggested` のときのみ corrections 追加。妥当か。

### 7. 履歴アップロード解析 `GET /upload` / `POST /analyze`
- [ ] 無認証でファイルアップロード＋AI 解析を誘発できる。
- [ ] ファイルサイズ・件数の上限なし（メモリ・コスト）。
- [ ] `decode(errors="ignore")` による文字化け・情報欠落。

### 8. 連絡先プロフィール `GET /contacts` / `POST /set_profile`
- [ ] `/contacts` が無認証で個人情報（プロフィール）を全公開。
- [ ] `/set_profile` が無認証で任意の `name`/`profile` を upsert 可能。

### 9. ユーザー色設定 `GET/POST /set-user-color`
- [ ] `__line_user_%` LIKE 検索でユーザー一覧を露出。
- [ ] 無認証で任意ユーザーの色を変更可能。

### 10. Google トークン管理 `GET/POST /save-token`
- [ ] **無認証で Google リフレッシュトークンを上書き可能**（カレンダー乗っ取り経路）。
- [ ] Supabase 優先・env フォールバックの順序が意図通りか。

### 11. デバッグ系 `GET /debug-auth` / `GET /test-ai`
- [ ] **`/debug-auth` が client_id / client_secret 先頭 / refresh_token 断片を無認証で露出**。
- [ ] `/test-ai` が無認証で AI 呼び出しを誘発。
- [ ] 本番でこれらを残す必要があるか（要削除 or 認証）。

### 横断 / 基盤
- [ ] Cloud Run `--allow-unauthenticated` 前提で、上記の公開範囲が許容できるか。
- [ ] `render.yaml` が `GEMINI_API_KEY`、`deploy.sh` が `GROQ_API_KEY` を要求＝**コードの
      `ANTHROPIC_API_KEY` と不整合**（過去の AI 乗り換えの残骸）。
- [ ] `requirements.txt` に未ピン留め（`supabase>=2.15.0`）。再現性。
- [ ] テスト・CI のレビュー工程なし（lint/型/テスト）。

---

## B. Claude 先行レビュー（一次診断 / Codex が裏取りする前提）

深刻度の目安: 🔴 高 / 🟡 中 / ⚪ 低。行番号は当時の `main.py`。

> **対応状況**: 🔴 1〜3 は本ブランチで修正済み（`ADMIN_TOKEN` ゲート導入 + `/debug-auth` 削除）。
> Codex は修正が妥当か（ゲートの抜け道・fail-closed の挙動）を裏取りすること。🟡⚪ は未対応。

### 🔴 1. `/debug-auth` が認証情報を無認証で露出（main.py:746-765）→ ✅ 削除済み
client_id・client_secret 先頭・refresh_token の断片を誰でも GET で取得できる。攻撃者の
当たり付けに使える。→ 本番から削除、または管理者トークン必須化。

### 🔴 2. `/save-token` が無認証で Google トークンを上書き可能（main.py:668-678）→ ✅ ADMIN_TOKEN 必須化
第三者が自分の refresh_token を POST すると、以降のカレンダー登録が攻撃者アカウントに
向く／正規トークンを破壊できる。→ シークレット/管理キー必須化。

### 🔴 3. 個人情報・会話の無認証公開（`/contacts` 606, `/latest` 393, `/copy` 442）→ ✅ ADMIN_TOKEN ゲート
取引先・友人のプロフィールや返信案が URL を知れば誰でも閲覧可能。→ 認証 or 推測困難な
トークン付き URL に。

### 🟡 4. `/latest` の格納型 XSS（main.py:406-413）
`reply` はエスケープしているが `their_message`（`their_msg[:30]`）と `contact` は素のまま
HTML に挿入。LINE 相手が送った文面に `<script>` 等が混ざると実行され得る。→ 全変数を
エスケープ（既存の escape ロジックを共通化）。

### 🟡 5. 無認証エンドポイントからの AI/外部呼び出し誘発（`/webhook` 275, `/analyze` 554, `/test-ai` 768）
署名なしで Claude 呼び出し・ファイル解析・ntfy 送信をトリガーできる＝コスト濫用。→
共有シークレット or レート制限。

### 🟡 6. `calc_end_time` の日跨ぎ破綻（main.py:106-115）
開始 17 時以降で `{(h+2)%24:02d}` を返すため、例えば 23:00 開始だと終了 01:00。イベントは
同一 `date` を使うので `end < start` となり Calendar API が弾く可能性。→ 終了が翌日に
なるケースを date ごと補正。

### 🟡 7. HTTP ステータス未チェックで `res.json()`（`ask_claude` 49, `get_line_display_name` 91 ほか）
非 200 時に想定外の本文を JSON 解釈し、わかりにくいエラーに。`ask_claude` は最終的に
RuntimeError 化されるが、429/5xx のリトライがない。→ ステータス確認＋簡易リトライ。

### ⚪ 8. 設定の不整合（残骸）
- `render.yaml`: `GEMINI_API_KEY`（コードは Anthropic）
- `setup/deploy.sh` / `.env.example`: `GROQ_API_KEY`（コードは Anthropic）
過去の AI 乗り換え（Groq→Gemini→Groq→Claude）の名残。→ 実際に使う `ANTHROPIC_API_KEY`
に統一。

### ⚪ 9. ハードコード値（main.py:17, 28, 375）
`NTFY_CHANNEL`、`CALENDAR_ID` デフォルト、`BASE_URL` デフォルトがコード直書き。→ env 化。

### ⚪ 10. `extract_schedule` の貪欲マッチ（main.py:149）
`\{.*\}` + DOTALL は複数オブジェクト時に広く取りすぎる可能性。単一 JSON 前提なら可。

---

## 進め方メモ
1. Codex に本ファイル B を 1 件ずつ裏取りさせ、再現するものだけ修正 PR を出させる。
2. 🔴 を最優先（公開範囲とシークレット）。
3. 修正後、`AGENTS.md` の「動かし方」で疎通確認。
