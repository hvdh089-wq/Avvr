import os
import re
import json
import time
import threading
import datetime
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

# ==========================================
# 1. الإعدادات والمسارات الرئيسية
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads", "JbouriApp")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

STATS_FILE = os.path.join(DATA_DIR, "stats.json")
BANNED_IPS_FILE = os.path.join(DATA_DIR, "banned_ips.json")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "chat_history.json")

# بيانات بوت الإدارة (مطور جبوري)
TELEGRAM_TOKEN = "8132377085:AAGNc0uYSU_5H6wHTxEzTSMYhYssEc6mKsw"
TELEGRAM_CHAT_ID = "8301511694"

UNIFIED_AI_NAME = "نظام جبوري الذكي"
SYSTEM_PROMPT_AR = """أنت 'نظام جبوري الذكي'، المساعد الذكي الموحد والتطويري الشامل.
- تتحدث بلسان عربي فصيح، دقيق، وسلس دون أي طلاسم أو ترجمة ركيكة.
- تتوحد جميع نماذج الذكاء الاصطناعي تحت اسمك وكيانك الموحد.
- تتذكر جميع سياقات المحادثة الممررة إليك بدقة متناهية.
- عند كتابة الأكواد البرمجية، تقدم كوداً ناصع الجودة وخالياً من الأخطاء مع توضيح مبسط."""

# ==========================================
# 2. إدارة البيانات المحلية (JSON DB)
# ==========================================
def load_json_file(filepath, default_data):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return default_data

def save_json_file(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[Error Saving JSON]: {e}")

stats_db = load_json_file(STATS_FILE, {
    "total_downloads": 0,
    "total_ai_messages": 0,
    "attacks_blocked": 0,
    "start_time": time.time()
})

banned_ips_db = load_json_file(BANNED_IPS_FILE, {})
chat_history_db = load_json_file(CHAT_HISTORY_FILE, {})

# ==========================================
# 3. بوت تيليجرام الإداري والتحكم عن بعد
# ==========================================
def send_telegram_alert(text, parse_mode="HTML"):
    def _send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode}
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Telegram Error]: {e}")
    threading.Thread(target=_send, daemon=True).start()

def handle_admin_telegram_commands(cmd_text):
    """معالجة أوامر المطور الواردة من بوت تيليجرام"""
    cmd = cmd_text.strip()
    if cmd == "/stats":
        msg = (
            f"📊 <b>إحصائيات {UNIFIED_AI_NAME}</b>\n\n"
            f"💬 عدد رسائل الذكاء: <code>{stats_db.get('total_ai_messages', 0)}</code>\n"
            f"📥 عدد التحميلات: <code>{stats_db.get('total_downloads', 0)}</code>\n"
            f"🛡️ الهجمات المحظورة: <code>{stats_db.get('attacks_blocked', 0)}</code>\n"
            f"🚫 عدد IP المحظورة حالياً: <code>{len(banned_ips_db)}</code>"
        )
        send_telegram_alert(msg)

    elif cmd == "/banned":
        if not banned_ips_db:
            send_telegram_alert("ℹ️ لا يوجد أي عنوان IP محظور حالياً.")
            return
        lines = ["<b>قائمة العناوين المحظورة (48 ساعة):</b>"]
        for ip, info in banned_ips_db.items():
            lines.append(f"• <code>{ip}</code> - السبب: {info.get('reason')}")
        send_telegram_alert("\n".join(lines))

    elif cmd.startswith("/unban"):
        parts = cmd.split()
        if len(parts) > 1:
            target_ip = parts[1].strip()
            if target_ip in banned_ips_db:
                del banned_ips_db[target_ip]
                save_json_file(BANNED_IPS_FILE, banned_ips_db)
                send_telegram_alert(f"✅ تم فك الحظر عن العنوان: <code>{target_ip}</code>")
            else:
                send_telegram_alert("⚠️ العنوان غير موجود في قائمة الحظر.")

def telegram_long_polling():
    """استقبال الأوامر الإدارية من بوت تيليجرام في الخلفية"""
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = requests.get(url, timeout=12).json()
            if res.get("ok"):
                for result in res.get("result", []):
                    offset = result["update_id"] + 1
                    msg = result.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if chat_id == TELEGRAM_CHAT_ID:
                        handle_admin_telegram_commands(text)
        except Exception:
            pass
        time.sleep(2)

threading.Thread(target=telegram_long_polling, daemon=True).start()
send_telegram_alert(f"🟢 <b>تم تشغيل نظام {UNIFIED_AI_NAME} وجدار الحماية بنجاح!</b>")

# ==========================================
# 4. جدار الحماية (Security WAF & 48h Ban)
# ==========================================
SUSPICIOUS_PATTERNS = [
    r"(?i)<script.*?>", r"(?i)javascript:", r"(?i)union.*select",
    r"(?i)select.*from", r"(?i)drop.*table", r"(?i)insert.*into",
    r"(?i)eval\(", r"(?i)base64_decode", r"\.\./\.\.", r"(?i)etc/passwd"
]

BLOCKED_USER_AGENTS = ["burpsuite", "sqlmap", "nikto", "nmap", "owasp", "acunetix", "w3af"]
RATE_LIMIT_STORE = {}
BAN_DURATION = 2 * 24 * 3600  # حظر لمدة 48 ساعة

def ban_ip_address(ip_addr, reason):
    unban_time = time.time() + BAN_DURATION
    banned_ips_db[ip_addr] = {
        "unban_at": unban_time,
        "reason": reason,
        "banned_date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    save_json_file(BANNED_IPS_FILE, banned_ips_db)
    stats_db["attacks_blocked"] += 1
    save_json_file(STATS_FILE, stats_db)
    
    send_telegram_alert(
        f"🚨 <b>تم حظر IP تلقائياً لمدة 48 ساعة!</b>\n"
        f"🌐 <b>IP:</b> <code>{ip_addr}</code>\n"
        f"⚠️ <b>السبب:</b> {reason}"
    )

@app.before_request
def security_firewall():
    client_ip = request.remote_addr or request.headers.get('X-Forwarded-For', 'Unknown')
    now = time.time()

    # 1. فحص قائمة الحظر
    if client_ip in banned_ips_db:
        unban_at = banned_ips_db[client_ip].get("unban_at", 0)
        if now < unban_at:
            rem_h = round((unban_at - now) / 3600, 1)
            return jsonify({"error": True, "message": f"تم حظر وصولك لمدة 48 ساعة. المتبقي: {rem_h} ساعة."}), 403
        else:
            del banned_ips_db[client_ip]
            save_json_file(BANNED_IPS_FILE, banned_ips_db)

    # 2. فحص الأدوات المحظورة
    user_agent = request.headers.get('User-Agent', '').lower()
    for blocked_ua in BLOCKED_USER_AGENTS:
        if blocked_ua in user_agent:
            ban_ip_address(client_ip, f"أداة فحص محظورة ({blocked_ua})")
            return jsonify({"error": True, "message": "Access Denied"}), 403

    # 3. منع هجمات حجب الخدمة (DDoS / Rate Limiting)
    timestamps = RATE_LIMIT_STORE.get(client_ip, [])
    timestamps = [t for t in timestamps if now - t < 10]
    timestamps.append(now)
    RATE_LIMIT_STORE[client_ip] = timestamps

    if len(timestamps) > 35:
        ban_ip_address(client_ip, "محاولة إغراق الخادم (Anti-DDoS)")
        return jsonify({"error": True, "message": "Too many requests. IP Banned."}), 429

    # 4. فحص محتوى الطلبات (SQLi / XSS)
    req_data = ""
    if request.method in ['POST', 'PUT']:
        try:
            req_data = request.get_data(as_text=True) or ""
        except Exception:
            pass
    full_payload = request.query_string.decode('utf-8', errors='ignore') + " " + req_data

    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, full_payload):
            ban_ip_address(client_ip, f"نمط مشبوه ({pattern})")
            return jsonify({"error": True, "message": "Security Alert"}), 400

# ==========================================
# 5. محرك الذكاء الاصطناعي والمسارات
# ==========================================
def ask_unified_ai_engine(prompt, session_history=None, image_data=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT_AR}]
    if session_history:
        for msg in session_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    user_content = prompt
    if image_data:
        user_content = f"[تم إرفاق صورة لتحليلها]: {prompt}"
    messages.append({"role": "user", "content": user_content})

    try:
        ai_api_key = os.environ.get('AI_API_KEY', '')
        if ai_api_key:
            res = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {ai_api_key}"},
                json={"model": "gpt-4o-mini", "messages": messages, "temperature": 0.7},
                timeout=25
            )
            if res.status_code == 200:
                return res.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"[AI Engine Error]: {e}")

    if image_data:
        return f"تم استلام الصورة بنجاح وتوجيه التحليل النصي المرفق: '{prompt}'."
    return f"مرحباً بك! أنا **{UNIFIED_AI_NAME}**. استلمت استفسارك: '{prompt}'. أنا جاهز لمساعدتك بكتابة الأكواد، تحليل النصوص، والإجابة عن جميع أسئلتك بدقة."

@app.route('/api/chat', methods=['POST'])
def handle_chat():
    data = request.json or {}
    session_id = data.get('session_id', '').strip()
    prompt = data.get('prompt', '').strip()
    image_b64 = data.get('image', None)

    if not prompt and not image_b64:
        return jsonify({'success': False, 'message': 'الرجاء كتابة نص أو إرسال صورة.'}), 400

    if not session_id:
        session_id = f"sess_{int(time.time() * 1000)}"

    session_data = chat_history_db.get(session_id, {
        "title": prompt[:30] if prompt else "محادثة جديدة",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "messages": []
    })

    ai_response = ask_unified_ai_engine(prompt, session_data["messages"], image_b64)

    session_data["messages"].append({"role": "user", "content": prompt, "time": time.strftime("%H:%M")})
    session_data["messages"].append({"role": "assistant", "content": ai_response, "time": time.strftime("%H:%M")})

    chat_history_db[session_id] = session_data
    save_json_file(CHAT_HISTORY_FILE, chat_history_db)

    stats_db["total_ai_messages"] += 1
    save_json_file(STATS_FILE, stats_db)

    return jsonify({'success': True, 'session_id': session_id, 'response': ai_response})

@app.route('/api/sessions', methods=['GET'])
def get_user_sessions():
    sessions_summary = []
    for sess_id, sess_info in chat_history_db.items():
        sessions_summary.append({
            "session_id": sess_id,
            "title": sess_info.get("title", "محادثة"),
            "created_at": sess_info.get("created_at", ""),
            "msg_count": len(sess_info.get("messages", []))
        })
    sessions_summary.sort(key=lambda x: x["created_at"], reverse=True)
    return jsonify({'success': True, 'sessions': sessions_summary})

@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session_detail(session_id):
    sess_info = chat_history_db.get(session_id)
    if not sess_info:
        return jsonify({'success': False, 'message': 'المحادثة غير موجودة'}), 404
    return jsonify({'success': True, 'session': sess_info})

@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    if session_id in chat_history_db:
        del chat_history_db[session_id]
        save_json_file(CHAT_HISTORY_FILE, chat_history_db)
        return jsonify({'success': True, 'message': 'تم الحذف'})
    return jsonify({'success': False, 'message': 'غير موجود'}), 404

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    data = request.json or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'message': 'لا يوجد نص'}), 400

    audio_filename = f"speech_{int(time.time())}.mp3"
    filepath = os.path.join(DOWNLOAD_FOLDER, audio_filename)

    try:
        tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={requests.utils.quote(text[:250])}&tl=ar&client=tw-ob"
        res = requests.get(tts_url, timeout=10)
        if res.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(res.content)
            return jsonify({'success': True, 'audio_url': f'/download_file/{audio_filename}'})
    except Exception as e:
        print(f"[TTS Error]: {e}")

    return jsonify({'success': False, 'message': 'تعذر تحويل النص إلى صوت'}), 500

@app.route('/download', methods=['POST'])
def handle_media_download():
    data = request.json or {}
    url = data.get('url', '').strip()

    if not url or not url.startswith(('http://', 'https://')):
        return jsonify({'success': False, 'message': 'رابط غير صالح.'}), 400

    ydl_opts = {
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'format': 'best'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = os.path.basename(ydl.prepare_filename(info))

            stats_db["total_downloads"] += 1
            save_json_file(STATS_FILE, stats_db)
            send_telegram_alert(f"📥 <b>تم تحميل فيديو جديد:</b>\n<code>{filename}</code>")
            return jsonify({'success': True, 'filename': filename})
    except Exception:
        return jsonify({'success': False, 'message': 'تعذر تحميل الفيديو.'}), 500

@app.route('/videos', methods=['GET'])
def list_downloaded_media():
    if not os.path.exists(DOWNLOAD_FOLDER):
        return jsonify({'success': True, 'videos': []})
    allowed = ('.mp4', '.mkv', '.webm', '.mp3', '.jpg', '.png')
    files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.lower().endswith(allowed)]
    return jsonify({'success': True, 'videos': files})

@app.route('/download_file/<path:filename>')
def serve_downloaded_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

# ==========================================
# 6. واجهة المستخدم الاحترافية (HTML/CSS/JS)
# ==========================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>نظام جبوري الذكي</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap');
        
        :root {
            --bg-main: #0f172a;
            --bg-card: #1e293b;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --accent: #38bdf8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: #334155;
            --user-msg: #1e3a8a;
            --ai-msg: #1e293b;
            --danger: #ef4444;
            --success: #10b981;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Tajawal', sans-serif; }
        body { background: var(--bg-main); color: var(--text-main); height: 100vh; display: flex; overflow: hidden; }

        .sidebar {
            width: 280px;
            background: #090d16;
            border-left: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            z-index: 100;
        }
        .sidebar-header { padding: 20px; border-bottom: 1px solid var(--border-color); text-align: center; }
        .sidebar-title { font-size: 20px; font-weight: 700; color: var(--accent); }
        .new-chat-btn {
            width: 100%; padding: 12px; margin-top: 15px; background: var(--primary);
            color: white; border: none; border-radius: 12px; font-weight: bold; cursor: pointer;
            display: flex; align-items: center; justify-content: center; gap: 8px; transition: 0.2s;
        }
        .new-chat-btn:hover { background: var(--primary-hover); }

        .sessions-list { flex: 1; overflow-y: auto; padding: 15px; }
        .session-item {
            padding: 12px; background: var(--bg-card); border: 1px solid var(--border-color);
            border-radius: 10px; margin-bottom: 10px; cursor: pointer; display: flex;
            justify-content: space-between; align-items: center; font-size: 14px; transition: 0.2s;
        }
        .session-item:hover, .session-item.active { border-color: var(--accent); background: #26334d; }
        .session-item .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 180px; }
        .delete-sess-btn { color: var(--text-muted); cursor: pointer; padding: 4px; }
        .delete-sess-btn:hover { color: var(--danger); }

        .main-container { flex: 1; display: flex; flex-direction: column; height: 100vh; position: relative; }

        .top-nav {
            height: 60px; background: var(--bg-card); border-bottom: 1px solid var(--border-color);
            display: flex; align-items: center; justify-content: space-between; padding: 0 20px;
        }
        .nav-tabs { display: flex; gap: 10px; }
        .tab-btn {
            padding: 8px 16px; background: transparent; border: 1px solid var(--border-color);
            color: var(--text-muted); border-radius: 8px; cursor: pointer; font-weight: bold; transition: 0.2s;
        }
        .tab-btn.active { background: var(--primary); color: white; border-color: var(--primary); }

        .chat-view { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .messages-box { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 15px; }

        .message-row { display: flex; flex-direction: column; max-width: 85%; }
        .message-row.user { align-self: flex-start; }
        .message-row.assistant { align-self: flex-end; width: 85%; }

        .message-bubble {
            padding: 15px 18px; border-radius: 18px; font-size: 15px; line-height: 1.6;
            position: relative; word-break: break-word;
        }
        .user .message-bubble { background: var(--user-msg); color: white; border-bottom-right-radius: 4px; }
        .assistant .message-bubble { background: var(--ai-msg); border: 1px solid var(--border-color); border-bottom-left-radius: 4px; }

        .image-preview-msg { max-width: 250px; border-radius: 12px; margin-bottom: 10px; border: 1px solid var(--border-color); }

        .msg-actions { display: flex; gap: 10px; margin-top: 6px; font-size: 13px; color: var(--text-muted); }
        .action-icon-btn {
            background: none; border: none; color: var(--text-muted); cursor: pointer;
            display: flex; align-items: center; gap: 4px; font-size: 13px; transition: 0.2s;
        }
        .action-icon-btn:hover { color: var(--accent); }

        pre {
            background: #050811; border: 1px solid var(--border-color); border-radius: 10px;
            padding: 12px; margin: 10px 0; overflow-x: auto; position: relative;
        }
        code { font-family: monospace; color: #38bdf8; }
        .copy-code-btn {
            position: absolute; top: 8px; left: 8px; background: var(--border-color);
            color: white; border: none; padding: 4px 8px; border-radius: 6px; font-size: 11px; cursor: pointer;
        }
        .copy-code-btn:hover { background: var(--primary); }

        .input-area {
            padding: 15px 20px; background: var(--bg-card); border-top: 1px solid var(--border-color);
            display: flex; flex-direction: column; gap: 10px;
        }
        .input-wrapper {
            display: flex; align-items: center; gap: 10px; background: #0f172a;
            border: 1px solid var(--border-color); border-radius: 16px; padding: 8px 15px;
        }
        .chat-input {
            flex: 1; background: transparent; border: none; color: white;
            font-size: 15px; outline: none; resize: none; max-height: 100px;
        }
        .input-btn { background: transparent; border: none; color: var(--text-muted); font-size: 18px; cursor: pointer; transition: 0.2s; }
        .input-btn:hover { color: var(--accent); }
        .send-btn { background: var(--primary); color: white; padding: 10px 16px; border-radius: 12px; }
        .send-btn:hover { background: var(--primary-hover); }

        #imagePreviewContainer {
            display: none; align-items: center; gap: 10px; background: #090d16;
            padding: 8px 12px; border-radius: 10px; width: fit-content;
        }
        #imagePreviewThumb { width: 40px; height: 40px; border-radius: 6px; object-fit: cover; }

        .download-view {
            display: none; flex: 1; padding: 30px; overflow-y: auto;
            align-items: center; flex-direction: column;
        }
        .dl-card {
            background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 20px;
            padding: 25px; width: 100%; max-width: 550px; text-align: center;
        }
        .dl-input {
            width: 100%; padding: 15px; background: #0f172a; border: 1px solid var(--border-color);
            border-radius: 12px; color: white; margin: 15px 0; font-size: 15px;
        }
        .dl-btn {
            width: 100%; padding: 14px; background: var(--success); color: white;
            border: none; border-radius: 12px; font-weight: bold; font-size: 16px; cursor: pointer;
        }

        .media-grid { width: 100%; max-width: 550px; margin-top: 20px; }
        .media-item {
            background: var(--bg-card); border: 1px solid var(--border-color); padding: 12px;
            border-radius: 12px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;
        }
        .media-item a { color: var(--accent); text-decoration: none; font-weight: bold; }
    </style>
</head>
<body>

    <div class="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-title"><i class="fa-solid fa-brain"></i> نظام جبوري الذكي</div>
            <button class="new-chat-btn" onclick="startNewChat()">
                <i class="fa-solid fa-plus"></i> محادثة جديدة
            </button>
        </div>
        <div class="sessions-list" id="sessionsList"></div>
    </div>

    <div class="main-container">
        <div class="top-nav">
            <div>
                <span style="font-weight:bold; font-size:17px;" id="currentSessionTitle">محادثة جديدة</span>
            </div>
            <div class="nav-tabs">
                <button class="tab-btn active" onclick="switchTab('chat')"><i class="fa-solid fa-comments"></i> الدردشة</button>
                <button class="tab-btn" onclick="switchTab('download')"><i class="fa-solid fa-download"></i> التحميلات</button>
            </div>
        </div>

        <div class="chat-view" id="chatView">
            <div class="messages-box" id="messagesBox">
                <div class="message-row assistant">
                    <div class="message-bubble">
                        أهلاً بك! أنا <b>نظام جبوري الذكي</b>. كيف يمكنني مساعدتك اليوم في كتابة الأكواد، تحليل النصوص، أو الإجابة عن استفساراتك؟
                    </div>
                </div>
            </div>

            <div class="input-area">
                <div id="imagePreviewContainer">
                    <img id="imagePreviewThumb" src="" alt="preview">
                    <span style="font-size:12px; color:var(--text-muted);" id="imgName">صورة مرفقة</span>
                    <i class="fa-solid fa-xmark" style="cursor:pointer; color:var(--danger);" onclick="clearAttachedImage()"></i>
                </div>

                <div class="input-wrapper">
                    <input type="file" id="fileInput" accept="image/*" style="display:none" onchange="handleImageSelect(event)">
                    <button class="input-btn" onclick="document.getElementById('fileInput').click()">
                        <i class="fa-solid fa-paperclip"></i>
                    </button>
                    <textarea class="chat-input" id="userInput" rows="1" placeholder="اكتب رسالتك هنا..." onkeydown="handleKeyPress(event)"></textarea>
                    <button class="input-btn send-btn" onclick="sendMessage()">
                        <i class="fa-solid fa-paper-plane"></i>
                    </button>
                </div>
            </div>
        </div>

        <div class="download-view" id="downloadView">
            <div class="dl-card">
                <h2><i class="fa-solid fa-cloud-arrow-down"></i> مركز التحميل السريع</h2>
                <p style="color:var(--text-muted); font-size:14px; margin-top:5px;">ضع رابط الفيديو للتحميل المباشر</p>
                <input type="url" id="dlUrlInput" class="dl-input" placeholder="https://example.com/video...">
                <button class="dl-btn" id="dlStartBtn" onclick="processVideoDownload()">بدء التحميل</button>
                <div id="dlStatus" style="margin-top:15px; font-weight:bold;"></div>
            </div>

            <div class="media-grid" id="mediaGallery"></div>
        </div>
    </div>

    <script>
        let activeSessionId = null;
        let attachedImageBase64 = null;
        let currentAudio = null;

        function switchTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            if (tab === 'chat') {
                document.getElementById('chatView').style.display = 'flex';
                document.getElementById('downloadView').style.display = 'none';
                event.target.classList.add('active');
            } else {
                document.getElementById('chatView').style.display = 'none';
                document.getElementById('downloadView').style.display = 'flex';
                event.target.classList.add('active');
                loadDownloadedVideos();
            }
        }

        window.onload = function() { loadSessionsList(); };

        async function loadSessionsList() {
            try {
                const res = await fetch('/api/sessions');
                const data = await res.json();
                if (data.success) {
                    const listEl = document.getElementById('sessionsList');
                    listEl.innerHTML = '';
                    data.sessions.forEach(sess => {
                        listEl.innerHTML += `
                            <div class="session-item ${sess.session_id === activeSessionId ? 'active' : ''}" onclick="loadSessionDetail('${sess.session_id}')">
                                <span class="title">${sess.title}</span>
                                <i class="fa-solid fa-trash delete-sess-btn" onclick="event.stopPropagation(); deleteSession('${sess.session_id}')"></i>
                            </div>`;
                    });
                }
            } catch (e) {}
        }

        function startNewChat() {
            activeSessionId = null;
            document.getElementById('currentSessionTitle').innerText = 'محادثة جديدة';
            document.getElementById('messagesBox').innerHTML = `
                <div class="message-row assistant">
                    <div class="message-bubble">
                        أهلاً بك! أنا <b>نظام جبوري الذكي</b>. كيف يمكنني مساعدتك اليوم؟
                    </div>
                </div>`;
            loadSessionsList();
        }

        async function loadSessionDetail(sessionId) {
            activeSessionId = sessionId;
            try {
                const res = await fetch(`/api/sessions/${sessionId}`);
                const data = await res.json();
                if (data.success) {
                    document.getElementById('currentSessionTitle').innerText = data.session.title;
                    const box = document.getElementById('messagesBox');
                    box.innerHTML = '';
                    data.session.messages.forEach(msg => { appendMessageBubble(msg.role, msg.content, false); });
                    loadSessionsList();
                }
            } catch (e) {}
        }

        async function deleteSession(sessionId) {
            if (!confirm('هل أنت تأكد من حذف هذه المحادثة؟')) return;
            try {
                await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
                if (activeSessionId === sessionId) startNewChat();
                else loadSessionsList();
            } catch (e) {}
        }

        function handleImageSelect(evt) {
            const file = evt.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                attachedImageBase64 = e.target.result;
                document.getElementById('imagePreviewThumb').src = attachedImageBase64;
                document.getElementById('imgName').innerText = file.name;
                document.getElementById('imagePreviewContainer').style.display = 'flex';
            };
            reader.readAsDataURL(file);
        }

        function clearAttachedImage() {
            attachedImageBase64 = null;
            document.getElementById('imagePreviewContainer').style.display = 'none';
            document.getElementById('fileInput').value = '';
        }

        function handleKeyPress(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        }

        async function sendMessage() {
            const input = document.getElementById('userInput');
            const prompt = input.value.trim();
            if (!prompt && !attachedImageBase64) return;

            appendMessageBubble('user', prompt, false, attachedImageBase64);
            input.value = '';
            const imgToSend = attachedImageBase64;
            clearAttachedImage();

            const aiRow = appendMessageBubble('assistant', '', true);
            const aiBubble = aiRow.querySelector('.message-bubble-content');

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ session_id: activeSessionId, prompt: prompt, image: imgToSend })
                });
                const data = await res.json();
                if (data.success) {
                    activeSessionId = data.session_id;
                    typeTextProgressive(aiBubble, data.response);
                    loadSessionsList();
                } else {
                    aiBubble.innerText = data.message || 'حدث خطأ.';
                }
            } catch (e) {
                aiBubble.innerText = 'تعذر الاتصال بالخادم.';
            }
        }

        function appendMessageBubble(role, content, isTyping = false, imageSrc = null) {
            const box = document.getElementById('messagesBox');
            const row = document.createElement('div');
            row.className = `message-row ${role}`;
            let formattedText = formatMarkdownCode(content);

            let imgHtml = imageSrc ? `<img src="${imageSrc}" class="image-preview-msg">` : '';
            let actionsHtml = role === 'assistant' && !isTyping ? `
                <div class="msg-actions">
                    <button class="action-icon-btn" onclick="copyMessageText(this)"><i class="fa-regular fa-copy"></i> نسخ</button>
                    <button class="action-icon-btn" onclick="toggleSpeakMessage(this)"><i class="fa-solid fa-volume-high"></i> قراءة</button>
                </div>` : '';

            row.innerHTML = `
                ${imgHtml}
                <div class="message-bubble">
                    <div class="message-bubble-content">${formattedText}</div>
                    ${actionsHtml}
                </div>`;

            box.appendChild(row);
            box.scrollTop = box.scrollHeight;
            return row;
        }

        function typeTextProgressive(element, fullText) {
            let i = 0;
            element.innerHTML = '';
            const timer = setInterval(() => {
                element.innerHTML = formatMarkdownCode(fullText.substring(0, i));
                element.scrollTop = element.scrollHeight;
                i += 3;
                if (i > fullText.length) {
                    element.innerHTML = formatMarkdownCode(fullText);
                    clearInterval(timer);
                    const parent = element.parentElement;
                    if (!parent.querySelector('.msg-actions')) {
                        parent.innerHTML += `
                            <div class="msg-actions">
                                <button class="action-icon-btn" onclick="copyMessageText(this)"><i class="fa-regular fa-copy"></i> نسخ</button>
                                <button class="action-icon-btn" onclick="toggleSpeakMessage(this)"><i class="fa-solid fa-volume-high"></i> قراءة</button>
                            </div>`;
                    }
                }
            }, 15);
        }

        function formatMarkdownCode(text) {
            if (!text) return '';
            let codeRegex = /```([a-zA-Z]*)\n([\s\S]*?)```/g;
            return text.replace(codeRegex, function(match, lang, code) {
                return `<pre><button class="copy-code-btn" onclick="copyCodeSnippet(this)">نسخ الكود</button><code>${code.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</code></pre>`;
            }).replace(/\n/g, '<br>');
        }

        function copyCodeSnippet(btn) {
            const code = btn.nextElementSibling.innerText;
            navigator.clipboard.writeText(code);
            btn.innerText = 'تم النسخ!';
            setTimeout(() => btn.innerText = 'نسخ الكود', 2000);
        }

        function copyMessageText(btn) {
            const text = btn.closest('.message-bubble').querySelector('.message-bubble-content').innerText;
            navigator.clipboard.writeText(text);
            btn.innerHTML = '<i class="fa-solid fa-check"></i> تم النسخ';
            setTimeout(() => btn.innerHTML = '<i class="fa-regular fa-copy"></i> نسخ', 2000);
        }

        async function toggleSpeakMessage(btn) {
            if (currentAudio) {
                currentAudio.pause();
                currentAudio = null;
                btn.innerHTML = '<i class="fa-solid fa-volume-high"></i> قراءة';
                return;
            }

            const text = btn.closest('.message-bubble').querySelector('.message-bubble-content').innerText;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> جاري التحميل...';

            try {
                const res = await fetch('/api/tts', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ text: text })
                });
                const data = await res.json();
                if (data.success) {
                    currentAudio = new Audio(data.audio_url);
                    currentAudio.play();
                    btn.innerHTML = '<i class="fa-solid fa-stop"></i> إيقاف';
                    currentAudio.onended = () => {
                        currentAudio = null;
                        btn.innerHTML = '<i class="fa-solid fa-volume-high"></i> قراءة';
                    };
                }
            } catch (e) {
                btn.innerHTML = '<i class="fa-solid fa-volume-high"></i> قراءة';
            }
        }

        async function processVideoDownload() {
            const urlInput = document.getElementById('dlUrlInput');
            const url = urlInput.value.trim();
            const status = document.getElementById('dlStatus');
            const btn = document.getElementById('dlStartBtn');

            if (!url) return;
            btn.disabled = true;
            status.innerHTML = '<span style="color:var(--accent);">جاري التحميل المعالجة...</span>';

            try {
                const res = await fetch('/download', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ url: url })
                });
                const data = await res.json();
                if (data.success) {
                    status.innerHTML = '<span style="color:var(--success);">تم التحميل بنجاح!</span>';
                    urlInput.value = '';
                    loadDownloadedVideos();
                } else {
                    status.innerHTML = `<span style="color:var(--danger);">${data.message}</span>`;
                }
            } catch (e) {
                status.innerHTML = '<span style="color:var(--danger);">خطأ في الاتصال.</span>';
            } finally {
                btn.disabled = false;
            }
        }

        async function loadDownloadedVideos() {
            try {
                const res = await fetch('/videos');
                const data = await res.json();
                const gallery = document.getElementById('mediaGallery');
                gallery.innerHTML = '';
                if (data.videos.length > 0) {
                    data.videos.forEach(file => {
                        gallery.innerHTML += `
                            <div class="media-item">
                                <span style="font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:350px;">${file}</span>
                                <a href="/download_file/${encodeURIComponent(file)}" download><i class="fa-solid fa-download"></i> حفظ الملف</a>
                            </div>`;
                    });
                }
            } catch (e) {}
        }
    </script>
</body>
</html>"""

@app.route('/')
def home():
    return HTML_TEMPLATE

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
