from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
import sqlite3
import httpx
import os
import re
import urllib.parse
from datetime import datetime

app = FastAPI()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
NTFY_CHANNEL = os.environ.get("NTFY_CHANNEL", "line-reply-default")
DB_PATH = "/data/line_assistant.db" if os.path.exists("/data") else "line_assistant.db"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"


async def ask_gemini(prompt: str) -> str:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 300}
    }
    async with httpx.AsyncClient(timeout=30) as http:
        res = await http.post(GEMINI_URL, json=payload)
        data = res.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return "（返信の生成に失敗しました）"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            name TEXT PRIMARY KEY,
            profile TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact TEXT,
            their_message TEXT,
            suggested_reply TEXT,
            actual_reply TEXT,
            timestamp TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact TEXT,
            suggested TEXT,
            corrected TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()


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

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT profile FROM contacts WHERE name = ?", (sender,))
    row = c.fetchone()
    profile = row[0] if row else "（履歴なし）"

    c.execute("""
        SELECT their_message, actual_reply FROM conversations
        WHERE contact = ? AND actual_reply IS NOT NULL
        ORDER BY timestamp DESC LIMIT 5
    """, (sender,))
    recent = list(reversed(c.fetchall()))

    c.execute("""
        SELECT suggested, corrected FROM corrections
        WHERE contact = ? ORDER BY timestamp DESC LIMIT 3
    """, (sender,))
    corrections = c.fetchall()
    conn.close()

    recent_text = ""
    if recent:
        recent_text = "\n\n【直近の会話】\n"
        for their_msg, my_reply in recent:
            recent_text += f"相手: {their_msg}\n自分: {my_reply}\n"

    correction_text = ""
    if corrections:
        correction_text = "\n\n【過去の修正から学んだこと】\n"
        for sugg, corr in corrections:
            correction_text += f"・「{sugg}」→「{corr}」に直された\n"

    prompt = f"""あなたはLINEの返信アシスタントです。
以下の情報をもとに、自然なLINE返信文を1つだけ生成してください。

【送信者】{sender}
【関係性・口調の特徴】{profile}
{correction_text}{recent_text}
【届いたメッセージ】{message}

返信文のみ出力してください。前置き・説明・引用符は不要です。"""

    reply = await ask_gemini(prompt)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO conversations (contact, their_message, suggested_reply, timestamp)
        VALUES (?, ?, ?, ?)
    """, (sender, message, reply, datetime.now().isoformat()))
    conv_id = c.lastrowid
    conn.commit()
    conn.close()

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

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT contact, suggested_reply FROM conversations WHERE id = ?", (conv_id,))
    row = c.fetchone()
    if row:
        contact, suggested = row
        c.execute("UPDATE conversations SET actual_reply = ? WHERE id = ?", (actual_reply, conv_id))
        if actual_reply and actual_reply != suggested:
            c.execute("""
                INSERT INTO corrections (contact, suggested, corrected, timestamp)
                VALUES (?, ?, ?, ?)
            """, (contact, suggested, actual_reply, datetime.now().isoformat()))
    conn.commit()
    conn.close()
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

        prompt = f"""以下はLINEトーク履歴です。この相手との関係性・口調・よく話す話題・絵文字の傾向を分析し、
LINEの返信を考えるときに役立つ情報を3〜5文でまとめてください。

{text[:5000]}

プロフィール文のみ出力してください。"""

        profile = await ask_gemini(prompt)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO contacts (name, profile) VALUES (?, ?)", (contact_name, profile))
        conn.commit()
        conn.close()

        results.append({"name": contact_name, "profile": profile})

    return {"analyzed": results}


@app.get("/")
async def root():
    return {"status": "✅ LINE返信アシスタント 稼働中", "ntfy_channel": NTFY_CHANNEL}
