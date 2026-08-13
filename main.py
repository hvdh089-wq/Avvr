import os
import io
import re
import json
import time
import socket
import random
import string
import urllib.parse
import hashlib
import base64
import datetime
import sqlite3
import requests
import threading
import zipfile
from flask import Flask, render_template_string, request, jsonify
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException
from gtts import gTTS
import qrcode

# ==================== [ إعدادات الحقوق والمفاتيح ] ====================

DEVELOPER_NAME = "المطور الجبوري"
DEVELOPER_RIGHTS = "\n\n👑 **تطوير:** المطور الجبوري"

# مفاتيح الربط
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8965727379:AAF2x-CTFF7MgttvUgHqOBvKyVkuekO6pIY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6KeiWbeu1PlIgMdPEe8ecmVYnnIbbwQScl-0IRhWvCUpw")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")
GITHUB_USER = os.environ.get("GITHUB_USER", "akoasad7-arch")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "my-sites")

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN)

# الذاكرة المؤقتة للعمليات
user_states = {}
pending_codes = {}

# ==================== [ إدارة قاعدة البيانات المركزية ] ====================

DB_NAME = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            joined_at TEXT,
            req_count INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            tool_name TEXT,
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT,
            url TEXT,
            sha TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def register_user(user_id, first_name, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT OR IGNORE INTO users (user_id, first_name, username, joined_at) VALUES (?, ?, ?, ?)",
                   (user_id, first_name, username or "لا يوجد", now))
    cursor.execute("UPDATE users SET req_count = req_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def log_activity(user_id, tool_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO activity_log (user_id, tool_name, created_at) VALUES (?, ?, ?)",
                   (user_id, tool_name, now))
    conn.commit()
    conn.close()

def save_ai_message(user_id, role, content):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO ai_history (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                   (user_id, role, content, now))
    conn.commit()
    conn.close()

def get_user_ai_history(user_id, limit=6):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM ai_history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "text": r[1]} for r in reversed(rows)]

def clear_user_ai_history(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_user_site(user_id, filename, url, sha):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("INSERT INTO user_sites (user_id, filename, url, sha, created_at) VALUES (?, ?, ?, ?, ?)",
                   (user_id, filename, url, sha, now))
    conn.commit()
    conn.close()

def remove_user_site(user_id, filename):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_sites WHERE user_id = ? AND filename = ?", (user_id, filename))
    conn.commit()
    conn.close()

def get_user_sites(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT filename, url, sha, created_at FROM user_sites WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [{"filename": r[0], "url": r[1], "sha": r[2], "date": r[3]} for r in rows]

def get_global_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    u_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM user_sites")
    s_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM ai_history")
    ai_cnt = cursor.fetchone()[0]
    conn.close()
    return u_cnt, s_cnt, ai_cnt

init_db()

# ==================== [ محرك GitHub لنشر المواقع العلنية ] ====================

def generate_random_name(length=6):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def sanitize_filename(name):
    name = re.sub(r'[^a-zA-Z0-9_-]', '', name.strip().replace(' ', '-'))
    return name if name else f"site_{generate_random_name()}"

def check_relative_assets(html_code):
    pattern = r'(?:src|href)=["\'](?!http|https|data:)([^"\']+)["\']'
    matches = re.findall(pattern, html_code, re.IGNORECASE)
    media_files = [m for m in matches if any(m.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.mp4', '.webm', '.mp3', '.css', '.js'])]
    return list(set(media_files))

def publish_file_to_github(filename, content_bytes):
    if not GITHUB_TOKEN or len(GITHUB_TOKEN) < 10:
        return None, None, "رمز GITHUB_TOKEN غير مضبوط بشكل صحيح."

    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        encoded_content = base64.b64encode(content_bytes).decode('utf-8')
        get_res = requests.get(url, headers=headers)
        sha = get_res.json().get('sha') if get_res.status_code == 200 else None

        data = {
            "message": f"Publish {filename} via Multi-Engine Bot",
            "content": encoded_content
        }
        if sha:
            data["sha"] = sha

        response = requests.put(url, json=data, headers=headers)
        if response.status_code in [200, 201]:
            new_sha = response.json().get("content", {}).get("sha", "")
            live_url = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/{filename}"
            return live_url, new_sha, None
        else:
            error_msg = response.json().get('message', 'خطأ في الاستجابة من GitHub')
            return None, None, f"فشل النشر ({response.status_code}): {error_msg}"
    except Exception as e:
        return None, None, f"خطأ الاتصال: {str(e)}"

def delete_from_github(filename, sha=None):
    url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    if not sha:
        get_res = requests.get(url, headers=headers)
        if get_res.status_code == 200:
            sha = get_res.json().get('sha')
        else:
            return False, "الملف غير موجود على GitHub."

    data = {
        "message": f"Delete {filename}",
        "sha": sha
    }
    res = requests.delete(url, json=data, headers=headers)
    return (True, "تم الحذف بنجاح") if res.status_code == 200 else (False, f"فشل الحذف: {res.text}")

# ==================== [ محرك الذكاء الاصطناعي (Gemini 2.5 Flash) ] ====================

def process_ai_chat(user_id, prompt):
    history = get_user_ai_history(user_id, limit=6)
    
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": GEMINI_API_KEY
            }
            contents = []
            for h in history:
                role_mapped = "model" if h["role"] in ["model", "assistant"] else "user"
                contents.append({"role": role_mapped, "parts": [{"text": h["text"]}]})
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            
            payload = {"contents": contents}
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if 'candidates' in data and len(data['candidates']) > 0:
                    ans = data['candidates'][0]['content']['parts'][0]['text']
                    save_ai_message(user_id, "user", prompt)
                    save_ai_message(user_id, "model", ans)
                    return ans
        except Exception as e:
            print(f"Gemini API Error: {e}")

    # السيرفر الاحتياطي
    try:
        sys_context = "أنت مساعد ذكي ومحترف، تجيب باللغة العربية بأسلوب دقيق وشامل."
        full_query = f"{sys_context}\nالمستخدم: {prompt}"
        fallback_url = f"https://text.pollinations.ai/{urllib.parse.quote(full_query)}?model=openai"
        res = requests.get(fallback_url, timeout=15)
        if res.status_code == 200 and res.text.strip():
            ans = res.text.strip()
            save_ai_message(user_id, "user", prompt)
            save_ai_message(user_id, "model", ans)
            return ans
    except Exception as e:
        print(f"Fallback AI error: {e}")

    return "❌ تعذر الاتصال بسيرفرات الذكاء الاصطناعي حالياً."

# ==================== [ أدوات مساعدة ورموز ] ====================

MORSE_CODE_DICT = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', '1': '.----', '2': '..---', '3': '...--',
    '4': '....-', '5': '.....', '6': '-....', '7': '--...', '8': '---..',
    '9': '----.', '0': '-----', ' ': '/'
}

def to_morse(text):
    return ' '.join(MORSE_CODE_DICT.get(char.upper(), char) for char in text)

# ==================== [ واجهة المتصفح المتقدمة بدون إيموجيات (Chrome Web UI) ] ====================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة التحكم الشاملة - المطور الجبوري</title>
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: #151c2c;
            --card-border: #232d42;
            --accent-color: #6366f1;
            --accent-hover: #4f46e5;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --success: #10b981;
            --danger: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Tajawal', sans-serif;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        .navbar {
            background: var(--card-bg);
            border-bottom: 1px solid var(--card-border);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text-main);
        }

        .svg-icon {
            width: 24px;
            height: 24px;
            fill: none;
            stroke: var(--accent-color);
            stroke-width: 2;
            stroke-linecap: round;
            stroke-linejoin: round;
        }

        .stats-badge {
            background: rgba(99, 102, 241, 0.1);
            color: var(--accent-color);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.85rem;
            border: 1px solid rgba(99, 102, 241, 0.3);
        }

        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
            width: 100%;
            flex: 1;
        }

        .tabs {
            display: flex;
            gap: 10px;
            border-bottom: 1px solid var(--card-border);
            margin-bottom: 2rem;
            overflow-x: auto;
            padding-bottom: 5px;
        }

        .tab-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            padding: 10px 20px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            border-radius: 8px;
            transition: all 0.3s ease;
            white-space: nowrap;
        }

        .tab-btn:hover, .tab-btn.active {
            color: var(--text-main);
            background: var(--card-bg);
        }

        .tab-btn.active {
            border-bottom: 2px solid var(--accent-color);
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        .card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.1rem;
            font-weight: 700;
        }

        textarea, input, select {
            width: 100%;
            background: var(--bg-color);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 12px;
            color: var(--text-main);
            font-size: 0.95rem;
            outline: none;
            transition: border-color 0.3s;
        }

        textarea:focus, input:focus {
            border-color: var(--accent-color);
        }

        .btn {
            background: var(--accent-color);
            color: #fff;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: background 0.3s;
        }

        .btn:hover {
            background: var(--accent-hover);
        }

        .response-box {
            background: var(--bg-color);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 1rem;
            min-height: 100px;
            max-height: 400px;
            overflow-y: auto;
            font-size: 0.9rem;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .url-box {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid var(--success);
            padding: 10px;
            border-radius: 8px;
            color: var(--success);
            font-size: 0.9rem;
            margin-top: 10px;
        }

        .url-box a {
            color: var(--success);
            text-decoration: underline;
            word-break: break-all;
        }

        footer {
            text-align: center;
            padding: 1.5rem;
            border-top: 1px solid var(--card-border);
            color: var(--text-muted);
            font-size: 0.85rem;
            background: var(--card-bg);
        }
    </style>
</head>
<body>

    <nav class="navbar">
        <div class="brand">
            <svg class="svg-icon" viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
            <span>منصة التحكم والإستضافة السحابية</span>
        </div>
        <div class="stats-badge">
            المستخدمين: {{ u_cnt }} | المواقع: {{ s_cnt }} | محادثات AI: {{ ai_cnt }}
        </div>
    </nav>

    <div class="container">
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('hosting')">نشر الأكواد والمواقع</button>
            <button class="tab-btn" onclick="switchTab('ai')">الذكاء الاصطناعي (Gemini 2.5)</button>
            <button class="tab-btn" onclick="switchTab('cyber')">الأمن السيبراني والشبكات</button>
            <button class="tab-btn" onclick="switchTab('tools')">الأدوات العامة</button>
        </div>

        <div id="hosting" class="tab-content active">
            <div class="grid">
                <div class="card">
                    <div class="card-header">
                        <span>تحويل كود HTML / CSS / JS إلى رابط مباشر</span>
                    </div>
                    <input type="text" id="custom_name" placeholder="اسم رابط الموقع (اختياري مثلاً: my-site)">
                    <textarea id="web_code" rows="10" placeholder="الصق كود HTML هنا..."></textarea>
                    <button class="btn" onclick="publishCode()">نشر الموقع على الإنترنت</button>
                    <div id="publish_result"></div>
                </div>
            </div>
        </div>

        <div id="ai" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <span>شاشة محادثة Gemini 2.5 Flash</span>
                </div>
                <div id="ai_chat_box" class="response-box" style="height: 300px;"></div>
                <div style="display: flex; gap: 10px;">
                    <input type="text" id="ai_prompt" placeholder="اكتب سؤالك للذكاء الاصطناعي..." onkeypress="if(event.key==='Enter') askAI()">
                    <button class="btn" onclick="askAI()">إرسال</button>
                </div>
            </div>
        </div>

        <div id="cyber" class="tab-content">
            <div class="grid">
                <div class="card">
                    <div class="card-header">
                        <span>فحص الـ IP والـ DNS</span>
                    </div>
                    <input type="text" id="cyber_input" placeholder="أدخل IP أو اسم الدومين (مثلاً google.com)">
                    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                        <button class="btn" onclick="runCyberTool('ip')">فحص IP</button>
                        <button class="btn" onclick="runCyberTool('dns')">سجلات DNS</button>
                        <button class="btn" onclick="runCyberTool('ping')">قياس Ping</button>
                    </div>
                    <div id="cyber_result" class="response-box"></div>
                </div>
            </div>
        </div>

        <div id="tools" class="tab-content">
            <div class="grid">
                <div class="card">
                    <div class="card-header">
                        <span>اختصار الروابط وتوليد باركود QR</span>
                    </div>
                    <input type="text" id="tool_url" placeholder="أدخل الرابط الطويل هنا...">
                    <div style="display: flex; gap: 10px;">
                        <button class="btn" onclick="shortenUrl()">اختصار الرابط</button>
                        <button class="btn" onclick="makeQR()">توليد رمز QR</button>
                    </div>
                    <div id="tool_result" class="response-box"></div>
                </div>
            </div>
        </div>
    </div>

    <footer>
        تطوير وبرمجة المطور الجبوري &copy; جميع الحقوق محفوظة 2026
    </footer>

    <script>
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
        }

        async function publishCode() {
            const code = document.getElementById('web_code').value;
            const name = document.getElementById('custom_name').value;
            const resBox = document.getElementById('publish_result');
            
            if(!code) return alert('يرجى كتابة كود HTML أولاً');
            resBox.innerHTML = 'جاري النشر وتوليد الرابط...';

            const resp = await fetch('/api/publish', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code, custom_name: name})
            });
            const data = await resp.json();

            if(data.status === 'success') {
                resBox.innerHTML = `<div class="url-box">تم نشر موقعك بنجاح:<br><a href="${data.url}" target="_blank">${data.url}</a></div>`;
            } else {
                resBox.innerHTML = `<div style="color:var(--danger)">حدث خطأ: ${data.message}</div>`;
            }
        }

        async function askAI() {
            const promptInput = document.getElementById('ai_prompt');
            const chatBox = document.getElementById('ai_chat_box');
            const text = promptInput.value;
            if(!text) return;

            chatBox.innerHTML += `<div><b>أنت:</b> ${text}</div>`;
            promptInput.value = '';

            const resp = await fetch('/api/ai', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({prompt: text})
            });
            const data = await resp.json();

            chatBox.innerHTML += `<div style="color:var(--accent-color); margin-top:5px;"><b>Gemini:</b> ${data.response}</div><hr style="border-color:var(--card-border); margin:10px 0;">`;
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        async function runCyberTool(type) {
            const val = document.getElementById('cyber_input').value;
            const resBox = document.getElementById('cyber_result');
            if(!val) return alert('يرجى إدخال البيانات المطلوبة');

            resBox.innerText = 'جاري الفحص...';
            const resp = await fetch(`/api/tools/cyber?type=${type}&target=${encodeURIComponent(val)}`);
            const data = await resp.json();
            resBox.innerText = data.result;
        }

        async function shortenUrl() {
            const url = document.getElementById('tool_url').value;
            const resBox = document.getElementById('tool_result');
            const resp = await fetch(`/api/tools/shorten?url=${encodeURIComponent(url)}`);
            const data = await resp.json();
            resBox.innerText = 'الرابط المختصر: ' + data.result;
        }

        async function makeQR() {
            const url = document.getElementById('tool_url').value;
            const resBox = document.getElementById('tool_result');
            resBox.innerHTML = `<img src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${encodeURIComponent(url)}" />`;
        }
    </script>
</body>
</html>
"""

@app.route('/')
def web_dashboard():
    u_cnt, s_cnt, ai_cnt = get_global_stats()
    return render_template_string(HTML_TEMPLATE, u_cnt=u_cnt, s_cnt=s_cnt, ai_cnt=ai_cnt)

@app.route('/api/publish', methods=['POST'])
def api_publish():
    data = request.json or {}
    code = data.get('code', '')
    custom_name = data.get('custom_name', '')
    
    if not code.strip():
        return jsonify({"status": "error", "message": "الكود فارغ"})

    filename = f"{sanitize_filename(custom_name)}.html"
    live_url, sha, err = publish_file_to_github(filename, code.encode('utf-8'))
    
    if live_url:
        add_user_site(1000, filename, live_url, sha)
        return jsonify({"status": "success", "url": live_url})
    return jsonify({"status": "error", "message": err})

@app.route('/api/ai', methods=['POST'])
def api_ai():
    data = request.json or {}
    prompt = data.get('prompt', '')
    ans = process_ai_chat(1000, prompt)
    return jsonify({"response": ans})

@app.route('/api/tools/cyber')
def api_cyber():
    tool_type = request.args.get('type')
    target = request.args.get('target', '').replace('http://', '').replace('https://', '').split('/')[0]
    
    if tool_type == 'ip':
        res = requests.get(f"http://ip-api.com/json/{target}").json()
        if res.get('status') == 'success':
            out = f"IP: {target}\nالدولة: {res.get('country')}\nالمدينة: {res.get('city')}\nالمزود: {res.get('isp')}"
        else:
            out = "تعذر الحصول على معلومات الـ IP."
    elif tool_type == 'dns':
        out = requests.get(f"https://api.hackertarget.com/dnslookup/?q={target}").text
    elif tool_type == 'ping':
        out = requests.get(f"https://api.hackertarget.com/nping/?q={target}").text
    else:
        out = "أداة غير معروفة."
    return jsonify({"result": out})

@app.route('/api/tools/shorten')
def api_shorten():
    url = request.args.get('url', '')
    res = requests.get(f"https://is.gd/create.php?format=json&url={urllib.parse.quote(url)}").json()
    return jsonify({"result": res.get('shorturl', 'فشل الاختصار')})

# ==================== [ معالجة بوت التليجرام والمناطق التفاعلية ] ====================

def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🤖 الذكاء الاصطناعي (12)", callback_data="menu_ai"),
        InlineKeyboardButton("🛡️ الأمن السيبراني (15)", callback_data="menu_cyber"),
        InlineKeyboardButton("📥 الوسائط والصوتيات (10)", callback_data="menu_media"),
        InlineKeyboardButton("🎨 الزخرفة والنصوص (12)", callback_data="menu_decor"),
        InlineKeyboardButton("🛠️ الأدوات العامة (15)", callback_data="menu_tools"),
        InlineKeyboardButton("🌐 مواقعك المنشورة (/myfiles)", callback_data="menu_myfiles"),
        InlineKeyboardButton("👤 حسابي وسجلي الخاص", callback_data="menu_profile")
    )
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    u_id = message.chat.id
    register_user(u_id, message.from_user.first_name, message.from_user.username)
    user_states[u_id] = None
    
    welcome_text = (
        f"🔥 **أهلاً بك يا {message.from_user.first_name} في البوت المطور المدمج!**\n\n"
        "✨ **أبرز الخدمات المتاحة:**\n"
        "• 🌐 **تحويل كود HTML / CSS / ZIP لرابط علني مباشر** (فقط أرسل الملف أو الكود هنا).\n"
        "• 🤖 **الذكاء الاصطناعي (Gemini 2.5 Flash)** للاستفسارات والبرمجة.\n"
        "• 🛡️ **أدوات الأمن السيبراني وفحص الشبكات**.\n"
        "• 🛠️ **أدوات النصوص والتشفير والوسائط**.\n"
        f"{DEVELOPER_RIGHTS}"
    )
    bot.send_message(u_id, welcome_text, reply_markup=main_menu())

@bot.message_handler(commands=['myfiles'])
def show_my_files(message):
    chat_id = message.chat.id
    sites = get_user_sites(chat_id)

    if not sites:
        bot.send_message(chat_id, "📂 لا توجد لديك أي مواقع منشورة حالياً.")
        return

    msg = "🌐 **قائمة مواقعك المنشورة:**\n\n"
    markup = InlineKeyboardMarkup()

    for idx, site in enumerate(sites, 1):
        msg += f"{idx}️⃣ **الملف:** `{site['filename']}`\n🔗 {site['url']}\n📅 {site.get('date', 'غير محدد')}\n\n"
        markup.add(
            InlineKeyboardButton(f"🗑️ حذف {site['filename']}", callback_data=f"del_{site['filename']}")
        )

    bot.send_message(chat_id, msg, reply_markup=markup)

@bot.message_handler(content_types=['text', 'document'])
def handle_incoming_content(message):
    chat_id = message.chat.id

    if user_states.get(chat_id) == "waiting_custom_name":
        custom_name = sanitize_filename(message.text)
        user_states[chat_id] = None
        if chat_id in pending_codes:
            pending_codes[chat_id]['custom_name'] = f"{custom_name}.html"
            execute_publishing_process(chat_id, pending_codes[chat_id]['message_id'])
        return

    state = user_states.get(chat_id)
    if state and state.startswith("tool_"):
        process_telegram_tool(message, state)
        return

    code_content = ""
    is_zip = False
    file_bytes = None

    if message.content_type == 'document':
        file_name = message.document.file_name.lower()
        file_info = bot.get_file(message.document.file_id)
        file_bytes = bot.download_file(file_info.file_path)

        if file_name.endswith('.zip'):
            is_zip = True
        else:
            code_content = file_bytes.decode('utf-8', errors='ignore')
    elif message.text and ("<html" in message.text.lower() or "<div" in message.text.lower() or "<script" in message.text.lower()):
        code_content = message.text
        file_bytes = code_content.encode('utf-8')
    else:
        ans = process_ai_chat(chat_id, message.text)
        bot.reply_to(message, f"🤖 **Gemini 2.5:**\n\n{ans}{DEVELOPER_RIGHTS}")
        return

    pending_codes[chat_id] = {
        'bytes': file_bytes,
        'is_zip': is_zip,
        'custom_name': None
    }

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🚀 نشر باسم عشوائي", callback_data="pub_random"),
        InlineKeyboardButton("✏️ تخصيص اسم الرابط", callback_data="pub_custom")
    )

    msg = bot.send_message(
        chat_id, 
        "📥 **تم استلام كود/مشروع الويب!**\nاختر طريقة النشر المولدة على GitHub Pages:",
        reply_markup=markup
    )
    pending_codes[chat_id]['message_id'] = msg.message_id

def execute_publishing_process(chat_id, message_id):
    if chat_id not in pending_codes:
        bot.send_message(chat_id, "⚠️ انتهت الجلسة، أرسل الكود مجدداً.")
        return

    data = pending_codes[chat_id]
    filename = data['custom_name']
    
    bot.edit_message_text("⏳ **جاري النشر والرفع على السيرفر...**", chat_id, message_id)

    if data['is_zip']:
        folder_name = filename.replace('.html', '')
        live_url, sha = None, None
        try:
            zip_buffer = io.BytesIO(data['bytes'])
            with zipfile.ZipFile(zip_buffer, 'r') as zip_ref:
                for file_in_zip in zip_ref.namelist():
                    if not file_in_zip.endswith('/'):
                        content = zip_ref.read(file_in_zip)
                        target_path = f"{folder_name}/{file_in_zip}"
                        url, file_sha, err = publish_file_to_github(target_path, content)
                        if file_in_zip.lower() in ['index.html', 'main.html']:
                            live_url, sha = url, file_sha
            if not live_url:
                live_url = f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/{folder_name}/index.html"
        except Exception as e:
            bot.send_message(chat_id, f"❌ فشل فك ضغط ZIP: {str(e)}")
            return
    else:
        live_url, sha, err = publish_file_to_github(filename, data['bytes'])

    if live_url:
        add_user_site(chat_id, filename, live_url, sha)
        del pending_codes[chat_id]
        bot.send_message(
            chat_id,
            f"🎉 **تم نشر موقعك بنجاح!**\n\n🔗 **الرابط العلني المباشر:**\n{live_url}"
        )
    else:
        bot.send_message(chat_id, f"❌ فشل النشر: {err}")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    data = call.data

    if data.startswith("del_"):
        filename = data.replace("del_", "")
        bot.edit_message_text(f"⏳ جاري حذف الملف `{filename}`...", chat_id, call.message.message_id)
        success, res_msg = delete_from_github(filename)
        if success:
            remove_user_site(chat_id, filename)
            bot.send_message(chat_id, f"✅ تم حذف الملف `{filename}` بنجاح.")
        else:
            bot.send_message(chat_id, f"❌ خطأ بالحذف: {res_msg}")
        return

    if data == "pub_random":
        pending_codes[chat_id]['custom_name'] = f"site_{generate_random_name()}.html"
        execute_publishing_process(chat_id, call.message.message_id)

    elif data == "pub_custom":
        user_states[chat_id] = "waiting_custom_name"
        bot.edit_message_text("✏️ أرسل اسم الرابط المطلوب (مثلاً: `my-portfolio`):", chat_id, call.message.message_id)

    elif data == "menu_myfiles":
        show_my_files(call.message)

def process_telegram_tool(message, state):
    chat_id = message.chat.id
    text = message.text.strip()

    if state == "tool_ip_info":
        res = requests.get(f"http://ip-api.com/json/{text}").json()
        if res.get('status') == 'success':
            bot.send_message(chat_id, f"🌐 **بيانات IP:**\nالدولة: {res.get('country')}\nالمدينة: {res.get('city')}\nالمزود: {res.get('isp')}")
        else:
            bot.send_message(chat_id, "❌ متعذر جلب بيانات هذا الـ IP.")

    elif state == "tool_make_qr":
        img = qrcode.make(text)
        bio = io.BytesIO()
        img.save(bio, 'PNG')
        bio.seek(0)
        bot.send_photo(chat_id, bio, caption="📱 **رمز QR Code الخاص بك:**")

    user_states[chat_id] = None

# ==================== [ تشغيل التطبيق والسيرفر المزدوج المحصن ] ====================

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    print(f"🚀 جاري تشغيل سيرفر المتصفح وبوت التليجرام برعاية {DEVELOPER_NAME}...")
    
    # تشغيل سيرفر الويب في خلفية متوازية
    threading.Thread(target=run_flask, daemon=True).start()
    
    bot.remove_webhook()
    print("✅ السيرفر يعمل الآن على المتصفح وبوت يستقبل الطلبات بكفاءة عالية!")

    # حلقة حماية ذكية لتفادي أخطاء التضارب 409 أو توقف الحاوية على Render
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except ApiTelegramException as e:
            if e.error_code == 409:
                print("⚠️ تم اكتشاف تضارب (Conflict 409)، جارٍ إعادة الاتصال خلال 5 ثوانٍ...")
                time.sleep(5)
            else:
                print(f"⚠️ خطأ تليجرام رقم {e.error_code}: {e}")
                time.sleep(3)
        except Exception as e:
            print(f"⚠️ خطأ غير متوقع في الاتصال: {e}")
            time.sleep(5)
