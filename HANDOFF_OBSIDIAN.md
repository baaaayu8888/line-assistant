# 引き継ぎ資料：Obsidian 取引先データ登録タスク

作成日: 2026-06-10  
対象セッション: Obsidian連携専用

---

## 背景・経緯

父親（中芝英三）のiPhoneの連絡先VCFファイルから、取引先の締め日・インボイス番号・住所・電話番号を抽出した。合計50社分。

抽出した情報は `取引先.md` としてGoogle Driveに保存済みだが、**ローカルのObsidianアプリに反映されていない**。

このタスクはObsidianへの正しい保存方法を確立し、データを適切に登録すること。

---

## 現状

### 保存済みファイル（Google Drive）

| ファイル名 | Google Drive ファイルID | 状況 |
|---|---|---|
| `取引先.md` | `1JCMTI4GpRWpAd3yVyi9BNPO6XiOPQWw3` | 作成済み・Obsidianに未反映 |
| `顧客情報_締め日一覧` | `155yF1hvep00tm8s12X7WHygPzatGYI8o` | 作成済み（締め日別整理・旧フォーマット）|

### Obsidianフォルダ（Google Drive）

前回セッションでファイルを保存したGoogle Driveフォルダ:
- フォルダID: `1SbhGODm-jIPbwFoJBp8EwrlFZyBcP0AY`
- 既存ファイル: `calendar-color-rules.md`, `calendar-event-format.md`, `mistakes.md`, `cloud-run-setup-progress.md`

**問題**: このフォルダに `取引先.md` を保存したが、ユーザーのローカルObsidianアプリに表示されない。
- 考えられる原因: Obsidianのvaultがこのフォルダと同期していない / フォルダ階層が違う / 同期遅延

---

## タスク

### 確認事項

1. ユーザーのObsidian vaultがどのGoogle Driveフォルダと同期しているか確認する  
   （上記フォルダID `1SbhGODm-jIPbwFoJBp8EwrlFZyBcP0AY` で合っているか？）

2. `取引先.md` が正しい場所に保存されているか確認する

3. もしフォルダが違うなら、正しいフォルダに移動 or 再作成する

### データの内容

`取引先.md`（ファイルID: `1JCMTI4GpRWpAd3yVyi9BNPO6XiOPQWw3`）をMCPツールでダウンロード・確認できる。

フォーマット例:
```markdown
## ㍿アシスト
- **締め日**: 15日　末日締め払い
- **インボイス番号**: T2-1200-0100-9118
- TEL: 06-6702-0473 / FAX: 06-6703-5670
- 住所: 大阪市住吉区長居南4丁目8-22
```

全50社の取引先情報が含まれている。

---

## 利用できるツール

- **Google Drive MCPツール**: `mcp__f180904f-8e41-4fdf-935d-b28ad2d1a887__*`
  - `search_files`: フォルダ検索
  - `list_recent_files`: ファイル一覧
  - `read_file_content` / `download_file_content`: ファイル読み取り
  - `create_file`: 新規ファイル作成

---

## 注意事項

- このCloud Run環境からはローカルのObsidianアプリに直接アクセス不可
- アクセスできるのはGoogle DriveのMCPツール経由のみ
- Obsidianがどのフォルダを同期しているか、ユーザーに確認する必要があるかもしれない

---

## 関連プロジェクト情報

- リポジトリ: `baaaayu8888/line-assistant`
- 開発ブランチ: `claude/schedule-registration-automation-ccZbP`
- Cloud Run URL: `https://line-assistant-ncpnpxg3hq-an.a.run.app`
- ユーザー: 中芝悠太（baaaayu.10969er@gmail.com）
