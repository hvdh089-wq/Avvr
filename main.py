# -*- coding: utf-8 -*-
# ============================================================
# ساحة الحديد - لعبة قتال جماعي لثلاثة هواتف | تطوير: أسعد المطور
# التثبيت (Render Build):  pip install flask flask-sock gunicorn
# التشغيل  (Render Start): gunicorn -w 1 --threads 100 -b 0.0.0.0:$PORT main:app
# محلياً: python main.py
# ملاحظة: يجب عامل واحد فقط (-w 1) لأن الغرف محفوظة في ذاكرة العملية.
# ============================================================
import os, time, json, math, random, secrets, threading, re
from flask import Flask, request, jsonify, Response
from flask_sock import Sock

# ---------- القسم 1: الإعدادات ----------
GAME_NAME = "ساحة الحديد"          # غيّر اسم اللعبة من هنا
DEV_NAME = "أسعد المطور"
W, H = 1600, 1000                   # أبعاد الساحة
WALLS = [(300,200,40,250),(1260,550,40,250),(700,100,200,40),(700,860,200,40),
         (500,450,120,100),(980,450,120,100),(150,700,200,40),(1250,260,200,40)]
ZONE = (800, 500, 110)              # نقطة استراتيجية: س، ص، نصف القطر
SPAWNS = [(100,100),(1500,900),(1500,100)]
ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MATCH_SECONDS, MAG, RESERVE, RADIUS = 150, 30, 90, 14
CODE_TTL = 3 * 3600
app = Flask(__name__)
sock = Sock(app)
LOCK = threading.RLock()
ROOMS, CODES, RATE = {}, {}, {}

# ---------- القسم 2: منطق الغرف (السيرفر هو المرجع) ----------
def new_code():
    while True:
        c = "".join(secrets.choice(ALPHA) for _ in range(6))
        if c not in CODES: return c

def new_player(i):
    x, y = SPAWNS[i]
    return dict(x=x, y=y, vx=0.0, vy=0.0, aim=0.0, hp=100, ammo=MAG, res=RESERVE, inp={},
                last=0.0, rel=0.0, dead=0.0, alive=True, score=0.0, kills=0, deaths=0, act=False)

def reset_player(i, p):
    p.update(new_player(i)); p["act"] = True

def make_room(name):
    rid = secrets.token_hex(8)
    r = dict(id=rid, name=name, codes=[new_code() for _ in range(3)], created=time.time(), st="lobby",
             players=[new_player(i) for i in range(3)], ws=[None]*3, conn=[False]*3, bullets=[],
             t_end=0, cd_end=0, ev=[], win=-1, empty_since=time.time(), msgs=[[0,0]]*3)
    for i, c in enumerate(r["codes"]): CODES[c] = (rid, i)
    ROOMS[rid] = r
    return r

def drop_room(r):
    for c in r["codes"]: CODES.pop(c, None)
    ROOMS.pop(r["id"], None)
    for w in r["ws"]:
        try:
            if w: w.close()
        except Exception: pass

def hit_wall(x, y, rad):
    for a, b, w, h in WALLS:
        cx, cy = min(max(x, a), a + w), min(max(y, b), b + h)
        if (x-cx)**2 + (y-cy)**2 < rad*rad: return True
    return x < rad or y < rad or x > W-rad or y > H-rad

def step(r, now, dt):
    r["ev"] = []
    if r["st"] == "countdown" and now >= r["cd_end"]:
        r["st"] = "playing"; r["t_end"] = now + MATCH_SECONDS
    if r["st"] != "playing": return
    P = r["players"]
    for i, p in enumerate(P):
        if not p["act"]: continue
        if not p["alive"]:
            if now >= p["dead"]:
                sx, sy = SPAWNS[i]; p.update(x=sx, y=sy, hp=100, ammo=MAG, res=RESERVE, alive=True, rel=0.0)
            continue
        inp = p["inp"] if r["conn"][i] else {}
        mx, my = inp.get("mx", 0), inp.get("my", 0)
        m = math.hypot(mx, my)
        if m > 1: mx, my = mx/m, my/m
        spd = 210 * (1.55 if inp.get("sp") and m > .3 else 1.0)      # سرعة المشي / الركض
        k = min(1, dt * 9)                                            # تسارع وتباطؤ
        p["vx"] += (mx*spd - p["vx"]) * k; p["vy"] += (my*spd - p["vy"]) * k
        nx = p["x"] + p["vx"]*dt
        if hit_wall(nx, p["y"], RADIUS): p["vx"] = 0
        else: p["x"] = nx
        ny = p["y"] + p["vy"]*dt
        if hit_wall(p["x"], ny, RADIUS): p["vy"] = 0
        else: p["y"] = ny
        ax, ay = inp.get("ax", 0), inp.get("ay", 0)
        if math.hypot(ax, ay) > .2: p["aim"] = math.atan2(ay, ax)
        if p["rel"] and now >= p["rel"]:                              # انتهاء إعادة التلقيم
            take = min(MAG - p["ammo"], p["res"]); p["ammo"] += take; p["res"] -= take; p["rel"] = 0.0
        if not p["rel"] and p["res"] > 0 and p["ammo"] < MAG and (inp.get("rl") or p["ammo"] == 0):
            p["rel"] = now + 1.6; r["ev"].append(["rl", i])
        if inp.get("fire") and not p["rel"] and p["ammo"] > 0 and now - p["last"] >= 0.11:
            p["last"] = now; p["ammo"] -= 1
            a = p["aim"] + random.uniform(-.045, .045) - (0.02 if inp.get("sp") else 0)  # انتشار الطلقات
            r["bullets"].append([p["x"], p["y"], math.cos(a)*760, math.sin(a)*760, 1.2, i, 0.0])
            r["ev"].append(["sh", i])
    for b in r["bullets"][:]:                                         # حركة الطلقات والإصابات
        dead = False
        for _ in range(3):
            d = dt / 3
            b[0] += b[2]*d; b[1] += b[3]*d; b[4] -= d; b[6] += 760*d
            if b[4] <= 0 or hit_wall(b[0], b[1], 1): dead = True; break
            for j, q in enumerate(P):
                if j == b[5] or not q["act"] or not q["alive"] or not r["conn"][j]: continue
                if (q["x"]-b[0])**2 + (q["y"]-b[1])**2 < (RADIUS+2)**2:
                    q["hp"] -= max(10, 26 - b[6]/60)                  # الضرر يقل مع المسافة
                    r["ev"].append(["hit", j]); dead = True
                    if q["hp"] <= 0:
                        q["alive"] = False; q["dead"] = now + 3; q["deaths"] += 1
                        P[b[5]]["kills"] += 1; P[b[5]]["score"] += 10
                        r["ev"].append(["kill", b[5], j])
                    break
            if dead: break
        if dead: r["bullets"].remove(b)
    inside = [i for i, p in enumerate(P) if p["act"] and p["alive"] and (p["x"]-ZONE[0])**2 + (p["y"]-ZONE[1])**2 < ZONE[2]**2]
    r["zone"] = inside[0] if len(inside) == 1 else (-2 if inside else -1)   # -2 متنازع عليها
    if len(inside) == 1: P[inside[0]]["score"] += dt                        # نقطة لكل ثانية سيطرة
    if now >= r["t_end"]:
        r["st"] = "ended"; r["bullets"] = []
        act = [i for i, p in enumerate(P) if p["act"]]
        r["win"] = max(act, key=lambda i: P[i]["score"]) if act else -1

def snapshot(r, now):
    P = r["players"]
    return json.dumps(dict(t="s", st=r["st"], name=r["name"], win=r["win"], zone=r.get("zone", -1),
        left=max(0, round(r["t_end"]-now)) if r["st"] == "playing" else MATCH_SECONDS,
        cd=max(1, math.ceil(r["cd_end"]-now)) if r["st"] == "countdown" else 0,
        p=[[round(p["x"]), round(p["y"]), round(p["aim"], 2), max(0, round(p["hp"])), p["ammo"], p["res"],
            int(p["score"]), p["kills"], p["deaths"], int(p["alive"]), int(r["conn"][i]), int(p["rel"] > 0), int(p["act"])]
           for i, p in enumerate(P)],
        b=[[round(b[0]), round(b[1])] for b in r["bullets"]], ev=r["ev"]))

def broadcast(r, now):
    msg = snapshot(r, now)
    for i, w in enumerate(r["ws"]):
        if w and r["conn"][i]:
            try: w.send(msg)
            except Exception: r["conn"][i] = False; r["players"][i]["inp"] = {}

def game_loop():
    last = time.time()
    while True:
        time.sleep(0.05)
        now = time.time(); dt = min(0.1, now - last); last = now
        with LOCK:
            for r in list(ROOMS.values()):
                try:
                    step(r, now, dt); broadcast(r, now)
                    if any(r["conn"]): r["empty_since"] = now
                    if now - r["created"] > CODE_TTL or now - r["empty_since"] > 900: drop_room(r)
                except Exception as e: print("loop error:", repr(e))
            for k in [k for k, v in RATE.items() if now - v[0] > 60]: RATE.pop(k, None)

threading.Thread(target=game_loop, daemon=True).start()

# ---------- القسم 3: مسارات HTTP ----------
@app.route("/health")
def health():
    with LOCK: return jsonify(ok=True, rooms=len(ROOMS))

@app.route("/api/create", methods=["POST"])
def api_create():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "x").split(",")[0].strip()
    now = time.time(); t0, n = RATE.get(ip, (now, 0))
    if now - t0 > 60: t0, n = now, 0
    RATE[ip] = (t0, n + 1)
    if n >= 8: return jsonify(error="محاولات كثيرة، انتظر دقيقة"), 429
    d = request.get_json(silent=True) or {}
    name = re.sub(r"[<>&\"'\\]", "", str(d.get("name", "")))[:24].strip() or "ASAD_BATTLE"
    with LOCK:
        if len(ROOMS) >= 60: return jsonify(error="السيرفر ممتلئ حالياً"), 503
        r = make_room(name)
        return jsonify(name=r["name"], codes=r["codes"])

@app.route("/")
def index():
    return Response(PAGE.replace("__GAME__", GAME_NAME).replace("__DEV__", DEV_NAME), mimetype="text/html")

# ---------- القسم 4: WebSocket ----------
def num(v):
    try:
        v = float(v)
        return 0.0 if v != v else max(-1.0, min(1.0, v))
    except Exception: return 0.0

@sock.route("/ws")
def ws_handler(ws):
    rid = slot = None
    try:
        while True:
            raw = ws.receive(timeout=40)
            if raw is None: continue
            if len(raw) > 400: continue
            try: m = json.loads(raw)
            except Exception: continue
            if not isinstance(m, dict): continue
            t = m.get("t")
            with LOCK:
                if rid is None:                                         # لا شيء قبل التحقق من الرمز
                    if t != "join": continue
                    code = str(m.get("code", "")).strip().upper()[:8]
                    hit = CODES.get(code)
                    if not hit: ws.send(json.dumps(dict(t="err", m="الرمز غير صحيح أو منتهي الصلاحية"))); continue
                    r = ROOMS.get(hit[0])
                    if not r: ws.send(json.dumps(dict(t="err", m="الغرفة غير موجودة"))); continue
                    if r["conn"][hit[1]]: ws.send(json.dumps(dict(t="err", m="هذا الرمز مستخدم بالفعل من جهاز متصل"))); continue
                    rid, slot = hit
                    r["ws"][slot] = ws; r["conn"][slot] = True
                    if r["st"] == "playing": reset_player(slot, r["players"][slot]) if not r["players"][slot]["act"] else None
                    ws.send(json.dumps(dict(t="joined", slot=slot, name=r["name"], codes=r["codes"] if slot == 0 else None)))
                    continue
                r = ROOMS.get(rid)
                if not r or r["ws"][slot] is not ws: return
                now = time.time(); c = r["msgs"][slot]
                if now - c[0] > 1: r["msgs"][slot] = c = [now, 0]
                c[1] += 1
                if c[1] > 60: continue                                   # حد معدل الرسائل
                if t == "in":
                    r["players"][slot]["inp"] = dict(mx=num(m.get("mx")), my=num(m.get("my")), ax=num(m.get("ax")),
                        ay=num(m.get("ay")), fire=bool(m.get("fire")), rl=bool(m.get("rl")), sp=bool(m.get("sp")))
                elif t == "start" and slot == 0 and r["st"] in ("lobby", "ended"):
                    for i, p in enumerate(r["players"]):
                        if r["conn"][i]: reset_player(i, p)
                        else: p.update(new_player(i))
                    r["bullets"] = []; r["win"] = -1; r["st"] = "countdown"; r["cd_end"] = now + 3
                elif t == "lobby" and slot == 0 and r["st"] == "ended": r["st"] = "lobby"
                elif t == "cancel" and slot == 0:
                    msg = json.dumps(dict(t="err", m="تم إلغاء الغرفة")); 
                    for w in r["ws"]:
                        try:
                            if w: w.send(msg)
                        except Exception: pass
                    drop_room(r); return
    except Exception:
        pass
    finally:
        with LOCK:
            r = ROOMS.get(rid) if rid else None
            if r and r["ws"][slot] is ws: r["conn"][slot] = False; r["players"][slot]["inp"] = {}

# ---------- القسم 5: الواجهة (HTML/CSS/JS) ----------
PAGE = r"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>__GAME__</title><style>
:root{--bg:#0d120e;--pn:#161d17;--ln:#2c3a2e;--tx:#e3eadc;--mu:#8a9a86;--ac:#d4a33a;--ok:#4ade80;--bad:#ef5350}
*{box-sizing:border-box;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;touch-action:none}
html,body{margin:0;height:100%;background:var(--bg);color:var(--tx);font-family:Tahoma,"Segoe UI",sans-serif;overflow:hidden}
.scr{position:fixed;inset:0;display:none;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding:max(16px,env(safe-area-inset-top)) 18px 18px}
.scr.on{display:flex}
#bg{position:fixed;inset:0;width:100%;height:100%}
h1{margin:0;font-size:44px;letter-spacing:1px;color:var(--ac);text-shadow:0 2px 0 #000}
.sub{color:var(--mu);font-size:14px}
.big{width:min(86vw,360px);padding:20px;border:2px solid var(--ln);background:rgba(22,29,23,.9);color:var(--tx);border-radius:4px;font-size:21px;font-weight:700;display:flex;align-items:center;gap:14px;transition:.15s}
.big:active{transform:scale(.97);border-color:var(--ac);background:#202a21}
.big svg{width:34px;height:34px;flex:none;fill:none;stroke:var(--ac);stroke-width:2}
input{width:min(86vw,360px);padding:15px;font-size:22px;text-align:center;background:#0a0e0a;border:2px solid var(--ln);color:var(--tx);border-radius:4px;direction:ltr;letter-spacing:3px;-webkit-user-select:text;user-select:text}
.btn{padding:13px 22px;font-size:17px;font-weight:700;border:0;border-radius:4px;background:var(--ac);color:#1a1405}
.btn.g{background:var(--pn);color:var(--tx);border:1px solid var(--ln)}
#err{color:var(--bad);min-height:22px;text-align:center}
.dev{position:fixed;bottom:max(8px,env(safe-area-inset-bottom));left:0;right:0;text-align:center;color:var(--mu);font-size:13px;pointer-events:none}
.dev b{color:var(--ac)}
#game{display:none}#game.on{display:block}
#cv{position:fixed;inset:0;width:100%;height:100%;background:#10160f}
.hud{position:fixed;pointer-events:none;font-weight:700;text-shadow:0 1px 2px #000}
#top{top:max(6px,env(safe-area-inset-top));left:0;right:0;display:flex;justify-content:center;gap:16px;font-size:16px}
#top span{background:rgba(10,14,10,.65);padding:4px 10px;border-radius:3px}
#st{left:12px;bottom:calc(50% + 8px);font-size:15px;line-height:1.5;text-align:left;direction:ltr;background:rgba(10,14,10,.65);padding:6px 10px;border-radius:3px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--bad);margin:0 4px}
.dot.on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
#ctl{position:fixed;inset:0;pointer-events:none}
#ctl>*{pointer-events:auto}
.stick{position:absolute;bottom:max(24px,env(safe-area-inset-bottom));width:calc(130px*var(--sz));height:calc(130px*var(--sz));border-radius:50%;background:rgba(255,255,255,.07);border:2px solid rgba(255,255,255,.25);opacity:var(--op)}
.stick i{position:absolute;left:50%;top:50%;width:54%;height:54%;margin:-27% 0 0 -27%;border-radius:50%;background:rgba(212,163,58,.7);border:2px solid #f3d27a}
#sL{left:max(22px,env(safe-area-inset-left))}#sR{right:calc(max(22px,env(safe-area-inset-right)) + 105px*var(--sz))}
.ab{position:absolute;width:calc(70px*var(--sz));height:calc(70px*var(--sz));border-radius:50%;border:2px solid rgba(255,255,255,.35);background:rgba(20,28,20,.6);color:var(--tx);font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;opacity:var(--op)}
.ab.p{background:rgba(212,163,58,.65);border-color:#f3d27a}
#bF{right:max(18px,env(safe-area-inset-right));bottom:calc(max(24px,env(safe-area-inset-bottom)) + 30px*var(--sz));width:calc(88px*var(--sz));height:calc(88px*var(--sz));background:rgba(239,83,80,.55);border-color:#ff9a97;font-size:16px}
#bR{right:max(18px,env(safe-area-inset-right));bottom:calc(max(24px,env(safe-area-inset-bottom)) + 140px*var(--sz))}
#bS{right:calc(max(18px,env(safe-area-inset-right)) + 82px*var(--sz));bottom:calc(max(24px,env(safe-area-inset-bottom)) + 120px*var(--sz))}
#ov{position:fixed;inset:0;display:none;flex-direction:column;align-items:center;justify-content:center;gap:10px;background:rgba(8,12,8,.86);padding:16px;z-index:5;text-align:center}
#ov.on{display:flex}
.code{display:flex;align-items:center;gap:8px;background:var(--pn);border:1px solid var(--ln);padding:8px 12px;border-radius:4px;width:min(92vw,380px);justify-content:space-between}
.code b{font-size:22px;letter-spacing:3px;direction:ltr;color:var(--ac);-webkit-user-select:text;user-select:text}
.code small{display:block;color:var(--mu);font-size:12px}
.row{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
#flash{position:fixed;inset:0;background:rgba(239,83,80,.35);opacity:0;pointer-events:none;transition:opacity .25s}
#cd{position:fixed;inset:0;display:none;align-items:center;justify-content:center;font-size:110px;font-weight:900;color:var(--ac);text-shadow:0 3px 0 #000;pointer-events:none}
#net{position:fixed;top:40px;left:0;right:0;text-align:center;background:var(--bad);color:#fff;padding:6px;display:none;z-index:9;font-weight:700}
#set{position:fixed;top:max(6px,env(safe-area-inset-top));right:8px;z-index:6;width:38px;height:38px;border-radius:4px;background:rgba(10,14,10,.7);border:1px solid var(--ln);color:var(--tx)}
#sp{display:none;position:fixed;inset:0;background:rgba(8,12,8,.92);z-index:8;flex-direction:column;align-items:center;justify-content:center;gap:12px}
#sp label{display:flex;gap:10px;align-items:center;width:min(86vw,320px);justify-content:space-between}
#sp input[type=range]{width:55%;padding:0;letter-spacing:0}
</style></head><body>
<canvas id="bg"></canvas>
<div class="scr on" id="menu">
 <h1>__GAME__</h1><div class="sub">قتال جماعي لثلاثة هواتف</div>
 <button class="big" id="mCreate"><svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11"/><path d="M16 5v6M16 21v6M5 16h6M21 16h6"/></svg>إنشاء غرفة واللعب</button>
 <button class="big" id="mCtl"><svg viewBox="0 0 32 32"><rect x="3" y="9" width="26" height="15" rx="7"/><path d="M10 13v7M6.5 16.5h7"/><circle cx="21" cy="14.5" r="1.4"/><circle cx="24" cy="18" r="1.4"/></svg>وحدة التحكم</button>
 <div class="dev">تطوير <b>__DEV__</b></div>
</div>
<div class="scr" id="create"><h1 style="font-size:30px">إنشاء غرفة</h1>
 <input id="rname" value="ASAD_BATTLE" maxlength="24" style="letter-spacing:1px">
 <button class="btn" id="doCreate">إنشاء الغرفة</button><button class="btn g" data-back>رجوع</button><div class="err" id="err1" style="color:var(--bad)"></div></div>
<div class="scr" id="join"><h1 style="font-size:30px">وحدة التحكم</h1><div class="sub">اكتب الرمز الظاهر على شاشة اللاعب الأساسي</div>
 <input id="jcode" maxlength="8" autocapitalize="characters" autocomplete="off" placeholder="XXXXXX">
 <button class="btn" id="doJoin">اتصال</button><button class="btn g" data-back>رجوع</button><div id="err"></div></div>
<div id="game">
 <canvas id="cv"></canvas>
 <div class="hud" id="top"><span id="tTime">0:00</span><span id="tScore"></span><span id="tConn"></span></div>
 <div class="hud" id="st"></div><div id="cd"></div><div id="flash"></div><div id="net">انقطع الاتصال - جارٍ إعادة المحاولة</div>
 <button id="set" aria-label="الإعدادات"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/></svg></button>
 <div id="ctl"><div class="stick" id="sL"><i></i></div><div class="stick" id="sR"><i></i></div>
  <div class="ab p" id="bF">نار</div><div class="ab" id="bR">تلقيم</div><div class="ab" id="bS">ركض</div></div>
 <div id="ov"></div>
 <div id="sp"><label>الصوت<input type="range" id="sVol" min="0" max="1" step=".05"></label>
  <label>حجم الأزرار<input type="range" id="sSz" min=".7" max="1.4" step=".05"></label>
  <label>الشفافية<input type="range" id="sOp" min=".3" max="1" step=".05"></label>
  <label>الاهتزاز<input type="checkbox" id="sVib"></label><button class="btn" id="spClose">متابعة</button></div>
</div>
<script>
const $=s=>document.querySelector(s);
let ws=null,slot=-1,S=null,joined=false,code='',retry=0,closing=false,disp=[],host=false,hitT=0,aud=null;
const NAMES=['القائد','اللاعب 2','اللاعب 3'],COL=['#d4a33a','#4aa3e0','#e0584a'];
let cfg=Object.assign({vol:.6,sz:1,op:.8,vib:true},JSON.parse(localStorage.getItem('cfg')||'{}'));
function applyCfg(){document.documentElement.style.setProperty('--sz',cfg.sz);document.documentElement.style.setProperty('--op',cfg.op);try{localStorage.setItem('cfg',JSON.stringify(cfg))}catch(e){}}
applyCfg();
['Vol','Sz','Op'].forEach(k=>{const e=$('#s'+k);e.value=cfg[k.toLowerCase()];e.oninput=()=>{cfg[k.toLowerCase()]=+e.value;applyCfg()}});
$('#sVib').checked=cfg.vib;$('#sVib').onchange=e=>{cfg.vib=e.target.checked;applyCfg()};
$('#set').onclick=()=>$('#sp').style.display='flex';$('#spClose').onclick=()=>$('#sp').style.display='none';
function show(id){document.querySelectorAll('.scr').forEach(e=>e.classList.toggle('on',e.id==id));$('#game').classList.toggle('on',id=='game');$('#bg').style.display=id=='game'?'none':'block'}
document.querySelectorAll('[data-back]').forEach(b=>b.onclick=()=>{closing=true;if(ws)ws.close();show('menu')});
// ---- صوت (Web Audio) ----
function au(){if(!aud){try{aud=new (window.AudioContext||window.webkitAudioContext)()}catch(e){}}if(aud&&aud.state=='suspended')aud.resume()}
document.addEventListener('pointerdown',au);
function snd(kind){if(!aud||!cfg.vol)return;const t=aud.currentTime,g=aud.createGain(),o=aud.createOscillator();o.connect(g);g.connect(aud.destination);
 const v=cfg.vol*.25;let f=[440,440,.1,'sine'];
 if(kind=='shot')f=[180,60,.09,'sawtooth'];else if(kind=='rl')f=[600,900,.12,'square'];else if(kind=='hit')f=[300,120,.15,'square'];
 else if(kind=='ok')f=[500,900,.2,'sine'];else if(kind=='bad')f=[300,150,.3,'sawtooth'];else if(kind=='win')f=[400,1000,.5,'triangle'];
 o.type=f[3];o.frequency.setValueAtTime(f[0],t);o.frequency.exponentialRampToValueAtTime(f[1],t+f[2]);g.gain.setValueAtTime(v,t);g.gain.exponentialRampToValueAtTime(.001,t+f[2]);o.start(t);o.stop(t+f[2]+.02)}
// ---- شاشة البداية المتحركة ----
(function(){const c=$('#bg'),x=c.getContext('2d');let P=[];function rs(){c.width=innerWidth;c.height=innerHeight}rs();onresize=rs;
 for(let i=0;i<40;i++)P.push([Math.random(),Math.random(),Math.random()*1.5+.5,Math.random()*.3+.05]);
 (function f(){if(c.style.display!='none'){const w=c.width,h=c.height,g=x.createLinearGradient(0,0,0,h);g.addColorStop(0,'#1b2a22');g.addColorStop(.6,'#2a3224');g.addColorStop(1,'#0d120e');x.fillStyle=g;x.fillRect(0,0,w,h);
 x.fillStyle='#0f1710';x.beginPath();x.moveTo(0,h*.72);for(let i=0;i<=8;i++)x.lineTo(w*i/8,h*(.66+.07*Math.sin(i*1.7)));x.lineTo(w,h);x.lineTo(0,h);x.fill();
 x.fillStyle='rgba(212,163,58,.35)';P.forEach(p=>{p[0]=(p[0]+p[3]*.0008)%1;x.fillRect(p[0]*w,p[1]*h,p[2],p[2])})}requestAnimationFrame(f)})()})();
// ---- الشبكة ----
function connect(){closing=false;const u=(location.protocol=='https:'?'wss://':'ws://')+location.host+'/ws';ws=new WebSocket(u);
 ws.onopen=()=>{ws.send(JSON.stringify({t:'join',code}))};
 ws.onmessage=e=>{const m=JSON.parse(e.data);
  if(m.t=='joined'){slot=m.slot;joined=true;retry=0;host=slot==0;$('#net').style.display='none';snd('ok');show('game');$('#cv').style.display=host?'block':'none';
   if(m.codes)window.CODES=m.codes;$('#ctl').style.display='block'}
  else if(m.t=='err'){snd('bad');if(!joined){$('#err').textContent=m.m;$('#err1').textContent=m.m;closing=true;ws.close()}else{closing=true;joined=false;ws.close();alert(m.m);show('menu')}}
  else if(m.t=='s'){S=m;onState()}};
 ws.onclose=()=>{if(closing)return;if(joined){$('#net').style.display='block';resetInput();setTimeout(connect,Math.min(5000,500*++retry))}else if(!$('#err').textContent){$('#err').textContent='تعذر الوصول إلى السيرفر';}};
 ws.onerror=()=>{}}
$('#mCreate').onclick=()=>show('create');$('#mCtl').onclick=()=>{$('#err').textContent='';show('join')};
$('#doCreate').onclick=async()=>{const b=$('#doCreate');b.disabled=true;$('#err1').textContent='';
 try{const r=await fetch('/api/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#rname').value})});const d=await r.json();
  if(!r.ok){$('#err1').textContent=d.error||'تعذر إنشاء الغرفة'}else{window.CODES=d.codes;code=d.codes[0];connect()}}catch(e){$('#err1').textContent='تعذر الوصول إلى السيرفر'}b.disabled=false};
$('#doJoin').onclick=()=>{code=$('#jcode').value.trim().toUpperCase();if(code.length<4){$('#err').textContent='اكتب الرمز كاملاً';return}$('#err').textContent='';joined=false;connect()};
// ---- التحكم باللمس المتعدد ----
const inp={mx:0,my:0,ax:0,ay:0,fire:0,rl:0,sp:0};
function resetInput(){Object.keys(inp).forEach(k=>inp[k]=0);document.querySelectorAll('.stick i').forEach(i=>i.style.transform='')}
function stick(el,cb){let id=null,cx=0,cy=0;const k=el.firstElementChild;
 function mv(e){const R=el.offsetWidth*.4;let dx=(e.clientX-cx)/R,dy=(e.clientY-cy)/R;const m=Math.hypot(dx,dy);if(m>1){dx/=m;dy/=m}k.style.transform='translate('+dx*R+'px,'+dy*R+'px)';cb(m<.12?0:dx,m<.12?0:dy)}
 el.addEventListener('pointerdown',e=>{if(id!==null)return;id=e.pointerId;try{el.setPointerCapture(id)}catch(_){}const r=el.getBoundingClientRect();cx=r.left+r.width/2;cy=r.top+r.height/2;mv(e)});
 el.addEventListener('pointermove',e=>{if(e.pointerId==id)mv(e)});
 const up=e=>{if(e.pointerId==id){id=null;k.style.transform='';cb(0,0)}};
 ['pointerup','pointercancel','lostpointercapture'].forEach(n=>el.addEventListener(n,up))}
stick($('#sL'),(x,y)=>{inp.mx=x;inp.my=y});
stick($('#sR'),(x,y)=>{inp.ax=x;inp.ay=y});
function btn(el,key){let id=null;el.addEventListener('pointerdown',e=>{id=e.pointerId;try{el.setPointerCapture(id)}catch(_){}inp[key]=1;if(cfg.vib&&navigator.vibrate)navigator.vibrate(8)});
 const up=e=>{if(e.pointerId==id){id=null;inp[key]=0}};['pointerup','pointercancel','lostpointercapture'].forEach(n=>el.addEventListener(n,up))}
btn($('#bF'),'fire');btn($('#bR'),'rl');btn($('#bS'),'sp');
document.addEventListener('visibilitychange',()=>{if(document.hidden)resetInput()});addEventListener('blur',resetInput);
$('#ctl').style.display='none';
setInterval(()=>{if(ws&&ws.readyState==1&&joined){const o=Object.assign({t:'in'},inp);ws.send(JSON.stringify(o))}},33);
setInterval(()=>{if(ws&&ws.readyState==1&&joined)ws.send('{"t":"ping"}')},8000);
function send(o){if(ws&&ws.readyState==1)ws.send(JSON.stringify(o))}
// ---- الحالة والواجهة ----
function copy(t,b){(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>{b.textContent='تم'}).catch(()=>{const i=document.createElement('input');i.value=t;document.body.appendChild(i);i.select();document.execCommand('copy');i.remove();b.textContent='تم'});setTimeout(()=>b.textContent='نسخ',1200)}
let lastSt='';
function onState(){const ov=$('#ov'),me=S.p[slot];
 (S.ev||[]).forEach(e=>{if(e[0]=='sh')snd('shot');else if(e[0]=='rl'&&e[1]==slot)snd('rl');else if(e[0]=='hit'&&e[1]==slot){snd('hit');hitT=performance.now();$('#flash').style.opacity=1;setTimeout(()=>$('#flash').style.opacity=0,120);if(cfg.vib&&navigator.vibrate)navigator.vibrate(40)}});
 const m=Math.floor(S.left/60),s=S.left%60;$('#tTime').textContent=m+':'+String(s).padStart(2,'0');
 $('#tScore').textContent=S.p.map((p,i)=>p[12]?NAMES[i]+' '+p[6]:'').filter(Boolean).join('  |  ');
 const nc=S.p.filter(p=>p[10]).length;$('#tConn').innerHTML='متصل '+nc+'/3 <span class="dot on"></span>';
 $('#st').innerHTML='الصحة '+me[3]+'<br>الذخيرة '+me[4]+' / '+me[5]+(me[11]?' (تلقيم)':'')+'<br>'+(me[9]?'':'تم إقصاؤك - عودة قريبة');
 $('#cd').style.display=S.cd?'flex':'none';$('#cd').textContent=S.cd||'';
 if(S.st=='playing'||S.st=='countdown'){ov.classList.remove('on')}
 else{let h='';const dots=S.p.map((p,i)=>'<span class="dot '+(p[10]?'on':'')+'"></span>'+NAMES[i]).join(' &nbsp; ');
  if(S.st=='ended'){const o=S.p.map((p,i)=>[i,p]).filter(x=>x[1][12]).sort((a,b)=>b[1][6]-a[1][6]);
   h='<h1 style="font-size:30px">انتهت المباراة</h1><div style="font-size:20px;color:var(--ac)">الفائز: '+NAMES[S.win]+'</div>'+o.map(x=>'<div class="code"><span>'+NAMES[x[0]]+'</span><span>نقاط '+x[1][6]+' | إقصاءات '+x[1][7]+' | خسارة '+x[1][8]+'</span></div>').join('');
   if(lastSt!='ended')snd('win')}
  else h='<h1 style="font-size:30px">'+'<span id="rn"></span></h1><div>بانتظار اللاعبين</div><div>'+dots+'</div>';
  if(host){h+='<div class="row">';if(S.st=='ended')h+='<button class="btn" id="bStart">إعادة المباراة</button><button class="btn g" id="bLobby">العودة إلى الغرفة</button>';
   else h+='<button class="btn" id="bStart">بدء المباراة</button>';h+='<button class="btn g" id="bCancel">إلغاء الغرفة</button></div>';
   if(S.st=='lobby'&&window.CODES)h+=['رمزك (القائد)','رمز وحدة التحكم الأولى','رمز وحدة التحكم الثانية'].map((l,i)=>'<div class="code"><div><small>'+l+'</small><b>'+window.CODES[i]+'</b></div><button class="btn g" data-c="'+i+'">نسخ</button></div>').join('')}
  else h+='<div style="color:var(--ok)">تم الاتصال بنجاح - بانتظار القائد</div>';
  if(ov.dataset.k!=S.st+nc+(S.win)+(host?1:0)){ov.dataset.k=S.st+nc+S.win+(host?1:0);ov.innerHTML=h;const rn=$('#rn');if(rn)rn.textContent=S.name;
   const bs=$('#bStart');if(bs)bs.onclick=()=>send({t:'start'});const bl=$('#bLobby');if(bl)bl.onclick=()=>send({t:'lobby'});
   const bc=$('#bCancel');if(bc)bc.onclick=()=>{if(confirm('إلغاء الغرفة؟')){send({t:'cancel'});closing=true;joined=false;ws.close();show('menu')}};
   ov.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>copy(window.CODES[+b.dataset.c],b))}
  ov.classList.add('on')}
 lastSt=S.st}
// ---- الرسم ----
const cv=$('#cv'),g=cv.getContext('2d');const WALLS=__WALLS__,ZONE=__ZONE__,AW=1600,AH=1000;
function fit(){const d=Math.min(devicePixelRatio||1,2);cv.width=innerWidth*d;cv.height=innerHeight*d}fit();onresize=fit;
function draw(){requestAnimationFrame(draw);if(document.hidden||!S||!host||!joined)return;
 const w=cv.width,h=cv.height,sc=Math.min(w/820,h/480);const me=disp[slot]||[800,500];
 S.p.forEach((p,i)=>{const d=disp[i]||(disp[i]=[p[0],p[1],p[2]]);d[0]+=(p[0]-d[0])*.4;d[1]+=(p[1]-d[1])*.4;let da=p[2]-d[2];while(da>3.14)da-=6.28;while(da<-3.14)da+=6.28;d[2]+=da*.4});
 g.setTransform(1,0,0,1,0,0);g.fillStyle='#0d120e';g.fillRect(0,0,w,h);
 g.setTransform(sc,0,0,sc,w/2-me[0]*sc,h/2-me[1]*sc);
 g.fillStyle='#2b3524';g.fillRect(0,0,AW,AH);g.strokeStyle='rgba(0,0,0,.12)';g.lineWidth=1;
 for(let x=0;x<=AW;x+=100){g.beginPath();g.moveTo(x,0);g.lineTo(x,AH);g.stroke()}for(let y=0;y<=AH;y+=100){g.beginPath();g.moveTo(0,y);g.lineTo(AW,y);g.stroke()}
 g.fillStyle='#3a3426';g.fillRect(0,470,AW,60);g.fillRect(770,0,60,AH);
 const zc=S.zone>=0?COL[S.zone]:S.zone==-2?'#fff':'#888';g.globalAlpha=.22;g.fillStyle=zc;g.beginPath();g.arc(ZONE[0],ZONE[1],ZONE[2],0,7);g.fill();g.globalAlpha=1;g.strokeStyle=zc;g.lineWidth=3;g.setLineDash([12,8]);g.stroke();g.setLineDash([]);
 WALLS.forEach(a=>{g.fillStyle='rgba(0,0,0,.35)';g.fillRect(a[0]+10,a[1]+12,a[2],a[3]);g.fillStyle='#4a5046';g.fillRect(a[0],a[1]-8,a[2],a[3]);g.fillStyle='#646b5d';g.fillRect(a[0],a[1]-8,a[2],5);g.strokeStyle='#22261f';g.lineWidth=2;g.strokeRect(a[0],a[1]-8,a[2],a[3])});
 g.fillStyle='#ffd966';S.b.forEach(b=>{g.beginPath();g.arc(b[0],b[1],3.2,0,7);g.fill()});
 S.p.forEach((p,i)=>{if(!p[12]||!p[9])return;const d=disp[i];g.globalAlpha=p[10]?1:.4;g.fillStyle='rgba(0,0,0,.35)';g.beginPath();g.ellipse(d[0]+3,d[1]+6,15,10,0,0,7);g.fill();
  g.save();g.translate(d[0],d[1]);g.rotate(d[2]);g.fillStyle='#222';g.fillRect(8,-3,22,6);g.fillStyle=COL[i];g.beginPath();g.arc(0,0,14,0,7);g.fill();g.fillStyle='#1b1f19';g.beginPath();g.arc(2,0,7,0,7);g.fill();g.restore();
  g.fillStyle='#000';g.fillRect(d[0]-18,d[1]-26,36,5);g.fillStyle=p[3]>40?'#4ade80':'#ef5350';g.fillRect(d[0]-17,d[1]-25,34*p[3]/100,3);
  g.fillStyle='#fff';g.font='bold 12px Tahoma';g.textAlign='center';g.fillText(NAMES[i],d[0],d[1]-31);g.globalAlpha=1});
 // خريطة مصغرة
 g.setTransform(1,0,0,1,0,0);const mw=130*(w/innerWidth),mh=mw*AH/AW,mx=w-mw-10,my=h*.12;g.fillStyle='rgba(10,14,10,.7)';g.fillRect(mx,my,mw,mh);
 g.fillStyle='#555';WALLS.forEach(a=>g.fillRect(mx+a[0]/AW*mw,my+a[1]/AH*mh,a[2]/AW*mw,Math.max(2,a[3]/AH*mh)));
 g.strokeStyle=zc;g.beginPath();g.arc(mx+ZONE[0]/AW*mw,my+ZONE[1]/AH*mh,ZONE[2]/AW*mw,0,7);g.stroke();
 S.p.forEach((p,i)=>{if(p[12]&&p[9]){g.fillStyle=COL[i];g.beginPath();g.arc(mx+p[0]/AW*mw,my+p[1]/AH*mh,3,0,7);g.fill()}})}
requestAnimationFrame(draw);
</script></body></html>"""
PAGE = PAGE.replace("__WALLS__", json.dumps([list(w) for w in WALLS])).replace("__ZONE__", json.dumps(list(ZONE)))

# ---------- القسم 6: التشغيل ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
