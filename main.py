import os
import json
import time
import threading
import requests
import telebot
from telebot import types
from flask import Flask

# ==================== البيانات والمفاتيح الأساسية ====================
MAIN_TOKEN = "8670100497:AAGoCnO6beXj9HIi2lNucddCPOLKxZHMiJc"
ADMIN_TOKEN = "8758801132:AAESDdtWE3iStnnfjtyXQhvHMzL-bzHqNR8"
ADMIN_ID = 8301511694
ELEVENLABS_API_KEY = "sk_7770bfbb6c5692dcc1ae2fe0d4516465cdf4acf0bddaa368"

main_bot = telebot.TeleBot(MAIN_TOKEN)
admin_bot = telebot.TeleBot(ADMIN_TOKEN)

USERS_FILE = "users.json"
VOICES_FILE = "user_voices.json"

# ==================== إدارة البيانات والدوال المساعدة ====================
def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filename, data):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ خطأ أثناء حفظ الملف {filename}: {e}")

users_db = set(load_json(USERS_FILE, []))
user_voices = load_json(VOICES_FILE, {})

# تشكيلة أصوات متنوعة احترافية (رجل / امرأة) تناسب كافة أنواع المحتوى
VOICES = {
    "male_1": {
        "name": "👨 أحمد | 👻 عميق ومرعب (لقصص الرعب والغموض)",
        "id": "ErXwobaYiN019PkySvjV"
    },
    "male_2": {
        "name": "👨 خالد | 🎬 وثائقي واحترافي (للمقاطع والإعلانات)",
        "id": "VR6AewLTigWG4xTVO15u"
    },
    "male_3": {
        "name": "👨 طارق | ☕ دافئ وهادئ (للشعر والخواطر)",
        "id": "pNInz6obpgDQGcFmaJgB"
    },
    "female_1": {
        "name": "👩 سارة | 🍃 رقيق وهادئ (للتأمل والسرد)",
        "id": "21m00Tcm4TlvDq8ikWAM"
    },
    "female_2": {
        "name": "👩 مريم | 📢 إخباري وقوي (للأخبار والتعليق الصوتي)",
        "id": "EXAVITQu4vr4xnSDxMaL"
    },
    "female_3": {
        "name": "👩 نادين | 🎭 درامي وسردي (للحكايات والروايات)",
        "id": "cgSgspJ2msm6clMCkdW9"
    }
}

DEFAULT_VOICE_ID = "ErXwobaYiN019PkySvjV"

def get_main_keyboard():
    """لوحة التحكم الثابتة للرجوع وتغيير الأصوات بسهولة"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🎙️ اختيار / تغيير الصوت", "🔙 الرجوع للقائمة الرئيسية")
    return markup

def split_text(text, max_length=800):
    """تقسيم النصوص الطويلة جداً لضمان جودة وسرعة المعالجة"""
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
    """الاتصال بمحرك ElevenLabs لتوليد الصوت"""
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
    try:
        response = requests.post(url, json=data, headers=headers, timeout=60)
        if response.status_code == 200:
            return response.content
        else:
            print(f"❌ ElevenLabs Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"⚠️ خطأ أثناء طلب تحويل الصوت: {e}")
    return None

# ==================== سيرفر الويب (Flask) لمنصة Render ====================
app = Flask(__name__)

@app.route('/')
def home():
    return "✨ البوت يعمل بنجاح 24/7 على منصة Render!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ==================== البوت الرئيسي (TELEGRAM_MAIN_TOKEN) ====================

@main_bot.message_handler(commands=['start', 'voice', 'menu'])
def send_welcome_and_voice_menu(message):
    user_id = message.from_user.id
    users_db.add(user_id)
    save_json(USERS_FILE, list(users_db))
    
    markup_inline = types.InlineKeyboardMarkup(row_width=1)
    for v_key, v_info in VOICES.items():
        markup_inline.add(types.InlineKeyboardButton(v_info['name'], callback_data=f"set_voice_{v_key}"))
    
    # خيار رجوع داخل القائمة الشفافة
    markup_inline.add(types.InlineKeyboardButton("🔙 إعادة تعيين / القائمة الرئيسية", callback_data="reset_menu"))

    welcome_text = (
        f"أهلاً بك يا {message.from_user.first_name} ✨\n\n"
        "مرحباً بك في بوت تحويل النص إلى صوت احترافي 🎙️\n"
        "يمكنك استخدام البوت لصناعة المحتوى (رعب، قصص، وثائقي، أخبار، خواطر).\n\n"
        "👇 *اختر الصوت المناسب لنوع محتواك من القائمة التالية:*"
    )
    
    main_bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    main_bot.send_message(
        message.chat.id,
        "🎭 *قائمة الأصوات المتاحة:*",
        reply_markup=markup_inline,
        parse_mode="Markdown"
    )

@main_bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = str(call.from_user.id)
    
    if call.data.startswith('set_voice_'):
        v_key = call.data.replace('set_voice_', '')
        if v_key in VOICES:
            user_voices[user_id] = VOICES[v_key]['id']
            save_json(VOICES_FILE, user_voices)
            
            main_bot.answer_callback_query(call.id, "✅ تم حفظ التفضيل!")
            main_bot.edit_message_text(
                f"✅ *تم تفعيل الصوت بنجاح:*\n{VOICES[v_key]['name']}\n\n"
                "✍️ أرسل الآن أي نص تريد تحويله لمقطع صوتي مباشرة!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
    elif call.data == "reset_menu":
        main_bot.answer_callback_query(call.id, "🔄 تم تحديث القائمة")
        main_bot.edit_message_text(
            "✨ *تم إعادة فتح قائمة خيارات الأصوات بنجاح.*",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )

@main_bot.message_handler(func=lambda message: True, content_types=['text'])
def process_user_messages(message):
    user_id = message.from_user.id
    users_db.add(user_id)
    save_json(USERS_FILE, list(users_db))
    
    text = message.text.strip()
    
    # التعامل مع أزرار الرجوع وتغيير الصوت
    if text in ["🔙 الرجوع للقائمة الرئيسية", "🎙️ اختيار / تغيير الصوت", "رجوع", "الرجوع", "/start"]:
        send_welcome_and_voice_menu(message)
        return

    # 1. إرسال تقرير كامل وبث النص لبوت الأدمن
    log_msg = (
        f"📩 *رسالة جديدة في البوت الرئيسي:*\n"
        f"👤 الاسم: {message.from_user.first_name}\n"
        f"🔗 اليوزر: @{message.from_user.username or 'بدون'}\n"
        f"🆔 المعرف: `{user_id}`\n\n"
        f"💬 *النص المرسل:*\n{text}"
    )
    try:
        admin_bot.send_message(ADMIN_ID, log_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"⚠️ خطأ أثناء إرسال التقرير للأدمن: {e}")

    # 2. تحويل النص إلى صوت
    voice_id = user_voices.get(str(user_id), DEFAULT_VOICE_ID)
    wait_msg = main_bot.reply_to(message, "⏳ جاري توليد الصوت الاحترافي، يرجى الانتظار قليلاً...")

    chunks = split_text(text)
    for index, chunk in enumerate(chunks):
        audio_bytes = generate_audio(chunk, voice_id)
        if audio_bytes:
            filename = f"audio_{user_id}_{index}.mp3"
            with open(filename, "wb") as f:
                f.write(audio_bytes)
            
            with open(filename, "rb") as f:
                caption = f"🔊 الجزء ({index+1}/{len(chunks)})" if len(chunks) > 1 else "🎙️ المقطع الصوتي جاهز بنجاح:"
                main_bot.send_voice(message.chat.id, voice=f, caption=caption, reply_markup=get_main_keyboard())
            
            if os.path.exists(filename):
                os.remove(filename)
        else:
            main_bot.send_message(
                message.chat.id,
                "❌ تعذر تحويل النص حالياً، يرجى التأكد من توفر الرصيد أو المحاولة لاحقاً.",
                reply_markup=get_main_keyboard()
            )

    try:
        main_bot.delete_message(message.chat.id, wait_msg.message_id)
    except Exception:
        pass

# ==================== بوت الأدمن (TELEGRAM_ADMIN_TOKEN) ====================

admin_states = {}

def get_admin_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📢 إرسال إعلان للمستخدمين", "📊 إحصائيات البوت")
    markup.row("🔙 الرجوع للقائمة الرئيسية")
    return markup

@admin_bot.message_handler(commands=['start'])
def admin_start(message):
    if message.from_user.id != ADMIN_ID:
        admin_bot.reply_to(message, "⛔ عفواً، هذه اللوحة مخصصة لإدارة البوت فقط.")
        return

    admin_bot.send_message(
        ADMIN_ID,
        "مرحباً بك في لوحة تحكم الأدمن ⚙️\nيمكنك إرسال الإعلانات ومتابعة إحصائيات البوت باستمرار.",
        reply_markup=get_admin_keyboard()
    )

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "🔙 الرجوع للقائمة الرئيسية")
def admin_back(message):
    admin_states[ADMIN_ID] = None
    admin_bot.send_message(ADMIN_ID, "🔙 تم الرجوع للقائمة الرئيسية للأدمن.", reply_markup=get_admin_keyboard())

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "📊 إحصائيات البوت")
def stats_handler(message):
    total = len(users_db)
    admin_bot.send_message(
        ADMIN_ID,
        f"📊 *إحصائيات البوت الرئيسي:*\n\n👥 إجمالي المستخدمين المسجلين: *{total}*",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and m.text == "📢 إرسال إعلان للمستخدمين")
def broadcast_request(message):
    admin_states[ADMIN_ID] = "waiting_broadcast"
    admin_bot.send_message(
        ADMIN_ID,
        "✍️ اكتب نص الإعلان الآن وسيتم توزيعه فوراً على جميع مستخدمي البوت الرئيسي:\n(أو اضغط '🔙 الرجوع للقائمة الرئيسية' للإلغاء)",
        reply_markup=get_admin_keyboard()
    )

@admin_bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and admin_states.get(ADMIN_ID) == "waiting_broadcast")
def execute_broadcast(message):
    if message.text == "🔙 الرجوع للقائمة الرئيسية":
        admin_states[ADMIN_ID] = None
        admin_bot.send_message(ADMIN_ID, "❌ تم إلغاء الإعلان.", reply_markup=get_admin_keyboard())
        return

    admin_states[ADMIN_ID] = None
    announcement_text = message.text
    
    success = 0
    failed = 0
    admin_bot.send_message(ADMIN_ID, "🚀 جاري توزيع الإعلان على جميع المستخدمين...")
    
    for uid in list(users_db):
        try:
            main_bot.send_message(uid, f"📢 *إعلان هام:*\n\n{announcement_text}", parse_mode="Markdown")
            success += 1
            time.sleep(0.04)
        except Exception:
            failed += 1
            
    admin_bot.send_message(
        ADMIN_ID,
        f"✅ اكتمل إرسال الإعلان بنجاح!\n\n🔹 تم الإرسال إلى: {success}\n❌ تعذر الإرسال إلى: {failed}",
        reply_markup=get_admin_keyboard()
    )

# ==================== تشغيل الخوادم والخدمات ====================

if __name__ == "__main__":
    print("⚡ تم تشغيل سيرفر Flask، وبوت تحويل النص إلى صوت، وبوت الأدمن بنجاح...")
    
    # 1. تشغيل سيرفر الويب في الخلفية لتوافق Render Web Service
    t_flask = threading.Thread(target=run_flask, daemon=True)
    t_flask.start()
    
    # 2. تشغيل بوت الأدمن في الخلفية
    t_admin = threading.Thread(target=admin_bot.infinity_polling, daemon=True)
    t_admin.start()
    
    # 3. تشغيل البوت الرئيسي في المسار الأساسي
    main_bot.infinity_polling()
            
