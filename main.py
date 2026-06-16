from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import httpx
import json
import os
import re
import urllib.parse
import hmac
import hashlib
import base64
from datetime import datetime
from supabase import create_client, Client

app = FastAPI()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "nakashibakogyo@gmail.com")

# 管理用エンドポイントのアクセスゲート。
# 認証情報・設定を扱うページ/APIは ADMIN_TOKEN を要求する（未設定なら常に拒否＝fail-closed）。
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def require_admin(request: Request, key: str = ""):
    """key クエリ or X-Admin-Token ヘッダが ADMIN_TOKEN と一致しなければ 401。"""
    provided = key or request.headers.get("X-Admin-Token", "")
    if not (ADMIN_TOKEN and hmac.compare_digest(provided, ADMIN_TOKEN)):
        raise HTTPException(status_code=401, detail="unauthorized")


async def ask_claude(prompt: str, max_tokens: int = 300, system: str = None) -> str:
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=30) as http:
        res = await http.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        )
        data = res.json()
    try:
        return data["content"][0]["text"].strip()
    except Exception as e:
        raise RuntimeError(f"Claude failed: status={res.status_code} body={json.dumps(data, ensure_ascii=False)[:500]} exc={e}")


async def get_google_access_token() -> str:
    # Supabaseに保存されたトークンを優先（/save-token で更新可能）
    refresh_token = GOOGLE_REFRESH_TOKEN
    try:
        res = sb.table("contacts").select("profile").eq("name", "__google_refresh_token__").execute()
        if res.data and res.data[0]["profile"]:
            refresh_token = res.data[0]["profile"]
    except Exception:
        pass

    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        )
        data = res.json()
        if "access_token" not in data:
            raise RuntimeError(f"Google token error: {data.get('error')}: {data.get('error_description')} (status={res.status_code})")
        return data["access_token"]


async def get_line_display_name(user_id: str) -> str:
    if not LINE_CHANNEL_ACCESS_TOKEN or not user_id:
        return user_id
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(
                f"https://api.line.me/v2/bot/profile/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
            )
            return res.json().get("displayName", user_id)
    except Exception:
        return user_id


async def get_calendar_color(user_id: str) -> str:
    try:
        res = sb.table("contacts").select("profile").eq("name", f"__line_color_{user_id}__").execute()
        if res.data and res.data[0]["profile"]:
            return res.data[0]["profile"]
    except Exception:
        pass
    return "5"  # デフォルト: 黄色（悠太）


def calc_end_time(start_time: str) -> str:
    h, m = map(int, start_time.split(":"))
    if h < 12:
        return "12:00"
    elif h < 15:
        return "15:00"
    elif h < 17:
        return "17:00"
    else:
        return f"{(h + 2) % 24:02d}:{m:02d}"


async def detect_intent(message: str) -> str:
    prompt = f"""以下のLINEメッセージは「スケジュール登録依頼」か「通常の会話返信」のどちらですか？

スケジュール登録依頼の特徴：日付・時間・会社名・作業内容が含まれる施工依頼

メッセージ：{message}

「schedule」または「reply」の1単語のみで答えてください。"""
    result = await ask_claude(prompt, max_tokens=10)
    return "schedule" if "schedule" in result.lower() else "reply"


async def extract_schedule(message: str) -> dict:
    today = datetime.now().strftime("%Y年%m月%d日")
    prompt = f"""今日は{today}です。以下のメッセージから施工スケジュール情報を抽出してください。

メッセージ：{message}

以下のJSON形式のみで返してください（不明な項目はnull）：
{{
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "company": "会社名（株式会社等の法人格表記なし）",
  "person": "担当者名（なければnull）",
  "work": "作業内容",
  "location": "場所（市区町村レベル）",
  "map_url": "GoogleマップURL（あれば）",
  "notes": "注意事項（あれば）"
}}"""
    result = await ask_claude(prompt, max_tokens=400)
    try:
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {}


async def register_calendar_event(schedule: dict, color_id: str = "5") -> str:
    access_token = await get_google_access_token()

    date = schedule["date"]
    start_time = schedule["start_time"]
    end_time = calc_end_time(start_time)

    title = schedule.get("company", "不明")
    if schedule.get("person"):
        title += schedule["person"]

    desc_parts = [p for p in [
        schedule.get("work"),
        schedule.get("notes"),
        schedule.get("map_url"),
    ] if p]

    event_body = {
        "summary": title,
        "location": schedule.get("location", ""),
        "description": "\n".join(desc_parts),
        "start": {"dateTime": f"{date}T{start_time}:00+09:00", "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": f"{date}T{end_time}:00+09:00", "timeZone": "Asia/Tokyo"},
        "colorId": color_id,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(CALENDAR_ID)}/events",
            json=event_body,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if res.status_code not in (200, 201):
            raise RuntimeError(f"Calendar API error: status={res.status_code} body={res.text[:300]}")
    return end_time


async def send_line_reply(reply_token: str, text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN or not reply_token:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            "https://api.line.me/v2/bot/message/reply",
            json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        )


@app.post("/line-webhook")
async def line_webhook(request: Request):
    body = await request.body()

    if LINE_CHANNEL_SECRET:
        signature = request.headers.get("X-Line-Signature", "")
        mac = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256)
        expected = base64.b64encode(mac.digest()).decode("utf-8")
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event.get("message", {}).get("type") != "text":
            continue

        message = event["message"]["text"].strip()
        reply_token = event.get("replyToken", "")
        user_id = event.get("source", {}).get("userId", "")

        try:
            # ユーザー情報を保存（色設定ページで表示するため）
            if user_id:
                display_name = await get_line_display_name(user_id)
                try:
                    sb.table("contacts").upsert({"name": f"__line_user_{user_id}__", "profile": display_name}).execute()
                except Exception:
                    pass

            color_id = await get_calendar_color(user_id)
            intent = await detect_intent(message)

            if intent == "schedule":
                schedule = await extract_schedule(message)
                missing = [label for label, val in [
                    ("日付", schedule.get("date")),
                    ("時間", schedule.get("start_time")),
                    ("会社名または作業内容", schedule.get("company") or schedule.get("work")),
                ] if not val]

                if missing:
                    reply = f"以下の情報が不足しています：{' / '.join(missing)}\nもう一度送ってください。"
                else:
                    end_time = await register_calendar_event(schedule, color_id)
                    title = schedule.get("company", "")
                    if schedule.get("person"):
                        title += schedule["person"]
                    reply = "\n".join(filter(None, [
                        "✅ 登録しました！",
                        f"{schedule['date']}  {schedule['start_time']}〜{end_time}",
                        title,
                        schedule.get("location", ""),
                    ]))
            else:
                reply = "予定として登録する場合は、日付・時間・会社名（または作業内容）を含めて送ってください。"
        except Exception as e:
            import traceback
            print(f"ERROR processing LINE message: {traceback.format_exc()}")
            reply = f"エラーが発生しました：{type(e).__name__}: {str(e)[:150]}"

        await send_line_reply(reply_token, reply)

    return {"status": "ok"}


@app.get("/save-token", response_class=HTMLResponse)
async def save_token_page(request: Request, key: str = ""):
    require_admin(request, key)
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Googleトークン更新</title>
<style>
  body{font-family:sans-serif;padding:20px;background:#f0f0f0;max-width:500px;margin:0 auto}
  .card{background:white;border-radius:16px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.1)}
  textarea{width:100%;box-sizing:border-box;padding:12px;font-size:14px;border:1px solid #ddd;border-radius:8px;margin:12px 0;height:100px;font-family:monospace}
  button{width:100%;padding:16px;font-size:18px;border:none;border-radius:12px;background:#4285f4;color:white;cursor:pointer;margin-top:4px}
  .done{color:#06c755;font-weight:bold;display:none;text-align:center;margin-top:12px;font-size:16px}
  p{color:#555;font-size:14px;line-height:1.6}
</style>
</head>
<body>
<div class="card">
  <h2>🔑 Googleカレンダー トークン更新</h2>
  <p>① <a href="https://developers.google.com/oauthplayground" target="_blank">OAuth2 Playground</a> を開く<br>
  ② 歯車アイコン → 「Use your own OAuth credentials」にチェック → Client ID・Secret入力<br>
  ③ スコープ: <code>https://www.googleapis.com/auth/calendar</code> を選択 → Authorize APIs<br>
  ④ Step 2: Exchange authorization code for tokens<br>
  ⑤ <strong>Refresh token</strong> をコピーして下に貼り付け</p>
  <textarea id="token" placeholder="1//04..."></textarea>
  <button onclick="save()">💾 保存する</button>
  <p class="done" id="done">✅ 保存しました！カレンダー登録が使えるようになりました。</p>
</div>
<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
async function save(){
  const token = document.getElementById('token').value.trim();
  if(!token) return alert('トークンを入力してください');
  const res = await fetch('/save-token', {method:'POST', headers:{'Content-Type':'application/json','X-Admin-Token':KEY}, body: JSON.stringify({token})});
  const data = await res.json();
  if(data.status === 'ok') document.getElementById('done').style.display = 'block';
  else alert('エラー: ' + (data.message || '不明'));
}
</script>
</body></html>"""


@app.post("/save-token")
async def save_token_api(request: Request):
    require_admin(request)
    data = await request.json()
    token = data.get("token", "").strip()
    if not token:
        return {"status": "error", "message": "token is required"}
    try:
        sb.table("contacts").upsert({"name": "__google_refresh_token__", "profile": token}).execute()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/set-user-color", response_class=HTMLResponse)
async def set_user_color_page(request: Request, key: str = ""):
    require_admin(request, key)
    # LINEユーザー一覧を取得
    try:
        res = sb.table("contacts").select("name, profile").like("name", "__line_user_%").execute()
        users = [{"user_id": r["name"].replace("__line_user_", "").replace("__", ""), "display_name": r["profile"]} for r in (res.data or [])]
        # 各ユーザーの現在の色を取得
        for u in users:
            cr = sb.table("contacts").select("profile").eq("name", f"__line_color_{u['user_id']}__").execute()
            u["color"] = cr.data[0]["profile"] if cr.data else "5"
    except Exception:
        users = []

    color_options = [
        ("1", "ラベンダー"), ("2", "セージ"), ("3", "グレープ"), ("4", "フラミンゴ"),
        ("5", "バナナ（黄・悠太）"), ("6", "タンジェリン"), ("7", "ピーコック"),
        ("8", "グラファイト（グレー）"), ("9", "ブルーベリー（青）"), ("10", "バジル"),
        ("11", "トマト（赤・英三）"),
    ]

    rows = ""
    for u in users:
        opts = "".join(f'<option value="{v}" {"selected" if v == u["color"] else ""}>{label}</option>' for v, label in color_options)
        rows += f"""
<div class="card">
  <p><strong>{u['display_name']}</strong></p>
  <select id="color_{u['user_id']}">{opts}</select>
  <button onclick="save('{u['user_id']}')">保存</button>
  <span id="done_{u['user_id']}" style="color:#06c755;display:none">✅</span>
</div>"""

    if not rows:
        rows = "<div class='card'><p>まだメッセージを送ったユーザーがいません</p></div>"

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ユーザー色設定</title>
<style>body{{font-family:sans-serif;padding:16px;background:#f0f0f0;max-width:500px;margin:0 auto}}
.card{{background:white;border-radius:16px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:12px}}
select{{width:100%;padding:10px;font-size:15px;border:1px solid #ddd;border-radius:8px;margin:8px 0}}
button{{width:100%;padding:12px;font-size:16px;border:none;border-radius:12px;background:#06c755;color:white;cursor:pointer}}</style>
</head><body>
<h2>🎨 カレンダー色設定</h2>
<p style="color:#999;font-size:13px">LINEでメッセージを送ったユーザーに色を割り当てます</p>
{rows}
<script>
const KEY = new URLSearchParams(location.search).get('key') || '';
async function save(userId){{
  const color = document.getElementById('color_' + userId).value;
  await fetch('/set-user-color', {{method:'POST', headers:{{'Content-Type':'application/json','X-Admin-Token':KEY}}, body:JSON.stringify({{user_id:userId, color}})}});
  document.getElementById('done_' + userId).style.display = 'inline';
}}
</script></body></html>"""


@app.post("/set-user-color")
async def set_user_color(request: Request):
    require_admin(request)
    data = await request.json()
    user_id = data.get("user_id", "").strip()
    color = data.get("color", "5").strip()
    if not user_id:
        return {"status": "error"}
    sb.table("contacts").upsert({"name": f"__line_color_{user_id}__", "profile": color}).execute()
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"status": "✅ スケジュール登録Bot 稼働中"}
