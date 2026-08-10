import os
import threading
import asyncio
import edge_tts
from flask import Flask
import telebot

# 1. إنشاء سيرفر Flask للاستجابة لرابط Render وربطه بـ UptimeRobot
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# 2. إعداد توكن البوت
TOKEN = "8839838895:AAEPvUsW7OgYOumvT74slLlP5WBHcLbaMuo"
bot = telebot.TeleBot(TOKEN)

# دالة توليد الصوت غير المتزامنة (Async)
async def generate_voice(text, output_file):
    # استخدام صوت "حامد" الفصيح والواقعي من Edge TTS
    communicate = edge_tts.Communicate(text, "ar-SA-HamedNeural")
    await communicate.save(output_file)

# 3. أوامر التليجرام
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "أهلاً بك! 👋\nأرسل لي أي نص وسأقوم بتحويله إلى صوت عربي فصيح بنجاح."
    )

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    msg = bot.reply_to(message, "⏳ جاري تحويل النص إلى صوت...")
    file_path = f"voice_{message.chat.id}.mp3"

    try:
        # تشغيل عملية الصوت
        asyncio.run(generate_voice(message.text, file_path))

        # إرسال المقطع الصوتي للمستخدم
        with open(file_path, 'rb') as audio:
            bot.send_voice(message.chat.id, audio, caption="🔊 تم التحويل بنجاح")

        # حذف رسالة الانتظار
        bot.delete_message(message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ أثناء التحويل: {e}", message.chat.id, msg.message_id)

    finally:
        # تنظيف الملف الصوتي المؤقت من السيرفر
        if os.path.exists(file_path):
            os.remove(file_path)

if __name__ == '__main__':
    # تشغيل سيرفر Flask في Thread مستقل لكي لا يعطل البوت
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # تشغيل البوت باستمرار
    print("Server & Bot are running successfully...")
    bot.infinity_polling()
    
