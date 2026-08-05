import os
import json
import time
import threading
import requests
import telebot
from telebot import types

# --- البيانات والمفاتيح ---
MAIN_TOKEN = "8670100497:AAGoCnO6beXj9HIi2lNucddCPOLKxZHMiJc"
ADMIN_TOKEN = "8758801132:AAESDdtWE3iStnnfjtyXQhvHMzL-bzHqNR8"
ADMIN_ID = 8301511694
ELEVENLABS_API_KEY = "sk_6e423b917963e592ef1d6941b9c58d941ccb45adaeb966c7"

main_bot = telebot.TeleBot(MAIN_TOKEN)
admin_bot = telebot.TeleBot(ADMIN_TOKEN)

USERS_FILE = "users.json"
VOICES_FILE = "user_voices.json"

def load_json(filename, default):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return default
    return default

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

users_db = set(load_json(USERS_FILE, []))
user_voices = load_json(VOICES_FILE, {})

# قائمة أصوات نسائية ورجالية داعمة للغة العربية الفصحى بقدرة عالية
VOICES = {
    "female_1": {"name": "♀️ سارة (صوت رقيق ونقي)", "id": "21m00Tcm4TlvDq8ikWAM"},
    "female_2": {"name": "♀️ مريم (صوت إخباري فصيح)", "id": "EXAVITQu4vr4xnSDxMaL"},
    "female_3": {"name": "♀️ نادين (صوت هادئ وسردي)", "id": "cgSgspJ2msm6clMCkdW9"},
    "male_1": {"name": "♂️ أحمد (صوت فخم وعميق)", "id": "ErXwobaYiN019PkySvjV"},
    "male_2": {"name": "♂️ خالد (صوت احترافي وواضح)", "id": "VR6AewLTigWG4xTVO15u"},
    "male_3": {"name": "♂️ طارق (صوت دافئ ومميز)", "id": "pNInz6obpgDQGcFmaJgB"}
}

DEFAULT_VOICE_ID = "ErXwobaYiN019PkySvjV"

def split_text(text, max_length=800):
    """تقسيم النصوص الطويلة جداً لأجزاء لضمان المعالجة الدقيقة"""
    chunks = []
    while len(text) > max_length:
        split_point = text.rfind(' ', 0, max_length)
        if split_point == -1:
            split_point = max_length
        chunks.append(text[:split_point])
        text = text[split_point:].strip()
    if text:
        chunks.append(text)
    return chunks

def generate_audio(text, voice_id):
    """تحويل النص إلى صوت باستخدام نموذج ElevenLabs Multilingual v2"""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80
        }
    }
    response = requests.post(url, json=data, headers=headers)
    if response.status_code == 200:
        return response.content
    return None

# ==================== البوت الرئيسي (TELEGRAM_MAIN_TOKEN) ====================

@main_bot.message_handler(commands=['start', 'voice'])
def send_voice_menu(message):
    user_id = message.from_user.id
    users_db.add(user_id)
    save_json(USERS_FILE, list(users_db))
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    for v_key, v_info in VOICES.items():
        markup.add(types.InlineKeyboardButton(v_info['name'], callback_data=f"set_voice_{v_key}"))
    
    main_bot.reply_to(
        message,
        f"مرحباً بك {message.from_user.first_name} 👋\n\n"
        "مرحباً بك في بوت تحويل النصوص إلى صوت عربي احترافي.\n"
        "اختر الصوت المطلوب من القائمة التالية ثم قم بإرسال أي نص:",
        reply_markup=markup
    )

@main_bot.callback_query_handler(func=lambda call: call.data.startswith('set_voice_'))
def set_voice_callback(call):
    v_key = call.data.replace('set_voice_', '')
    if v_key in VOICES:
        user_id = str(call.from_user.id)
        user_voices[user_id] = VOICES[v_key]['id']
        save_json(VOICES_FILE, user_voices)
        
        main_bot.answer_callback_query(call.id, "تم حفظ الصوت المختار!")
        main_bot.edit_message_text(
            f"✅ تم تفعيل الصوت: *{VOICES[v_key]['name']}*\n\nأرسل النص الآن لتم تحويله مباشرة إلى مقطع صوتي.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )

@main_bot.message_handler(func=lambda message: True, content_types=['text'])
def process_user_text(message):
    user_id = message.from_user.id
    users_db.add(user_id)
    save_json(USERS_FILE, list(users_db))
    
    text = message.text
    
    # 1. إرسال تقرير كامل ونسخة من النص لبوت الأدمن
    log_msg = (
        f"📩 *رسالة جديدة في البوت الرئيسي:*\n"
        f"👤 الاسم: {message.from_user.first_name}\n"
        f"🔗 اليوزر: @{message.from_user.username or 'بدون'}\n"
        f"🆔 المعرف: `{user_id}`\n\n"
        f"💬 *النص:* \n{text}"
    )
    try:
        admin_bot.send_message(ADMIN_ID, log_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"خطأ في توجيه التقرير للأدمن: {e}")

    # 2. تحديد الصوت ومعالجة النص
    voice_id = user_voices.get(str(user_id), DEFAULT_VOICE_ID)
    wait_msg = main_bot.reply_to(message, "⏳ جاري توليد الصوت العربي الاحترافي، يرجى الانتظار...")

    chunks = split_text(text)
    for index, chunk in enumerate(chunks):
        audio_bytes = generate_audio(chunk, voice_id)
        if audio_bytes:
            filename = f"audio_{user_id}_{index}.mp3"
            with open(filename, "wb") as f:
                f.write(audio_bytes)
            
            with open(filename, "rb") as f:
                caption = f"🔊 الجزء ({index+1}/{len(chunks)})" if len(chunks) > 1 else "🎙️ المقطع الصوتي جاهز:"
                main_bot.send_voice(message.chat.id, voice=f, caption=caption)
            
            if os.path.exists(filename):
                os.remove(filename)
        else:
            main_bot.send_message(message.chat.id, "❌ تعذر تحويل النص حالياً، تأكد من صحة الرصيد أو حاول لاحقاً.")

    try:
        main_bot.delete_message(message.chat.id, wait_msg.message_id)
    except Exception:
        pass

# ==================== بوت الأدمن (TELEGRAM_ADMIN_TOKEN) ====================

admin_states = {}

@admin_bot.message_handler(commands=['start'])
def admin_start(message):
    if message.from_user.id != ADMIN_ID:
        admin_bot.reply_to(message, "⛔ عفواً، هذه اللوحة مخصصة للأدمن فقط.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📢 إرسال إعلان للمستخدمين", "📊 إحصائيات البوت")
    admin_bot.send_message(
        ADMIN_ID,
        "مرحباً بك في لوحة التحكم الإدارية للبوت ⚙️\nيمكنك متابعة الرسائل فوراً أو إرسال إعلانات عامة.",
        reply_markup=markup
    )

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "📊 إحصائيات البوت")
def stats_handler(message):
    total = len(users_db)
    admin_bot.send_message(ADMIN_ID, f"📊 *إحصائيات البوت الرئيسي:*\n\nعدد المستخدمين المسجلين: *{total}*", parse_mode="Markdown")

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "📢 إرسال إعلان للمستخدمين")
def broadcast_request(message):
    admin_states[ADMIN_ID] = "waiting_broadcast"
    admin_bot.send_message(ADMIN_ID, "✍️ اكتب نص الإعلان الآن وسيتم إرساله تلقائياً لجميع مستخدمي البوت الرئيسي:")

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(ADMIN_ID) == "waiting_broadcast")
def execute_broadcast(message):
    admin_states[ADMIN_ID] = None
    announcement_text = message.text
    
    success = 0
    failed = 0
    admin_bot.send_message(ADMIN_ID, "🚀 جاري توزيع الإعلان على جميع المستخدمين...")
    
    for uid in list(users_db):
        try:
            main_bot.send_message(uid, f"📢 *إعلان جديد:*\n\n{announcement_text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.04)
        except Exception:
            failed += 1
            
    admin_bot.send_message(ADMIN_ID, f"✅ اكتمل الإرسال!\n\n🔹 تم بنجاح: {success}\n❌ تعذر (قاموا بحظر البوت): {failed}")

# ==================== تشغيل الخادمين ====================

if __name__ == "__main__":
    print("⚡ تم تشغيل بوت تحويل الصوت وبوت الأدمن بنجاح...")
    
    # تشغيل بوت الأدمن في الخلفية
    t = threading.Thread(target=admin_bot.infinity_polling, daemon=True)
    t.start()
    
    # تشغيل البوت الرئيسي
    main_bot.infinity_polling()
