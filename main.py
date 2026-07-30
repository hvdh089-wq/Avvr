import os
import json
import time
import threading
import requests
import yt_dlp
from flask import Flask, request, jsonify, render_template_string, send_file
import telebot
from telebot import types

# ================= إعدادات سيرفر الويب (Flask App) =================
app = Flask(__name__)

# ================= الواجهة التفاعلية (HTML + CSS + JavaScript) =================
WEB_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Avvr | المنصة الذكية المتكاملة</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@300;500;700;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 31, 48, 0.7);
            --accent-color: #6366f1;
            --accent-glow: rgba(99, 102, 241, 0.4);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border-color: rgba(255, 255, 255, 0.08);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Tajawal', sans-serif;
        }

        body {
            background-color: var(--bg-color);
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.15) 0px, transparent 50%);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        header {
            padding: 20px;
            text-align: center;
            border-bottom: 1px solid var(--border-color);
            background: rgba(11, 15, 25, 0.8);
            backdrop-filter: blur(10px);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        header h1 {
            font-size: 1.8rem;
            font-weight: 900;
            background: linear-gradient(135deg, #818cf8, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        header p {
            font-size: 0.9rem;
            color: var(--text-muted);
            margin-top: 5px;
        }

        .container {
            max-width: 900px;
            margin: 20px auto;
            padding: 0 15px;
            width: 100%;
            flex: 1;
        }

        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 25px;
            overflow-x: auto;
            padding-bottom: 5px;
        }

        .tab-btn {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            padding: 12px 20px;
            border-radius: 12px;
            cursor: pointer;
            font-size: 0.95rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s ease;
            white-space: nowrap;
        }

        .tab-btn.active, .tab-btn:hover {
            background: var(--accent-color);
            color: #fff;
            border-color: var(--accent-color);
            box-shadow: 0 0 15px var(--accent-glow);
        }

        .panel {
            display: none;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 25px;
            backdrop-filter: blur(12px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
            animation: fadeIn 0.4s ease;
        }

        .panel.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .chat-box {
            height: 380px;
            overflow-y: auto;
            border: 1px solid var(--border-color);
            border-radius: 15px;
            padding: 15px;
            background: rgba(0, 0, 0, 0.2);
            margin-bottom: 15px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .msg {
            max-width: 80%;
            padding: 12px 16px;
            border-radius: 15px;
            font-size: 0.95rem;
            line-height: 1.5;
        }

        .msg.user {
            background: var(--accent-color);
            color: #fff;
            align-self: flex-start;
            border-bottom-right-radius: 2px;
        }

        .msg.ai {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
            align-self: flex-end;
            border: 1px solid var(--border-color);
            border-bottom-left-radius: 2px;
        }

        .input-group {
            display: flex;
            gap: 10px;
        }

        input[type="text"], textarea, select {
            width: 100%;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border-color);
            padding: 14px;
            border-radius: 12px;
            color: #fff;
            font-size: 0.95rem;
            outline: none;
            transition: border 0.3s;
        }

        input[type="text"]:focus, textarea:focus, select:focus {
            border-color: var(--accent-color);
        }

        .btn-submit {
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            color: white;
            border: none;
            padding: 14px 25px;
            border-radius: 12px;
            cursor: pointer;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: 0.3s;
            white-space: nowrap;
        }

        .btn-submit:hover {
            opacity: 0.9;
            transform: translateY(-2px);
        }

        .loader {
            display: none;
            text-align: center;
            margin: 15px 0;
            color: var(--accent-color);
        }

        footer {
            text-align: center;
            padding: 20px;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-top: 1px solid var(--border-color);
            margin-top: auto;
        }
    </style>
</head>
<body>

    <header>
        <h1><i class="fa-solid fa-bolt"></i> Avvr Web Ecosystem</h1>
        <p>المنصة الذكية المتكاملة للمطور الجبوري</p>
    </header>

    <div class="container">
        <!-- التبويبات -->
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('chat')"><i class="fa-solid fa-robot"></i> الذكاء الاصطناعي</button>
            <button class="tab-btn" onclick="switchTab('tts')"><i class="fa-solid fa-microphone"></i> تحويل النص لصوت</button>
            <button class="tab-btn" onclick="switchTab('download')"><i class="fa-solid fa-download"></i> تحميل الميديا</button>
            <button class="tab-btn" onclick="switchTab('status')"><i class="fa-solid fa-chart-line"></i> حالة النظام</button>
        </div>

        <!-- تبويب الذكاء الاصطناعي -->
        <div id="chat-panel" class="panel active">
            <div class="chat-box" id="chatBox">
                <div class="msg ai">أهلاً بك! أنا مساعدك الذكي المتصل بأقوى نماذج الذكاء الاصطناعي. كيف يمكنني مساعدتك اليوم؟</div>
            </div>
            <div class="input-group">
                <input type="text" id="chatInput" placeholder="اكتب سؤالك أو طلبك هنا..." onkeypress="if(event.key==='Enter') sendChat()">
                <button class="btn-submit" onclick="sendChat()"><i class="fa-solid fa-paper-plane"></i> إرسال</button>
            </div>
        </div>

        <!-- تبويب تحويل النص إلى صوت -->
        <div id="tts-panel" class="panel">
            <h3 style="margin-bottom: 15px;"><i class="fa-solid fa-headset"></i> توليد صوت احترافي (ElevenLabs)</h3>
            <div style="margin-bottom: 15px;">
                <label style="display:block; margin-bottom:8px; color:var(--text-muted);">اختر نبرة الصوت:</label>
                <select id="voiceSelect">
                    <option value="pNInz6obpgDQGcFmaJgB">👨 آدم (فصيح وعميق)</option>
                    <option value="ErXwobaYiN019PkySvjV">👨 أنطوني (إخباري)</option>
                    <option value="IKne3meq5aSn9XLyUdCD">👨 تشارلي (ودي)</option>
                    <option value="21m00Tcm4TlvDq8ikWAM">👩 راشيل (فصحى)</option>
                    <option value="EXAVITQu4vr4xnSDxMaL">👩 بيلا (ناعمة)</option>
                </select>
            </div>
            <div style="margin-bottom: 15px;">
                <textarea id="ttsText" rows="4" placeholder="اكتب النص الذي ترغب بتحويله إلى مقطع صوتي..."></textarea>
            </div>
            <button class="btn-submit" onclick="generateTTS()"><i class="fa-solid fa-wand-magic-sparkles"></i> توليد الصوت</button>
            <div id="ttsLoader" class="loader"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p>جاري توليد الصوت...</p></div>
            <div id="audioResult" style="margin-top: 20px;"></div>
        </div>

        <!-- تبويب تحميل الميديا -->
        <div id="download-panel" class="panel">
            <h3 style="margin-bottom: 15px;"><i class="fa-solid fa-circle-down"></i> تحميل الفيديو والصوتيات</h3>
            <p style="color:var(--text-muted); margin-bottom:15px;">ادعم التحميل من YouTube, TikTok, Instagram, Facebook وغيرها.</p>
            <div class="input-group" style="margin-bottom: 15px;">
                <input type="text" id="dlUrl" placeholder="أدخل رابط الفيديو هنا...">
                <button class="btn-submit" onclick="startDownload()"><i class="fa-solid fa-download"></i> استخراج</button>
            </div>
            <div id="dlLoader" class="loader"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p>جاري التحميل والمعالجة...</p></div>
            <div id="dlResult" style="margin-top: 15px;"></div>
        </div>

        <!-- تبويب حالة النظام -->
        <div id="status-panel" class="panel">
            <h3><i class="fa-solid fa-server"></i> حالة الخادم والأنظمة</h3>
            <div style="margin-top:20px; line-height:2;">
                <p>🟢 <b>حالة السيرفر:</b> متصل ويعمل 24/7</p>
                <p>🤖 <b>البوتات المربوطة:</b> البوت العام + بوت المطور</p>
                <p>⚡ <b>محرك الذكاء الاصطناعي:</b> Groq, OpenRouter, Gemini, Hugging Face</p>
                <p>🔊 <b>محرك الصوتيات:</b> ElevenLabs v2</p>
            </div>
        </div>

    </div>

    <footer>
        تطوير وإشراف المطور الجبوري © 2026 | جميع الحقوق محفوظة
    </footer>

    <script>
        function switchTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
            
            event.currentTarget.classList.add('active');
            document.getElementById(tab + '-panel').classList.add('active');
        }

        async function sendChat() {
            const input = document.getElementById('chatInput');
            const box = document.getElementById('chatBox');
            const text = input.value.trim();
            if (!text) return;

            box.innerHTML += `<div class="msg user">${text}</div>`;
            input.value = '';
            box.scrollTop = box.scrollHeight;

            const aiMsg = document.createElement('div');
            aiMsg.className = 'msg ai';
            aiMsg.innerText = 'جاري التفكير...';
            box.appendChild(aiMsg);
            box.scrollTop = box.scrollHeight;

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt: text})
                });
                const data = await res.json();
                aiMsg.innerText = data.response;
            } catch {
                aiMsg.innerText = 'عذراً، حدث خطأ أثناء الاتصال بالخادم.';
            }
            box.scrollTop = box.scrollHeight;
        }

        async function generateTTS() {
            const text = document.getElementById('ttsText').value.trim();
            const voice = document.getElementById('voiceSelect').value;
            const loader = document.getElementById('ttsLoader');
            const resDiv = document.getElementById('audioResult');

            if (!text) return alert('يرجى كتابة نص أولاً');
            loader.style.display = 'block';
            resDiv.innerHTML = '';

            try {
                const res = await fetch('/api/tts', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: text, voice: voice})
                });
                const data = await res.json();
                loader.style.display = 'none';
                if(data.success) {
                    resDiv.innerHTML = `<audio controls autoplay src="${data.audio_url}" style="width:100%"></audio>`;
                } else {
                    resDiv.innerHTML = `<p style="color:red">${data.error}</p>`;
                }
            } catch {
                loader.style.display = 'none';
                alert('فشل في إنشاء المقطع الصوتي');
            }
        }

        async function startDownload() {
            const url = document.getElementById('dlUrl').value.trim();
            const loader = document.getElementById('dlLoader');
            const resDiv = document.getElementById('dlResult');

            if (!url) return alert('يرجى وضع رابط صالح');
            loader.style.display = 'block';
            resDiv.innerHTML = '';

            try {
                const res = await fetch('/api/download', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: url})
                });
                const data = await res.json();
                loader.style.display = 'none';
                if(data.success) {
                    resDiv.innerHTML = `<a href="${data.file_url}" download class="btn-submit" style="text-decoration:none; display:inline-flex;"><i class="fa-solid fa-file-arrow-down"></i> تحميل الملف المباشر</a>`;
                } else {
                    resDiv.innerHTML = `<p style="color:red">فشل التحميل: ${data.error}</p>`;
                }
            } catch {
                loader.style.display = 'none';
                alert('حدث خطأ أثناء معالجة الرابط');
            }
        }
    </script>
</body>
</html>
"""

# ================= مسارات موقع الويب (Flask Routes & APIs) =================
@app.route('/')
def home():
    return render_template_string(WEB_HTML)

@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.json or {}
    prompt = data.get('prompt', '')
    if not prompt:
        return jsonify({'response': 'يرجى تقديم نص للاستفسار.'})
    reply = ask_united_ai(prompt)
    return jsonify({'response': reply})

@app.route('/api/tts', methods=['POST'])
def api_tts():
    data = request.json or {}
    text = data.get('text', '')
    voice = data.get('voice', 'pNInz6obpgDQGcFmaJgB')
    
    if not text:
        return jsonify({'success': False, 'error': 'النص فارغ'})
        
    fn = f"static_tts_{int(time.time())}.mp3"
    filepath = os.path.join("downloads", fn)
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        
    if generate_audio(text, voice, filepath):
        return jsonify({'success': True, 'audio_url': f'/get_file/{fn}'})
    return jsonify({'success': False, 'error': 'فشل توليد الصوت عبر ElevenLabs'})

@app.route('/api/download', methods=['POST'])
def api_download():
    data = request.json or {}
    url = data.get('url', '')
    if not url:
        return jsonify({'success': False, 'error': 'الرابط فارغ'})
        
    ok, res = download_media(url)
    if ok:
        filename = os.path.basename(res)
        return jsonify({'success': True, 'file_url': f'/get_file/{filename}'})
    return jsonify({'success': False, 'error': res})

@app.route('/get_file/<filename>')
def get_file(filename):
    path = os.path.join("downloads", filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return "الملف غير موجود", 404

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
            # ================= الإعدادات الأساسية والمفاتيح =================
MAIN_BOT_TOKEN = "8670100497:AAGoCnO6beXj9HIi2lNucddCPOLKxZHMiJc"
ADMIN_BOT_TOKEN = "8758801132:AAESDdtWE3iStnnfjtyXQhvHMzL-bzHqNR8"
ADMIN_ID = 8301511694

ELEVENLABS_KEY = "sk_6e423b917963e592ef1d6941b9c58d941ccb45adaeb966c7"
GEMINI_KEY = "AQ.Ab8RN6KHKLylkD52rbgbAlpny4UDouWx0epLQvkj_fGwBQ4BMg"
HUGGINGFACE_KEY = "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"
OPENROUTER_KEY = "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"
GROQ_KEY = "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"

WEB_APP_URL = "https://avvr.onrender.com"

main_bot = telebot.TeleBot(MAIN_BOT_TOKEN)
admin_bot = telebot.TeleBot(ADMIN_BOT_TOKEN)

VOICES = {
    '👨 آدم (فصيح وعميق)': 'pNInz6obpgDQGcFmaJgB',
    '👨 أنطوني (إخباري)': 'ErXwobaYiN019PkySvjV',
    '👨 تشارلي (ودي)': 'IKne3meq5aSn9XLyUdCD',
    '👩 راشيل (فصحى)': '21m00Tcm4TlvDq8ikWAM',
    '👩 بيلا (ناعمة)': 'EXAVITQu4vr4xnSDxMaL'
}
DEFAULT_VOICE = 'pNInz6obpgDQGcFmaJgB'
DB_FILE = 'global_nuclear_db.json'

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {"bot_active": True, "users": {}}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_user(user_id):
    db = load_db()
    uid = str(user_id)
    if "users" not in db:
        db["users"] = {}
    if uid not in db["users"]:
        db["users"][uid] = {
            "voice": DEFAULT_VOICE,
            "mode": "chat",
            "requests_count": 0,
            "join_date": time.strftime("%Y-%m-%d")
        }
        save_db(db)
    return db["users"][uid]

def update_user(user_id, key, value):
    db = load_db()
    uid = str(user_id)
    if uid in db.get("users", {}):
        db["users"][uid][key] = value
        save_db(db)

def is_bot_active():
    db = load_db()
    return db.get("bot_active", True)

# ================= نظام الذكاء الاصطناعي الاحتياطي المتكامل =================
def ask_united_ai(prompt):
    system_prompt = "أنت مساعد ذكي ولطيف للغاية، تم تطويرك بواسطة المطور العبقري الجبوري. قدم الإجابات كاملة وفي رسالة واحدة دقيقة ومنسقة."
    
    # 1. Groq
    try:
        res = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]}, timeout=10)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
    except:
        pass

    # 2. OpenRouter
    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}"},
            json={"model": "deepseek/deepseek-chat", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]}, timeout=10)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
    except:
        pass

    # 3. Gemini
    try:
        res = requests.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
            headers={"Content-Type": "application/json", "X-goog-api-key": GEMINI_KEY},
            json={"contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}]}, timeout=10)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        pass

    # 4. Hugging Face
    try:
        res = requests.post("https://router.huggingface.co/v1/chat/completions",
            headers={"Authorization": f"Bearer {HUGGINGFACE_KEY}"},
            json={"model": "Qwen/Qwen2.5-7B-Instruct", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]}, timeout=10)
        if res.status_code == 200:
            return res.json()['choices'][0]['message']['content']
    except:
        pass

    return "عذراً يا صديقي، واجهت ضغطاً شديداً حالياً، يرجى إعادة المحاولة!"

def download_media(url):
    output_dir = "downloads"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    ydl_opts = {
        'outtmpl': f'{output_dir}/media_%(id)s.%(ext)s',
        'format': 'best',
        'noplaylist': True,
        'quiet': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return True, ydl.prepare_filename(info)
    except Exception as e:
        return False, str(e)

def generate_audio(text, voice_id, output_path):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": ELEVENLABS_KEY}
    data = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}
    res = requests.post(url, json=data, headers=headers)
    if res.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(res.content)
        return True
    return False

# ================= البوت الأساسي (للجمهور) =================
@main_bot.message_handler(commands=['start'])
def main_start(message):
    if not is_bot_active():
        main_bot.reply_to(message, "⚠️ البوت في حالة صيانة وتحديث حالياً، عودوا قريباً!")
        return
    get_user(message.from_user.id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🌐 فتح موقع التحكم والخدمات", url=WEB_APP_URL),
        types.InlineKeyboardButton("🤖 الدردشة والذكاء الاصطناعي", callback_data="mode_chat"),
        types.InlineKeyboardButton("🗣️ تحويل النص إلى صوت", callback_data="mode_tts"),
        types.InlineKeyboardButton("📥 تحميل من السوشيال ميديا", callback_data="mode_download"),
        types.InlineKeyboardButton("🎙️ اختيار نبرة الصوت", callback_data="voices_menu")
    )
    main_bot.reply_to(message, f"أهلاً بك يا {message.from_user.first_name}\nأنا مساعدك الذكي والشامل، تم تطويري بواسطة **الجبوري**!\n\nيمكنك الآن استعراض كافة الخدمات عبر البوت أو عبر **موقعنا الإلكتروني المباشر**:", reply_markup=markup, parse_mode="Markdown")

@main_bot.callback_query_handler(func=lambda call: True)
def main_callbacks(call):
    main_bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    
    if call.data == "mode_chat":
        update_user(user_id, "mode", "chat")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu"))
        main_bot.edit_message_text("🤖 **تم تفعيل وضع الدردشة والذكاء الاصطناعي.**\nاسألني عن أي شيء وسأجيبك فوراً!", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "mode_tts":
        update_user(user_id, "mode", "tts")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu"))
        main_bot.edit_message_text("🗣️ **تم تفعيل وضع تحويل النص إلى صوت.**\nأرسل النص المطلوب تحويله.", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "mode_download":
        update_user(user_id, "mode", "download")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu"))
        main_bot.edit_message_text("📥 **تم تفعيل وضع التحميل.**\nأرسل رابط الميديا المراد تحميلها.", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "voices_menu":
        markup = types.InlineKeyboardMarkup(row_width=1)
        for name, vid in VOICES.items():
            markup.add(types.InlineKeyboardButton(name, callback_data=f"setv_{vid}"))
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu"))
        main_bot.edit_message_text("🎛️ **اختر نبرة الصوت المفضلة لديك:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data.startswith("setv_"):
        update_user(user_id, "voice", call.data.split("_")[1])
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu"))
        main_bot.edit_message_text("✅ **تم تحديث نبرة الصوت بنجاح!**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    
    elif call.data == "main_menu":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🌐 فتح موقع التحكم والخدمات", url=WEB_APP_URL),
            types.InlineKeyboardButton("🤖 الدردشة والذكاء الاصطناعي", callback_data="mode_chat"),
            types.InlineKeyboardButton("🗣️ تحويل النص إلى صوت", callback_data="mode_tts"),
            types.InlineKeyboardButton("📥 تحميل من السوشيال ميديا", callback_data="mode_download"),
            types.InlineKeyboardButton("🎙️ اختيار نبرة الصوت", callback_data="voices_menu")
        )
        main_bot.edit_message_text("🚀 **القائمة الرئيسية:**\nاختر الخدمة المطلوبة:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@main_bot.message_handler(content_types=['text'])
def main_messages(message):
    if not is_bot_active():
        return
    if message.text.startswith('/'): return
    user_id = message.from_user.id
    user_data = get_user(user_id)
    mode = user_data.get("mode", "chat")
    update_user(user_id, "requests_count", user_data["requests_count"] + 1)
    
    if mode == "chat":
        wait_msg = main_bot.reply_to(message, "🧠 جاري تجهيز الإجابة...")
        def run():
            res = ask_united_ai(message.text)
            main_bot.edit_message_text(res, message.chat.id, wait_msg.message_id)
        threading.Thread(target=run).start()
        
    elif mode == "tts":
        wait_msg = main_bot.reply_to(message, "⚡ جاري توليد الصوت...")
        def run():
            fn = f"audio_{user_id}_{int(time.time())}.mp3"
            if generate_audio(message.text, user_data["voice"], fn):
                with open(fn, 'rb') as aud:
                    main_bot.send_audio(message.chat.id, aud)
                main_bot.delete_message(message.chat.id, wait_msg.message_id)
                if os.path.exists(fn): os.remove(fn)
            else:
                main_bot.edit_message_text("❌ عذراً، فشل توليد الصوت.", message.chat.id, wait_msg.message_id)
        threading.Thread(target=run).start()
        
    elif mode == "download":
        if not message.text.startswith("http"):
            main_bot.reply_to(message, "⚠️ يرجى إرسال رابط صالح.")
            return
        wait_msg = main_bot.reply_to(message, "📥 جاري التحميل...")
        def run():
            ok, res = download_media(message.text.strip())
            if ok and os.path.exists(res):
                try:
                    with open(res, 'rb') as vid:
                        if res.endswith(('.mp4', '.mkv', '.webm', '.mov')):
                            main_bot.send_video(message.chat.id, vid, caption="✅ تم التحميل بنجاح!")
                        else:
                            main_bot.send_document(message.chat.id, vid, caption="✅ تم التحميل بنجاح!")
                    main_bot.delete_message(message.chat.id, wait_msg.message_id)
                finally:
                    if os.path.exists(res): os.remove(res)
            else:
                main_bot.edit_message_text(f"❌ فشل التحميل: <code>{res}</code>", message.chat.id, wait_msg.message_id, parse_mode="HTML")
        threading.Thread(target=run).start()

# ================= بوت المطور (Admin Bot) =================
@admin_bot.message_handler(commands=['start'])
def admin_start(message):
    if message.from_user.id != ADMIN_ID:
        admin_bot.reply_to(message, "⛔ عذراً، هذا البوت خاص بالمطور الجبوري فقط.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 تشغيل البوت الأساسي", callback_data="turn_on"),
        types.InlineKeyboardButton("🔴 إطفاء البوت الأساسي", callback_data="turn_off"),
        types.InlineKeyboardButton("📊 إحصائيات النظام", callback_data="admin_stats"),
        types.InlineKeyboardButton("🌐 فتح موقع التحكم", url=WEB_APP_URL)
    )
    admin_bot.reply_to(message, f"أهلاً بك يا سيدي الجبوري في غرفة التحكم المركزية للبوت والموقع.", reply_markup=markup, parse_mode="Markdown")

@admin_bot.callback_query_handler(func=lambda call: True)
def admin_callbacks(call):
    if call.from_user.id != ADMIN_ID:
        return
    admin_bot.answer_callback_query(call.id)
    db = load_db()
    
    if call.data == "turn_on":
        db["bot_active"] = True
        save_db(db)
        admin_bot.edit_message_text("🟢 **تم تشغيل البوت الأساسي بنجاح يا سيدي.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    elif call.data == "turn_off":
        db["bot_active"] = False
        save_db(db)
        admin_bot.edit_message_text("🔴 **تم إطفاء البوت الأساسي وإدخاله في وضع الصيانة يا سيدي.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    elif call.data == "admin_stats":
        users_count = len(db.get("users", {}))
        status = "🟢 يعمل" if db.get("bot_active", True) else "🔴 مطفأ"
        text = f"📊 **إحصائيات النظام:**\n\n• حالة البوت: {status}\n• عدد المستخدمين: `{users_count}`"
        admin_bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@admin_bot.message_handler(content_types=['text'])
def admin_messages(message):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text.startswith('/'): return
    
    prompt_text = message.text
    ai_response = ask_united_ai(f"المتحدث هو سيدي ومطوري الجبوري: {prompt_text}")
    admin_bot.reply_to(message, f"🤖 **أمرك يا سيدي الجبوري:**\n\n{ai_response}", parse_mode="Markdown")

# ================= تشغيل السيرفر والبوتات معاً =================
def run_main_bot():
    while True:
        try:
            main_bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except:
            time.sleep(5)

def run_admin_bot():
    while True:
        try:
            admin_bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except:
            time.sleep(5)

if __name__ == '__main__':
    t_flask = threading.Thread(target=run_flask)
    t_main = threading.Thread(target=run_main_bot)
    t_admin = threading.Thread(target=run_admin_bot)
    
    t_flask.start()
    t_main.start()
    t_admin.start()
    
    print("🚀 تم تشغيل الخادم الإلكتروني والبوتات بنجاح...")
    
    t_flask.join()
    t_main.join()
    t_admin.join()
        
