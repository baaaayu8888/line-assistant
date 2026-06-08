from fastapi import FastAPI, UploadFile, File, Request, HTTPException
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

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
NTFY_CHANNEL = os.environ.get("NTFY_CHANNEL", "line-reply-default")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "nakashibakogyo@gmail.com")


async def ask_groq(prompt: str, max_tokens: int = 300, system: str = None) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    async with httpx.AsyncClient(timeout=30) as http:
        res = await http.post(
            GROQ_URL,
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"}
        )
        data = res.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise RuntimeError(f"Groq failed: status={res.status_code} body={json.dumps(data, ensure_ascii=False)[:500]} exc={e}")


async def get_google_access_token() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": GOOGLE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            }
        )
        data = res.json()
        if "access_token" not in data:
            raise RuntimeError(f"Google token error: {data.get('error')}: {data.get('error_description')} (status={res.status_code})")
        return data["access_token"]


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
    result = await ask_groq(prompt, max_tokens=10)
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
    result = await ask_groq(prompt, max_tokens=400)
    try:
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {}


async def register_calendar_event(schedule: dict) -> str:
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
        "colorId": "5",
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

        try:
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
                    end_time = await register_calendar_event(schedule)
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
                reply = await ask_groq(
                    f"以下のLINEメッセージに自然な短い返信を1文で:\n{message}"
                )
        except Exception as e:
            import traceback
            print(f"ERROR processing LINE message: {traceback.format_exc()}")
            reply = f"エラーが発生しました：{type(e).__name__}: {str(e)[:150]}"

        await send_line_reply(reply_token, reply)

    return {"status": "ok"}


@app.post("/webhook")
async def receive_message(request: Request):
    try:
        body = await request.body()
        data = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        data = {}
    sender = data.get("sender", "不明").strip()
    message = data.get("message", "").strip()

    if not message:
        message = "（メッセージ内容を取得できませんでした）"

    # プロフィール取得
    res = sb.table("contacts").select("profile").eq("name", sender).execute()
    profile = res.data[0]["profile"] if res.data else None

    # 直近の会話取得
    res = sb.table("conversations").select("their_message, actual_reply") \
        .eq("contact", sender).not_.is_("actual_reply", "null") \
        .order("timestamp", desc=True).limit(5).execute()
    recent = list(reversed(res.data)) if res.data else []

    # 修正履歴取得
    res = sb.table("corrections").select("suggested, corrected") \
        .eq("contact", sender).order("timestamp", desc=True).limit(3).execute()
    corrections = res.data if res.data else []

    # システムプロンプト構築
    system_parts = [
        "あなたは中芝悠太（ゆうだい）のLINE返信アシスタントです。",
        "悠太になりきって、自然でカジュアルな返信文を1つだけ生成してください。",
        "",
        "【返信ルール】",
        "- 返信文のみ出力。前置き・説明・「返信:」などの見出し・引用符は一切不要",
        "- タメ口・短文・テンポよく（1〜3文が理想）",
        "- 感情への共感を先に出し、解決策は後",
        "- 絵文字は相手のトーンに合わせて適度に使う",
        "- 長々と説明しない。LINEらしく簡潔に",
    ]
    if profile:
        system_parts += ["", f"【{sender}のプロフィール】", profile]
    else:
        system_parts += ["", f"【{sender}】との関係: 詳細不明。無難にタメ口で返す"]
    if corrections:
        system_parts.append("\n【過去の修正（この反省を活かす）】")
        for row in corrections:
            system_parts.append(f"- NG:「{row['suggested']}」→ OK:「{row['corrected']}」")
    system_prompt = "\n".join(system_parts)

    # ユーザープロンプト構築
    user_parts = []
    if recent:
        user_parts.append("【直近の会話の流れ】")
        for row in recent:
            user_parts.append(f"相手: {row['their_message']}")
            user_parts.append(f"自分: {row['actual_reply']}")
        user_parts.append("")
    user_parts.append(f"【{sender}からの今のメッセージ】")
    user_parts.append(message)
    user_prompt = "\n".join(user_parts)

    reply = await ask_groq(user_prompt, system=system_prompt)

    # 会話を保存
    res = sb.table("conversations").insert({
        "contact": sender,
        "their_message": message,
        "suggested_reply": reply,
        "timestamp": datetime.now().isoformat()
    }).execute()
    conv_id = res.data[0]["id"] if res.data else 0

    base_url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")
    encoded_reply = urllib.parse.quote(reply)

    async with httpx.AsyncClient(timeout=10) as http:
        await http.post(
            f"https://ntfy.sh/{NTFY_CHANNEL}",
            content=reply.encode("utf-8"),
            headers={
                "Title": f"{sender}への返信案".encode("utf-8"),
                "Tags": "speech_balloon",
                "Actions": f"view, Copy, {base_url}/copy?text={encoded_reply}&id={conv_id}".encode("utf-8")
            }
        )

    return {"status": "ok", "reply": reply, "conv_id": conv_id}


@app.get("/latest", response_class=HTMLResponse)
async def latest_page():
    res = sb.table("conversations").select("contact, their_message, suggested_reply, timestamp, id") \
        .order("timestamp", desc=True).limit(10).execute()
    rows = res.data if res.data else []

    cards = ""
    for row in rows:
        contact = row["contact"]
        their_msg = row["their_message"]
        reply = row["suggested_reply"]
        ts = row["timestamp"]
        conv_id = row["id"]
        escaped_reply = reply.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        encoded = urllib.parse.quote(reply)
        cards += f"""
<div class="card">
  <p class="meta">{ts[:16]} ／ <strong>{contact}</strong>「{their_msg[:30]}」</p>
  <div class="msg">{escaped_reply}</div>
  <a href="/copy?text={encoded}&id={conv_id}"><button>📋 コピーページへ</button></a>
</div>"""

    if not cards:
        cards = "<div class='card'><p>まだ返信案がありません</p></div>"

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>最新の返信案</title>
<style>
  body{{font-family:sans-serif;padding:16px;background:#f0f0f0;max-width:500px;margin:0 auto}}
  .card{{background:white;border-radius:16px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:12px}}
  .meta{{color:#999;font-size:12px;margin:0 0 8px}}
  .msg{{font-size:18px;line-height:1.6;color:#222;background:#e8f5e9;border-radius:12px;padding:12px;word-break:break-all}}
  button{{width:100%;padding:14px;font-size:16px;border:none;border-radius:12px;background:#06c755;color:white;cursor:pointer;margin-top:10px}}
  a{{text-decoration:none}}
  h2{{color:#333;margin:0 0 16px}}
</style>
</head>
<body>
<h2>💬 最新の返信案</h2>
<p style="color:#999;font-size:12px;margin:-8px 0 16px">30秒ごとに自動更新</p>
{cards}
</body></html>"""


@app.get("/copy", response_class=HTMLResponse)
async def copy_page(text: str = "", id: int = 0):
    escaped = text.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>返信案</title>
<style>
  body{{font-family:sans-serif;padding:20px;background:#f0f0f0;max-width:500px;margin:0 auto}}
  .card{{background:white;border-radius:16px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:16px}}
  .msg{{font-size:20px;line-height:1.6;margin:16px 0;color:#222;word-break:break-all;background:#e8f5e9;border-radius:12px;padding:16px}}
  button{{width:100%;padding:16px;font-size:18px;border:none;border-radius:12px;background:#06c755;color:white;cursor:pointer;margin:6px 0}}
  button.gray{{background:#aaa}}
  .done{{color:#06c755;font-weight:bold;display:none;text-align:center;margin-top:8px;font-size:16px}}
  textarea{{width:100%;box-sizing:border-box;padding:12px;font-size:16px;border:1px solid #ddd;border-radius:8px;margin-top:8px}}
  hr{{border:none;border-top:1px solid #eee;margin:16px 0}}
  p.hint{{color:#999;font-size:13px;margin:4px 0}}
</style>
</head>
<body>
<div class="card">
  <p style="color:#666;margin:0;font-size:14px">返信案</p>
  <div class="msg" id="msg">{escaped}</div>
  <button onclick="copyText()">📋 クリップボードにコピー</button>
  <p class="done" id="done">✅ コピーしました！LINEに貼り付けて送信してください</p>
  <hr>
  <p class="hint">修正して送った場合は記録できます（次回の返信が改善されます）</p>
  <textarea id="actual" placeholder="実際に送った内容..." rows="3"></textarea>
  <button class="gray" onclick="sendFeedback({id})">📝 修正内容を記録する</button>
  <p class="done" id="fb-done">✅ 記録しました！</p>
</div>
<script>
function copyText(){{
  navigator.clipboard.writeText(document.getElementById('msg').innerText)
    .then(()=>document.getElementById('done').style.display='block');
}}
async function sendFeedback(convId){{
  const actual=document.getElementById('actual').value.trim();
  if(!actual)return alert('内容を入力してください');
  await fetch('/feedback',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{conv_id:convId,actual_reply:actual}})}});
  document.getElementById('fb-done').style.display='block';
}}
</script>
</body></html>"""


@app.post("/feedback")
async def save_feedback(request: Request):
    data = await request.json()
    conv_id = data.get("conv_id")
    actual_reply = data.get("actual_reply", "").strip()

    res = sb.table("conversations").select("contact, suggested_reply").eq("id", conv_id).execute()
    if res.data:
        contact = res.data[0]["contact"]
        suggested = res.data[0]["suggested_reply"]
        sb.table("conversations").update({"actual_reply": actual_reply}).eq("id", conv_id).execute()
        if actual_reply and actual_reply != suggested:
            sb.table("corrections").insert({
                "contact": contact,
                "suggested": suggested,
                "corrected": actual_reply,
                "timestamp": datetime.now().isoformat()
            }).execute()
    return {"status": "ok"}


@app.get("/upload", response_class=HTMLResponse)
async def upload_page():
    return """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LINE履歴アップロード</title>
<style>
  body{font-family:sans-serif;padding:20px;background:#f0f0f0;max-width:600px;margin:0 auto}
  .card{background:white;border-radius:16px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:16px}
  button{width:100%;padding:16px;font-size:18px;border:none;border-radius:12px;background:#06c755;color:white;cursor:pointer;margin-top:12px}
  .profile-card{background:#f9f9f9;border-radius:8px;padding:16px;margin:8px 0;border-left:4px solid #06c755}
  input[type=file]{width:100%;padding:12px;box-sizing:border-box;font-size:16px}
</style>
</head>
<body>
<div class="card">
  <h2>📂 LINE履歴をアップロード</h2>
  <p>LINEの「トーク履歴を送信」で取り出した .txt ファイルを選んでください。複数まとめて選べます。</p>
  <input type="file" id="files" multiple accept=".txt">
  <button onclick="upload()">🔍 分析開始</button>
</div>
<div id="result"></div>
<script>
async function upload(){
  const files=document.getElementById('files').files;
  if(!files.length)return alert('ファイルを選択してください');
  const form=new FormData();
  for(const f of files)form.append('files',f);
  document.getElementById('result').innerHTML='<div class="card"><p>⏳ 分析中...</p></div>';
  const res=await fetch('/analyze',{method:'POST',body:form});
  const data=await res.json();
  let html='<div class="card"><h3>✅ 分析完了！</h3>';
  for(const item of data.analyzed)
    html+=`<div class="profile-card"><strong>${item.name}</strong><p>${item.profile}</p></div>`;
  html+='</div>';
  document.getElementById('result').innerHTML=html;
}
</script>
</body></html>"""


@app.post("/analyze")
async def analyze_history(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        content = await file.read()
        text = content.decode("utf-8", errors="ignore")

        filename = file.filename or ""
        name_match = re.search(r'\[LINE\]\s*(.+?)とのトーク', filename) or \
                     re.search(r'LINE_(.+?)のトーク', filename)
        contact_name = name_match.group(1).strip() if name_match else filename.replace(".txt", "").strip()

        # 全履歴から均等にサンプリング（冒頭・中間・最新）
        lines = text.splitlines()
        total = len(lines)
        if total <= 300:
            sample = text
        else:
            head = "\n".join(lines[:100])
            mid = "\n".join(lines[total // 2 - 50: total // 2 + 50])
            tail = "\n".join(lines[-100:])
            sample = f"{head}\n\n...(中略)...\n\n{mid}\n\n...(中略)...\n\n{tail}"

        prompt = f"""以下はLINEトーク履歴のサンプルです（冒頭・中間・最新を抜粋）。
この相手との関係性・口調・よく話す話題・絵文字の傾向・返信するときの注意点を分析し、
LINEの返信を考えるときに役立つ情報を5〜8文でまとめてください。

{sample[:6000]}

プロフィール文のみ出力してください。"""

        profile = await ask_groq(prompt)

        sb.table("contacts").upsert({"name": contact_name, "profile": profile}).execute()

        results.append({"name": contact_name, "profile": profile})

    return {"analyzed": results}


@app.post("/set_profile")
async def set_profile(request: Request):
    """Claude等が直接プロフィールを書き込む用エンドポイント"""
    data = await request.json()
    name = data.get("name", "").strip()
    profile = data.get("profile", "").strip()
    if not name or not profile:
        return {"status": "error", "message": "name と profile は必須"}
    sb.table("contacts").upsert({"name": name, "profile": profile}).execute()
    return {"status": "ok", "name": name}


@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page():
    res = sb.table("contacts").select("name, profile").order("name").execute()
    rows = res.data if res.data else []
    cards = ""
    for row in rows:
        name = row["name"].replace("<", "&lt;").replace(">", "&gt;")
        profile = (row["profile"] or "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        cards += f'<div class="card"><h3>{name}</h3><p>{profile}</p></div>'
    if not cards:
        cards = "<div class='card'><p>まだ登録なし</p></div>"
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>連絡先プロフィール</title>
<style>body{{font-family:sans-serif;padding:16px;background:#f0f0f0;max-width:600px;margin:0 auto}}
.card{{background:white;border-radius:16px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1);margin-bottom:12px}}
h3{{margin:0 0 8px;color:#333}}p{{color:#555;font-size:14px;line-height:1.6;margin:0}}</style>
</head><body><h2>👥 連絡先プロフィール</h2>{cards}</body></html>"""


@app.get("/")
async def root():
    return {"status": "✅ LINE返信アシスタント 稼働中", "ntfy_channel": NTFY_CHANNEL}
