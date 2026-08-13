import os
import io
import re
import json
import time
import random
import string
import urllib.parse
import hashlib
import base64
import datetime
import sqlite3
import zipfile
import threading
from pathlib import PurePosixPath

import requests
from flask import Flask, render_template_string, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from gtts import gTTS
import qrcode

# ============================================================
# NEXORA | Telegram + Flask + GitHub Pages + Gemini
# Render-friendly version: Telegram WEBHOOK (no infinity_polling)
# ============================================================

DEVELOPER_NAME = "المطور الجبوري"
DEVELOPER_RIGHTS = "\n\n👑 تطوير: المطور الجبوري"

# ------------------------------------------------------------
# Secrets: PUT THESE IN RENDER ENVIRONMENT VARIABLES
# ------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_USER = os.environ.get("GITHUB_USER", "akoasad7-arch").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "my-sites").strip()

# Render automatically provides this for a web service.
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))

# Secret path for Telegram webhook.
# Set WEBHOOK_SECRET in Render to a long random string.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
if not WEBHOOK_SECRET:
    WEBHOOK_SECRET = hashlib.sha256(
        (BOT_TOKEN or "nexora-webhook").encode("utf-8")
    ).hexdigest()[:32]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN in Render Environment.")

app = Flask(__name__)
bot = telebot.TeleBot("8638334231:AAEZr_3sZ3jbQKg_Syq04CgOnXDWvbTWLdg", parse_mode="Markdown")


user_states = {}
pending_codes = {}

# ============================================================
# Database
# ============================================================

DB_NAME = "bot_database.db"
DB_LOCK = threading.Lock()


def db_connect():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    return conn


def init_db():
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                joined_at TEXT,
                req_count INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                tool_name TEXT,
                created_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                filename TEXT,
                url TEXT,
                sha TEXT,
                created_at TEXT
            )
        """)

        conn.commit()
        conn.close()


def register_user(user_id, first_name, username):
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT OR IGNORE INTO users
            (user_id, first_name, username, joined_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, first_name or "مستخدم", username or "لا يوجد", now),
        )

        cursor.execute(
            "UPDATE users SET req_count = req_count + 1 WHERE user_id = ?",
            (user_id,),
        )

        conn.commit()
        conn.close()


def log_activity(user_id, tool_name):
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO activity_log (user_id, tool_name, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, tool_name, now),
        )

        conn.commit()
        conn.close()


def save_ai_message(user_id, role, content):
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            INSERT INTO ai_history
            (user_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, role, content, now),
        )

        conn.commit()
        conn.close()


def get_user_ai_history(user_id, limit=6):
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT role, content
        FROM ai_history
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )

    rows = cursor.fetchall()
    conn.close()

    return [{"role": r[0], "text": r[1]} for r in reversed(rows)]


def clear_user_ai_history(user_id):
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM ai_history WHERE user_id = ?",
            (user_id,),
        )

        conn.commit()
        conn.close()


def add_user_site(user_id, filename, url, sha):
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        cursor.execute(
            """
            INSERT INTO user_sites
            (user_id, filename, url, sha, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, filename, url, sha or "", now),
        )

        conn.commit()
        conn.close()


def remove_user_site(user_id, filename):
    with DB_LOCK:
        conn = db_connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM user_sites
            WHERE user_id = ? AND filename = ?
            """,
            (user_id, filename),
        )

        conn.commit()
        conn.close()


def get_user_sites(user_id):
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT filename, url, sha, created_at
        FROM user_sites
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,),
    )

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "filename": r[0],
            "url": r[1],
            "sha": r[2],
            "date": r[3],
        }
        for r in rows
    ]


def get_global_stats():
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM user_sites")
    sites_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ai_history")
    ai_count = cursor.fetchone()[0]

    conn.close()
    return users_count, sites_count, ai_count


init_db()

# ============================================================
# GitHub publishing
# ============================================================

def generate_random_name(length=6):
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=length)
    )


def sanitize_filename(name):
    name = str(name or "").strip()
    name = name.replace(" ", "-")
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    return name if name else f"site_{generate_random_name()}"


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def publish_file_to_github(filename, content_bytes):
    if not GITHUB_TOKEN or len(GITHUB_TOKEN) < 10:
        return None, None, "GITHUB_TOKEN غير مضبوط في Render."

    filename = filename.lstrip("/")
    api_url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    )

    try:
        headers = github_headers()

        get_res = requests.get(
            api_url,
            headers=headers,
            timeout=20,
        )

        sha = None
        if get_res.status_code == 200:
            sha = get_res.json().get("sha")

        encoded_content = base64.b64encode(content_bytes).decode("utf-8")

        data = {
            "message": f"Publish {filename} via NEXORA",
            "content": encoded_content,
        }

        if sha:
            data["sha"] = sha

        response = requests.put(
            api_url,
            json=data,
            headers=headers,
            timeout=30,
        )

        if response.status_code in (200, 201):
            result = response.json()
            new_sha = result.get("content", {}).get("sha", "")

            live_url = (
                f"https://{GITHUB_USER}.github.io/"
                f"{GITHUB_REPO}/{filename}"
            )

            return live_url, new_sha, None

        try:
            error_msg = response.json().get(
                "message",
                "خطأ من GitHub",
            )
        except Exception:
            error_msg = response.text[:500]

        return (
            None,
            None,
            f"فشل النشر ({response.status_code}): {error_msg}",
        )

    except Exception as e:
        return None, None, f"خطأ اتصال GitHub: {e}"


def safe_zip_path(name):
    """
    Prevent ../ traversal when extracting ZIP entries.
    Returns a normalized POSIX path or None.
    """
    name = name.replace("\\", "/").lstrip("/")
    p = PurePosixPath(name)

    if any(part in ("", ".", "..") for part in p.parts):
        return None

    return "/".join(p.parts)


def delete_from_github(filename, sha=None):
    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN غير مضبوط."

    api_url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    )

    try:
        headers = github_headers()

        if not sha:
            get_res = requests.get(
                api_url,
                headers=headers,
                timeout=20,
            )

            if get_res.status_code != 200:
                return False, "الملف غير موجود على GitHub."

            sha = get_res.json().get("sha")

        data = {
            "message": f"Delete {filename} via NEXORA",
            "sha": sha,
        }

        response = requests.delete(
            api_url,
            json=data,
            headers=headers,
            timeout=20,
        )

        if response.status_code == 200:
            return True, "تم الحذف بنجاح"

        return False, f"فشل الحذف: {response.text[:500]}"

    except Exception as e:
        return False, f"خطأ اتصال GitHub: {e}"


# ============================================================
# Gemini
# ============================================================

def process_ai_chat(user_id, prompt):
    history = get_user_ai_history(user_id, limit=6)

    if GEMINI_API_KEY:
        try:
            url = (
                "https://generativelanguage.googleapis.com/"
                "v1beta/models/gemini-2.5-flash:generateContent"
            )

            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY,
            }

            contents = []

            for item in history:
                role = (
                    "model"
                    if item["role"] in ("model", "assistant")
                    else "user"
                )

                contents.append(
                    {
                        "role": role,
                        "parts": [{"text": item["text"]}],
                    }
                )

            contents.append(
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            )

            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.7,
                },
            }

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()

                candidates = data.get("candidates", [])

                if candidates:
                    parts = (
                        candidates[0]
                        .get("content", {})
                        .get("parts", [])
                    )

                    if parts and parts[0].get("text"):
                        answer = parts[0]["text"]

                        save_ai_message(
                            user_id,
                            "user",
                            prompt,
                        )
                        save_ai_message(
                            user_id,
                            "model",
                            answer,
                        )

                        return answer

            print(
                "Gemini HTTP error:",
                response.status_code,
                response.text[:500],
            )

        except Exception as e:
            print("Gemini API error:", e)

    # Fallback
    try:
        sys_context = (
            "أنت مساعد ذكي ومحترف. "
            "أجب باللغة العربية بوضوح ودقة."
        )

        full_query = f"{sys_context}\nالمستخدم: {prompt}"

        fallback_url = (
            "https://text.pollinations.ai/"
            f"{urllib.parse.quote(full_query)}?model=openai"
        )

        response = requests.get(
            fallback_url,
            timeout=30,
        )

        if response.status_code == 200 and response.text.strip():
            answer = response.text.strip()

            save_ai_message(user_id, "user", prompt)
            save_ai_message(user_id, "model", answer)

            return answer

    except Exception as e:
        print("Fallback AI error:", e)

    return "تعذر الاتصال بخدمات الذكاء الاصطناعي حاليًا."


# ============================================================
# Tools
# ============================================================

MORSE_CODE_DICT = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..",
    "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "1": ".----", "2": "..---", "3": "...--",
    "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.",
    "0": "-----", " ": "/",
}


def to_morse(text):
    return " ".join(
        MORSE_CODE_DICT.get(char.upper(), char)
        for char in text
    )


def generate_password(length=18):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-"
    return "".join(random.SystemRandom().choice(alphabet) for _ in range(length))


# ============================================================
# Web dashboard
# ============================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXORA | لوحة التحكم</title>
<style>
*{box-sizing:border-box}
body{
    margin:0;
    font-family:Arial,Tahoma,sans-serif;
    background:#0b0f19;
    color:#f3f4f6;
}
.navbar{
    padding:18px;
    background:#151c2c;
    border-bottom:1px solid #263047;
    display:flex;
    justify-content:space-between;
    gap:15px;
    flex-wrap:wrap;
}
.brand{font-size:22px;font-weight:bold}
.stats{
    color:#9ca3af;
    padding:8px 12px;
    border:1px solid #303a55;
    border-radius:10px;
}
.container{max-width:1200px;margin:auto;padding:20px}
.tabs{
    display:flex;
    gap:8px;
    overflow:auto;
    margin-bottom:20px;
}
.tab-btn{
    border:1px solid #303a55;
    background:#151c2c;
    color:#ddd;
    padding:12px 16px;
    border-radius:10px;
    cursor:pointer;
    white-space:nowrap;
}
.tab-btn.active{background:#4f46e5}
.tab-content{display:none}
.tab-content.active{display:block}
.grid{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
    gap:18px;
}
.card{
    background:#151c2c;
    border:1px solid #263047;
    border-radius:14px;
    padding:20px;
}
input,textarea{
    width:100%;
    margin:8px 0;
    padding:13px;
    background:#0b0f19;
    border:1px solid #303a55;
    border-radius:9px;
    color:#fff;
}
button{
    border:0;
    border-radius:9px;
    padding:12px 16px;
    cursor:pointer;
}
.btn{
    background:#6366f1;
    color:white;
    margin-top:8px;
}
.result{
    margin-top:12px;
    padding:14px;
    background:#0b0f19;
    border-radius:9px;
    white-space:pre-wrap;
    word-break:break-word;
    min-height:60px;
}
a{color:#34d399}
footer{
    text-align:center;
    padding:25px;
    color:#9ca3af;
}
</style>
</head>

<body>
<nav class="navbar">
    <div class="brand">NEXORA | نكسورا</div>
    <div class="stats">
        المستخدمون: {{u_cnt}} |
        المواقع: {{s_cnt}} |
        محادثات AI: {{ai_cnt}}
    </div>
</nav>

<div class="container">

<div class="tabs">
    <button class="tab-btn active" onclick="switchTab('hosting',this)">
        نشر المواقع
    </button>
    <button class="tab-btn" onclick="switchTab('ai',this)">
        الذكاء الاصطناعي
    </button>
    <button class="tab-btn" onclick="switchTab('cyber',this)">
        أدوات الشبكات
    </button>
    <button class="tab-btn" onclick="switchTab('tools',this)">
        الأدوات العامة
    </button>
</div>

<section id="hosting" class="tab-content active">
<div class="grid">

<div class="card">
<h3>نشر HTML / CSS / JS</h3>
<input id="custom_name" placeholder="اسم الموقع مثل my-site">
<textarea id="web_code" rows="12"
placeholder="ألصق كود HTML هنا"></textarea>
<button class="btn" onclick="publishCode()">نشر الموقع</button>
<div id="publish_result" class="result"></div>
</div>

<div class="card">
<h3>رفع ZIP</h3>
<input type="file" id="zip_file" accept=".zip">
<button class="btn" onclick="publishZip()">رفع ونشر ZIP</button>
<div id="zip_result" class="result"></div>
</div>

</div>
</section>

<section id="ai" class="tab-content">
<div class="card">
<h3>Gemini 2.5 Flash</h3>
<div id="ai_chat_box" class="result"
style="height:300px;overflow:auto"></div>
<input id="ai_prompt" placeholder="اكتب سؤالك">
<button class="btn" onclick="askAI()">إرسال</button>
</div>
</section>

<section id="cyber" class="tab-content">
<div class="grid">

<div class="card">
<h3>فحص معلومات IP / DNS / Ping</h3>
<input id="cyber_input"
placeholder="IP أو domain مثل example.com">
<button class="btn" onclick="runCyber('ip')">IP</button>
<button class="btn" onclick="runCyber('dns')">DNS</button>
<button class="btn" onclick="runCyber('ping')">Ping</button>
<div id="cyber_result" class="result"></div>
</div>

<div class="card">
<h3>Hash / Password</h3>
<input id="hash_input" placeholder="النص">
<button class="btn" onclick="makeHash()">MD5 / SHA256</button>
<button class="btn" onclick="makePass()">كلمة مرور</button>
<div id="hash_result" class="result"></div>
</div>

</div>
</section>

<section id="tools" class="tab-content">
<div class="card">
<h3>اختصار رابط / QR</h3>
<input id="tool_url" placeholder="الرابط">
<button class="btn" onclick="shorten()">اختصار</button>
<button class="btn" onclick="qr()">QR</button>
<div id="tool_result" class="result"></div>
</div>
</section>

</div>

<footer>NEXORA — {{developer}}</footer>

<script>
function switchTab(id,btn){
    document.querySelectorAll('.tab-content')
        .forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.tab-btn')
        .forEach(x=>x.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    btn.classList.add('active');
}

async function publishCode(){
    const code=document.getElementById('web_code').value;
    const name=document.getElementById('custom_name').value;
    const box=document.getElementById('publish_result');

    if(!code.trim()){
        box.textContent='اكتب الكود أولاً';
        return;
    }

    box.textContent='جاري النشر...';

    const r=await fetch('/api/publish',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({code,custom_name:name})
    });

    const d=await r.json();

    box.innerHTML=d.status==='success'
        ? 'تم النشر:<br><a target="_blank" href="'+d.url+'">'+d.url+'</a>'
        : d.message;
}

async function publishZip(){
    const file=document.getElementById('zip_file').files[0];
    const box=document.getElementById('zip_result');

    if(!file){
        box.textContent='اختر ZIP أولاً';
        return;
    }

    const form=new FormData();
    form.append('file',file);

    box.textContent='جاري الرفع...';

    const r=await fetch('/api/publish_zip',{
        method:'POST',
        body:form
    });

    const d=await r.json();

    box.innerHTML=d.status==='success'
        ? 'تم النشر:<br><a target="_blank" href="'+d.url+'">'+d.url+'</a>'
        : d.message;
}

async function askAI(){
    const input=document.getElementById('ai_prompt');
    const box=document.getElementById('ai_chat_box');
    const prompt=input.value.trim();

    if(!prompt)return;

    box.innerHTML+='<div><b>أنت:</b> '+escapeHtml(prompt)+'</div>';
    input.value='';

    const r=await fetch('/api/ai',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({prompt})
    });

    const d=await r.json();

    box.innerHTML+='<div><b>NEXORA:</b> '
        +escapeHtml(d.response||'')
        +'</div><hr>';

    box.scrollTop=box.scrollHeight;
}

async function runCyber(type){
    const target=document.getElementById('cyber_input').value;
    const box=document.getElementById('cyber_result');

    if(!target)return;

    box.textContent='جاري الفحص...';

    const r=await fetch(
        '/api/tools/cyber?type='+encodeURIComponent(type)
        +'&target='+encodeURIComponent(target)
    );

    const d=await r.json();
    box.textContent=d.result||'حدث خطأ';
}

async function makeHash(){
    const text=document.getElementById('hash_input').value;
    const r=await fetch(
        '/api/tools/hash?text='+encodeURIComponent(text)
    );
    const d=await r.json();
    document.getElementById('hash_result').textContent=d.result;
}

async function makePass(){
    const r=await fetch('/api/tools/pass');
    const d=await r.json();
    document.getElementById('hash_result').textContent=d.result;
}

async function shorten(){
    const url=document.getElementById('tool_url').value;
    const r=await fetch(
        '/api/tools/shorten?url='+encodeURIComponent(url)
    );
    const d=await r.json();
    document.getElementById('tool_result').textContent=d.result;
}

function qr(){
    const url=document.getElementById('tool_url').value;
    if(!url)return;

    document.getElementById('tool_result').innerHTML=
        '<img width="180" height="180" src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data='
        +encodeURIComponent(url)+'">';
}

function escapeHtml(s){
    return String(s).replace(/[&<>"']/g,function(m){
        return ({
            '&':'&amp;',
            '<':'&lt;',
            '>':'&gt;',
            '"':'&quot;',
            "'":'&#039;'
        })[m];
    });
}
</script>

</body>
</html>
"""


@app.route("/")
def web_dashboard():
    u_cnt, s_cnt, ai_cnt = get_global_stats()

    return render_template_string(
        HTML_TEMPLATE,
        u_cnt=u_cnt,
        s_cnt=s_cnt,
        ai_cnt=ai_cnt,
        developer=DEVELOPER_NAME,
    )


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "NEXORA",
            "telegram": "webhook",
        }
    )


@app.route("/api/publish", methods=["POST"])
def api_publish():
    data = request.get_json(silent=True) or {}

    code = data.get("code", "")
    custom_name = data.get("custom_name", "")

    if not code.strip():
        return jsonify(
            {
                "status": "error",
                "message": "الكود فارغ",
            }
        )

    filename = f"{sanitize_filename(custom_name)}.html"

    live_url, sha, err = publish_file_to_github(
        filename,
        code.encode("utf-8"),
    )

    if live_url:
        # Website dashboard has no Telegram user, so use 0.
        add_user_site(0, filename, live_url, sha)

        return jsonify(
            {
                "status": "success",
                "url": live_url,
            }
        )

    return jsonify(
        {
            "status": "error",
            "message": err or "فشل النشر",
        }
    )


@app.route("/api/publish_zip", methods=["POST"])
def api_publish_zip():
    uploaded = request.files.get("file")

    if not uploaded:
        return jsonify(
            {
                "status": "error",
                "message": "لم يتم رفع ملف ZIP.",
            }
        )

    if not uploaded.filename.lower().endswith(".zip"):
        return jsonify(
            {
                "status": "error",
                "message": "الملف يجب أن يكون ZIP.",
            }
        )

    try:
        data = uploaded.read()

        if len(data) > 25 * 1024 * 1024:
            return jsonify(
                {
                    "status": "error",
                    "message": "حجم ZIP كبير جدًا.",
                }
            )

        folder = f"site_{generate_random_name()}"

        with zipfile.ZipFile(io.BytesIO(data), "r") as z:
            names = z.namelist()

            index_url = None

            for original_name in names:
                if original_name.endswith("/"):
                    continue

                safe_name = safe_zip_path(original_name)

                if not safe_name:
                    continue

                content = z.read(original_name)

                target = f"{folder}/{safe_name}"

                url, sha, err = publish_file_to_github(
                    target,
                    content,
                )

                if err:
                    return jsonify(
                        {
                            "status": "error",
                            "message": err,
                        }
                    )

                if safe_name.lower() == "index.html":
                    index_url = url

        if not index_url:
            index_url = (
                f"https://{GITHUB_USER}.github.io/"
                f"{GITHUB_REPO}/{folder}/index.html"
            )

        add_user_site(0, folder, index_url, "")

        return jsonify(
            {
                "status": "success",
                "url": index_url,
            }
        )

    except zipfile.BadZipFile:
        return jsonify(
            {
                "status": "error",
                "message": "ملف ZIP غير صالح.",
            }
        )

    except Exception as e:
        return jsonify(
            {
                "status": "error",
                "message": f"فشل ZIP: {e}",
            }
        )


@app.route("/api/ai", methods=["POST"])
def api_ai():
    data = request.get_json(silent=True) or {}

    prompt = str(data.get("prompt", "")).strip()

    if not prompt:
        return jsonify(
            {
                "response": "اكتب سؤالًا أولاً."
            }
        )

    answer = process_ai_chat(0, prompt)

    return jsonify({"response": answer})


@app.route("/api/tools/cyber")
def api_cyber():
    tool_type = request.args.get("type", "").strip()
    target = request.args.get("target", "").strip()

    target = (
        target
        .replace("http://", "")
        .replace("https://", "")
        .split("/")[0]
    )

    if not target:
        return jsonify({"result": "أدخل IP أو domain."})

    try:
        if tool_type == "ip":
            response = requests.get(
                f"https://ip-api.com/json/{urllib.parse.quote(target)}",
                timeout=10,
            )

            data = response.json()

            if data.get("status") == "success":
                result = (
                    f"IP: {target}\n"
                    f"الدولة: {data.get('country')}\n"
                    f"المدينة: {data.get('city')}\n"
                    f"المزود: {data.get('isp')}"
                )
            else:
                result = "تعذر الحصول على معلومات IP."

        elif tool_type == "dns":
            response = requests.get(
                "https://api.hackertarget.com/"
                f"dnslookup/?q={urllib.parse.quote(target)}",
                timeout=15,
            )

            result = response.text[:8000]

        elif tool_type == "ping":
            response = requests.get(
                "https://api.hackertarget.com/"
                f"nping/?q={urllib.parse.quote(target)}",
                timeout=15,
            )

            result = response.text[:8000]

        else:
            result = "أداة غير معروفة."

    except Exception as e:
        result = f"فشل الفحص: {e}"

    return jsonify({"result": result})


@app.route("/api/tools/hash")
def api_hash():
    text = request.args.get("text", "")

    md5 = hashlib.md5(
        text.encode("utf-8")
    ).hexdigest()

    sha256 = hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()

    return jsonify(
        {
            "result":
                f"MD5:\n{md5}\n\n"
                f"SHA256:\n{sha256}"
        }
    )


@app.route("/api/tools/pass")
def api_pass():
    return jsonify(
        {
            "result": generate_password(18)
        }
    )


@app.route("/api/tools/shorten")
def api_shorten():
    url = request.args.get("url", "").strip()

    if not url:
        return jsonify(
            {
                "result": "أدخل رابطًا أولاً."
            }
        )

    try:
        response = requests.get(
            "https://is.gd/create.php",
            params={
                "format": "json",
                "url": url,
            },
            timeout=15,
        )

        data = response.json()

        return jsonify(
            {
                "result": data.get(
                    "shorturl",
                    "فشل الاختصار",
                )
            }
        )

    except Exception as e:
        return jsonify(
            {
                "result": f"فشل الاختصار: {e}"
            }
        )


# ============================================================
# Telegram UI
# ============================================================

def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton(
            "🤖 الذكاء الاصطناعي",
            callback_data="menu_ai",
        ),
        InlineKeyboardButton(
            "🛡️ الأمن السيبراني",
            callback_data="menu_cyber",
        ),
        InlineKeyboardButton(
            "📥 الوسائط والصوتيات",
            callback_data="menu_media",
        ),
        InlineKeyboardButton(
            "🎨 الزخرفة والنصوص",
            callback_data="menu_decor",
        ),
        InlineKeyboardButton(
            "🛠️ الأدوات العامة",
            callback_data="menu_tools",
        ),
        InlineKeyboardButton(
            "🌐 مواقعي المنشورة",
            callback_data="menu_myfiles",
        ),
        InlineKeyboardButton(
            "👤 حسابي",
            callback_data="menu_profile",
        ),
    )

    return markup


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    user_id = message.chat.id

    register_user(
        user_id,
        message.from_user.first_name,
        message.from_user.username,
    )

    user_states[user_id] = None

    first_name = message.from_user.first_name or "صديقي"

    welcome_text = (
        f"مرحبًا {first_name} في NEXORA | نكسورا\n\n"
        "منصة تقنية تجمع الذكاء الاصطناعي، "
        "أدوات الشبكات، ونشر المواقع.\n\n"
        "الخدمات:\n"
        "• نشر HTML / CSS / JS\n"
        "• نشر مشاريع ZIP\n"
        "• Gemini 2.5 Flash\n"
        "• أدوات معلومات الشبكات\n"
        "• Hash وكلمات مرور\n"
        "• QR واختصار الروابط\n"
        f"{DEVELOPER_RIGHTS}"
    )

    bot.send_message(
        user_id,
        welcome_text,
        reply_markup=main_menu(),
    )


@bot.message_handler(commands=["myfiles"])
def show_my_files(message):
    chat_id = message.chat.id

    sites = get_user_sites(chat_id)

    if not sites:
        bot.send_message(
            chat_id,
            "لا توجد لديك مواقع منشورة حاليًا.",
        )
        return

    text = "قائمة مواقعك المنشورة:\n\n"
    markup = InlineKeyboardMarkup()

    for index, site in enumerate(sites, 1):
        text += (
            f"{index}. {site['filename']}\n"
            f"الرابط: {site['url']}\n"
            f"التاريخ: {site['date']}\n\n"
        )

        markup.add(
            InlineKeyboardButton(
                f"حذف {site['filename']}",
                callback_data=f"del:{site['filename']}",
            )
        )

    bot.send_message(
        chat_id,
        text,
        reply_markup=markup,
    )


@bot.message_handler(content_types=["text", "document"])
def handle_incoming_content(message):
    chat_id = message.chat.id

    register_user(
        chat_id,
        message.from_user.first_name,
        message.from_user.username,
    )

    state = user_states.get(chat_id)

    if state == "waiting_custom_name":
        if not message.text:
            bot.send_message(
                chat_id,
                "أرسل اسم الموقع كنص.",
            )
            return

        custom_name = sanitize_filename(message.text)

        user_states[chat_id] = None

        if chat_id in pending_codes:
            pending_codes[chat_id]["custom_name"] = (
                f"{custom_name}.html"
            )

            execute_publishing_process(
                chat_id,
                pending_codes[chat_id]["message_id"],
            )

        return

    if state and state.startswith("tool_"):
        process_telegram_tool(message, state)
        return

    code_content = ""
    is_zip = False
    file_bytes = None

    try:
        if message.content_type == "document":
            file_name = (
                message.document.file_name or ""
            ).lower()

            if message.document.file_size and message.document.file_size > 25 * 1024 * 1024:
                bot.send_message(
                    chat_id,
                    "حجم الملف أكبر من 25MB.",
                )
                return

            file_info = bot.get_file(
                message.document.file_id
            )

            file_bytes = bot.download_file(
                file_info.file_path
            )

            if file_name.endswith(".zip"):
                is_zip = True
            else:
                code_content = file_bytes.decode(
                    "utf-8",
                    errors="ignore",
                )

        elif message.text and (
            "<html" in message.text.lower()
            or "<div" in message.text.lower()
            or "<script" in message.text.lower()
            or "<!doctype" in message.text.lower()
        ):
            code_content = message.text
            file_bytes = code_content.encode("utf-8")

        else:
            prompt = message.text or ""

            answer = process_ai_chat(
                chat_id,
                prompt,
            )

            bot.reply_to(
                message,
                f"🤖 NEXORA:\n\n{answer}"
                f"{DEVELOPER_RIGHTS}",
            )

            return

    except Exception as e:
        bot.send_message(
            chat_id,
            f"حدث خطأ أثناء قراءة الملف: {e}",
        )
        return

    pending_codes[chat_id] = {
        "bytes": file_bytes,
        "is_zip": is_zip,
        "custom_name": None,
    }

    markup = InlineKeyboardMarkup()

    markup.row(
        InlineKeyboardButton(
            "🚀 نشر باسم عشوائي",
            callback_data="pub_random",
        ),
        InlineKeyboardButton(
            "✏️ تخصيص الاسم",
            callback_data="pub_custom",
        ),
    )

    sent = bot.send_message(
        chat_id,
        "تم استلام الكود/المشروع.\n"
        "اختر طريقة النشر:",
        reply_markup=markup,
    )

    pending_codes[chat_id]["message_id"] = (
        sent.message_id
    )


def execute_publishing_process(chat_id, message_id):
    if chat_id not in pending_codes:
        bot.send_message(
            chat_id,
            "انتهت الجلسة، أرسل الملف مرة أخرى.",
        )
        return

    data = pending_codes[chat_id]

    filename = data["custom_name"]

    try:
        bot.edit_message_text(
            "جاري النشر على GitHub...",
            chat_id,
            message_id,
        )
    except Exception:
        pass

    live_url = None
    sha = None
    err = None

    try:
        if data["is_zip"]:
            folder_name = (
                filename
                .replace(".html", "")
            )

            with zipfile.ZipFile(
                io.BytesIO(data["bytes"]),
                "r",
            ) as zip_ref:

                for file_in_zip in zip_ref.namelist():
                    if file_in_zip.endswith("/"):
                        continue

                    safe_name = safe_zip_path(
                        file_in_zip
                    )

                    if not safe_name:
                        continue

                    content = zip_ref.read(
                        file_in_zip
                    )

                    target_path = (
                        f"{folder_name}/{safe_name}"
                    )

                    url, file_sha, file_err = (
                        publish_file_to_github(
                            target_path,
                            content,
                        )
                    )

                    if file_err:
                        err = file_err
                        break

                    if safe_name.lower() == "index.html":
                        live_url = url
                        sha = file_sha

            if not err and not live_url:
                live_url = (
                    f"https://{GITHUB_USER}.github.io/"
                    f"{GITHUB_REPO}/{folder_name}/index.html"
                )

        else:
            live_url, sha, err = (
                publish_file_to_github(
                    filename,
                    data["bytes"],
                )
            )

    except zipfile.BadZipFile:
        err = "ملف ZIP غير صالح."

    except Exception as e:
        err = str(e)

    if live_url and not err:
        add_user_site(
            chat_id,
            filename,
            live_url,
            sha,
        )

        pending_codes.pop(chat_id, None)

        bot.send_message(
            chat_id,
            "تم نشر موقعك بنجاح.\n\n"
            f"الرابط:\n{live_url}",
        )

    else:
        bot.send_message(
            chat_id,
            f"فشل النشر:\n{err or 'خطأ غير معروف'}",
        )


@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    data = call.data or ""

    try:
        bot.answer_callback_query(
            call.id
        )
    except Exception:
        pass

    if data.startswith("del:"):
        filename = data.split(":", 1)[1]

        try:
            bot.edit_message_text(
                f"جاري حذف {filename}...",
                chat_id,
                call.message.message_id,
            )
        except Exception:
            pass

        success, message = delete_from_github(
            filename
        )

        if success:
            remove_user_site(
                chat_id,
                filename,
            )

            bot.send_message(
                chat_id,
                f"تم حذف {filename} بنجاح.",
            )
        else:
            bot.send_message(
                chat_id,
                f"فشل الحذف:\n{message}",
            )

        return

    if data == "pub_random":
        if chat_id not in pending_codes:
            bot.send_message(
                chat_id,
                "انتهت الجلسة، أرسل الملف مرة أخرى.",
            )
            return

        is_zip = pending_codes[chat_id]["is_zip"]

        if is_zip:
            pending_codes[chat_id]["custom_name"] = (
                f"site_{generate_random_name()}.html"
            )
        else:
            pending_codes[chat_id]["custom_name"] = (
                f"site_{generate_random_name()}.html"
            )

        execute_publishing_process(
            chat_id,
            call.message.message_id,
        )

        return

    if data == "pub_custom":
        if chat_id not in pending_codes:
            bot.send_message(
                chat_id,
                "انتهت الجلسة، أرسل الملف مرة أخرى.",
            )
            return

        user_states[chat_id] = (
            "waiting_custom_name"
        )

        try:
            bot.edit_message_text(
                "أرسل اسم الموقع الآن، مثل:\n"
                "my-portfolio",
                chat_id,
                call.message.message_id,
            )
        except Exception:
            pass

        return

    if data == "menu_myfiles":
        show_my_files(call.message)
        return

    if data == "menu_ai":
        user_states[chat_id] = "tool_ai"

        bot.send_message(
            chat_id,
            "أرسل سؤالك الآن وسأرسله إلى Gemini.",
        )

        return

    if data == "menu_cyber":
        user_states[chat_id] = "tool_ip_info"

        bot.send_message(
            chat_id,
            "أرسل IP أو domain للحصول على معلومات عامة عنه.",
        )

        return

    if data == "menu_tools":
        markup = InlineKeyboardMarkup(row_width=2)

        markup.add(
            InlineKeyboardButton(
                "🔐 توليد كلمة مرور",
                callback_data="tool_password",
            ),
            InlineKeyboardButton(
                "🔗 اختصار رابط",
                callback_data="tool_short",
            ),
            InlineKeyboardButton(
                "📱 QR",
                callback_data="tool_qr",
            ),
            InlineKeyboardButton(
                "🔢 Hash",
                callback_data="tool_hash",
            ),
        )

        bot.send_message(
            chat_id,
            "اختر أداة:",
            reply_markup=markup,
        )

        return

    if data == "menu_profile":
        sites = get_user_sites(chat_id)

        bot.send_message(
            chat_id,
            f"👤 حسابك\n\n"
            f"ID: {chat_id}\n"
            f"عدد المواقع المنشورة: {len(sites)}",
        )

        return

    if data == "menu_media":
        bot.send_message(
            chat_id,
            "قسم الوسائط جاهز للإضافة في هذه النسخة.",
        )
        return

    if data == "menu_decor":
        bot.send_message(
            chat_id,
            "أرسل النص الذي تريد زخرفته.",
        )
        user_states[chat_id] = "tool_decor"
        return

    if data == "tool_password":
        bot.send_message(
            chat_id,
            f"كلمة المرور:\n`{generate_password()}`",
        )
        return

    if data == "tool_qr":
        user_states[chat_id] = "tool_make_qr"

        bot.send_message(
            chat_id,
            "أرسل الرابط أو النص لإنشاء QR.",
        )
        return

    if data == "tool_hash":
        user_states[chat_id] = "tool_hash"

        bot.send_message(
            chat_id,
            "أرسل النص لإنشاء MD5 وSHA256.",
        )
        return

    if data == "tool_short":
        user_states[chat_id] = "tool_short"

        bot.send_message(
            chat_id,
            "أرسل الرابط الطويل.",
        )
        return


def process_telegram_tool(message, state):
    chat_id = message.chat.id
    text = (message.text or "").strip()

    try:
        if state == "tool_ai":
            answer = process_ai_chat(
                chat_id,
                text,
            )

            bot.send_message(
                chat_id,
                f"🤖 NEXORA:\n\n{answer}",
            )

        elif state == "tool_ip_info":
            target = (
                text
                .replace("http://", "")
                .replace("https://", "")
                .split("/")[0]
            )

            response = requests.get(
                f"https://ip-api.com/json/"
                f"{urllib.parse.quote(target)}",
                timeout=10,
            )

            data = response.json()

            if data.get("status") == "success":
                bot.send_message(
                    chat_id,
                    "بيانات عامة:\n"
                    f"الدولة: {data.get('country')}\n"
                    f"المدينة: {data.get('city')}\n"
                    f"المزود: {data.get('isp')}\n"
                    f"IP: {data.get('query')}",
                )
            else:
                bot.send_message(
                    chat_id,
                    "تعذر الحصول على البيانات.",
                )

        elif state == "tool_make_qr":
            image = qrcode.make(text)

            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            buffer.seek(0)
            buffer.name = "qrcode.png"

            bot.send_photo(
                chat_id,
                buffer,
                caption="رمز QR الخاص بك.",
            )

        elif state == "tool_hash":
            md5 = hashlib.md5(
                text.encode("utf-8")
            ).hexdigest()

            sha = hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest()

            bot.send_message(
                chat_id,
                f"MD5:\n`{md5}`\n\n"
                f"SHA256:\n`{sha}`",
            )

        elif state == "tool_short":
            response = requests.get(
                "https://is.gd/create.php",
                params={
                    "format": "json",
                    "url": text,
                },
                timeout=15,
            )

            data = response.json()

            bot.send_message(
                chat_id,
                data.get(
                    "shorturl",
                    "فشل اختصار الرابط.",
                ),
            )

        elif state == "tool_decor":
            decorated = (
                f"『 {text} 』\n"
                f"★ {text} ★\n"
                f"「 {text} 」"
            )

            bot.send_message(
                chat_id,
                decorated,
            )

    except Exception as e:
        bot.send_message(
            chat_id,
            f"حدث خطأ:\n{e}",
        )

    finally:
        user_states[chat_id] = None


# ============================================================
# Telegram WEBHOOK
# ============================================================

WEBHOOK_PATH = f"/telegram/{WEBHOOK_SECRET}"


@app.route(
    WEBHOOK_PATH,
    methods=["POST"],
)
def telegram_webhook():
    try:
        raw = request.get_data(
            cache=False,
            as_text=True,
        )

        if not raw:
            return "empty", 400

        update = telebot.types.Update.de_json(
            raw
        )

        if update:
            bot.process_new_updates(
                [update]
            )

        return "OK", 200

    except Exception as e:
        print("Telegram webhook error:", e)
        return "error", 500


def setup_telegram_webhook():
    if not RENDER_EXTERNAL_URL:
        print(
            "WARNING: RENDER_EXTERNAL_URL is missing."
        )
        print(
            "Add it manually in Render, e.g. "
            "https://your-service.onrender.com"
        )
        return False

    webhook_url = (
        f"{RENDER_EXTERNAL_URL}"
        f"{WEBHOOK_PATH}"
    )

    try:
        # This replaces any previous webhook for THIS token.
        bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True,
        )

        info = bot.get_webhook_info()

        print("========================================")
        print("Telegram webhook configured.")
        print("Webhook URL:", webhook_url)
        print("Pending updates:", info.pending_update_count)
        print("========================================")

        return True

    except Exception as e:
        print(
            "Telegram webhook setup failed:",
            e,
        )
        return False


# ============================================================
# Main
# ============================================================

def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    print("========================================")
    print("NEXORA starting...")
    print("Developer:", DEVELOPER_NAME)
    print("Port:", PORT)
    print("Mode: Telegram WEBHOOK")
    print("========================================")

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )

    flask_thread.start()

    # Give Flask a moment to bind the port.
    time.sleep(2)

    setup_telegram_webhook()

    print("NEXORA is running.")
    print("Telegram polling is NOT used.")
    print("Keep this process alive for Render.")

    # Keep the main process alive.
    while True:
        time.sleep(60)
