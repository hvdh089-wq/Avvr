# -*- coding: utf-8 -*-
"""WAR FRONT 3D - الإصدار 0.1 (نواة قابلة للعب)
تشغيل محلي:  pip install flask  ثم  python main.py  ثم افتح http://127.0.0.1:5000
نشر (Render): gunicorn main:app --workers 1 --threads 8
الغرف الجماعية: خادم حقيقي (Flask) يدير الغرف ويتحقق من الإصابات، والعملاء يتزامنون عبر HTTP كل 100ms."""
import os, time, math, secrets, threading, logging
from flask import Flask, jsonify, request, Response

# ========================= 1) إعداد الخادم =========================
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2048
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("warfront")
ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LOCK = threading.Lock()
ROOMS = {}
HITS = {}
KILL_TARGET = 10
SPAWNS = [(-20, 70), (20, 70), (0, -70), (60, 0)]
WEAPON_RULES = {0: (25, 0.30, 90), 1: (18, 0.08, 130), 2: (90, 1.0, 310)}  # ضرر، تبريد، مدى
MAX_SPEED = 12.0


def _json():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def _num(v, lo, hi, default=0.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    if v != v:
        return default
    return max(lo, min(hi, v))


def _name(v):
    s = "".join(c for c in str(v or "")[:14] if c.isprintable()).strip()
    return s or "لاعب"


def _limit(key, count, per):
    now = time.time()
    lst = [t for t in HITS.get(key, []) if now - t < per]
    if len(lst) >= count:
        HITS[key] = lst
        return False
    lst.append(now)
    HITS[key] = lst
    return True


def _cleanup():
    now = time.time()
    for code in list(ROOMS):
        room = ROOMS[code]
        for pid in [k for k, p in room["players"].items() if now - p["seen"] > 20]:
            gone = room["players"].pop(pid)
            if gone["id"] == room["host"] and room["players"]:
                room["host"] = next(iter(room["players"].values()))["id"]
        if not room["players"] or now - room["t"] > 7200:
            del ROOMS[code]
    if len(HITS) > 2000:
        HITS.clear()


def _spawn(room, idx):
    return SPAWNS[idx % len(SPAWNS)]


def _new_player(room, name):
    room["n"] += 1
    sx, sz = _spawn(room, room["n"] - 1)
    return {"id": "p%d" % room["n"], "name": name, "x": sx, "y": 0, "z": sz, "ry": 0, "hp": 100,
            "kills": 0, "seen": time.time(), "last": time.time(), "lw": 0, "dead_until": 0, "flag": ""}


def _ctx(d):
    code = str(d.get("code", ""))[:8].upper()
    room = ROOMS.get(code)
    if not room:
        return None, None
    return room, room["players"].get(str(d.get("pid", ""))[:40])


@app.post("/api/create")
def api_create():
    d = _json()
    with LOCK:
        _cleanup()
        if not _limit("c" + str(request.remote_addr), 8, 60) or len(ROOMS) >= 300:
            return jsonify(ok=False, err="limit"), 429
        code = "".join(secrets.choice(ALPHA) for _ in range(6))
        room = {"code": code, "players": {}, "n": 0, "host": "", "state": "lobby", "chat": [], "round": 0,
                "winner": "", "t": time.time()}
        p = _new_player(room, _name(d.get("name")))
        pid = secrets.token_urlsafe(12)
        room["players"][pid] = p
        room["host"] = p["id"]
        ROOMS[code] = room
        log.info("room created %s", code)
        return jsonify(ok=True, code=code, pid=pid)


@app.post("/api/join")
def api_join():
    d = _json()
    with LOCK:
        _cleanup()
        if not _limit("j" + str(request.remote_addr), 20, 60):
            return jsonify(ok=False, err="limit"), 429
        room, _ = _ctx(d)
        if not room:
            return jsonify(ok=False, err="room"), 404
        if len(room["players"]) >= 2:
            return jsonify(ok=False, err="full"), 409
        if room["state"] != "lobby":
            return jsonify(ok=False, err="started"), 409
        p = _new_player(room, _name(d.get("name")))
        pid = secrets.token_urlsafe(12)
        room["players"][pid] = p
        return jsonify(ok=True, code=room["code"], pid=pid)


def _view(room, p, now):
    return jsonify(
        ok=True, state=room["state"], round=room["round"], winner=room["winner"], host=(p["id"] == room["host"]),
        me={"id": p["id"], "hp": p["hp"], "x": p["x"], "z": p["z"], "flag": p["flag"], "kills": p["kills"]},
        players=[{"id": q["id"], "name": q["name"], "x": q["x"], "y": q["y"], "z": q["z"], "ry": q["ry"],
                  "hp": q["hp"], "kills": q["kills"]} for q in room["players"].values()],
        chat=room["chat"][-15:], target=KILL_TARGET)


@app.post("/api/sync")
def api_sync():
    d = _json()
    now = time.time()
    with LOCK:
        room, p = _ctx(d)
        if not p:
            return jsonify(ok=False, err="room"), 404
        dt = now - p["last"]
        p["seen"] = now
        p["flag"] = ""
        if dt >= 0.04:
            nx, nz = _num(d.get("x"), -95, 95, p["x"]), _num(d.get("z"), -95, 95, p["z"])
            if room["state"] == "play" and p["hp"] > 0:
                if math.hypot(nx - p["x"], nz - p["z"]) <= MAX_SPEED * min(dt, 1.0) + 2.5:
                    p["x"], p["z"] = nx, nz
                    p["y"] = _num(d.get("y"), 0, 30, p["y"])
                    p["ry"] = _num(d.get("ry"), -1000, 1000, p["ry"])
                else:
                    p["flag"] = "snap"
            p["last"] = now
        if room["state"] == "play" and p["hp"] <= 0 and now >= p["dead_until"]:
            p["hp"] = 100
            p["x"], p["z"] = _spawn(room, secrets.randbelow(4))
            p["flag"] = "resp"
        return _view(room, p, now)


@app.post("/api/shoot")
def api_shoot():
    d = _json()
    now = time.time()
    with LOCK:
        room, p = _ctx(d)
        if not p or room["state"] != "play" or p["hp"] <= 0:
            return jsonify(ok=False)
        rule = WEAPON_RULES.get(int(_num(d.get("w"), 0, 2, 0)))
        if now - p["lw"] < rule[1] * 0.8:
            return jsonify(ok=False, err="rate")
        p["lw"] = now
        target = next((q for q in room["players"].values() if q["id"] == str(d.get("target", ""))[:8]), None)
        if not target or target is p or target["hp"] <= 0:
            return jsonify(ok=False)
        dist = math.dist((p["x"], p["y"], p["z"]), (target["x"], target["y"], target["z"]))
        if dist > rule[2] + 8:
            return jsonify(ok=False, err="range")
        target["hp"] -= rule[0]
        if target["hp"] <= 0:
            target["hp"] = 0
            target["dead_until"] = now + 3
            p["kills"] += 1
            if p["kills"] >= KILL_TARGET:
                room["state"], room["winner"] = "over", p["name"]
        return jsonify(ok=True)


def _host_action(d, fn):
    with LOCK:
        room, p = _ctx(d)
        if not p or p["id"] != room["host"]:
            return jsonify(ok=False, err="host"), 403
        return fn(room)


@app.post("/api/start")
def api_start():
    def go(room):
        if len(room["players"]) < 2:
            return jsonify(ok=False, err="need2")
        room["state"], room["winner"] = "play", ""
        room["round"] += 1
        for i, q in enumerate(room["players"].values()):
            q["hp"], q["kills"] = 100, 0
            q["x"], q["z"] = _spawn(room, i)
            q["flag"] = "snap"
        return jsonify(ok=True)
    return _host_action(_json(), go)


@app.post("/api/close")
def api_close():
    def go(room):
        ROOMS.pop(room["code"], None)
        return jsonify(ok=True)
    return _host_action(_json(), go)


@app.post("/api/leave")
def api_leave():
    d = _json()
    with LOCK:
        room, p = _ctx(d)
        if p:
            room["players"].pop(str(d.get("pid")), None)
            if not room["players"]:
                ROOMS.pop(room["code"], None)
            elif p["id"] == room["host"]:
                room["host"] = next(iter(room["players"].values()))["id"]
        return jsonify(ok=True)


@app.post("/api/chat")
def api_chat():
    d = _json()
    with LOCK:
        room, p = _ctx(d)
        if not p or not _limit("m" + p["id"] + room["code"], 4, 10):
            return jsonify(ok=False, err="limit")
        text = "".join(c for c in str(d.get("text", ""))[:120] if c.isprintable()).strip()
        if text:
            room["chat"].append({"n": p["name"], "t": text})
            del room["chat"][:-40]
        return jsonify(ok=True)


@app.get("/health")
def health():
    return "ok"


@app.get("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html; charset=utf-8")


# ========================= 2) واجهة HTML + CSS =========================
HTML_PAGE = r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>WAR FRONT 3D</title><style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none;touch-action:none}
html,body{margin:0;height:100%;overflow:hidden;background:#05070a;color:#d7e0d0;font-family:system-ui,Tahoma,sans-serif}
#c{position:fixed;inset:0;width:100%;height:100%}#look{position:fixed;inset:0;z-index:1}
#hud{position:fixed;inset:0;z-index:2;pointer-events:none;display:none}
.bar{height:2.6vmin;background:#0009;border:1px solid #6b7d5a;margin-bottom:.8vmin}.bar i{display:block;height:100%}
#hb{position:absolute;top:2vmin;left:2vmin;width:34vmin}
#obj{position:absolute;top:2vmin;left:50%;transform:translateX(-50%);background:#000a;border:1px solid #6b7d5a;padding:.8vmin 2vmin;font-size:3vmin;white-space:nowrap}
#am{position:absolute;bottom:2vmin;left:50%;transform:translateX(-50%);font-size:4vmin;background:#000a;padding:.6vmin 2vmin;border:1px solid #6b7d5a;direction:ltr}
#xh{position:absolute;top:50%;left:50%;width:3vmin;height:3vmin;margin:-1.5vmin;border:2px solid #fff9;border-radius:50%}
#dm{position:absolute;inset:0;box-shadow:inset 0 0 14vmin #f00;opacity:0;transition:opacity .3s}
#sc{position:absolute;inset:0;background:radial-gradient(circle,transparent 30%,#000 31%);display:none}
#net,#fps{position:absolute;right:2vmin;font-size:2.4vmin;opacity:.8}#net{top:16vmin}#fps{top:12vmin}
#dead{position:absolute;inset:0;display:none;align-items:center;justify-content:center;font-size:7vmin;background:#400a}
#tc{display:none}.tb{position:fixed;z-index:4;border-radius:50%;background:#1b2a1bcc;border:2px solid #7e9b66;color:#cfe3b8;display:flex;align-items:center;justify-content:center}
.tb svg{width:55%;height:55%}.tb.on{background:#5c8a3acc}
#jz{position:fixed;z-index:3;left:0;bottom:0;width:45%;height:70%}
#jb{position:fixed;z-index:3;width:100px;height:100px;margin:-50px;border:2px solid #7e9b6699;border-radius:50%;display:none;pointer-events:none}
#jk{position:absolute;left:30px;top:30px;width:40px;height:40px;border-radius:50%;background:#7e9b66aa}
#ov{position:fixed;inset:0;z-index:10;display:flex;align-items:center;justify-content:center;background:radial-gradient(#1b2a1bee,#05070aee)}
.box{width:min(92vw,520px);max-height:94vh;overflow:auto;padding:2vmin 3vmin;text-align:center}
h1{font-size:8vmin;letter-spacing:.6vmin;margin:.5vmin 0;color:#b9d98c;direction:ltr}h2{margin:1vmin 0;color:#b9d98c}
.mb{display:block;width:100%;margin:1vmin 0;padding:1.6vmin;font-size:max(3.6vmin,15px);background:#1d2a1dcc;color:#dfe9d0;border:1px solid #7e9b66;border-radius:6px;font-family:inherit}
.mb:active{background:#4a6b2f}.mb[disabled]{opacity:.4}.row{display:flex;gap:1vmin}.row .mb{flex:1}
.chip.sel{background:#4a6b2f}input[type=text]{width:100%;padding:1.4vmin;font-size:5vmin;text-align:center;direction:ltr;background:#0b120b;color:#fff;border:1px solid #7e9b66;letter-spacing:1vmin;user-select:text;touch-action:auto}
input[type=range]{width:100%;touch-action:auto}.sm{font-size:max(2.6vmin,12px);opacity:.85}.code{font-size:9vmin;letter-spacing:1.5vmin;direction:ltr;color:#ffd77a}
#chat{height:14vmin;overflow:auto;background:#0008;text-align:right;font-size:max(2.4vmin,12px);padding:.6vmin 1vmin;margin:.6vmin 0}
#err{position:fixed;inset:0;z-index:20;display:none;align-items:center;justify-content:center;background:#200;text-align:center;padding:5vmin;font-size:4vmin}
</style></head><body>
<canvas id="c"></canvas><div id="look"></div>
<div id="hud"><div id="hb"><div class="bar"><i id="hpb" style="background:#c0392b;width:100%"></i></div><div class="bar"><i id="arb" style="background:#3b82c4;width:0"></i></div></div>
<div id="obj"></div><div id="xh"></div><div id="am"></div><div id="dm"></div><div id="sc"></div><div id="fps"></div><div id="net"></div><div id="dead">تم القضاء عليك - إعادة الظهور...</div></div>
<div id="tc"><div id="jz"></div><div id="jb"><div id="jk"></div></div></div>
<div id="ov"></div><div id="err">تعذر تشغيل WebGL أو تحميل مكتبة Three.js. تأكد من الاتصال بالإنترنت وحدّث المتصفح.</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
// ========================= 3) إعدادات وحفظ =========================
(()=>{'use strict';
const $=i=>document.getElementById(i);
const ld=(k,d)=>{try{return Object.assign(d,JSON.parse(localStorage.getItem(k)||'{}'))}catch(e){return d}};
const weak=(navigator.hardwareConcurrency||4)<=4;
const S=ld('wf_s',{q:weak?0:1,sens:1,vol:.7,d:1,fx:1}),P=ld('wf_p',{unl:1,xp:0,coins:0,done:[],kills:0});
const sv=()=>{try{localStorage.setItem('wf_s',JSON.stringify(S));localStorage.setItem('wf_p',JSON.stringify(P))}catch(e){}};
const WP=[{n:'مسدس',dmg:25,rate:.3,mag:12,rl:1.2,range:90,sp:.012,auto:0,rec:.02,len:.3,spd:1},
{n:'بندقية هجومية',dmg:18,rate:.08,mag:30,rl:1.8,range:130,sp:.025,auto:1,rec:.012,len:.6,spd:.95},
{n:'بندقية قنص',dmg:90,rate:1,mag:5,rl:2.5,range:310,sp:0,auto:0,rec:.05,len:.9,spd:.85}];
const LV=[{i:0,n:'التدريب - المدينة',map:'city',night:0,type:'kill',goal:6,diff:0,seed:11},
{i:1,n:'الصمود - الصحراء',map:'desert',night:0,type:'survive',goal:75,diff:1,seed:22},
{i:2,n:'مواجهة القائد - الغابة ليلاً',map:'forest',night:1,type:'boss',goal:8,diff:2,seed:33}];
const DF=[{view:35,acc:.22,dmg:5,rate:1.2,hp:60},{view:50,acc:.36,dmg:7,rate:.9,hp:80},{view:65,acc:.5,dmg:9,rate:.65,hp:100}];
const ICO={fire:'<circle cx="12" cy="12" r="7"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',jump:'<path d="M12 19V5M6 11l6-6 6 6"/>',reload:'<path d="M20 12a8 8 0 1 1-3-6.2M20 4v5h-5"/>',aim:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="1.5"/>',view:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',weapon:'<path d="M3 10h13l2 2h3v3h-6l-1 4h-4l1-4H3z"/>',sprint:'<path d="M5 19l5-7 3 3 5-8M14 7h5v5"/>',crouch:'<path d="M6 8l6 6 6-6M6 14l6 6 6-6"/>',pause:'<path d="M8 5v14M16 5v14"/>'};
const ic=n=>'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'+ICO[n]+'</svg>';
if(!window.THREE){$('err').style.display='flex';return}
// ========================= 4) محرك العالم ثلاثي الأبعاد =========================
let R;try{R=new THREE.WebGLRenderer({canvas:$('c'),antialias:false,powerPreference:'high-performance'})}catch(e){$('err').style.display='flex';return}
const V=THREE.Vector3,scene=new THREE.Scene(),cam=new THREE.PerspectiveCamera(75,1,.1,400);cam.rotation.order='YXZ';scene.add(cam);
const hemi=new THREE.HemisphereLight(0xcfe3ff,0x444433,.85),sun=new THREE.DirectionalLight(0xffffff,.9),torch=new THREE.PointLight(0xffffff,.8,28);
scene.add(hemi,sun,sun.target);cam.add(torch);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);
{const c=sun.shadow.camera;c.left=c.bottom=-55;c.right=c.top=55;c.far=220}
function applyQ(){R.setPixelRatio([.6,.85,1][S.q]*Math.min(devicePixelRatio||1,2));R.shadowMap.enabled=S.q>0;R.setSize(innerWidth,innerHeight,false);cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix()}
addEventListener('resize',applyQ);applyQ();
const MC={};const mat=c=>MC[c]||(MC[c]=new THREE.MeshLambertMaterial({color:c}));
const MAPS={city:{g:0x50555b,sky:0x9db4c8,b:[0x7b8794,0x66707a,0x8a8f96],n:24,h:15},desert:{g:0xc8a56a,sky:0xe3c89a,b:[0xb08d57,0x9b7b4c,0x7d6a4a],n:18,h:6},forest:{g:0x36552b,sky:0x88a8c0,b:[0x555b50,0x4a5046],n:8,h:5}};
const rng=s=>()=>{s|=0;s=s+0x6D2B79F5|0;let t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296};
let WG=new THREE.Group(),C=[];scene.add(WG);
function box(x,z,w,d,h,c,y0){y0=y0||0;const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat(c));m.position.set(x,y0+h/2,z);m.castShadow=m.receiveShadow=true;WG.add(m);C.push({x0:x-w/2,x1:x+w/2,z0:z-d/2,z1:z+d/2,y0:y0,y1:y0+h})}
function build(map,night,seed){scene.remove(WG);WG.traverse(o=>o.geometry&&o.geometry.dispose());WG=new THREE.Group();scene.add(WG);C=[];
const M=MAPS[map],r=rng(seed),sky=night?0x0a1020:M.sky;scene.background=new THREE.Color(sky);scene.fog=new THREE.Fog(sky,night?20:55,[90,130,170][S.q]);
hemi.intensity=night?.3:.85;sun.intensity=night?.2:.9;torch.intensity=night?.9:0;
const g=new THREE.Mesh(new THREE.PlaneGeometry(500,500),mat(M.g));g.rotation.x=-Math.PI/2;g.receiveShadow=true;WG.add(g);
for(const[x,z,w,d]of[[0,-96,194,2],[0,96,194,2],[-96,0,2,194],[96,0,2,194]])box(x,z,w,d,7,0x2b2f2b);
for(let i=0;i<M.n;i++){const x=r()*170-85,z=r()*170-85,w=6+r()*8,d=6+r()*8;if(Math.hypot(x,z-70)<16||Math.hypot(x-20,z-70)<16)continue;box(x,z,w,d,3+r()*M.h,M.b[i%M.b.length])}
for(let i=0;i<28;i++){const x=r()*170-85,z=r()*170-85;if(Math.hypot(x,z-70)<10)continue;box(x,z,1.6,1.6,1.3,0x6b5a3a)}
if(map==='forest')for(let i=0;i<70;i++){const x=r()*180-90,z=r()*180-90;if(Math.hypot(x,z-70)<8)continue;const t=new THREE.Mesh(new THREE.CylinderGeometry(.25,.35,3,6),mat(0x4a3320));t.position.set(x,1.5,z);const k=new THREE.Mesh(new THREE.ConeGeometry(1.8,5,7),mat(0x1f4a22));k.position.set(x,5,z);k.castShadow=true;WG.add(t,k);C.push({x0:x-.4,x1:x+.4,z0:z-.4,z1:z+.4,y0:0,y1:8})}
if(map==='city')for(let i=-2;i<=2;i++){const rd=new THREE.Mesh(new THREE.PlaneGeometry(10,190),mat(0x2a2d31));rd.rotation.x=-Math.PI/2;rd.position.set(i*38,.02,0);WG.add(rd)}
for(let i=0;i<14;i++){const a=i/14*6.28,h=new THREE.Mesh(new THREE.ConeGeometry(30,25+r()*20,6),mat(night?0x10151d:M.b[0]));h.position.set(Math.cos(a)*150,10,Math.sin(a)*150);WG.add(h)}}
const inC=(x,y,z)=>{for(const b of C)if(x>b.x0&&x<b.x1&&z>b.z0&&z<b.z1&&y>=b.y0&&y<b.y1)return 1;return 0};
const blk=(x,z,y,r)=>{r=r||.4;for(const b of C)if(x+r>b.x0&&x-r<b.x1&&z+r>b.z0&&z-r<b.z1&&b.y1>y+.6&&b.y0<y+1.7)return 1;return 0};
const gnd=(x,z,y)=>{let g=0;for(const b of C)if(x+.3>b.x0&&x-.3<b.x1&&z+.3>b.z0&&z-.3<b.z1&&b.y1<=y+.6&&b.y1>g)g=b.y1;return g};
function human(col,sc){const g=new THREE.Group(),sk=mat(0xd2a679),dk=mat(0x1b1b1b);const t=new THREE.Mesh(new THREE.BoxGeometry(.6,.8,.35),mat(col));t.position.y=1.15;
const h=new THREE.Mesh(new THREE.SphereGeometry(.2,8,6),sk);h.position.y=1.75;const hm=new THREE.Mesh(new THREE.SphereGeometry(.23,8,6,0,6.3,0,1.6),mat(col));hm.position.y=1.78;
const gun=new THREE.Mesh(new THREE.BoxGeometry(.08,.1,.7),dk);gun.position.set(.2,1.2,-.4);const L=[];
for(const s of[-.15,.15]){const p=new THREE.Group();p.position.set(s,.75,0);const l=new THREE.Mesh(new THREE.BoxGeometry(.22,.75,.25),dk);l.position.y=-.375;p.add(l);g.add(p);L.push(p)}
g.add(t,h,hm,gun);g.userData.legs=L;g.scale.setScalar(sc||1);g.traverse(o=>o.castShadow=S.q>0);return g}
// ========================= 5) اللاعب والكاميرا والأسلحة =========================
const pl={p:new V(0,0,70),vy:0,yaw:0,pitch:0,hp:100,ar:0,og:1,cr:0,sp:0,fps:1,w:0,am:[],rs:[],rl:0,cd:0,aim:0,kick:0,shake:0,mv:0};
const pm=human(0x3d5a2e);scene.add(pm);
const vm=new THREE.Mesh(new THREE.BoxGeometry(.07,.09,1),mat(0x222222));cam.add(vm);
function setVM(){const w=WP[pl.w];vm.scale.z=w.len;vm.position.set(.22,-.2,-.35-w.len*.3)}
const K={},joy={x:0,y:0},B={};let G=null,E=[],PK=[],FX=[],AC=null,NB=null;
function snd(f,d,t,v){if(S.vol<=0)return;try{if(!AC){AC=new(window.AudioContext||window.webkitAudioContext)();NB=AC.createBuffer(1,AC.sampleRate*.5,AC.sampleRate);const a=NB.getChannelData(0);for(let i=0;i<a.length;i++)a[i]=Math.random()*2-1}
const g=AC.createGain();g.gain.setValueAtTime(S.vol*(v||1)*.5,AC.currentTime);g.gain.exponentialRampToValueAtTime(.001,AC.currentTime+d);g.connect(AC.destination);
if(t==='n'){const s=AC.createBufferSource(),fl=AC.createBiquadFilter();s.buffer=NB;fl.frequency.value=f;s.connect(fl);fl.connect(g);s.start();s.stop(AC.currentTime+d)}
else{const o=AC.createOscillator();o.type='square';o.frequency.value=f;o.connect(g);o.start();o.stop(AC.currentTime+d)}}catch(e){}}
function reload(){const w=WP[pl.w];if(pl.rl>0||pl.am[pl.w]>=w.mag||pl.rs[pl.w]<=0)return;pl.rl=w.rl;snd(300,.1,'o')}
function swap(){for(let i=1;i<3;i++){const n=(pl.w+i)%3;if(n<P.unl){pl.w=n;pl.rl=0;setVM();snd(500,.08,'o');return}}}
function spark(p,c){if(!S.fx)return;for(let i=0;i<4;i++){const m=new THREE.Mesh(new THREE.BoxGeometry(.06,.06,.06),new THREE.MeshBasicMaterial({color:c||0xffcc66}));m.position.copy(p);m.userData={v:new V(Math.random()-.5,Math.random()*2,Math.random()-.5).multiplyScalar(3),l:.4};scene.add(m);FX.push(m)}}
function tracer(a,b){const l=new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]),new THREE.LineBasicMaterial({color:0xffe08a}));l.userData={l:.06};scene.add(l);FX.push(l)}
function fire(){const w=WP[pl.w];if(pl.cd>0||pl.rl>0||G.dead)return;if(pl.am[pl.w]<=0){reload();return}
pl.cd=w.rate;pl.am[pl.w]--;pl.kick=.08;pl.pitch+=w.rec*(.6+Math.random()*.8);snd(w.dmg>50?200:700,w.dmg>50?.35:.12,'n');
const o=new V();cam.getWorldPosition(o);const d=new V(0,0,-1).applyQuaternion(cam.quaternion),s=w.sp*(pl.aim?.3:1);d.x+=(Math.random()-.5)*s;d.y+=(Math.random()-.5)*s;d.normalize();
let tw=w.range;for(let t=.6;t<w.range;t+=.5){const x=o.x+d.x*t,y=o.y+d.y*t,z=o.z+d.z*t;if(y<0||inC(x,y,z)){tw=t;break}}
let bt=tw,be=null,br=null;const hit=(c,rad)=>{const v=c.clone().sub(o),t=v.dot(d);if(t>0&&t<bt&&v.sub(d.clone().multiplyScalar(t)).length()<rad){bt=t;return 1}return 0};
for(const e of E)if(hit(new V(e.g.position.x,e.g.position.y+1.1*e.sc,e.g.position.z),.65*e.sc)){be=e;br=null}
if(G.mode==='mp')for(const id in MP.rem){const m=MP.rem[id];if(m.hp>0&&hit(new V(m.g.position.x,m.g.position.y+1.1,m.g.position.z),.65)){br=id;be=null}}
const end=o.clone().add(d.clone().multiplyScalar(bt));tracer(o.clone().add(d.clone().multiplyScalar(1.2)).add(new V(0,-.2,0)),end);spark(end);
if(be){const hs=end.y>be.g.position.y+1.55*be.sc?2:1;be.hp-=w.dmg*hs;be.st='attack';be.last=pl.p.clone();snd(900,.05,'o',.6);if(be.hp<=0)killE(be)}
if(br){snd(900,.05,'o',.6);api('shoot',{code:MP.code,pid:MP.pid,target:br,w:pl.w})}
for(const e of E)if(e.st==='patrol'&&e.g.position.distanceTo(pl.p)<45){e.st='search';e.last=pl.p.clone();e.lost=0}}
function killE(e){scene.remove(e.g);E.splice(E.indexOf(e),1);G.kills++;P.kills++;P.coins+=e.boss?50:5;if(e.boss)G.bossDead=1;snd(120,.2,'n')}
function dmgP(n){if(G.mode==='mp'||G.over)return;const a=Math.min(pl.ar,n*.5);pl.ar-=a;pl.hp-=n-a;pl.shake=.15;$('dm').style.opacity=1;setTimeout(()=>$('dm').style.opacity=0,200);if(pl.hp<=0)finish(false)}
// ========================= 6) الذكاء الاصطناعي للأعداء =========================
function los(a,b){const n=Math.ceil(a.distanceTo(b));for(let i=1;i<n;i++){const t=i/n;if(inC(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,a.z+(b.z-a.z)*t))return 0}return 1}
function spawnE(boss){let x=0,z=0;for(let k=0;k<30;k++){x=Math.random()*170-85;z=Math.random()*170-85;if(Math.hypot(x-pl.p.x,z-pl.p.z)>35&&!blk(x,z,0,1))break}
const sc=boss?1.6:1,g=human(boss?0x8a1c1c:[0x5a3d2e,0x2e3d5a,0x4a2e5a][E.length%3],sc);g.position.set(x,0,z);scene.add(g);
E.push({g,sc,boss:!!boss,hp:G.D.hp*(boss?6:1),st:'patrol',wp:new V(x,0,z),last:null,lost:0,cd:1,see:0,lt:Math.random()*.3,sd:1,sdT:0,cov:0,ph:0,home:new V(x,0,z)})}
function moveE(e,tx,tz,sp,dt){const p=e.g.position,dx=tx-p.x,dz=tz-p.z,l=Math.hypot(dx,dz);if(l<.3)return 0;const vx=dx/l*sp*dt,vz=dz/l*sp*dt;let m=0;
if(!blk(p.x+vx,p.z,0,.5)){p.x+=vx;m=1}if(!blk(p.x,p.z+vz,0,.5)){p.z+=vz;m=1}if(!m)e.wp.set(e.home.x+(Math.random()-.5)*40,0,e.home.z+(Math.random()-.5)*40);
e.g.rotation.y=Math.atan2(-dx,-dz);e.ph+=dt*8;return 1}
function aiE(e,dt){const D=G.D,p=e.g.position,pp=pl.p,dist=p.distanceTo(pp);e.cd-=dt;e.lt-=dt;
if(e.lt<=0){e.lt=.25;const fw=new V(-Math.sin(e.g.rotation.y),0,-Math.cos(e.g.rotation.y)),to=pp.clone().sub(p).normalize();
e.see=dist<D.view*(G.lv.night?.7:1)&&(dist<10||fw.dot(to)>-.2)&&los(new V(p.x,1.6*e.sc,p.z),new V(pp.x,pp.y+1.4,pp.z))}
let mv=0;if(e.see){if(e.st!=='attack'){for(const o of E)if(o!==e&&o.g.position.distanceTo(p)<30&&o.st==='patrol'){o.st='search';o.last=pp.clone();o.lost=0}}e.st='attack';e.last=pp.clone();e.lost=0}
else if(e.st==='attack'){e.st='search';e.lost=0}
if(e.st==='attack'){e.g.rotation.y=Math.atan2(-(pp.x-p.x),-(pp.z-p.z));e.sdT-=dt;if(e.sdT<=0){e.sdT=1+Math.random()*1.5;e.sd=-e.sd}
const f=new V(pp.x-p.x,0,pp.z-p.z).normalize(),sp=e.boss?2.5:3.2;
if(e.hp<e.sc*D.hp*.4&&!e.boss&&!e.cov){let nb=null,nd=25;for(const b of C){const cx=(b.x0+b.x1)/2,cz=(b.z0+b.z1)/2,dd=Math.hypot(cx-p.x,cz-p.z);if(b.y1>1&&dd<nd){nd=dd;nb=[cx,cz,b]}}if(nb){e.cov=3;e.cvp=new V(nb[0]+(nb[0]-pp.x)*.05,0,nb[1]+(nb[1]-pp.z)*.05);const dx=nb[0]-pp.x,dz=nb[1]-pp.z,l=Math.hypot(dx,dz)||1;e.cvp.set(nb[0]+dx/l*((nb[2].x1-nb[2].x0)/2+1.5),0,nb[1]+dz/l*((nb[2].z1-nb[2].z0)/2+1.5))}}
if(e.cov>0){e.cov-=dt;mv=moveE(e,e.cvp.x,e.cvp.z,4,dt);e.g.rotation.y=Math.atan2(-(pp.x-p.x),-(pp.z-p.z))}
else if(dist>16)mv=moveE(e,pp.x,pp.z,sp,dt);else if(dist<7)mv=moveE(e,p.x-f.x*5,p.z-f.z*5,sp,dt);else mv=moveE(e,p.x+f.z*e.sd*5,p.z-f.x*e.sd*5,sp*.7,dt);
e.g.rotation.y=Math.atan2(-(pp.x-p.x),-(pp.z-p.z));
if(e.cd<=0&&e.see){e.cd=D.rate*(.8+Math.random()*.4)*(e.boss?.6:1);const a=new V(p.x,1.4*e.sc,p.z),b=new V(pp.x,pp.y+1.2,pp.z);tracer(a,b);snd(500,.1,'n',Math.max(.1,1-dist/80));if(Math.random()<D.acc*(1-.6*dist/D.view))dmgP(D.dmg*(e.boss?1.6:1))}}
else if(e.st==='search'){e.lost+=dt;mv=moveE(e,e.last.x,e.last.z,3.4,dt);if(e.lost>6)e.st='patrol'}
else{if(p.distanceTo(e.wp)<1.5)e.wp.set(e.home.x+(Math.random()-.5)*40,0,e.home.z+(Math.random()-.5)*40);mv=moveE(e,e.wp.x,e.wp.z,1.8,dt)}
const l=e.g.userData.legs;l[0].rotation.x=mv?Math.sin(e.ph)*.7:0;l[1].rotation.x=mv?-Math.sin(e.ph)*.7:0}
// ========================= 7) المراحل والتحديث =========================
function spawnPK(){for(const k of PK)scene.remove(k.m);PK=[];for(let i=0;i<8;i++){let x,z,n=0;do{x=Math.random()*160-80;z=Math.random()*160-80;n++}while(blk(x,z,0,1)&&n<30);const ty=i%3,m=new THREE.Mesh(new THREE.BoxGeometry(.6,.6,.6),mat([0x2ecc71,0x3b82c4,0xf1c40f][ty]));m.position.set(x,.6,z);scene.add(m);PK.push({m,ty})}}
function start(mode,lv){hideP();build(lv.map,lv.night,lv.seed||5);for(const e of E)scene.remove(e.g);E=[];
G={mode,lv,t:0,kills:0,over:0,paused:0,bossDead:0,boss:0,sT:0,dead:0,D:DF[Math.max(0,Math.min(2,lv.diff+S.d-1))]};
const sp=mode==='mp'?SPAWNS[MP.idx||0]:[0,70];pl.p.set(sp[0],0,sp[1]);pl.vy=0;pl.yaw=0;pl.pitch=0;pl.hp=100;pl.ar=mode==='mp'?0:25;pl.w=0;pl.rl=0;pl.cr=0;pl.sp=0;
WP.forEach((w,i)=>{pl.am[i]=w.mag;pl.rs[i]=w.mag*5});setVM();$('hud').style.display='block';$('dead').style.display='none';
if(mode!=='mp'){spawnPK();$('net').textContent=''}else{for(const k of PK)scene.remove(k.m);PK=[]}
if(isTouch)$('tc').style.display='block';try{if(!isTouch)$('c').requestPointerLock()}catch(e){}}
function finish(win){if(!G||G.over)return;G.over=1;try{document.exitPointerLock()}catch(e){}$('hud').style.display='none';
const sc=G.kills*100+Math.max(0,Math.round(pl.hp))*2+(win?500:0),st=!win?0:pl.hp>70?3:pl.hp>35?2:1;
if(G.mode!=='mp'){P.xp+=Math.floor(sc/10);P.coins+=Math.floor(sc/20);if(win&&G.mode==='camp'){if(!P.done.includes(G.lv.i))P.done.push(G.lv.i);P.unl=Math.max(P.unl,Math.min(3,G.lv.i+2))}sv()}
const nx=G.mode==='camp'&&win&&LV[G.lv.i+1];panel('<h2>'+(win?'نجحت المهمة':'فشلت المهمة')+'</h2><div class="sm">القتلى: '+G.kills+' | النقاط: '+sc+' | التقييم: '+'★'.repeat(st)+'☆'.repeat(3-st)+'</div>'+
(nx?'<button class="mb" onclick="U.camp('+nx.i+')">المرحلة التالية</button>':'')+'<button class="mb" onclick="U.retry()">إعادة المحاولة</button><button class="mb" onclick="U.main()">القائمة الرئيسية</button>')}
function update(dt){G.t+=dt;const w=WP[pl.w];pl.cd-=dt;if(pl.kick>0)pl.kick-=dt;
if(pl.rl>0){pl.rl-=dt;if(pl.rl<=0){const t=Math.min(w.mag-pl.am[pl.w],pl.rs[pl.w]);pl.am[pl.w]+=t;pl.rs[pl.w]-=t}}
if(!G.dead){const ix=(K.d?1:0)-(K.a?1:0)+joy.x,iy=(K.w?1:0)-(K.s?1:0)+joy.y,l=Math.hypot(ix,iy);pl.aim=B.aim||K.rm;pl.mv=0;
if(l>.05){const n=Math.min(l,1)/l,fx=ix*n,fy=iy*n,sp=((pl.sp||K.shift)&&!pl.cr&&fy>0?7:4.6)*(pl.cr?.5:1)*(pl.aim?.6:1)*w.spd,c=Math.cos(pl.yaw),s=Math.sin(pl.yaw),dx=(fx*c-fy*s)*sp*dt,dz=(-fx*s-fy*c)*sp*dt;
if(!blk(pl.p.x+dx,pl.p.z,pl.p.y))pl.p.x+=dx;if(!blk(pl.p.x,pl.p.z+dz,pl.p.y))pl.p.z+=dz;pl.mv=1}
if((B.jump||K[' '])&&pl.og){pl.vy=7.5;pl.og=0}B.jump=0;
pl.vy-=22*dt;pl.p.y+=pl.vy*dt;const g=gnd(pl.p.x,pl.p.z,pl.p.y-pl.vy*dt);if(pl.p.y<=g){pl.p.y=g;pl.vy=0;pl.og=1}else pl.og=0;
pl.p.x=Math.max(-94,Math.min(94,pl.p.x));pl.p.z=Math.max(-94,Math.min(94,pl.p.z));
if(B.fire||K.lm){if(w.auto||!B.held){fire()}B.held=1}else B.held=0;if(K.r){K.r=0;reload()}}
pl.pitch=Math.max(-1.4,Math.min(1.4,pl.pitch));
for(const e of E)aiE(e,dt);
for(const k of PK){k.m.rotation.y+=dt*2;if(!G.dead&&Math.hypot(k.m.position.x-pl.p.x,k.m.position.z-pl.p.z)<1.5){if(k.ty===0&&pl.hp<100)pl.hp=Math.min(100,pl.hp+40);else if(k.ty===1&&pl.ar<100)pl.ar=Math.min(100,pl.ar+50);else if(k.ty===2)pl.rs[pl.w]+=w.mag*2;else continue;snd(800,.1,'o');scene.remove(k.m);PK.splice(PK.indexOf(k),1);break}}
for(let i=FX.length-1;i>=0;i--){const f=FX[i];f.userData.l-=dt;if(f.userData.v){f.position.addScaledVector(f.userData.v,dt);f.userData.v.y-=9*dt}if(f.userData.l<=0){scene.remove(f);f.geometry.dispose();FX.splice(i,1)}}
const lv=G.lv;if(G.mode!=='mp'){if(lv.type==='kill'||lv.type==='boss'){const need=lv.goal-G.kills-E.length;let n=0;while(E.length<3+lv.diff&&need-n>0){spawnE(0);n++}
if(lv.type==='boss'&&G.kills>=lv.goal&&!G.boss){G.boss=1;spawnE(1)}if(lv.type==='kill'&&G.kills>=lv.goal)finish(true);if(lv.type==='boss'&&G.bossDead)finish(true)}
else{G.sT+=dt;if(G.sT>3&&E.length<5+lv.diff){G.sT=0;spawnE(0)}if(G.t>=lv.goal)finish(true)}
$('obj').textContent=lv.type==='survive'?'الصمود: '+Math.max(0,Math.ceil(lv.goal-G.t))+' ث':lv.type==='boss'&&G.boss?'اقضِ على القائد':'تصفية الأعداء: '+G.kills+'/'+lv.goal}
// كاميرا
const eh=pl.cr?1:1.6;cam.rotation.set(pl.pitch,pl.yaw,0);const sh=S.fx?pl.shake:0;pl.shake=Math.max(0,pl.shake-dt);
const ex=pl.p.x+(Math.random()-.5)*sh,ey=pl.p.y+eh+(Math.random()-.5)*sh,ez=pl.p.z;
if(pl.fps){cam.position.set(ex,ey,ez)}else{const s=Math.sin(pl.yaw),c=Math.cos(pl.yaw);cam.position.set(ex+s*3.2+c*.6,ey+.4,ez+c*3.2-s*.6);if(cam.position.y<.3)cam.position.y=.3}
vm.visible=!!pl.fps;vm.position.z=-.35-WP[pl.w].len*.3+(pl.kick>0?.06:0);pm.visible=!pl.fps;pm.position.copy(pl.p);pm.rotation.y=pl.yaw;const lg=pm.userData.legs;lg[0].rotation.x=pl.mv?Math.sin(G.t*9)*.7:0;lg[1].rotation.x=-lg[0].rotation.x;pm.scale.y=pl.cr?.75:1;
const tf=pl.aim?(pl.w===2?22:50):75;cam.fov+=(tf-cam.fov)*Math.min(1,dt*10);cam.updateProjectionMatrix();$('sc').style.display=pl.aim&&pl.w===2&&pl.fps?'block':'none';
sun.position.set(pl.p.x+40,pl.p.y+70,pl.p.z+25);sun.target.position.copy(pl.p);
$('hpb').style.width=Math.max(0,pl.hp)+'%';$('arb').style.width=pl.ar+'%';$('am').textContent=WP[pl.w].n+'  '+(pl.rl>0?'...':pl.am[pl.w]+' / '+pl.rs[pl.w])}
// ========================= 8) الإدخال: لمس وكيبورد وفأرة =========================
const isTouch=matchMedia('(pointer:coarse)').matches||'ontouchstart' in window;
const BT=[['fire','fire','right:3vmin;bottom:6vmin;width:22vmin;height:22vmin'],['jump','jump','right:27vmin;bottom:5vmin;width:14vmin;height:14vmin'],['reload','reload','right:21vmin;bottom:24vmin;width:13vmin;height:13vmin'],['aim','aim','right:4vmin;bottom:31vmin;width:13vmin;height:13vmin'],['weapon','weapon','right:37vmin;bottom:22vmin;width:12vmin;height:12vmin'],['view','view','right:2vmin;top:2vmin;width:11vmin;height:11vmin'],['pause','pause','right:15vmin;top:2vmin;width:11vmin;height:11vmin'],['sprint','sprint','left:3vmin;bottom:46vmin;width:12vmin;height:12vmin'],['crouch','crouch','left:18vmin;bottom:46vmin;width:12vmin;height:12vmin']];
function act(n,d){if(!G)return;if(n==='fire'){B.fire=d;return}if(n==='aim'){B.aim=d;return}if(!d)return;if(n==='jump')B.jump=1;else if(n==='reload')reload();else if(n==='sprint')pl.sp=!pl.sp;else if(n==='crouch')pl.cr=!pl.cr;else if(n==='view')pl.fps=!pl.fps;else if(n==='weapon')swap();else if(n==='pause')pause()}
for(const[n,i,css]of BT){const b=document.createElement('div');b.className='tb';b.style.cssText=css;b.innerHTML=ic(i);$('tc').appendChild(b);
b.addEventListener('pointerdown',e=>{e.preventDefault();b.setPointerCapture(e.pointerId);b.classList.add('on');act(n,true)});const up=()=>{b.classList.remove('on');act(n,false)};b.addEventListener('pointerup',up);b.addEventListener('pointercancel',up)}
{const jz=$('jz'),jb=$('jb'),jk=$('jk');let id=null,c=null;
jz.addEventListener('pointerdown',e=>{e.preventDefault();jz.setPointerCapture(e.pointerId);id=e.pointerId;c={x:e.clientX,y:e.clientY};jb.style.display='block';jb.style.left=c.x+'px';jb.style.top=c.y+'px'});
jz.addEventListener('pointermove',e=>{if(e.pointerId!==id)return;let dx=(e.clientX-c.x)/50,dy=(e.clientY-c.y)/50;const l=Math.hypot(dx,dy);if(l>1){dx/=l;dy/=l}joy.x=dx;joy.y=-dy;jk.style.left=(30+dx*30)+'px';jk.style.top=(30+dy*30)+'px'});
const end=e=>{if(e.pointerId!==id)return;id=null;joy.x=joy.y=0;jb.style.display='none';jk.style.left=jk.style.top='30px'};jz.addEventListener('pointerup',end);jz.addEventListener('pointercancel',end)}
{const lk=$('look');let id=null,lx=0,ly=0;lk.addEventListener('pointerdown',e=>{if(!isTouch)return;lk.setPointerCapture(e.pointerId);id=e.pointerId;lx=e.clientX;ly=e.clientY});
lk.addEventListener('pointermove',e=>{if(e.pointerId!==id)return;pl.yaw-=(e.clientX-lx)*.005*S.sens;pl.pitch-=(e.clientY-ly)*.005*S.sens;lx=e.clientX;ly=e.clientY});
const end=e=>{if(e.pointerId===id)id=null};lk.addEventListener('pointerup',end);lk.addEventListener('pointercancel',end)}
addEventListener('keydown',e=>{const k=e.key.toLowerCase();K[k]=1;if(!G)return;if(k==='v')pl.fps=!pl.fps;if(k==='c')pl.cr=!pl.cr;if(k==='escape')pause();if(k==='q')swap();if('123'.includes(k)&&k!==''&&+k<=P.unl){pl.w=+k-1;setVM()}});
addEventListener('keyup',e=>{K[e.key.toLowerCase()]=0});
document.addEventListener('mousemove',e=>{if(document.pointerLockElement){pl.yaw-=e.movementX*.0022*S.sens;pl.pitch-=e.movementY*.0022*S.sens}});
document.addEventListener('mousedown',e=>{if(!G||isTouch||ov.style.display!=='none')return;if(!document.pointerLockElement)try{$('c').requestPointerLock()}catch(x){}if(e.button===0)K.lm=1;if(e.button===2)K.rm=1});
document.addEventListener('mouseup',e=>{if(e.button===0)K.lm=0;if(e.button===2)K.rm=0});addEventListener('contextmenu',e=>e.preventDefault());
document.addEventListener('visibilitychange',()=>{if(document.hidden&&G&&G.mode!=='mp'&&!G.over)pause()});
function pause(){if(!G||G.over||ov.style.display!=='none')return;if(G.mode!=='mp')G.paused=1;try{document.exitPointerLock()}catch(e){}
panel('<h2>إيقاف مؤقت</h2><button class="mb" onclick="U.resume()">متابعة</button><button class="mb" onclick="U.set()">الإعدادات</button><button class="mb" onclick="U.quit()">العودة للقائمة</button>')}
// ========================= 9) الغرف الجماعية (عميل) =========================
const MP={on:0,code:'',pid:'',host:0,state:'lobby',round:0,rem:{},fail:0,idx:0,me:''};
async function api(p,b){try{const r=await fetch('/api/'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});return await r.json()}catch(e){return{ok:false,err:'net'}}}
const pname=()=>'لاعب'+Math.floor(Math.random()*900+100);
async function mpEnter(r){if(!r.ok){alert(r.err==='room'?'الرمز غير صحيح':r.err==='full'?'الغرفة ممتلئة':r.err==='started'?'المباراة بدأت':r.err==='limit'?'محاولات كثيرة، انتظر قليلاً':'تعذر الاتصال بالخادم');return}
Object.assign(MP,{on:1,code:r.code,pid:r.pid,state:'lobby',round:0,fail:0,host:0});lobbyUI();mpTick()}
async function mpTick(){if(!MP.on)return;const r=await api('sync',{code:MP.code,pid:MP.pid,x:pl.p.x,y:pl.p.y,z:pl.p.z,ry:pl.yaw});
if(!MP.on)return;if(!r.ok){MP.fail++;if(G&&G.mode==='mp')$('net').textContent='انقطع الاتصال... إعادة المحاولة';if(r.err==='room'&&MP.fail>3){MP.on=0;alert('أُغلقت الغرفة');U.main();return}}
else{MP.fail=0;MP.host=r.host;MP.me=r.me.id;MP.idx=Math.max(0,+r.me.id.slice(1)-1);const first=!MP.rem._init;
if(G&&G.mode==='mp'){$('net').textContent='متصل | الغرفة '+MP.code;for(const q of r.players){if(q.id===r.me.id)continue;let m=MP.rem[q.id];if(!m){m={g:human(0x7a2e2e),hp:100};scene.add(m.g);MP.rem[q.id]=m}m.hp=q.hp;m.g.visible=q.hp>0;m.tx=new V(q.x,q.y,q.z);m.ry=q.ry}
if(r.me.flag){pl.p.set(r.me.x,0,r.me.z);pl.vy=0;if(r.me.flag==='resp'){pl.hp=100;G.dead=0;$('dead').style.display='none'}}
pl.hp=r.me.hp;if(pl.hp<=0&&!G.dead){G.dead=1;$('dead').style.display='flex'}
const o=r.players.find(q=>q.id!==r.me.id);$('obj').textContent='أنت '+r.me.kills+' - '+(o?o.kills:0)+' الخصم (الهدف '+r.target+')'}
if(r.state==='play'&&(!G||G.mode!=='mp'||MP.round!==r.round)){MP.round=r.round;MP.state='play';for(const k in MP.rem)if(k!=='_init'){scene.remove(MP.rem[k].g);delete MP.rem[k]}start('mp',{map:'city',night:0,type:'mp',goal:0,diff:1,seed:7,i:-1})}
if(r.state==='over'&&MP.state!=='over'){MP.state='over';if(G)G.over=1;$('hud').style.display='none';try{document.exitPointerLock()}catch(e){}panel('<h2>انتهت المباراة</h2><div>الفائز: '+esc(r.winner)+'</div><div class="sm">'+r.players.map(q=>esc(q.name)+': '+q.kills).join(' | ')+'</div>'+(MP.host?'<button class="mb" onclick="U.mpstart()">إعادة الجولة</button>':'<div class="sm">بانتظار صاحب الغرفة لإعادة الجولة</div>')+'<button class="mb" onclick="U.mpleave()">مغادرة الغرفة</button>')}
if(!G||G.mode!=='mp'||ov.style.display!=='none')lobbyUpd(r)}
setTimeout(mpTick,MP.state==='play'?100:600)}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function lobbyUI(){panel('<h2>غرفة خاصة</h2><div class="code" id="rc">'+MP.code+'</div><button class="mb" onclick="U.copy()">نسخ الرمز</button><div id="lp" class="sm"></div><div id="chat"></div><input type="text" id="ci" maxlength="120" style="font-size:3vmin;letter-spacing:0;direction:rtl" placeholder="رسالة"><div class="row"><button class="mb" onclick="U.send()">إرسال</button><button class="mb" id="sb" onclick="U.mpstart()" disabled>بدء المباراة</button></div><button class="mb" onclick="U.mpleave()">مغادرة</button>')}
function lobbyUpd(r){const lp=$('lp');if(!lp)return;lp.textContent='متصل | اللاعبون '+r.players.length+'/2: '+r.players.map(q=>q.name).join('، ');$('sb').disabled=!(MP.host&&r.players.length===2);
const ch=$('chat');ch.textContent='';for(const m of r.chat){const d=document.createElement('div');d.textContent=m.n+': '+m.t;ch.appendChild(d)}ch.scrollTop=1e5}
// ========================= 10) القوائم =========================
const ov=$('ov');function panel(h){ov.innerHTML='<div class="box">'+h+'</div>';ov.style.display='flex'}function hideP(){ov.style.display='none'}
const U=window.U={
main(){if(MP.on&&MP.code){api('leave',{code:MP.code,pid:MP.pid})}MP.on=0;for(const k in MP.rem)if(MP.rem[k].g)scene.remove(MP.rem[k].g);MP.rem={};G=null;for(const e of E)scene.remove(e.g);E=[];$('hud').style.display='none';$('tc').style.display='none';
panel('<svg width="70" height="70" viewBox="0 0 24 24" fill="none" stroke="#b9d98c" stroke-width="1.5"><path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z"/><path d="M12 7l1.5 3 3.3.4-2.4 2.3.6 3.3-3-1.6-3 1.6.6-3.3-2.4-2.3 3.3-.4z"/></svg><h1>WAR FRONT 3D</h1>'+
'<button class="mb" onclick="U.campM()">الحملة</button><button class="mb" onclick="U.quickM()">لعب سريع ضد الروبوتات</button><button class="mb" onclick="U.mpM()">اللعب مع صديق</button><div class="row"><button class="mb" onclick="U.arsM()">المستودع</button><button class="mb" onclick="U.rec()">السجل</button><button class="mb" onclick="U.set()">الإعدادات</button></div>')},
campM(){panel('<h2>الحملة</h2>'+LV.map(l=>{const ok=l.i===0||P.done.includes(l.i-1);return '<button class="mb" '+(ok?'':'disabled')+' onclick="U.camp('+l.i+')">'+l.n+(P.done.includes(l.i)?' (مكتملة)':ok?'':' (مغلقة)')+'</button>'}).join('')+'<button class="mb" onclick="U.main()">رجوع</button>')},
camp(i){U.last=['camp',LV[i]];start('camp',LV[i])},
quickM(){const q=U.q=U.q||{map:'city',night:0};panel('<h2>لعب سريع</h2><div class="row">'+['city:مدينة','desert:صحراء','forest:غابة'].map(s=>{const[a,b]=s.split(':');return '<button class="mb chip '+(q.map===a?'sel':'')+'" onclick="U.q.map=\''+a+'\';U.quickM()">'+b+'</button>'}).join('')+'</div><div class="row"><button class="mb chip '+(q.night?'':'sel')+'" onclick="U.q.night=0;U.quickM()">نهار</button><button class="mb chip '+(q.night?'sel':'')+'" onclick="U.q.night=1;U.quickM()">ليل</button></div><div class="sm">الصعوبة: '+['سهل','متوسط','صعب'][S.d]+' (من الإعدادات)</div><button class="mb" onclick="U.go()">ابدأ</button><button class="mb" onclick="U.main()">رجوع</button>')},
go(){const l={i:-1,n:'لعب سريع',map:U.q.map,night:U.q.night,type:'kill',goal:10,diff:1,seed:Math.floor(Math.random()*999)};U.last=['quick',l];start('quick',l)},
retry(){start(U.last[0],U.last[1])},
mpM(){panel('<h2>اللعب مع صديق</h2><button class="mb" onclick="U.create()">إنشاء غرفة</button><input type="text" id="jc" maxlength="6" placeholder="رمز الغرفة"><button class="mb" onclick="U.join()">الانضمام إلى غرفة</button><button class="mb" onclick="U.main()">رجوع</button>')},
async create(){mpEnter(await api('create',{name:pname()}))},
async join(){const c=$('jc').value.trim().toUpperCase();if(c.length!==6){alert('أدخل الرمز المكون من 6 أحرف');return}mpEnter(await api('join',{code:c,name:pname()}))},
copy(){try{navigator.clipboard.writeText(MP.code)}catch(e){}},
async mpstart(){const r=await api('start',{code:MP.code,pid:MP.pid});if(!r.ok)alert(r.err==='need2'?'تحتاج لاعباً ثانياً':'للمضيف فقط')},
send(){const i=$('ci');if(i.value.trim())api('chat',{code:MP.code,pid:MP.pid,text:i.value});i.value=''},
mpleave(){U.main()},
arsM(){panel('<h2>المستودع</h2>'+WP.map((w,i)=>'<div class="sm">'+w.n+(i<P.unl?'':' (مغلق - أكمل مرحلة '+i+')')+' | ضرر '+w.dmg+' | مدى '+w.range+' | مخزن '+w.mag+'</div>').join('')+'<div class="sm">عملات: '+P.coins+'</div><button class="mb" onclick="U.main()">رجوع</button>')},
rec(){const a=[['أول مهمة',P.done.includes(0)],['100 قتيل',P.kills>=100],['إنهاء الحملة',P.done.length>=3],['1000 خبرة',P.xp>=1000]];panel('<h2>السجل والإنجازات</h2><div class="sm">الخبرة: '+P.xp+' | العملات: '+P.coins+' | القتلى: '+P.kills+'</div>'+a.map(x=>'<div class="sm">'+(x[1]?'[مكتمل] ':'[ ] ')+x[0]+'</div>').join('')+'<button class="mb" onclick="U.main()">رجوع</button>')},
set(){const back=G?'U.pause2()':'U.main()';panel('<h2>الإعدادات</h2><div class="sm">جودة الرسومات</div><div class="row">'+['منخفضة','متوسطة','عالية'].map((n,i)=>'<button class="mb chip '+(S.q===i?'sel':'')+'" onclick="S_(\'q\','+i+')">'+n+'</button>').join('')+'</div><div class="sm">الصعوبة</div><div class="row">'+['سهل','متوسط','صعب'].map((n,i)=>'<button class="mb chip '+(S.d===i?'sel':'')+'" onclick="S_(\'d\','+i+')">'+n+'</button>').join('')+'</div><div class="sm">حساسية الكاميرا</div><input type="range" min="0.3" max="2.5" step="0.1" value="'+S.sens+'" oninput="S.sens=+this.value;sv_()"><div class="sm">مستوى الصوت</div><input type="range" min="0" max="1" step="0.05" value="'+S.vol+'" oninput="S.vol=+this.value;sv_()"><div class="sm">مؤثرات الاهتزاز والشرر</div><div class="row"><button class="mb chip '+(S.fx?'sel':'')+'" onclick="S_(\'fx\',1)">تشغيل</button><button class="mb chip '+(S.fx?'':'sel')+'" onclick="S_(\'fx\',0)">إيقاف</button></div><button class="mb" onclick="'+back+'">رجوع</button>')},
pause2(){panel('<h2>إيقاف مؤقت</h2><button class="mb" onclick="U.resume()">متابعة</button><button class="mb" onclick="U.set()">الإعدادات</button><button class="mb" onclick="U.quit()">العودة للقائمة</button>')},
resume(){hideP();if(G)G.paused=0;if(!isTouch)try{$('c').requestPointerLock()}catch(e){}},
quit(){U.main()}};
window.S=S;window.sv_=sv;window.S_=(k,v)=>{S[k]=v;sv();if(k==='q')applyQ();U.set()};
// ========================= 11) الحلقة الرئيسية =========================
let last=performance.now(),fr=0,ft=0,low=0;
function loop(now){requestAnimationFrame(loop);const dt=Math.min(.05,(now-last)/1000);last=now;fr++;ft+=dt;
if(ft>=1){$('fps').textContent=fr+' FPS';if(G&&!G.paused&&fr<22&&S.q>0){if(++low>=3){S.q--;applyQ();low=0}}else low=0;fr=0;ft=0}
if(G&&!G.paused&&!G.over){update(dt);for(const id in MP.rem){const m=MP.rem[id];if(m.tx){m.g.position.lerp(m.tx,Math.min(1,dt*12));m.g.rotation.y=m.ry;const mv=m.g.position.distanceTo(m.tx)>.05;m.g.userData.legs[0].rotation.x=mv?Math.sin(now/110)*.7:0;m.g.userData.legs[1].rotation.x=-m.g.userData.legs[0].rotation.x}}}
R.render(scene,cam)}
build('city',0,3);cam.position.set(0,6,70);U.main();requestAnimationFrame(loop);
})();
</script></body></html>"""

# ========================= 12) تشغيل =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
