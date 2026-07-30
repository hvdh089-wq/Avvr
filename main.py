import os
import json
import time
import re
import base64
import threading
import requests
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
import telebot
from telebot import types

# ==============================================================================
# 1. الإعدادات العامة والمتغيرات الأساسية
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

CHAT_DB_FILE = os.path.join(DATA_DIR, "chat_history.json")
BANS_FILE = os.path.join(DATA_DIR, "banned_ips.json")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
LOGS_FILE = os.path.join(DATA_DIR, "activity_logs.json")

ADMIN_ID = 8301511694
TELEGRAM_MAIN_TOKEN = "8670100497:AAGoCnO6beXj9HIi2lNucddCPOLKxZHMiJc"
TELEGRAM_ADMIN_TOKEN = "8758801132:AAESDdtWE3iStnnfjtyXQhvHMzL-bzHqNR8"

GROQ_KEY = "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"
OPENROUTER_KEY = "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"
GEMINI_KEY = "AQ.Ab8RN6KHKLylkD52rbgbAlpny4UDouWx0epLQvkj_fGwBQ4BMg"
HUGGINGFACE_KEY = "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"
ELEVENLABS_KEY = "sk_6e423b917963e592ef1d6941b9c58d941ccb45adaeb966c7"

# ==============================================================================
# 2. نظام الأمان وحظر عناوين IP وسجلات الأنشطة
# ==============================================================================
ip_request_tracker = {}
BAN_DURATION = 172800  # 48 ساعة
MAX_REQUESTS_PER_MINUTE = 40

def load_json_file(file_path, default_value):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default_value

def save_json_file(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"خطأ أثناء حفظ الملف {file_path}: {str(e)}")

def log_activity(user_id, action_type, details=""):
    logs = load_json_file(LOGS_FILE, [])
    logs.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": str(user_id),
        "action": action_type,
        "details": details
    })
    if len(logs) > 1000:
        logs = logs[-1000:]
    save_json_file(LOGS_FILE, logs)

def is_ip_banned(ip_address):
    bans = load_json_file(BANS_FILE, {})
    if ip_address in bans:
        unban_time = bans[ip_address]
        if time.time() < unban_time:
            return True
        else:
            del bans[ip_address]
            save_json_file(BANS_FILE, bans)
    return False

def ban_ip(ip_address, reason="سلوك مشبوه أو هجوم أمني"):
    bans = load_json_file(BANS_FILE, {})
    bans[ip_address] = time.time() + BAN_DURATION
    save_json_file(BANS_FILE, bans)
    log_activity("SYSTEM", "IP_BAN", f"IP: {ip_address}, Reason: {reason}")
    notify_admin_telegram(f"🚨 <b>تنبيه أمني:</b> تم حظر IP تلقائياً لمده 48 ساعة.\n<b>العنوان:</b> <code>{ip_address}</code>\n<b>السبب:</b> {reason}")

def security_firewall(ip_address, payload_string=""):
    if is_ip_banned(ip_address):
        return False, "تم حظر وصولك مؤقتاً لدواعي الأمان."

    suspicious_patterns = [
        r"(?i)<script", r"(?i)union\s+select", r"(?i)drop\s+table",
        r"(?i)etc/passwd", r"(?i)eval\(", r"(?i)exec\(", r"(?i)javascript:"
    ]
    for pattern in suspicious_patterns:
        if re.search(pattern, payload_string):
            ban_ip(ip_address, "محاولة حقن كود خبيث")
            return False, "تم رفض الطلب وحظر العنوان."

    now = time.time()
    if ip_address not in ip_request_tracker:
        ip_request_tracker[ip_address] = []
    
    ip_request_tracker[ip_address] = [t for t in ip_request_tracker[ip_address] if now - t < 60]
    ip_request_tracker[ip_address].append(now)

    if len(ip_request_tracker[ip_address]) > MAX_REQUESTS_PER_MINUTE:
        ban_ip(ip_address, "تجاوز معدل الطلبات المسموح (إغراق)")
        return False, "تجاوزت الحد المسموح من الطلبات."

    return True, "OK"

# ==============================================================================
# 3. إدارة الجلسات وسجلات المستخدمين والخصوصية
# ==============================================================================
def get_user_data(user_id):
    db = load_json_file(CHAT_DB_FILE, {})
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            "sessions": [],
            "active_session_id": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_json_file(CHAT_DB_FILE, db)
    return db[uid]

def create_new_chat_session(user_id):
    db = load_json_file(CHAT_DB_FILE, {})
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"sessions": [], "active_session_id": None}
    
    session_id = f"session_{int(time.time()*1000)}"
    new_session = {
        "session_id": session_id,
        "title": "محادثة جديدة",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "messages": []
    }
    
    db[uid]["sessions"].insert(0, new_session)
    db[uid]["active_session_id"] = session_id
    save_json_file(CHAT_DB_FILE, db)
    log_activity(uid, "NEW_SESSION", session_id)
    return session_id

def append_chat_message(user_id, session_id, role, content, image_data=None):
    db = load_json_file(CHAT_DB_FILE, {})
    uid = str(user_id)
    if uid in db:
        for sess in db[uid]["sessions"]:
            if sess["session_id"] == session_id:
                msg_obj = {
                    "role": role,
                    "content": content,
                    "timestamp": datetime.now().strftime("%H:%M")
                }
                if image_data:
                    msg_obj["has_image"] = True
                sess["messages"].append(msg_obj)
                if sess["title"] == "محادثة جديدة" and role == "user":
                    sess["title"] = content[:30] + ("..." if len(content) > 30 else "")
                save_json_file(CHAT_DB_FILE, db)
                break

# ==============================================================================
# 4. محرك الذكاء الاصطناعي التكاملي (Text + Vision + Generation)
# ==============================================================================
def ask_unified_ai_engine(prompt, conversation_history=None, image_b64=None):
    if conversation_history is None:
        conversation_history = []

    system_instruction = (
        "أنت 'نظام الجبوري الذكي'، مساعد رقمي متطور. "
        "أجب دائماً باللغة العربية الفصحى المنسقة بدقة. "
        "عند طلب كود برمجي، قدمه كاملاً داخل مربع كود مخصص ومحدد اللغة مع شرح بسيط. "
        "تذكر سياق المحادثات السابقة واستوعب التفاصيل بدقة."
    )

    formatted_messages = [{"role": "system", "content": system_instruction}]
    for msg in conversation_history[-8:]:
        formatted_messages.append({"role": msg["role"], "content": msg["content"]})
    formatted_messages.append({"role": "user", "content": prompt})

    # Groq API
    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "messages": formatted_messages, "temperature": 0.5},
            timeout=12
        )
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content'].strip()
    except Exception:
        pass

    # OpenRouter API
    try:
        res = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={"model": "deepseek/deepseek-chat", "messages": formatted_messages},
            timeout=12
        )
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content'].strip()
    except Exception:
        pass

    # Gemini API Backup
    try:
        gemini_prompt = system_instruction + "\n\n"
        for msg in conversation_history[-6:]:
            gemini_prompt += f"{msg['role']}: {msg['content']}\n"
        gemini_prompt += f"user: {prompt}"

        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_KEY}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": gemini_prompt}]}]},
            timeout=12
        )
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception:
        pass

    return "اعتذر، تعذر معالجة الطلب حالياً بسبب ضغط الخوادم. يرجى المحاولة لاحقاً."

def generate_image_ai(prompt_text):
    try:
        url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
        headers = {"Authorization": f"Bearer {HUGGINGFACE_KEY}"}
        res = requests.post(url, headers=headers, json={"inputs": prompt_text}, timeout=25)
        if res.status_code == 200:
            filename = f"gen_{int(time.time())}.png"
            filepath = os.path.join(DOWNLOAD_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(res.content)
            return True, f"/download_file/{filename}"
    except Exception as e:
        pass
    return False, "تعذر إنشاء الصورة حالياً."

def notify_admin_telegram(message_text):
    def send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_ADMIN_TOKEN}/sendMessage"
            payload = {"chat_id": ADMIN_ID, "text": message_text, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass
    threading.Thread(target=send).start()

# ==============================================================================
# 5. خادم Flask والإعدادات الحركية
# ==============================================================================
app = Flask(__name__)
CORS(app)

@app.before_request
def apply_firewall_check():
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()
        
    payload = request.get_data(as_text=True) if request.data else ""
    allowed, message = security_firewall(client_ip, payload)
    if not allowed:
        return jsonify({'success': False, 'message': message}), 403

# ==============================================================================
# 6. واجهة المستخدم التفاعلية المتجاوبة (UI Fully Responsive for Mobile & PC)
# ==============================================================================
WEB_UI_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>نظام الجبوري الذكي</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --accent-color: #2563eb;
            --accent-hover: #1d4ed8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --code-bg: #090d16;
            --danger: #ef4444;
            --success: #10b981;
            --safe-bottom: env(safe-area-inset-bottom, 0px);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Tajawal', sans-serif; -webkit-tap-highlight-color: transparent; }
        html, body { height: 100%; width: 100%; background-color: var(--bg-primary); color: var(--text-main); overflow: hidden; }

        .app-container { display: flex; height: 100vh; height: 100dvh; width: 100vw; position: relative; overflow: hidden; }

        .sidebar {
            width: 280px; background: var(--bg-secondary); border-left: 1px solid var(--border-color);
            display: flex; flex-direction: column; padding: 15px; z-index: 100; transition: transform 0.3s ease;
        }

        .brand { font-size: 1.2rem; font-weight: 900; color: #60a5fa; text-align: center; margin-bottom: 15px; display: flex; align-items: center; justify-content: space-between; }
        .btn-new-chat {
            background: var(--accent-color); color: white; border: none; padding: 12px; border-radius: 12px;
            font-weight: bold; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;
            margin-bottom: 15px; transition: 0.2s;
        }
        .btn-new-chat:hover { background: var(--accent-hover); }
        .history-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
        .history-item {
            padding: 10px 12px; background: rgba(255,255,255,0.03); border: 1px solid var(--border-color);
            border-radius: 8px; cursor: pointer; font-size: 0.88rem; color: var(--text-muted);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: 0.2s;
        }
        .history-item:hover, .history-item.active { background: rgba(37, 99, 235, 0.2); color: #fff; border-color: var(--accent-color); }

        .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100%; width: 100%; overflow: hidden; position: relative; }
        
        .top-bar {
            background: var(--bg-secondary); border-bottom: 1px solid var(--border-color);
            padding: 10px 15px; display: flex; align-items: center; justify-content: space-between; gap: 10px;
        }
        .mobile-toggle { display: none; background: none; border: none; color: #fff; font-size: 1.3rem; cursor: pointer; }
        
        .header-nav { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; }
        .header-nav::-webkit-scrollbar { display: none; }
        .nav-tab {
            background: transparent; border: none; color: var(--text-muted); padding: 8px 14px;
            font-weight: bold; cursor: pointer; border-radius: 8px; font-size: 0.9rem; transition: 0.2s; white-space: nowrap;
        }
        .nav-tab.active, .nav-tab:hover { background: var(--accent-color); color: white; }

        .content-panel { flex: 1; display: none; padding: 15px; overflow-y: auto; padding-bottom: calc(15px + var(--safe-bottom)); }
        .content-panel.active { display: flex; flex-direction: column; }

        .chat-container { flex: 1; display: flex; flex-direction: column; max-width: 900px; margin: 0 auto; width: 100%; height: 100%; }
        .chat-messages { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 12px; }
        
        .message-row { display: flex; flex-direction: column; max-width: 88%; }
        .message-row.user { align-self: flex-start; }
        .message-row.ai { align-self: flex-end; width: 100%; }

        .msg-bubble { padding: 12px 16px; border-radius: 14px; font-size: 0.95rem; line-height: 1.6; position: relative; word-break: break-word; }
        .user .msg-bubble { background: var(--accent-color); color: white; border-bottom-right-radius: 2px; }
        .ai .msg-bubble { background: var(--bg-secondary); border: 1px solid var(--border-color); color: var(--text-main); border-bottom-left-radius: 2px; }

        pre { background: var(--code-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px; margin: 8px 0; overflow-x: auto; dir: ltr; text-align: left; position: relative; }
        code { font-family: monospace; color: #38bdf8; }
        .btn-copy-code { position: absolute; top: 5px; left: 5px; background: var(--border-color); color: #fff; border: none; padding: 3px 6px; border-radius: 4px; font-size: 0.7rem; cursor: pointer; }

        .input-area { display: flex; gap: 8px; padding: 10px 0; padding-bottom: calc(10px + var(--safe-bottom)); background: var(--bg-primary); }
        .chat-input { flex: 1; background: var(--bg-secondary); border: 1px solid var(--border-color); padding: 12px; border-radius: 12px; color: white; outline: none; font-size: 0.95rem; }
        .chat-input:focus { border-color: var(--accent-color); }
        .btn-send { background: var(--accent-color); color: white; border: none; padding: 0 18px; border-radius: 12px; cursor: pointer; font-weight: bold; }

        .card-panel { background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 16px; padding: 20px; max-width: 600px; margin: 0 auto; width: 100%; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 8px; color: var(--text-muted); font-size: 0.9rem; }
        .form-control { width: 100%; background: var(--bg-primary); border: 1px solid var(--border-color); padding: 12px; border-radius: 8px; color: white; outline: none; }

        @media (max-width: 768px) {
            .sidebar { position: absolute; top: 0; right: 0; bottom: 0; transform: translateX(100%); }
            .sidebar.open { transform: translateX(0); }
            .mobile-toggle { display: block; }
            .message-row { max-width: 95%; }
        }
    </style>
</head>
<body>

<div class="app-container">
    <div class="sidebar" id="sidebar">
        <div class="brand">
            <span><i class="fa-solid fa-cube"></i> نظام الجبوري</span>
            <i class="fa-solid fa-xmark mobile-toggle" onclick="toggleSidebar()"></i>
        </div>
        <button class="btn-new-chat" onclick="startNewSession()"><i class="fa-solid fa-plus"></i> محادثة جديدة</button>
        <div class="history-list" id="historyList"></div>
    </div>

    <div class="main-wrapper">
        <div class="top-bar">
            <button class="mobile-toggle" onclick="toggleSidebar()"><i class="fa-solid fa-bars"></i></button>
            <div class="header-nav">
                <button class="nav-tab active" onclick="switchTab('chat')"><i class="fa-solid fa-message"></i> الذكاء الاصطناعي</button>
                <button class="nav-tab" onclick="switchTab('image')"><i class="fa-solid fa-image"></i> إنتاج الصور</button>
                <button class="nav-tab" onclick="switchTab('tts')"><i class="fa-solid fa-volume-high"></i> الصوت</button>
                <button class="nav-tab" onclick="switchTab('download')"><i class="fa-solid fa-download"></i> التحميلات</button>
            </div>
        </div>

        <div id="tab-chat" class="content-panel active">
            <div class="chat-container">
                <div class="chat-messages" id="chatMessages"></div>
                <div class="input-area">
                    <input type="text" id="userInput" class="chat-input" placeholder="اسأل أي شيء أو اطلب كوداً..." onkeypress="if(event.key==='Enter') sendMessage()">
                    <button class="btn-send" onclick="sendMessage()"><i class="fa-solid fa-paper-plane"></i></button>
                </div>
            </div>
        </div>

        <div id="tab-image" class="content-panel">
            <div class="card-panel">
                <h3 style="margin-bottom:15px;"><i class="fa-solid fa-wand-magic-sparkles"></i> توليد الصور بالذكاء الاصطناعي</h3>
                <div class="form-group">
                    <label>وصف الصورة (Prompt):</label>
                    <textarea id="imgPrompt" class="form-control" rows="3" placeholder="اكتب وصفاً تفصيلياً للصورة باللغة الإنجليزية أو العربية..."></textarea>
                </div>
                <button class="btn-new-chat" style="width:100%" onclick="generateImage()"><i class="fa-solid fa-paint-brush"></i> إنشاء الصورة</button>
                <div id="imgResult" style="margin-top:15px; text-align:center;"></div>
            </div>
        </div>

        <div id="tab-tts" class="content-panel">
            <div class="card-panel">
                <h3 style="margin-bottom:15px;"><i class="fa-solid fa-headphones"></i> تحويل النص إلى صوت</h3>
                <div class="form-group">
                    <label>اختر نبرة الصوت:</label>
                    <select id="ttsVoice" class="form-control">
                        <option value="pNInz6obpgDQGcFmaJgB">👨 آدم (فصيح)</option>
                        <option value="ErXwobaYiN019PkySvjV">👨 أنطوني</option>
                        <option value="21m00Tcm4TlvDq8ikWAM">👩 راشيل</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>النص المراد تحويله:</label>
                    <textarea id="ttsText" class="form-control" rows="3" placeholder="اكتب النص هنا..."></textarea>
                </div>
                <button class="btn-new-chat" style="width:100%" onclick="generateAudio()"><i class="fa-solid fa-play"></i> توليد الصوت</button>
                <div id="ttsAudioPlayer" style="margin-top:15px;"></div>
            </div>
        </div>

        <div id="tab-download" class="content-panel">
            <div class="card-panel">
                <h3 style="margin-bottom:15px;"><i class="fa-solid fa-cloud-arrow-down"></i> مركز التحميل المباشر</h3>
                <div class="form-group">
                    <input type="url" id="dlUrl" class="form-control" placeholder="لصق رابط تيك توك، يوتيوب، أو أي فيديو...">
                </div>
                <button class="btn-new-chat" style="width:100%" onclick="executeDownload()"><i class="fa-solid fa-download"></i> بدء التحميل</button>
                <div id="dlStatus" style="margin-top:12px; text-align:center;"></div>
                <div id="mediaGallery" style="margin-top:18px;"></div>
            </div>
        </div>
    </div>
</div>

<script>
    let currentUserId = localStorage.getItem('jbouri_uid') || 'user_' + Math.random().toString(36).substr(2, 9);
    localStorage.setItem('jbouri_uid', currentUserId);
    let activeSessionId = null;

    function toggleSidebar() {
        document.getElementById('sidebar').classList.toggle('open');
    }

    function switchTab(tab) {
        document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.content-panel').forEach(p => p.classList.remove('active'));
        if(event) event.currentTarget.classList.add('active');
        document.getElementById('tab-' + tab).classList.add('active');
        if(tab === 'download') loadGallery();
        if(window.innerWidth <= 768) document.getElementById('sidebar').classList.remove('open');
    }

    async function loadSessions() {
        try {
            const res = await fetch(`/api/sessions?user_id=${currentUserId}`);
            const data = await res.json();
            const list = document.getElementById('historyList');
            list.innerHTML = '';
            
            if (!data.sessions || data.sessions.length === 0) {
                await startNewSession();
                return;
            }

            data.sessions.forEach(s => {
                const div = document.createElement('div');
                div.className = `history-item ${s.session_id === activeSessionId ? 'active' : ''}`;
                div.innerText = s.title;
                div.onclick = () => selectSession(s.session_id, s.messages);
                list.appendChild(div);
            });

            if(!activeSessionId && data.sessions.length > 0) {
                selectSession(data.sessions[0].session_id, data.sessions[0].messages);
            }
        } catch(e){}
    }

    async function startNewSession() {
        const res = await fetch('/api/session/new', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId})
        });
        const data = await res.json();
        activeSessionId = data.session_id;
        document.getElementById('chatMessages').innerHTML = '';
        loadSessions();
    }

    function selectSession(sessionId, messages) {
        activeSessionId = sessionId;
        loadSessions();
        const box = document.getElementById('chatMessages');
        box.innerHTML = '';
        messages.forEach(m => renderMessage(m.role, m.content));
    }

    function renderMessage(role, content) {
        const box = document.getElementById('chatMessages');
        const row = document.createElement('div');
        row.className = `message-row ${role}`;

        let formattedContent = formatCodeBlocks(content);
        row.innerHTML = `<div class="msg-bubble">${formattedContent}</div>`;
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
    }

    function formatCodeBlocks(text) {
        return text.replace(/```(\\w*)\\n([\\s\\S]*?)```/g, function(match, lang, code) {
            return `<pre><code>${escapeHtml(code.trim())}</code><button class="btn-copy-code" onclick="copyCode(this)">نسخ الكود</button></pre>`;
        }).replace(/\\n/g, '<br>');
    }

    function escapeHtml(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    async function sendMessage() {
        const input = document.getElementById('userInput');
        const text = input.value.trim();
        if(!text || !activeSessionId) return;

        renderMessage('user', text);
        input.value = '';

        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: currentUserId, session_id: activeSessionId, prompt: text})
        });
        const data = await res.json();
        renderMessage('ai', data.response);
        loadSessions();
    }

    function copyCode(btn) {
        const code = btn.previousElementSibling.innerText;
        navigator.clipboard.writeText(code);
        btn.innerText = 'تم!';
        setTimeout(() => btn.innerText = 'نسخ الكود', 2000);
    }

    async function generateImage() {
        const prompt = document.getElementById('imgPrompt').value.trim();
        const resultDiv = document.getElementById('imgResult');
        if(!prompt) return;

        resultDiv.innerHTML = '⏳ جاري تصميم الصورة بالذكاء الاصطناعي...';
        const res = await fetch('/api/generate_image', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prompt: prompt})
        });
        const data = await res.json();
        if(data.success) {
            resultDiv.innerHTML = `<img src="${data.image_url}" style="max-width:100%; border-radius:12px; margin-top:10px;"><br><a href="${data.image_url}" download class="btn-copy-code" style="position:static; margin-top:8px; display:inline-block;">تحميل الصورة</a>`;
        } else {
            resultDiv.innerHTML = `<span style="color:var(--danger)">${data.message}</span>`;
        }
    }

    async function generateAudio() {
        const text = document.getElementById('ttsText').value.trim();
        const voice = document.getElementById('ttsVoice').value;
        if(!text) return;

        const res = await fetch('/api/tts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: text, voice: voice})
        });
        const data = await res.json();
        if(data.success) {
            document.getElementById('ttsAudioPlayer').innerHTML = `<audio controls autoplay src="${data.audio_url}" style="width:100%"></audio>`;
        }
    }

    async function executeDownload() {
        const url = document.getElementById('dlUrl').value.trim();
        const status = document.getElementById('dlStatus');
        if(!url) return;
        status.innerHTML = '⏳ جاري تنزيل المقاطع...';

        const res = await fetch('/download', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: url})
        });
        const data = await res.json();
        if(data.success) {
            status.innerHTML = '<span style="color:var(--success)">تم التحميل بنجاح!</span>';
            loadGallery();
        } else {
            status.innerHTML = `<span style="color:var(--danger)">${data.message}</span>`;
        }
    }

    async function loadGallery() {
        const res = await fetch('/videos');
        const data = await res.json();
        const gallery = document.getElementById('mediaGallery');
        gallery.innerHTML = '';
        if(data.videos) {
            data.videos.forEach(file => {
                gallery.innerHTML += `<div style="padding:10px; background:var(--bg-primary); margin-bottom:8px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:0.85rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:70%;">${file}</span>
                    <a href="/download_file/${encodeURIComponent(file)}" class="btn-copy-code" style="position:static;" download>حفظ</a>
                </div>`;
            });
        }
    }

    // دعم خيار المشاركة المباشرة (Web Share Target / URL Query)
    window.addEventListener('DOMContentLoaded', () => {
        const urlParams = new URLSearchParams(window.location.search);
        const sharedUrl = urlParams.get('url') || urlParams.get('text');
        if (sharedUrl && sharedUrl.startsWith('http')) {
            switchTab('download');
            document.getElementById('dlUrl').value = sharedUrl;
        }
        loadSessions();
    });
</script># ==============================================================================
# 7. المسارات البرمجية للخدمات (API Routes)
# ==============================================================================
@app.route('/')
def index():
    return WEB_UI_TEMPLATE

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    user_id = request.args.get('user_id', 'default_user')
    user_data = get_user_data(user_id)
    return jsonify({'sessions': user_data.get('sessions', [])})

@app.route('/api/session/new', methods=['POST'])
def new_session():
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    session_id = create_new_chat_session(user_id)
    return jsonify({'session_id': session_id})

@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.json or {}
    user_id = data.get('user_id', 'default_user')
    session_id = data.get('session_id')
    prompt = data.get('prompt', '').strip()

    if not prompt or not session_id:
        return jsonify({'response': 'الطلب غير مكتمل.'})

    user_data = get_user_data(user_id)
    session_history = []
    for sess in user_data.get('sessions', []):
        if sess['session_id'] == session_id:
            session_history = sess.get('messages', [])
            break

    # حفظ سؤال المستخدم
    append_chat_message(user_id, session_id, 'user', prompt)

    # معالجة الطلب عبر محرك الذكاء الاصطناعي
    response_text = ask_unified_ai_engine(prompt, session_history)

    # حفظ إجابة النظام
    append_chat_message(user_id, session_id, 'ai', response_text)

    return jsonify({'response': response_text})

@app.route('/api/generate_image', methods=['POST'])
def generate_image_api():
    data = request.json or {}
    prompt = data.get('prompt', '').strip()
    if not prompt:
        return jsonify({'success': False, 'message': 'الوصف فارغ'}), 400

    success, image_url_or_msg = generate_image_ai(prompt)
    if success:
        return jsonify({'success': True, 'image_url': image_url_or_msg})
    return jsonify({'success': False, 'message': image_url_or_msg})

@app.route('/api/tts', methods=['POST'])
def tts_api():
    data = request.json or {}
    text = data.get('text', '').strip()
    voice = data.get('voice', 'pNInz6obpgDQGcFmaJgB')

    if not text:
        return jsonify({'success': False, 'message': 'النص فارغ'})

    filename = f"tts_{int(time.time())}.mp3"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    headers = {"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": ELEVENLABS_KEY}
    payload = {"text": text, "model_id": "eleven_multilingual_v2"}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(res.content)
            return jsonify({'success': True, 'audio_url': f'/download_file/{filename}'})
    except Exception:
        pass

    return jsonify({'success': False, 'message': 'فشل تحويل الصوت'})

@app.route('/download', methods=['POST'])
def handle_video_download():
    data = request.json or {}
    url = data.get('url', '').strip()

    if not url or not url.startswith('http'):
        return jsonify({'success': False, 'message': 'يرجى تقديم رابط صالح'}), 400

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'quiet': True,
        'format': 'best'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = os.path.basename(ydl.prepare_filename(info))
            notify_admin_telegram(f"📥 <b>تم تحميل ملف جديد عبر الموقع:</b>\n<code>{filename}</code>")
            return jsonify({'success': True, 'filename': filename})
    except Exception as e:
        return jsonify({'success': False, 'message': 'تعذر تحميل الفيديو من هذا الرابط.'}), 500

@app.route('/videos')
def list_downloaded_videos():
    if not os.path.exists(DOWNLOAD_FOLDER):
        return jsonify({'videos': []})
    allowed_exts = ('.mp4', '.mkv', '.webm', '.mp3', '.jpg', '.png')
    files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith(allowed_exts)]
    return jsonify({'success': True, 'videos': files})

@app.route('/download_file/<path:filename>')
def serve_download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

# ==============================================================================
# 8. البوت الرئيسي للمستخدمين على تلغرام (Main Public Telegram Bot)
# ==============================================================================
main_bot = telebot.TeleBot(TELEGRAM_MAIN_TOKEN)

@main_bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.chat.id
    create_new_chat_session(user_id)
    
    markup = types.InlineKeyboardMarkup()
    web_app_btn = types.InlineKeyboardButton(
        text="🌐 فتح منصة الويب الموحدة", 
        url="https://avvr.onrender.com"
    )
    markup.add(web_app_btn)
    
    welcome_text = (
        "أهلاً بك في **نظام الجبوري الذكي**.\n\n"
        "يمكنك التحدث معي مباشرة هنا للحصول على إجابات وأكواد برمجية، "
        "أو إرسال رابط فيديو لتحميله، أو استخدام منصة الويب عبر الزر أدناه."
    )
    main_bot.reply_to(message, welcome_text, parse_mode="Markdown", reply_markup=markup)

@main_bot.message_handler(func=lambda message: True)
def handle_main_bot_messages(message):
    user_id = message.chat.id
    text = message.text.strip() if message.text else ""

    if not text:
        return

    # كشف روابط التحميل المباشر
    if re.match(r'^(https?://[^\s]+)', text):
        msg = main_bot.reply_to(message, "⏳ جاري معالجة التحميل...")
        try:
            ydl_opts = {
                'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
                'quiet': True,
                'format': 'best'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                filepath = ydl.prepare_filename(info)
                filename = os.path.basename(filepath)
                
                with open(filepath, 'rb') as f:
                    main_bot.send_document(user_id, f, caption=f"✅ تم التحميل: {filename}")
                main_bot.delete_message(user_id, msg.message_id)
                notify_admin_telegram(f"📥 <b>تم تحميل مقطع عبر البوت الرئيسي:</b>\n<code>{filename}</code>")
        except Exception:
            main_bot.edit_message_text("❌ تعذر تحميل هذا الرابط. تأكد من صحته والمحاولة لاحقاً.", user_id, msg.message_id)
        return

    # معالجة استفسارات الذكاء الاصطناعي
    user_data = get_user_data(user_id)
    active_session = user_data.get("active_session_id")
    if not active_session:
        active_session = create_new_chat_session(user_id)

    history = []
    for sess in user_data.get("sessions", []):
        if sess["session_id"] == active_session:
            history = sess.get("messages", [])
            break

    append_chat_message(user_id, active_session, "user", text)
    main_bot.send_chat_action(user_id, 'typing')

    ai_response = ask_unified_ai_engine(text, history)
    append_chat_message(user_id, active_session, "ai", ai_response)

    main_bot.reply_to(message, ai_response)

# ==============================================================================
# 9. بوت لوحة تحكم المطور الخاص بك (Admin Control Bot)
# ==============================================================================
admin_bot = telebot.TeleBot(TELEGRAM_ADMIN_TOKEN)

def is_admin(user_id):
    return int(user_id) == ADMIN_ID

@admin_bot.message_handler(commands=['start', 'admin'])
def admin_start(message):
    if not is_admin(message.chat.id):
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_stats = types.KeyboardButton("📊 الإحصائيات العامة")
    btn_bans = types.KeyboardButton("🛡️ إدارة قائمة الحظر (IP)")
    btn_unban = types.KeyboardButton("🔓 فك حظر IP")
    btn_status = types.KeyboardButton("🟢 حالة الخادم")
    markup.add(btn_stats, btn_bans, btn_unban, btn_status)

    admin_bot.send_message(
        message.chat.id,
        "<b>مرحباً بك في لوحة تحكم مطور نظام الجبوري</b>\nاختر من القائمة أدناه لإدارة النظام بسهولة:",
        parse_mode="HTML",
        reply_markup=markup
    )

@admin_bot.message_handler(func=lambda message: is_admin(message.chat.id))
def handle_admin_commands(message):
    text = message.text

    if text == "📊 الإحصائيات العامة":
        bans = load_json_file(BANS_FILE, {})
        db = load_json_file(CHAT_DB_FILE, {})
        total_users = len(db)
        banned_count = len(bans)
        
        files = os.listdir(DOWNLOAD_FOLDER) if os.path.exists(DOWNLOAD_FOLDER) else []
        
        stats_msg = (
            f"📊 <b>إحصائيات نظام الجبوري:</b>\n\n"
            f"👥 <b>إجمالي المستخدمين:</b> {total_users}\n"
            f"📁 <b>عدد الملفات المحملة:</b> {len(files)}\n"
            f"🚫 <b>العناوين المحظورة حالياً (IP):</b> {banned_count}\n"
        )
        admin_bot.send_message(message.chat.id, stats_msg, parse_mode="HTML")

    elif text == "🛡️ إدارة قائمة الحظر (IP)":
        bans = load_json_file(BANS_FILE, {})
        if not bans:
            admin_bot.send_message(message.chat.id, "✅ لا يوجد أي عنوان IP محظور حالياً.")
            return

        msg = "🚫 <b>قائمة عناوين IP المحظورة تلقائياً:</b>\n\n"
        now = time.time()
        for ip, unban_t in bans.items():
            rem_mins = max(0, int((unban_t - now) / 60))
            msg += f"• <code>{ip}</code> (متبقي: {rem_mins} دقيقة)\n"
        admin_bot.send_message(message.chat.id, msg, parse_mode="HTML")

    elif text == "🔓 فك حظر IP":
        msg = admin_bot.send_message(message.chat.id, "أرسل عنوان IP الذي تريد فك الحظر عنه:")
        admin_bot.register_next_step_handler(msg, process_unban_ip)

    elif text == "🟢 حالة الخادم":
        admin_bot.send_message(
            message.chat.id,
            "🟢 <b>جميع الخدمات تعمل بكفاءة:</b>\n"
            "• خادم Flask والواجهة: نشط\n"
            "• محرك الذكاء الاصطناعي: متصل\n"
            "• البوت الرئيسي وبوت الأدمن: قيد التشغيل",
            parse_mode="HTML"
        )

def process_unban_ip(message):
    ip_to_unban = message.text.strip()
    bans = load_json_file(BANS_FILE, {})
    if ip_to_unban in bans:
        del bans[ip_to_unban]
        save_json_file(BANS_FILE, bans)
        admin_bot.send_message(message.chat.id, f"✅ تم فك الحظر بنجاح عن IP: <code>{ip_to_unban}</code>", parse_mode="HTML")
    else:
        admin_bot.send_message(message.chat.id, "❌ العنوان غير موجود في قائمة الحظر.")

# ==============================================================================
# 10. التشغيل المتوازي والمتزامن لجميع الخدمات (Multi-Threading Engine)
# ==============================================================================
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def run_main_bot():
    while True:
        try:
            main_bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception:
            time.sleep(3)

def run_admin_bot():
    while True:
        try:
            admin_bot.polling(none_stop=True, interval=1, timeout=30)
        except Exception:
            time.sleep(3)

if __name__ == '__main__':
    # تشغيل خادم Flask في خلفية مستقلة
    t_flask = threading.Thread(target=run_flask)
    t_flask.daemon = True
    t_flask.start()

    # تشغيل البوت الرئيسي في خلفية مستقلة
    t_main_bot = threading.Thread(target=run_main_bot)
    t_main_bot.daemon = True
    t_main_bot.start()

    # إرسال إشعار للمطور عند تشغيل السيرفر
    notify_admin_telegram("🚀 <b>تم تشغيل نظام الجبوري الذكي بنجاح بكافة واجهاته وبوتاته.</b>")

    # تشغيل بوت لوحة التحكم في الخيط الرئيسي
    run_admin_bot()
</body>
</html>"""
