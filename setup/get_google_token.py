#!/usr/bin/env python3
"""
Google Calendar OAuth2 リフレッシュトークン取得スクリプト

使い方:
  1. Google Cloud Console で OAuth2 クライアントID を作成（デスクトップアプリ）
  2. python3 setup/get_google_token.py
  3. 表示されたURLをブラウザで開いて認証
  4. 出力されたトークンを Cloud Run の環境変数に設定
"""

import json
import urllib.parse
import urllib.request
import webbrowser
import http.server
import threading

print("=== Google Calendar リフレッシュトークン取得 ===\n")
CLIENT_ID = input("Google OAuth2 Client ID: ").strip()
CLIENT_SECRET = input("Google OAuth2 Client Secret: ").strip()

REDIRECT_URI = "http://localhost:8888"
SCOPE = "https://www.googleapis.com/auth/calendar"

auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": SCOPE,
    "access_type": "offline",
    "prompt": "consent",
})

print(f"\n以下のURLをブラウザで開いてください:\n{auth_url}\n")
webbrowser.open(auth_url)

code = None

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global code
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write("<html><body><h1>認証完了！このタブを閉じてください。</h1></body></html>".encode())
    def log_message(self, *args):
        pass

server = http.server.HTTPServer(("localhost", 8888), Handler)
print("ブラウザでの認証を待機中...")
thread = threading.Thread(target=server.handle_request)
thread.start()
thread.join(timeout=120)

if not code:
    print("タイムアウト。手動でコードを入力してください:")
    code = input("認証コード: ").strip()

data = urllib.parse.urlencode({
    "code": code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
with urllib.request.urlopen(req) as res:
    tokens = json.loads(res.read())

refresh_token = tokens.get("refresh_token", "")
if not refresh_token:
    print("\n⚠️  リフレッシュトークンが取得できませんでした。")
    print("Google Cloud Console で既存の認証を削除してから再実行してください。")
else:
    print("\n✅ 取得成功！以下を Cloud Run の環境変数に設定してください:\n")
    print(f"GOOGLE_CLIENT_ID={CLIENT_ID}")
    print(f"GOOGLE_CLIENT_SECRET={CLIENT_SECRET}")
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
