import threading

def run_bot():
    try:
        bot.infinity_polling(none_stop=True)
    except Exception as e:
        print(f"Bot Error: {e}")

if __name__ == "__main__":
    # تشغيل البوت في خلفية مستقلة
    t = threading.Thread(target=run_bot)
    t.daemon = True
    t.start()

    # تشغيل سيرفر الفلاسك
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
    
