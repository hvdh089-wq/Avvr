import os
import re
import time
import socket
import urllib.parse
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
import requests

app = Flask(__name__)

# ================================
#  تكوينات الأمان والتليجرام
# ================================
TELEGRAM_BOT_TOKEN = "8462774652:AAHpRor2oT883nJM2I_xSXg6h08eYuu1_qw"
ADMIN_CHAT_ID = "6874343840"

# ذاكرة الحظر وعدد الطلبات (في الذاكرة الحية)
BANNED_IPS = {}       # { ip: unban_datetime }
REQUEST_HISTORY = {}  # { ip: [timestamps] }

# أنماط الهجمات الخبيثة (WAF Signatures)
ATTACK_PATTERNS = [
    r"(?i)(<\s*script)", r"(?i)(javascript\s*:)", r"(?i)(UNION\s+SELECT)",
    r"(?i)(OR\s+1\s*=\s*1)", r"(?i)(DROP\s+TABLE)", r"(?i)(exec\s*\()",
    r"(?i)(\.\./\.\./)", r"(?i)(/etc/passwd)", r"(?i)(acunetix)",
    r"(?i)(sqlmap)", r"(?i)(nikto)", r"(?i)(burp)", r"(?i)(eval\s*\()"
]

def send_telegram_alert(ip, reason, payload="N/A"):
    """إرسال إشعار فوري لمطور التطبيق عبر التليجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    user_agent = request.headers.get('User-Agent', 'Unknown')
    path = request.path
    method = request.method
    
    text = (
        f"🚨 <b>تنبيه أمني: تم حظر IP مهاجم!</b>\n\n"
        f"🌐 <b>IP المهاجم:</b> <code>{ip}</code>\n"
        f"⏰ <b>المدة:</b> 48 ساعة (يومان)\n"
        f"⚠️ <b>السبب:</b> {reason}\n"
        f"🔗 <b>المسار:</b> <code>{path}</code> [{method}]\n"
        f"🖥️ <b>User-Agent:</b> <code>{user_agent}</code>\n"
        f"📦 <b>الحمولة المشبوهة:</b> <code>{payload[:200]}</code>\n\n"
        f"🛠️ <b>لوحة التحكم:</b> يمكنك رفع الحظر أو تمديده يدوياً."
    )
    
    payload_data = {
        "chat_id": ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload_data, timeout=5)
    except Exception as e:
        print(f"Telegram Alert Error: {e}")

def get_client_ip():
    """استخراج IP الحقيقي للعميل حتى خلف خوادم Render/Cloudflare"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr

@app.before_request
def security_firewall():
    """جدار حماية برلمجي يفحص كل طلب قادم"""
    ip = get_client_ip()
    now = datetime.now()

    # 1. التحقق من الحظر الحالي
    if ip in BANNED_IPS:
        if now < BANNED_IPS[ip]:
            remaining = BANNED_IPS[ip] - now
            hours = int(remaining.total_seconds() // 3600)
            return jsonify({
                "error": True,
                "message": f"تم حظر IP الخاص بك بسبب نشاط مشبوه. متبقي: {hours} ساعة."
            }), 403
        else:
            del BANNED_IPS[ip]

    # 2. الحماية من الإغراق (Rate Limiting - 20 طلب بالدقيقة)
    timestamps = REQUEST_HISTORY.get(ip, [])
    timestamps = [t for t in timestamps if now - t < timedelta(seconds=60)]
    timestamps.append(now)
    REQUEST_HISTORY[ip] = timestamps

    if len(timestamps) > 20:
        BANNED_IPS[ip] = now + timedelta(days=2)
        send_telegram_alert(ip, "محاولة إغراق السيرفر (DOS/Flood Attack)")
        return jsonify({"error": True, "message": "تم حظرك لمدة 48 ساعة بسبب الإغراق."}), 403

    # 3. فحص الأنماط الخبيثة في المعاملات والجسم والنصوص
    full_str = f"{request.path} {request.query_string.decode('utf-8', errors='ignore')} {request.get_data(as_text=True)}"
    for pattern in ATTACK_PATTERNS:
        if re.search(pattern, full_str):
            BANNED_IPS[ip] = now + timedelta(days=2)
            send_telegram_alert(ip, "اكتشاف محاولة اختراق (WAF Trigger)", full_str)
            return jsonify({"error": True, "message": "تم حظرك لمدة 48 ساعة محاولة هجوم."}), 403

def is_safe_url(url):
    """التحقق من عدم توجيه الفحص للسيرفر المحلي (SSRF Protection)"""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        ip = socket.gethostbyname(hostname)
        # منع النطاقات الداخلية
        forbidden_ranges = ['127.', '10.', '172.16.', '192.168.', '0.0.0.0']
        if any(ip.startswith(prefix) for prefix in forbidden_ranges) or hostname in ['localhost']:
            return False
        return True
    except Exception:
        return False

# ================================
#  واجهة الموقع الرئيسية HTML/CSS/JS
# ================================
INDEX_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>مستخرج الأكواد والماسح الأمني</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
    
    <style>
        :root {
            --bg-color: #0a0d14;
            --card-bg: #121824;
            --accent-cyan: #00f3ff;
            --accent-green: #00ff9d;
            --accent-red: #ff0055;
            --text-main: #e2e8f0;
            --text-muted: #94a3b8;
            --border-color: #1e293b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Tajawal', sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        /* منع التمرير بالكامل في الصفحة الرئيسية */
        html, body {
            width: 100%;
            height: 100vh;
            height: 100dvh;
            overflow: hidden;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
        }

        .header {
            padding: 12px 16px;
            background: var(--card-bg);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 800;
            font-size: 1.1rem;
            color: var(--accent-cyan);
        }

        .icon-svg {
            width: 22px;
            height: 22px;
            fill: currentColor;
        }

        .dev-badge {
            font-size: 0.75rem;
            background: rgba(0, 243, 255, 0.1);
            color: var(--accent-cyan);
            padding: 4px 10px;
            border-radius: 20px;
            border: 1px solid rgba(0, 243, 255, 0.3);
        }

        /* حاوي التطبيق الرئيسي */
        .app-container {
            flex: 1;
            position: relative;
            width: 100%;
            height: calc(100% - 55px);
            overflow: hidden;
        }

        /* الشاشات المختلفة */
        .view-screen {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            display: flex;
            flex-direction: column;
            padding: 14px;
            gap: 12px;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.25s ease-in-out;
            background: var(--bg-color);
            padding-bottom: calc(14px + env(safe-area-inset-bottom, 0px));
        }

        .view-screen.active {
            opacity: 1;
            pointer-events: auto;
        }

        /* شريط إدخال الرابط */
        .search-box {
            display: flex;
            gap: 8px;
            background: var(--card-bg);
            padding: 6px;
            border-radius: 10px;
            border: 1px solid var(--border-color);
            flex-shrink: 0;
        }

        .search-input {
            flex: 1;
            background: transparent;
            border: none;
            outline: none;
            color: var(--text-main);
            font-size: 0.95rem;
            padding: 8px 10px;
            direction: ltr;
            text-align: left;
        }

        .btn {
            background: var(--accent-cyan);
            color: #000;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.9rem;
            transition: opacity 0.2s;
        }

        .btn:active { opacity: 0.8; }
        .btn-secondary { background: var(--border-color); color: var(--text-main); }
        .btn-danger { background: var(--accent-red); color: #fff; }

        /* منطقة عرض الكود الاستعراضية */
        .code-container {
            flex: 1;
            background: var(--card-bg);
            border-radius: 10px;
            border: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .code-header {
            padding: 10px 14px;
            background: rgba(0,0,0,0.3);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }

        .code-actions {
            display: flex;
            gap: 6px;
        }

        /* السماح بالتمرير داخل الكود فقط */
        .code-area {
            flex: 1;
            padding: 14px;
            overflow: auto;
            font-family: monospace;
            font-size: 0.85rem;
            color: #a7f3d0;
            white-space: pre-wrap;
            word-break: break-all;
            direction: ltr;
            text-align: left;
            -webkit-overflow-scrolling: touch;
        }

        /* شاشة التفاصيل الأمنية */
        .details-content {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 14px;
            -webkit-overflow-scrolling: touch;
        }

        .gauge-card {
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            padding: 20px;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
        }

        .gauge-circle {
            width: 110px;
            height: 110px;
            border-radius: 50%;
            background: conic-gradient(var(--accent-green) 0deg, var(--border-color) 0deg);
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }

        .gauge-circle::before {
            content: '';
            position: absolute;
            width: 86px;
            height: 86px;
            border-radius: 50%;
            background: var(--card-bg);
        }

        .gauge-value {
            position: relative;
            font-size: 1.6rem;
            font-weight: 800;
        }

        .status-badge {
            padding: 6px 16px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 0.9rem;
        }

        .status-safe { background: rgba(0, 255, 157, 0.15); color: var(--accent-green); border: 1px solid var(--accent-green); }
        .status-danger { background: rgba(255, 0, 85, 0.15); color: var(--accent-red); border: 1px solid var(--accent-red); }

        .info-list {
            background: var(--card-bg);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .info-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            font-size: 0.9rem;
        }

        .info-item:last-child { border-bottom: none; }
        .info-label { color: var(--text-muted); }
        .info-val { font-weight: 600; direction: ltr; }

        .loader {
            display: none;
            width: 20px;
            height: 20px;
            border: 2px solid transparent;
            border-top-color: #000;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin { to { transform: rotate(360deg); } }
    </style>
</head>
<body>

    <!-- الشريط العلوي -->
    <header class="header">
        <div class="brand">
            <svg class="icon-svg" viewBox="0 0 24 24"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-5.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8s0 0 0 0z"/></svg>
            <span>فاحص الأكواد والمواقع</span>
        </div>
        <div class="dev-badge">المطور أسعد</div>
    </header>

    <div class="app-container">
        
        <!-- الواجهة الرئيسية (استخراج الكود) -->
        <main id="mainScreen" class="view-screen active">
            <div class="search-box">
                <input type="url" id="targetUrl" class="search-input" placeholder="https://example.com" required>
                <button class="btn" onclick="startScan()">
                    <span id="btnText">فحص</span>
                    <div id="btnLoader" class="loader"></div>
                </button>
            </div>

            <div class="code-container">
                <div class="code-header">
                    <span style="font-size: 0.85rem; color: var(--text-muted);">الكود المستخرج (HTML / CSS / JS)</span>
                    <div class="code-actions">
                        <button class="btn btn-secondary" onclick="copyCode()" title="نسخ">
                            <svg class="icon-svg" viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>
                        </button>
                        <button class="btn btn-secondary" onclick="downloadCode()" title="تحميل">
                            <svg class="icon-svg" viewBox="0 0 24 24"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
                        </button>
                        <button class="btn" onclick="switchScreen('detailsScreen')" style="background: rgba(0,243,255,0.2); color: var(--accent-cyan);">
                            <svg class="icon-svg" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
                            تفاصيل
                        </button>
                    </div>
                </div>
                <pre id="codeOutput" class="code-area">ضع الرابط واضغط فحص لاستخراج السورس كود الكامل والمعلومات...</pre>
            </div>
        </main>

        <!-- واجهة التفاصيل الأمنية -->
        <section id="detailsScreen" class="view-screen">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-shrink: 0;">
                <button class="btn btn-secondary" onclick="switchScreen('mainScreen')">
                    <svg class="icon-svg" viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
                    رجوع
                </button>
                <h3 style="font-size: 1rem;">التقرير الأمني المفصل</h3>
            </div>

            <div class="details-content">
                <div class="gauge-card">
                    <div class="gauge-circle" id="gaugeCircle">
                        <div class="gauge-value" id="gaugeVal">0%</div>
                    </div>
                    <div id="statusBadge" class="status-badge status-safe">بانتظار الفحص</div>
                </div>

                <div class="info-list" id="detailsList">
                    <div class="info-item">
                        <span class="info-label">حالة الفحص</span>
                        <span class="info-val">لم يتم الفحص بعد</span>
                    </div>
                </div>
            </div>
        </section>

    </div>

    <script>
        let currentScanData = null;

        function switchScreen(screenId) {
            document.querySelectorAll('.view-screen').forEach(s => s.classList.remove('active'));
            document.getElementById(screenId).classList.add('active');
        }

        async function startScan() {
            const urlInput = document.getElementById('targetUrl').value.trim();
            if (!urlInput) return alert('يرجى إدخال الرابط أولاً!');

            const btnText = document.getElementById('btnText');
            const btnLoader = document.getElementById('btnLoader');
            const codeOutput = document.getElementById('codeOutput');

            btnText.style.display = 'none';
            btnLoader.style.display = 'block';
            codeOutput.textContent = 'جاري الاتصال بالسيرفر والتحليل...';

            try {
                const response = await fetch('/api/scan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: urlInput })
                });

                const data = await response.json();

                if (data.error) {
                    alert(data.message);
                    codeOutput.textContent = 'خطأ: ' + data.message;
                } else {
                    currentScanData = data;
                    codeOutput.textContent = data.raw_code;
                    renderDetails(data);
                }
            } catch (err) {
                alert('حدث خطأ أثناء التواصل مع السيرفر');
                codeOutput.textContent = 'فشل الاتصال بالشبكة.';
            } finally {
                btnText.style.display = 'inline';
                btnLoader.style.display = 'none';
            }
        }

        function renderDetails(data) {
            const score = data.score;
            const gaugeCircle = document.getElementById('gaugeCircle');
            const gaugeVal = document.getElementById('gaugeVal');
            const statusBadge = document.getElementById('statusBadge');
            const detailsList = document.getElementById('detailsList');

            // تحديث العداد
            gaugeVal.textContent = score + '%';
            gaugeCircle.style.background = `conic-gradient(${score > 60 ? 'var(--accent-green)' : 'var(--accent-red)'} ${score * 3.6}deg, var(--border-color) 0deg)`;

            // التقييم النهائي
            if (data.is_safe) {
                statusBadge.textContent = 'موقع صالح وآمن';
                statusBadge.className = 'status-badge status-safe';
            } else {
                statusBadge.textContent = 'موقع مشبوه / غير آمن';
                statusBadge.className = 'status-badge status-danger';
            }

            // قائمة التفاصيل الحقيقية
            detailsList.innerHTML = '';
            data.details.forEach(item => {
                const row = document.createElement('div');
                row.className = 'info-item';
                row.innerHTML = `<span class="info-label">${item.label}</span><span class="info-val" style="color:${item.color || 'var(--text-main)'}">${item.value}</span>`;
                detailsList.appendChild(row);
            });
        }

        function copyCode() {
            const code = document.getElementById('codeOutput').textContent;
            navigator.clipboard.writeText(code).then(() => {
                alert('تم نسخ الكود بنجاح!');
            });
        }

        function downloadCode() {
            const code = document.getElementById('codeOutput').textContent;
            const blob = new Blob([code], { type: 'text/html;charset=utf-8' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = 'extracted_source.html';
            link.click();
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/api/scan', methods=['POST'])
def scan_url():
    data = request.get_json() or {}
    target_url = data.get('url', '').strip()

    if not target_url.startswith(('http://', 'https://')):
        target_url = 'https://' + target_url

    if not is_safe_url(target_url):
        return jsonify({"error": True, "message": "الرابط غير مسموح به أو يشير لنطاق داخلي!"}), 400

    try:
        start_time = time.time()
        res = requests.get(
            target_url,
            timeout=10,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CyberSecurityScanner/2.0'}
        )
        latency = round((time.time() - start_time) * 1000, 2)

        # حساب النتيجة بناءً على المعايير الأمنية الحقيقية
        score = 100
        details = []

        # 1. التشفير SSL/HTTPS
        is_https = target_url.startswith('https://')
        if not is_https:
            score -= 30
            details.append({"label": "بروتوكول التشفير", "value": "HTTP (غير مشفر)", "color": "var(--accent-red)"})
        else:
            details.append({"label": "بروتوكول التشفير", "value": "HTTPS (مشفر)", "color": "var(--accent-green)"})

        # 2. الهيدرز الأمنية
        headers = res.headers
        sec_headers = ['Strict-Transport-Security', 'Content-Security-Policy', 'X-Frame-Options', 'X-Content-Type-Options']
        found_sec_headers = [h for h in sec_headers if h in headers]

        if len(found_sec_headers) < 2:
            score -= 20
            details.append({"label": "الحماية من الاختراق (Security Headers)", "value": "ضعيفة جداً", "color": "var(--accent-red)"})
        else:
            details.append({"label": "الحماية من الاختراق (Security Headers)", "value": f"جيدة ({len(found_sec_headers)}/4)", "color": "var(--accent-green)"})

        # 3. زمن الاستجابة والحجم
        details.append({"label": "زمن استجابة السيرفر", "value": f"{latency} ms"})
        details.append({"label": "حالة استجابة HTTP", "value": str(res.status_code)})
        details.append({"label": "نوع الخادم (Server)", "value": headers.get('Server', 'مخفي/غير معروف')})

        # 4. فحص محتوى HTML لأمور مشبوهة
        body_text = res.text.lower()
        if 'eval(' in body_text or 'unescape(' in body_text:
            score -= 25
            details.append({"label": "أكواد جافاسكربت", "value": "تم كشف دلالات مضللة/مشفّرة", "color": "var(--accent-red)"})
        else:
            details.append({"label": "أكواد جافاسكربت", "value": "طبيعية بدون تشفير مشبوه", "color": "var(--accent-green)"})

        score = max(5, min(100, score))
        is_safe = score >= 60

        return jsonify({
            "error": False,
            "raw_code": res.text,
            "score": score,
            "is_safe": is_safe,
            "details": details
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": True, "message": f"فشل الاتصال بالموقع: {str(e)}"}), 500

if __name__ == '__main__':
    # تشغيل محلي متوافق مع Pydroid 3 و Termux
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
