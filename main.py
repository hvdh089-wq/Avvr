
# -*- coding: utf-8 -*-
"""
ASAD: FRONTLINE
ملف واحد: main.py
المطور: أسعد المطور

التقنيات:
  Flask + Flask-SocketIO + Simple-WebSocket
  HTML/CSS/JavaScript + Three.js
  Socket.IO للتزامن الفوري

تشغيل محلي:
  python -m pip install flask flask-socketio simple-websocket
  python main.py

تشغيل إنتاجي على Render:
  Build: pip install flask flask-socketio simple-websocket gunicorn
  Start: gunicorn --worker-class gthread --threads 100 --timeout 120 main:app

ملاحظة: الحالة والنتائج محفوظة في ذاكرة العملية الحالية.
لا تستخدم أكثر من عامل Gunicorn واحد مع هذا التخزين الداخلي.
"""

import os
import re
import math
import time
import secrets
import threading
from collections import defaultdict
from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit, join_room, disconnect

# ============================================================
# 1. إعداد التطبيق
# ============================================================

GAME_NAME = "ASAD: FRONTLINE"
DEVELOPER = "أسعد المطور"
MAX_PLAYERS = 3
MATCH_SECONDS = 180
TICK_RATE = 20
ROOM_TTL = 60 * 60
TOKEN_TTL = 30 * 60

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", secrets.token_hex(32)
)

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins=[],
    ping_interval=20,
    ping_timeout=35,
    max_http_buffer_size=100_000,
)

# لا تُشارك هذه القواميس بين عدة عمليات خادم.
rooms = {}
sid_index = {}
rate_limits = defaultdict(list)
world_lock = threading.RLock()
engine_started = False

WORLD_LIMIT = 45.0
PLAYER_RADIUS = 0.48
PLAYER_HEIGHT = 1.8

# عوائق ثابتة: x, z, نصف العرض، نصف العمق، الارتفاع
OBSTACLES = [
    (-8, -7, 3.5, 1.0, 2.7),
    (8, -8, 3.0, 1.0, 2.4),
    (-13, 3, 1.0, 4.0, 3.2),
    (13, 4, 1.0, 4.0, 3.2),
    (-5, 12, 3.0, 1.0, 2.5),
    (6, 12, 3.2, 1.0, 2.5),
    (0, -16, 5.0, 1.0, 3.0),
    (-19, -12, 1.0, 3.0, 2.5),
    (19, 14, 1.0, 4.0, 3.0),
    (0, 20, 7.0, 1.0, 2.6),
    (-22, 0, 1.0, 5.0, 3.0),
    (22, -3, 1.0, 5.0, 3.0),
    (-3, 2, 1.0, 2.0, 1.8),
    (4, -2, 1.0, 2.0, 1.8),
]

SPAWNS = [
    (-3.0, 0.0),
    (3.0, 0.0),
    (0.0, 4.0),
]

WEAPONS = {
    "rifle": {
        "name": "بندقية هجومية",
        "mag": 30,
        "reserve": 120,
        "reload": 1.65,
        "rate": 0.115,
        "damage": 22,
        "range": 34,
        "spread": 0.045,
    },
    "smg": {
        "name": "رشاش خفيف",
        "mag": 36,
        "reserve": 144,
        "reload": 1.4,
        "rate": 0.075,
        "damage": 14,
        "range": 23,
        "spread": 0.075,
    },
}


def now():
    return time.time()


def clean_name(value, default="SOLDIER"):
    value = str(value or "").strip()
    value = re.sub(r"[\x00-\x1f<>]", "", value)
    return value[:22] or default


def make_code(length=8):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def make_unique_code():
    for _ in range(100):
        code = make_code()
        if not any(code in r["codes"] for r in rooms.values()):
            return code
    raise RuntimeError("تعذر إنشاء رمز فريد")


def allowed_rate(sid, action, limit, period=1.0):
    key = (sid, action)
    current = now()
    events = [t for t in rate_limits[key] if current - t < period]
    if len(events) >= limit:
        rate_limits[key] = events
        return False
    events.append(current)
    rate_limits[key] = events
    return True


def fresh_player(slot, name, sid=None):
    x, z = SPAWNS[slot]
    return {
        "slot": slot,
        "name": name,
        "sid": sid,
        "connected": sid is not None,
        "x": x,
        "z": z,
        "y": 0.0,
        "vx": 0.0,
        "vz": 0.0,
        "vy": 0.0,
        "yaw": 0.0 if slot == 0 else math.pi,
        "pitch": 0.0,
        "health": 100,
        "alive": True,
        "kills": 0,
        "deaths": 0,
        "score": 0,
        "weapon": "rifle",
        "ammo": WEAPONS["rifle"]["mag"],
        "reserve": WEAPONS["rifle"]["reserve"],
        "reloading": False,
        "reload_until": 0.0,
        "last_shot": 0.0,
        "last_grenade": 0.0,
        "respawn_at": 0.0,
        "jump_requested": False,
        "crouch": False,
        "sprint": False,
        "aim": False,
        "fire": False,
        "interact": False,
        "grenade": False,
        "move_x": 0.0,
        "move_z": 0.0,
        "last_input": 0.0,
        "last_seen": now(),
        "damage_flash": 0,
    }


def new_room(name, host_sid):
    room_id = secrets.token_urlsafe(7).replace("-", "").replace("_", "")[:10].upper()
    while room_id in rooms:
        room_id = secrets.token_urlsafe(7)[:10].upper()

    codes = {
        "host": make_unique_code(),
        "controller1": make_unique_code(),
        "controller2": make_unique_code(),
    }

    room = {
        "id": room_id,
        "name": clean_name(name, "ASAD_BATTLE"),
        "created": now(),
        "last_active": now(),
        "codes": codes,
        "used_codes": set(),
        "slots": [None, None, None],
        "players": {},
        "host_sid": host_sid,
        "state": "lobby",
        "started_at": 0.0,
        "ends_at": 0.0,
        "remaining": MATCH_SECONDS,
        "winner": None,
        "objective": {"x": 0.0, "z": 0.0, "progress": {}},
        "revision": 0,
    }
    room["slots"][0] = host_sid
    room["players"][host_sid] = fresh_player(0, "ASAD", host_sid)
    rooms[room_id] = room
    sid_index[host_sid] = (room_id, 0)
    return room


def public_room(room):
    players = []
    for slot in range(MAX_PLAYERS):
        sid = room["slots"][slot]
        p = room["players"].get(sid) if sid else None
        players.append({
            "slot": slot,
            "name": p["name"] if p else (
                "اللاعب الأساسي" if slot == 0 else f"وحدة التحكم {slot}"
            ),
            "connected": bool(p and p["connected"]),
            "occupied": bool(p),
            "health": p["health"] if p else 0,
            "kills": p["kills"] if p else 0,
            "deaths": p["deaths"] if p else 0,
            "score": p["score"] if p else 0,
        })
    return {
        "id": room["id"],
        "name": room["name"],
        "state": room["state"],
        "remaining": max(0, int(room["ends_at"] - now()))
        if room["state"] == "playing" else room["remaining"],
        "players": players,
        "winner": room["winner"],
        "developer": DEVELOPER,
    }


def room_emit(room, event, data):
    socketio.emit(event, data, to=room["id"])


def update_room_status(room):
    room_emit(room, "room_status", public_room(room))


def reset_player_for_match(p):
    slot = p["slot"]
    x, z = SPAWNS[slot]
    p.update({
        "x": x, "z": z, "y": 0.0,
        "vx": 0.0, "vz": 0.0, "vy": 0.0,
        "yaw": 0.0 if slot == 0 else math.pi,
        "pitch": 0.0,
        "health": 100, "alive": True,
        "kills": 0, "deaths": 0, "score": 0,
        "weapon": "rifle",
        "ammo": WEAPONS["rifle"]["mag"],
        "reserve": WEAPONS["rifle"]["reserve"],
        "reloading": False, "reload_until": 0.0,
        "last_shot": 0.0, "last_grenade": 0.0,
        "respawn_at": 0.0,
        "fire": False, "jump_requested": False,
        "grenade": False, "move_x": 0.0, "move_z": 0.0,
    })


def start_match(room):
    if room["state"] == "playing":
        return False, "المباراة جارية بالفعل"
    if not room["players"]:
        return False, "لا يوجد لاعب لبدء المباراة"

    room["state"] = "playing"
    room["started_at"] = now() + 3.0
    room["ends_at"] = room["started_at"] + MATCH_SECONDS
    room["remaining"] = MATCH_SECONDS
    room["winner"] = None
    room["objective"]["progress"] = {}

    for p in room["players"].values():
        reset_player_for_match(p)

    room_emit(room, "match_countdown", {"seconds": 3})
    update_room_status(room)
    return True, "بدأت المباراة"


def end_match(room, reason="time"):
    if room["state"] != "playing":
        return
    room["state"] = "results"
    room["remaining"] = max(0, int(room["ends_at"] - now()))
    room["winner"] = None
    ranked = sorted(
        room["players"].values(),
        key=lambda p: (p["score"], p["kills"], -p["deaths"]),
        reverse=True,
    )
    if ranked:
        room["winner"] = {
            "slot": ranked[0]["slot"],
            "name": ranked[0]["name"],
            "score": ranked[0]["score"],
        }
    room_emit(room, "match_over", {
        "reason": reason,
        "winner": room["winner"],
        "players": [{
            "slot": p["slot"],
            "name": p["name"],
            "kills": p["kills"],
            "deaths": p["deaths"],
            "score": p["score"],
        } for p in ranked],
    })
    update_room_status(room)


# ============================================================
# 2. فيزياء وتصادمات الخادم
# ============================================================

def circle_hits_box(x, z, radius, box):
    bx, bz, hx, hz, _ = box
    nearest_x = max(bx - hx, min(x, bx + hx))
    nearest_z = max(bz - hz, min(z, bz + hz))
    dx = x - nearest_x
    dz = z - nearest_z
    return dx * dx + dz * dz < radius * radius


def is_blocked(x, z, radius=PLAYER_RADIUS):
    if abs(x) > WORLD_LIMIT or abs(z) > WORLD_LIMIT:
        return True
    return any(circle_hits_box(x, z, radius, box) for box in OBSTACLES)


def move_player(p, dt):
    if not p["alive"]:
        return

    # تُرفض الحركة بعد توقف إرسال الأوامر أو فقدان الاتصال.
    if not p["connected"] or now() - p["last_input"] > 1.0:
        p["move_x"] = 0.0
        p["move_z"] = 0.0
        p["fire"] = False
        p["sprint"] = False

    mx = max(-1.0, min(1.0, p["move_x"]))
    mz = max(-1.0, min(1.0, p["move_z"]))
    magnitude = math.hypot(mx, mz)
    if magnitude > 1.0:
        mx /= magnitude
        mz /= magnitude

    yaw = p["yaw"]
    # اتجاه أمامي متوافق مع منظور الكاميرا.
    forward_x = -math.sin(yaw)
    forward_z = -math.cos(yaw)
    right_x = math.cos(yaw)
    right_z = -math.sin(yaw)

    target_x = (right_x * mx + forward_x * mz)
    target_z = (right_z * mx + forward_z * mz)
    speed = 8.0 if p["sprint"] else 4.6
    if p["crouch"]:
        speed = 2.3
    if p["aim"]:
        speed *= 0.78

    target_vx = target_x * speed
    target_vz = target_z * speed
    acceleration = 18.0 if magnitude > 0.05 else 13.0
    blend = min(1.0, acceleration * dt)
    p["vx"] += (target_vx - p["vx"]) * blend
    p["vz"] += (target_vz - p["vz"]) * blend

    nx = p["x"] + p["vx"] * dt
    nz = p["z"] + p["vz"] * dt

    # فصل التصادم على المحورين لتجنب اختراق الزوايا.
    if not is_blocked(nx, p["z"]):
        p["x"] = nx
    else:
        p["vx"] = 0.0
    if not is_blocked(p["x"], nz):
        p["z"] = nz
    else:
        p["vz"] = 0.0

    # جاذبية وقَفز تقريبيان على سطح مستوٍ.
    if p["jump_requested"] and p["y"] <= 0.001:
        p["vy"] = 6.5
    p["jump_requested"] = False
    p["vy"] -= 18.0 * dt
    p["y"] += p["vy"] * dt
    if p["y"] < 0:
        p["y"] = 0.0
        p["vy"] = 0.0

    p["x"] = max(-WORLD_LIMIT, min(WORLD_LIMIT, p["x"]))
    p["z"] = max(-WORLD_LIMIT, min(WORLD_LIMIT, p["z"]))


def line_hits_obstacle(ax, az, bx, bz):
    # فحص عينات على مسار المقذوف؛ مناسب لساحة صغيرة.
    distance = math.hypot(bx - ax, bz - az)
    samples = max(2, int(distance / 0.35))
    for i in range(1, samples):
        t = i / samples
        x = ax + (bx - ax) * t
        z = az + (bz - az) * t
        for box in OBSTACLES:
            if circle_hits_box(x, z, 0.16, box):
                return True
    return False


def fire_weapon(room, shooter):
    current = now()
    weapon = WEAPONS[shooter["weapon"]]

    if not shooter["connected"] or not shooter["alive"]:
        return
    if shooter["reloading"] or shooter["ammo"] <= 0:
        return
    if current - shooter["last_shot"] < weapon["rate"]:
        return

    shooter["last_shot"] = current
    shooter["ammo"] -= 1

    yaw = shooter["yaw"]
    pitch = shooter["pitch"]
    # انحراف صغير متوازن، محسوب على الخادم.
    spread = weapon["spread"]
    yaw += secrets.randbelow(10000) / 10000 * spread - spread / 2
    pitch += secrets.randbelow(10000) / 10000 * spread - spread / 2

    dx = -math.sin(yaw) * math.cos(pitch)
    dz = -math.cos(yaw) * math.cos(pitch)
    dy = math.sin(pitch)

    origin_x = shooter["x"]
    origin_z = shooter["z"]
    origin_y = shooter["y"] + (0.9 if shooter["crouch"] else 1.45)

    best = None
    best_distance = weapon["range"]
    for target in room["players"].values():
        if target is shooter or not target["alive"] or not target["connected"]:
            continue
        tx = target["x"] - origin_x
        tz = target["z"] - origin_z
        ty = target["y"] + 0.9 - origin_y
        projection = tx * dx + tz * dz + ty * dy
        if projection <= 0 or projection > weapon["range"]:
            continue

        px = origin_x + dx * projection
        pz = origin_z + dz * projection
        py = origin_y + dy * projection
        target_y = target["y"] + 0.9
        dist_sq = (
            (target["x"] - px) ** 2
            + (target["z"] - pz) ** 2
            + (target_y - py) ** 2
        )
        if dist_sq > 0.95 ** 2 or projection >= best_distance:
            continue
        if line_hits_obstacle(origin_x, origin_z, target["x"], target["z"]):
            continue
        best = target
        best_distance = projection

    event = {
        "slot": shooter["slot"],
        "x": origin_x,
        "y": origin_y,
        "z": origin_z,
        "dx": dx,
        "dy": dy,
        "dz": dz,
        "distance": best_distance if best else weapon["range"],
        "hit": best["slot"] if best else None,
        "weapon": shooter["weapon"],
    }

    if best:
        # ضرر المنطقة العلوية عند إصابة الرأس تقريبي.
        head_hit = abs(best["y"] + 1.55 - (origin_y + dy * best_distance)) < 0.32
        damage = weapon["damage"] * (1.6 if head_hit else 1.0)
        best["health"] = max(0, best["health"] - int(damage))
        best["damage_flash"] = 1
        room_emit(room, "hit_confirm", {
            "attacker": shooter["slot"],
            "target": best["slot"],
            "damage": int(damage),
            "head": head_hit,
        })
        if best["health"] <= 0:
            best["alive"] = False
            best["deaths"] += 1
            best["respawn_at"] = current + 3.0
            shooter["kills"] += 1
            shooter["score"] += 100
            room_emit(room, "elimination", {
                "killer": shooter["slot"],
                "victim": best["slot"],
            })

    room_emit(room, "shot", event)


def reload_weapon(p):
    if p["reloading"] or p["reserve"] <= 0:
        return
    weapon = WEAPONS[p["weapon"]]
    if p["ammo"] >= weapon["mag"]:
        return
    p["reloading"] = True
    p["reload_until"] = now() + weapon["reload"]


def throw_grenade(room, p):
    current = now()
    if current - p["last_grenade"] < 4.0 or not p["alive"]:
        return
    p["last_grenade"] = current

    yaw = p["yaw"]
    cx = p["x"] - math.sin(yaw) * 6.0
    cz = p["z"] - math.cos(yaw) * 6.0

    affected = []
    for target in room["players"].values():
        if target is p or not target["alive"]:
            continue
        distance = math.hypot(target["x"] - cx, target["z"] - cz)
        if distance > 5.0:
            continue
        if line_hits_obstacle(cx, cz, target["x"], target["z"]):
            continue
        damage = int(65 * (1 - distance / 6.0))
        if damage <= 0:
            continue
        target["health"] = max(0, target["health"] - damage)
        target["damage_flash"] = 1
        affected.append({"slot": target["slot"], "damage": damage})
        if target["health"] <= 0:
            target["alive"] = False
            target["deaths"] += 1
            target["respawn_at"] = current + 3.0
            p["kills"] += 1
            p["score"] += 100

    room_emit(room, "explosion", {
        "x": cx, "z": cz, "affected": affected, "by": p["slot"]
    })


def game_tick():
    last = now()
    while True:
        tick_start = now()
        dt = max(0.001, min(0.08, tick_start - last))
        last = tick_start

        with world_lock:
            stale_rooms = []
            for room_id, room in list(rooms.items()):
                if tick_start - room["last_active"] > ROOM_TTL:
                    stale_rooms.append(room_id)
                    continue

                if room["state"] != "playing":
                    continue
                if tick_start < room["started_at"]:
                    continue
                if tick_start >= room["ends_at"]:
                    end_match(room, "time")
                    continue

                # نقطة سيطرة في وسط الساحة: تمنح نقاطاً عند البقاء قريباً.
                active_near = []
                for p in room["players"].values():
                    if p["connected"] and p["alive"] and math.hypot(p["x"], p["z"]) < 3.2:
                        active_near.append(p)

                if len(active_near) == 1:
                    active_near[0]["score"] += dt * 2.0

                for p in list(room["players"].values()):
                    p["last_seen"] = tick_start
                    if p["damage_flash"]:
                        p["damage_flash"] = 0

                    if p["reloading"] and tick_start >= p["reload_until"]:
                        weapon = WEAPONS[p["weapon"]]
                        needed = weapon["mag"] - p["ammo"]
                        loaded = min(needed, p["reserve"])
                        p["ammo"] += loaded
                        p["reserve"] -= loaded
                        p["reloading"] = False

                    if not p["alive"]:
                        if p["connected"] and tick_start >= p["respawn_at"]:
                            slot = p["slot"]
                            x, z = SPAWNS[slot]
                            p["x"], p["z"], p["y"] = x, z, 0
                            p["vx"], p["vz"], p["vy"] = 0, 0, 0
                            p["health"] = 100
                            p["alive"] = True
                            p["ammo"] = WEAPONS[p["weapon"]]["mag"]
                            p["reserve"] = max(p["reserve"], 60)
                            room_emit(room, "respawn", {"slot": slot})
                        continue

                    move_player(p, dt)

                    if p["fire"]:
                        fire_weapon(room, p)
                    if p["grenade"]:
                        p["grenade"] = False
                        throw_grenade(room, p)

                room["remaining"] = max(0, int(room["ends_at"] - tick_start))
                room["revision"] += 1

                # إرسال حالة صغيرة نسبياً بمعدل 10 تحديثات/ثانية.
                if room["revision"] % 2 == 0:
                    snapshot = {
                        "state": room["state"],
                        "remaining": room["remaining"],
                        "players": [{
                            "slot": p["slot"],
                            "name": p["name"],
                            "connected": p["connected"],
                            "x": round(p["x"], 3),
                            "y": round(p["y"], 3),
                            "z": round(p["z"], 3),
                            "yaw": p["yaw"],
                            "pitch": p["pitch"],
                            "health": p["health"],
                            "alive": p["alive"],
                            "kills": p["kills"],
                            "deaths": p["deaths"],
                            "score": int(p["score"]),
                            "weapon": p["weapon"],
                            "ammo": p["ammo"],
                            "reserve": p["reserve"],
                            "reloading": p["reloading"],
                            "crouch": p["crouch"],
                            "sprint": p["sprint"],
                        } for p in room["players"].values()],
                    }
                    room_emit(room, "snapshot", snapshot)

                if room["revision"] % 10 == 0:
                    update_room_status(room)

            for room_id in stale_rooms:
                room = rooms.pop(room_id, None)
                if room:
                    for sid in list(room["players"].keys()):
                        sid_index.pop(sid, None)

        socketio.sleep(1.0 / TICK_RATE)


def start_engine_once():
    global engine_started
    if not engine_started:
        engine_started = True
        socketio.start_background_task(game_tick)


# ============================================================
# 3. صفحات الويب المولّدة داخل Python
# ============================================================

PAGE = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0a1015">
<title>ASAD: FRONTLINE</title>
<style>
:root{
 --bg:#080d11;--panel:#101a20;--panel2:#17242a;--line:#2d4248;
 --text:#eaf2ef;--muted:#91a7a6;--lime:#c7f36b;--cyan:#64e1d3;
 --red:#ff626a;--gold:#e6c879;--safe-top:env(safe-area-inset-top,0px);
 --safe-bottom:env(safe-area-inset-bottom,0px);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:var(--bg);color:var(--text);
 font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;touch-action:none}
button,input{font:inherit}
button{cursor:pointer;color:var(--text);border:1px solid var(--line);background:#17242a;
 border-radius:12px;padding:12px 16px;user-select:none}
button:active{transform:scale(.97);filter:brightness(1.2)}
button:disabled{opacity:.4}
input{width:100%;padding:14px;border-radius:10px;border:1px solid var(--line);
 background:#080f13;color:var(--text);outline:none}
input:focus{border-color:var(--lime)}
.hidden{display:none!important}
#world{position:fixed;inset:0;width:100%;height:100%;display:block}
.screen{position:fixed;inset:0;overflow:auto;padding:calc(20px + var(--safe-top)) 18px calc(20px + var(--safe-bottom));
 background:linear-gradient(145deg,rgba(7,13,17,.96),rgba(9,19,23,.91)),radial-gradient(ellipse at 65% 20%,#263c38,transparent 60%);
 z-index:4}
.center{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.logo{font-size:clamp(28px,7vw,52px);font-weight:950;letter-spacing:2px;line-height:1.05}
.logo span{color:var(--lime)}
.kicker{color:var(--cyan);letter-spacing:3px;font-size:11px;font-weight:800;margin-bottom:13px}
.subtitle{color:var(--muted);font-size:13px;line-height:1.8;max-width:390px}
.brand{position:absolute;bottom:calc(15px + var(--safe-bottom));font-size:12px;color:#8da19f}
.brand b{color:var(--lime);font-weight:700}
.home-actions{width:min(100%,370px);display:grid;gap:12px;margin-top:34px}
.primary{background:var(--lime);color:#11170a;border-color:var(--lime);font-weight:900}
.secondary{background:rgba(19,34,39,.9);font-weight:750}
.panel{width:min(100%,540px);margin:0 auto;border:1px solid var(--line);border-radius:17px;
 background:rgba(14,24,29,.95);padding:18px;box-shadow:0 22px 80px #0007}
.panel h2{font-size:21px;margin:0 0 8px}
.label{font-size:12px;color:var(--muted);display:block;margin:15px 0 7px}
.row{display:flex;gap:9px;align-items:center}
.row>*{min-width:0}
.grow{flex:1}
.note{color:var(--muted);font-size:12px;line-height:1.7}
.status{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:#607177;display:inline-block}
.dot.on{background:var(--lime);box-shadow:0 0 12px #c7f36b88}
.dot.off{background:var(--red)}
.token-row{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;margin-top:10px}
.token{direction:ltr;text-align:center;font-weight:900;letter-spacing:3px;color:var(--lime);
 background:#070d10;padding:12px;border:1px dashed #435c57;border-radius:9px}
.player-row{display:flex;justify-content:space-between;gap:8px;padding:12px 0;border-bottom:1px solid #223238}
.player-row:last-child{border-bottom:0}
.badge{font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:30px;padding:4px 7px}
#hud{position:fixed;z-index:2;inset:0;pointer-events:none}
.hud-top{position:absolute;top:calc(10px + var(--safe-top));left:10px;right:10px;display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
.hud-box{background:#071015d9;border:1px solid #34484c;border-radius:9px;padding:8px 11px;backdrop-filter:blur(8px)}
.hud-label{font-size:9px;letter-spacing:1.4px;color:var(--muted)}
.hud-value{font-weight:900;font-size:17px}
.healthbar{height:5px;background:#394549;border-radius:10px;overflow:hidden;margin-top:5px;width:130px}
.healthbar>div{height:100%;width:100%;background:var(--lime);transition:width .15s}
#crosshair{position:absolute;left:50%;top:50%;width:20px;height:20px;transform:translate(-50%,-50%)}
#crosshair:before,#crosshair:after{content:"";position:absolute;background:#dff9e8;box-shadow:0 0 5px #000}
#crosshair:before{width:2px;height:18px;left:9px;top:1px}
#crosshair:after{height:2px;width:18px;left:1px;top:9px}
#message{position:absolute;top:25%;left:50%;transform:translateX(-50%);padding:9px 16px;
 border-radius:9px;background:#0a1419e8;border:1px solid var(--lime);font-size:13px;white-space:nowrap}
#minimap{position:absolute;left:12px;bottom:12px;width:100px;height:100px;border-radius:50%;
 border:1px solid #79908a;background:#071015bb}
#controls{position:fixed;inset:0;z-index:3;pointer-events:none}
.stick{position:absolute;bottom:calc(25px + var(--safe-bottom));width:132px;height:132px;border-radius:50%;
 border:1px solid #d7eee755;background:#14252c77;pointer-events:auto;touch-action:none}
#moveStick{left:18px}
#lookStick{right:18px}
.stick:before{content:"";position:absolute;inset:20%;border:1px solid #d7eee733;border-radius:50%}
.knob{position:absolute;left:50%;top:50%;width:48px;height:48px;border-radius:50%;transform:translate(-50%,-50%);
 background:#c7f36bcc;border:2px solid #efffdc;box-shadow:0 3px 18px #0008}
.action{position:absolute;pointer-events:auto;touch-action:none;border-radius:50%;width:58px;height:58px;
 padding:0;background:#13262dd9;border:1px solid #c7f36b99;color:#e9f6ef;font-size:11px;font-weight:800;
 display:flex;align-items:center;justify-content:center}
#fireBtn{right:158px;bottom:calc(42px + var(--safe-bottom));width:72px;height:72px;background:#a93b3bd9;border-color:#ff8585}
#aimBtn{right:169px;bottom:calc(122px + var(--safe-bottom))}
#reloadBtn{right:105px;bottom:calc(154px + var(--safe-bottom))}
#jumpBtn{right:22px;bottom:calc(150px + var(--safe-bottom))}
#crouchBtn{right:82px;bottom:calc(222px + var(--safe-bottom))}
#sprintBtn{left:145px;bottom:calc(30px + var(--safe-bottom))}
#switchBtn{right:25px;bottom:calc(225px + var(--safe-bottom))}
#grenadeBtn{right:92px;bottom:calc(90px + var(--safe-bottom))}
#interactBtn{left:155px;bottom:calc(100px + var(--safe-bottom))}
#gameTopButtons{position:absolute;top:calc(65px + var(--safe-top));right:12px;display:flex;gap:6px;pointer-events:auto}
.smallbtn{font-size:10px;padding:7px 10px}
#pauseScreen,#resultScreen{z-index:8;background:#050a0deF}
.settings-grid{display:grid;gap:12px;margin-top:15px}
.settings-grid label{font-size:12px;color:var(--muted)}
.settings-grid input[type=range]{padding:0;accent-color:var(--lime)}
#controllerInfo{position:fixed;z-index:2;top:calc(10px + var(--safe-top));left:50%;transform:translateX(-50%);
 background:#071015d9;border:1px solid #34484c;border-radius:9px;padding:8px 13px;text-align:center;
 width:max-content;max-width:90%}
#toast{position:fixed;z-index:20;left:50%;top:calc(15px + var(--safe-top));transform:translateX(-50%);
 background:#13252a;border:1px solid var(--lime);border-radius:9px;padding:11px 16px;display:none;
 max-width:90%;font-size:13px}
@media(max-width:390px){
 .stick{width:112px;height:112px}
 .knob{width:42px;height:42px}
 #moveStick{left:10px}#lookStick{right:10px}
 #fireBtn{right:127px;width:64px;height:64px}
 #aimBtn{right:140px;bottom:calc(110px + var(--safe-bottom))}
 #reloadBtn{right:85px;bottom:calc(140px + var(--safe-bottom))}
 #jumpBtn{right:13px;bottom:calc(135px + var(--safe-bottom))}
 #crouchBtn{right:65px;bottom:calc(205px + var(--safe-bottom))}
 #switchBtn{right:14px;bottom:calc(205px + var(--safe-bottom))}
 #grenadeBtn{right:70px;bottom:calc(80px + var(--safe-bottom))}
 #interactBtn{left:126px}
}
@media(orientation:portrait) and (max-height:650px){
 .stick{width:95px;height:95px}
 .action{width:48px;height:48px;font-size:9px}
 #fireBtn{width:60px;height:60px}
}
</style>
</head>
<body>
<canvas id="world"></canvas>

<section id="home" class="screen center">
 <div class="kicker">TACTICAL COMBAT SYSTEMS</div>
 <div class="logo">ASAD <span>:</span><br>FRONTLINE</div>
 <p class="subtitle">ساحة قتال تكتيكية مصغرة. تحرك، سيطر على المركز، وحقق أعلى نتيجة.</p>
 <div class="home-actions">
  <button id="hostEntry" class="primary">إنشاء غرفة واللعب</button>
  <button id="controllerEntry" class="secondary">وحدة التحكم</button>
 </div>
 <div class="brand">تطوير <b>أسعد المطور</b></div>
</section>

<section id="createScreen" class="screen hidden">
 <div class="panel">
  <div class="kicker">ROOM COMMAND</div>
  <h2>إنشاء غرفة معركة</h2>
  <p class="note">أنشئ غرفة فعلية على الخادم. احتفظ بالرموز ولا تشارك رمز الجهاز الأساسي.</p>
  <label class="label" for="roomName">اسم الغرفة</label>
  <input id="roomName" maxlength="22" value="ASAD_BATTLE" autocomplete="off">
  <label class="label" for="playerName">اسم اللاعب الأساسي</label>
  <input id="playerName" maxlength="22" value="ASAD" autocomplete="off">
  <div class="row" style="margin-top:16px">
   <button id="createRoomBtn" class="primary grow">إنشاء الغرفة</button>
   <button id="backHome1">رجوع</button>
  </div>
  <p class="note" id="createError"></p>
 </div>
 <div class="brand">تطوير <b>أسعد المطور</b></div>
</section>

<section id="roomScreen" class="screen hidden">
 <div class="panel">
  <div class="kicker">SECURE LOBBY</div>
  <h2 id="roomTitle">غرفة المعركة</h2>
  <div class="row" style="justify-content:space-between;margin:10px 0">
   <span class="note">معرّف الغرفة</span><b id="roomId" dir="ltr"></b>
   <span class="badge" id="roomCount">1 / 3</span>
  </div>
  <div id="playersList"></div>
  <label class="label">رمز الجهاز الأساسي — لاستخدام شاشة اللعبة</label>
  <div class="token-row"><div id="hostToken" class="token">--------</div><button data-copy="hostToken">نسخ</button></div>
  <label class="label">رمز وحدة التحكم الأولى</label>
  <div class="token-row"><div id="controllerToken1" class="token">--------</div><button data-copy="controllerToken1">نسخ</button></div>
  <label class="label">رمز وحدة التحكم الثانية</label>
  <div class="token-row"><div id="controllerToken2" class="token">--------</div><button data-copy="controllerToken2">نسخ</button></div>
  <p class="note">أرسل الرمز الأول لوحدة التحكم للهاتف الثاني، والثاني للهاتف الثالث. الرموز منفصلة ومخصصة لكل دور.</p>
  <div class="row" style="margin-top:14px">
   <button id="startBtn" class="primary grow">بدء المباراة</button>
   <button id="rotateTokensBtn">تجديد الرموز</button>
  </div>
  <div class="row" style="margin-top:9px">
   <button id="enterGameBtn" class="secondary grow">الدخول إلى ساحة المعركة</button>
   <button id="cancelRoomBtn">إلغاء الغرفة</button>
  </div>
  <p id="roomError" class="note"></p>
 </div>
 <div class="brand">تطوير <b>أسعد المطور</b></div>
</section>

<section id="controllerScreen" class="screen center hidden">
 <div class="panel">
  <div class="kicker">REMOTE LINK</div>
  <h2>ربط وحدة التحكم</h2>
  <p class="note">أدخل رمز وحدة التحكم المخصص لهذا الهاتف. لا تستخدم رمز الجهاز الأساسي.</p>
  <label class="label" for="joinToken">رمز الاتصال</label>
  <input id="joinToken" maxlength="12" placeholder="أدخل الرمز" autocomplete="off" autocapitalize="characters" dir="ltr">
  <label class="label" for="controllerName">اسم اللاعب</label>
  <input id="controllerName" maxlength="22" placeholder="SOLDIER 02" value="SOLDIER">
  <div class="row" style="margin-top:15px">
   <button id="joinBtn" class="primary grow">اتصال</button>
   <button id="backHome2">رجوع</button>
  </div>
  <p id="joinError" class="note"></p>
  <div class="status" style="margin-top:12px"><i id="joinDot" class="dot"></i><span id="joinStatus">غير متصل</span></div>
 </div>
 <div class="brand">تطوير <b>أسعد المطور</b></div>
</section>

<div id="hud" class="hidden">
 <div class="hud-top">
  <div class="hud-box">
   <div class="hud-label">HEALTH / الصحة</div>
   <div class="hud-value" id="healthValue">100</div>
   <div class="healthbar"><div id="healthFill"></div></div>
  </div>
  <div class="hud-box" style="text-align:center">
   <div class="hud-label">TIME / الوقت</div><div class="hud-value" id="timeValue">03:00</div>
   <div class="hud-label" id="playerCountHud">PLAYERS 1/3</div>
  </div>
  <div class="hud-box" style="text-align:left;direction:ltr">
   <div class="hud-label" id="weaponName">RIFLE</div>
   <div class="hud-value"><span id="ammoValue">30</span><span style="color:#718984"> / </span><span id="reserveValue">120</span></div>
   <div class="hud-label">AMMO</div>
  </div>
 </div>
 <div id="crosshair"></div>
 <div id="message" class="hidden"></div>
 <canvas id="minimap" width="180" height="180"></canvas>
 <div id="gameTopButtons"><button class="smallbtn" id="pauseBtn">إيقاف / إعدادات</button></div>
</div>

<div id="controls" class="hidden">
 <div id="moveStick" class="stick"><div class="knob"></div></div>
 <div id="lookStick" class="stick"><div class="knob"></div></div>
 <button id="fireBtn" class="action">إطلاق</button>
 <button id="aimBtn" class="action">تصويب</button>
 <button id="reloadBtn" class="action">تلقيم</button>
 <button id="jumpBtn" class="action">قفز</button>
 <button id="crouchBtn" class="action">انحناء</button>
 <button id="sprintBtn" class="action">ركض</button>
 <button id="switchBtn" class="action">السلاح</button>
 <button id="grenadeBtn" class="action">قنبلة</button>
 <button id="interactBtn" class="action">تفاعل</button>
</div>

<div id="controllerInfo" class="hidden">
 <div class="status"><i id="connectionDot" class="dot on"></i><b id="connectionText">متصل</b></div>
 <div class="note" id="controllerPlayerLabel">وحدة التحكم</div>
</div>

<section id="pauseScreen" class="screen center hidden">
 <div class="panel">
  <div class="kicker">SYSTEM MENU</div><h2>الإعدادات</h2>
  <div class="settings-grid">
   <label>حساسية التصويب <span id="sensLabel">1.0</span>
    <input id="sensRange" type="range" min="0.4" max="2.2" step="0.1" value="1">
   </label>
   <label>حجم الأزرار <span id="sizeLabel">100%</span>
    <input id="sizeRange" type="range" min="80" max="125" step="5" value="100">
   </label>
   <label>شفافية التحكم <span id="opacityLabel">75%</span>
    <input id="opacityRange" type="range" min="35" max="100" step="5" value="75">
   </label>
   <label>جودة الرسومات
    <select id="qualitySelect" style="width:100%;padding:10px;background:#081015;color:white;border:1px solid var(--line);border-radius:8px">
     <option value="low">منخفضة</option><option value="medium" selected>متوسطة</option><option value="high">عالية</option>
    </select>
   </label>
   <label><input id="invertY" type="checkbox" style="width:auto"> عكس محور التصويب العمودي</label>
   <label><input id="soundToggle" type="checkbox" checked style="width:auto"> تفعيل الصوت</label>
  </div>
  <div class="row" style="margin-top:18px">
   <button id="resumeBtn" class="primary grow">متابعة المباراة</button>
   <button id="backLobbyBtn">العودة للغرفة</button>
  </div>
  <div class="note" style="margin-top:10px">ASAD: FRONTLINE — أسعد المطور</div>
 </div>
</section>

<section id="resultScreen" class="screen center hidden">
 <div class="panel">
  <div class="kicker">MISSION DEBRIEF</div><h2 id="resultTitle">انتهت المباراة</h2>
  <p class="subtitle" id="winnerText"></p>
  <div id="resultsList"></div>
  <div class="row" style="margin-top:16px">
   <button id="replayBtn" class="primary grow">إعادة المباراة</button>
   <button id="resultsLobbyBtn">العودة إلى الغرفة</button>
  </div>
 </div>
 <div class="brand">تطوير <b>أسعد المطور</b></div>
</section>

<div id="toast"></div>

<script src="/socket.io/socket.io.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js"></script>
<script>
(() => {
"use strict";

const $ = id => document.getElementById(id);
const socket = io({transports:["websocket","polling"], reconnection:true, reconnectionAttempts:Infinity});
let role = null, roomId = null, playerSlot = null, roomCodes = null;
let connected = false, inGame = false, matchState = "lobby";
let latestSnapshot = null, lastSnapshotAt = 0, toastTimer = null;
let audioContext = null, renderer = null, scene = null, camera = null;
let localMeshes = new Map(), effects = [], lastFrame = performance.now();
let cameraYaw = 0, cameraPitch = -0.12, localSettings = {
 sensitivity:1, size:100, opacity:75, quality:"medium", invertY:false, sound:true
};
let control = {
 moveX:0, moveZ:0, yawDelta:0, pitchDelta:0, fire:false, aim:false,
 sprint:false, crouch:false, jump:false, reload:false, grenade:false,
 interact:false, switchWeapon:false
};
let sendTimer = 0, lastFireSound = 0, inputSeq = 0, lastInputSend = 0;
let pointerState = new Map();
let localLookPointer = null;

function showScreen(id) {
 ["home","createScreen","roomScreen","controllerScreen"].forEach(x => $(x).classList.add("hidden"));
 if (id) $(id).classList.remove("hidden");
}
function toast(text, bad=false) {
 const el=$("toast"); el.textContent=text; el.style.display="block";
 el.style.borderColor=bad?"var(--red)":"var(--lime)";
 clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.style.display="none",2600);
}
function errorText(id,text) { $(id).textContent=text || ""; }
function emitAck(event,data,callback) {
 socket.timeout(7000).emit(event,data,(err,response)=>{
  if(err) { callback({ok:false,error:"تعذر الوصول إلى السيرفر أو انتهت مهلة الاتصال"}); return; }
  callback(response || {ok:false,error:"استجابة غير صالحة من السيرفر"});
 });
}
function setConnected(v) {
 connected=v;
 $("connectionDot").className="dot "+(v?"on":"off");
 $("connectionText").textContent=v?"متصل بالخادم":"انقطع الاتصال";
}
socket.on("connect",()=>{
 setConnected(true);
 if(role==="host" && roomId) {
  // لا تُنشأ هوية جديدة تلقائياً بعد انقطاع المقبس.
  // يجب على المضيف إعادة إنشاء الغرفة إذا فُقدت جلسة الخادم.
  toast("تم الاتصال بالخادم");
 }
});
socket.on("disconnect",()=> {
 setConnected(false);
 control.fire=false; control.moveX=0; control.moveZ=0;
 toast("انقطع الاتصال. توقفت الأوامر المستمرة.",true);
});
socket.on("connect_error",()=>setConnected(false));
socket.on("server_error",d=>toast(d.error || "حدث خطأ",true));

$("hostEntry").onclick=()=>showScreen("createScreen");
$("controllerEntry").onclick=()=>showScreen("controllerScreen");
$("backHome1").onclick=()=>showScreen("home");
$("backHome2").onclick=()=>showScreen("home");

$("createRoomBtn").onclick=()=>{
 errorText("createError","");
 if(!socket.connected){errorText("createError","السيرفر غير متاح. تحقق من الإنترنت ثم أعد المحاولة.");return;}
 $("createRoomBtn").disabled=true;
 emitAck("create_room",{
  name:$("roomName").value,
  player_name:$("playerName").value
 },res=>{
  $("createRoomBtn").disabled=false;
  if(!res.ok){errorText("createError",res.error);return;}
  role="host";roomId=res.room.id;playerSlot=0;roomCodes=res.codes;
  renderRoom(res.room);showScreen("roomScreen");
  toast("تم إنشاء الغرفة على الخادم");
 });
};

function renderRoom(data) {
 $("roomTitle").textContent=data.name;
 $("roomId").textContent=data.id;
 $("roomCount").textContent=data.players.filter(p=>p.occupied).length+" / 3";
 if(roomCodes){
  $("hostToken").textContent=roomCodes.host;
  $("controllerToken1").textContent=roomCodes.controller1;
  $("controllerToken2").textContent=roomCodes.controller2;
 }
 $("playersList").innerHTML="";
 data.players.forEach(p=>{
  const row=document.createElement("div");row.className="player-row";
  const left=document.createElement("div");
  const name=document.createElement("b");name.textContent=p.name;
  const sub=document.createElement("div");sub.className="note";
  sub.textContent=p.occupied?(p.connected?"متصل بالخادم":"انقطع الاتصال"):"بانتظار الاتصال";
  left.append(name,sub);
  const right=document.createElement("span");
  right.className="status";
  const dot=document.createElement("i");dot.className="dot "+(p.connected?"on":p.occupied?"off":"");
  const label=document.createElement("span");label.textContent=p.connected?"متصل":p.occupied?"منقطع":"فارغ";
  right.append(dot,label);row.append(left,right);$("playersList").append(row);
 });
}
socket.on("room_status",data=>{
 if(data.id===roomId && role==="host") renderRoom(data);
});

document.querySelectorAll("[data-copy]").forEach(btn=>{
 btn.onclick=async()=>{
  const value=$(btn.dataset.copy).textContent;
  try {await navigator.clipboard.writeText(value);toast("تم نسخ الرمز");}
  catch(e){const ta=document.createElement("textarea");ta.value=value;document.body.append(ta);ta.select();document.execCommand("copy");ta.remove();toast("تم نسخ الرمز");}
 };
});

$("startBtn").onclick=()=>{
 if(role!=="host")return;
 emitAck("start_match",{room_id:roomId},res=>{
  if(!res.ok){errorText("roomError",res.error);return;}
  errorText("roomError","بدأت المباراة. اضغط «الدخول إلى ساحة المعركة» على هذا الهاتف.");
  toast("بدأ العد التنازلي");
 });
};
$("rotateTokensBtn").onclick=()=>{
 if(!confirm("سيتم إبطال الرموز الحالية. هل تريد المتابعة؟"))return;
 emitAck("rotate_codes",{room_id:roomId},res=>{
  if(!res.ok){errorText("roomError",res.error);return;}
  roomCodes=res.codes;renderRoom(res.room);toast("تم تجديد الرموز");
 });
};
$("cancelRoomBtn").onclick=()=>{
 if(!confirm("هل تريد إلغاء الغرفة وفصل وحدات التحكم؟"))return;
 emitAck("cancel_room",{room_id:roomId},res=>{
  if(!res.ok){errorText("roomError",res.error);return;}
  leaveGame();role=null;roomId=null;roomCodes=null;showScreen("home");
 });
};
$("enterGameBtn").onclick=()=>enterGame();

$("joinBtn").onclick=()=>{
 errorText("joinError","");
 if(!socket.connected){errorText("joinError","السيرفر غير متاح حالياً.");return;}
 const token=$("joinToken").value.trim().toUpperCase();
 if(!token){errorText("joinError","أدخل رمز الاتصال.");return;}
 $("joinBtn").disabled=true;
 emitAck("join_controller",{
  code:token,name:$("controllerName").value
 },res=>{
  $("joinBtn").disabled=false;
  if(!res.ok){errorText("joinError",res.error);$("joinDot").className="dot off";$("joinStatus").textContent="فشل الاتصال";return;}
  role="controller";roomId=res.room.id;playerSlot=res.slot;
  $("joinDot").className="dot on";$("joinStatus").textContent="تم الاتصال بنجاح";
  $("controllerPlayerLabel").textContent="وحدة التحكم "+(res.slot);
  showController();toast("تم الاتصال بالغرفة");
 });
};

function showController() {
 ["home","createScreen","roomScreen","controllerScreen"].forEach(x=>$(x).classList.add("hidden"));
 $("hud").classList.add("hidden");
 $("controls").classList.remove("hidden");
 $("controllerInfo").classList.remove("hidden");
 $("pauseScreen").classList.add("hidden");
 $("resultScreen").classList.add("hidden");
 inGame=true;
 applySettings();
}

function enterGame() {
 if(role!=="host" || !roomId)return;
 emitAck("enter_game",{room_id:roomId},res=>{
  if(!res.ok){toast(res.error,true);return;}
  ["home","createScreen","roomScreen","controllerScreen"].forEach(x=>$(x).classList.add("hidden"));
  $("hud").classList.remove("hidden");$("controls").classList.remove("hidden");
  $("controllerInfo").classList.add("hidden");
  $("pauseScreen").classList.add("hidden");$("resultScreen").classList.add("hidden");
  inGame=true;applySettings();ensureRenderer();toast("تم دخول ساحة المعركة");
 });
}
function leaveGame() {
 control.fire=false;control.moveX=0;control.moveZ=0;
 $("hud").classList.add("hidden");$("controls").classList.add("hidden");
 $("controllerInfo").classList.add("hidden");
 $("pauseScreen").classList.add("hidden");$("resultScreen").classList.add("hidden");
 inGame=false;
}

$("pauseBtn").onclick=()=>{if(role==="host"){$("pauseScreen").classList.remove("hidden");control.fire=false;}};
$("resumeBtn").onclick=()=>$("pauseScreen").classList.add("hidden");
$("backLobbyBtn").onclick=()=>{
 if(role!=="host")return;
 leaveGame();showScreen("roomScreen");
};
$("backLobbyBtn").title="العودة إلى غرفة المضيف";

$("replayBtn").onclick=()=>{
 if(role!=="host")return;
 emitAck("start_match",{room_id:roomId},res=>{
  if(!res.ok){toast(res.error,true);return;}
  $("resultScreen").classList.add("hidden");$("hud").classList.remove("hidden");
  $("controls").classList.remove("hidden");inGame=true;toast("بدأت مباراة جديدة");
 });
};
$("resultsLobbyBtn").onclick=()=>{
 if(role==="host"){leaveGame();showScreen("roomScreen");}
 else {$("resultScreen").classList.add("hidden");showController();}
};

socket.on("match_countdown",d=>toast("بدء المباراة خلال "+d.seconds+" ثوانٍ"));
socket.on("match_over",d=>{
 control.fire=false;control.moveX=0;control.moveZ=0;
 $("hud").classList.add("hidden");$("controls").classList.add("hidden");
 $("pauseScreen").classList.add("hidden");$("resultScreen").classList.remove("hidden");
 inGame=false;
 $("winnerText").textContent=d.winner?"الفائز: "+d.winner.name+" — "+d.winner.score+" نقطة":"انتهت المباراة";
 $("resultsList").innerHTML="";
 (d.players||[]).forEach(p=>{
  const row=document.createElement("div");row.className="player-row";
  const a=document.createElement("b");a.textContent=p.name;
  const b=document.createElement("span");b.textContent=p.score+" نقطة · "+p.kills+" إقصاء · "+p.deaths+" خسارة";
  row.append(a,b);$("resultsList").append(row);
 });
});
socket.on("match_started",()=>toast("بدأت المعركة"));
socket.on("respawn",d=>{if(d.slot===playerSlot)toast("تمت إعادة الظهور");});
socket.on("elimination",d=>{
 if(d.killer===playerSlot)toast("تم إقصاء الخصم");
 else if(d.victim===playerSlot)toast("تم إقصاؤك",true);
});
socket.on("hit_confirm",d=>{
 if(d.attacker===playerSlot)toast("إصابة مؤكدة · "+d.damage);
 if(d.target===playerSlot)screenFlash();
});
socket.on("shot",d=>{
 spawnTracer(d);
 if(d.slot!==playerSlot)playTone(110,0.045,"sawtooth",0.04);
 else playTone(80,0.055,"square",0.035);
});
socket.on("explosion",d=>spawnExplosion(d.x,d.z));
socket.on("snapshot",d=>{
 latestSnapshot=d;lastSnapshotAt=performance.now();matchState=d.state;
 if(inGame)updateHud(d);
});
socket.on("room_status",d=>{
 if(role==="controller" && d.id===roomId && d.state==="playing") {
  // لا نبدّل الشاشة قسراً؛ وحدة التحكم تبقى جاهزة.
 }
});

function screenFlash(){
 const el=document.createElement("div");
 el.style.cssText="position:fixed;inset:0;z-index:7;pointer-events:none;background:#f44;opacity:.25";
 document.body.append(el);setTimeout(()=>el.remove(),100);
}
function updateHud(d) {
 $("timeValue").textContent=String(Math.floor(d.remaining/60)).padStart(2,"0")+":"+String(d.remaining%60).padStart(2,"0");
 $("playerCountHud").textContent="PLAYERS "+d.players.filter(p=>p.connected).length+"/3";
 const me=d.players.find(p=>p.slot===playerSlot);
 if(me){
  $("healthValue").textContent=me.health;
  $("healthFill").style.width=me.health+"%";
  $("ammoValue").textContent=me.ammo;
  $("reserveValue").textContent=me.reserve;
  $("weaponName").textContent=me.weapon==="smg"?"SMG":"RIFLE";
 }
 drawMinimap(d);
}

function drawMinimap(d) {
 const c=$("minimap"),ctx=c.getContext("2d");
 ctx.clearRect(0,0,c.width,c.height);
 ctx.fillStyle="#0b191c";ctx.fillRect(0,0,c.width,c.height);
 const scale=1.8,center=90;
 ctx.strokeStyle="#344c4b";ctx.lineWidth=2;
 for(let i=0;i<OBSTACLE_DATA.length;i++){
  const o=OBSTACLE_DATA[i];ctx.fillStyle="#425451";
  ctx.fillRect(center+o[0]*scale-o[2]*scale,center+o[1]*scale-o[3]*scale,o[2]*2*scale,o[3]*2*scale);
 }
 ctx.beginPath();ctx.arc(center,center,6,0,Math.PI*2);ctx.strokeStyle="#c7f36b";ctx.stroke();
 d.players.forEach(p=>{
  if(!p.connected)return;
  ctx.beginPath();ctx.arc(center+p.x*scale,center+p.z*scale,4.5,0,Math.PI*2);
  ctx.fillStyle=p.slot===playerSlot?"#c7f36b":["#65d8ce","#f2c96c","#e77b7b"][p.slot];ctx.fill();
 });
}
const OBSTACLE_DATA=[
 [-8,-7,3.5,1], [8,-8,3,1],[-13,3,1,4],[13,4,1,4],
 [-5,12,3,1],[6,12,3.2,1],[0,-16,5,1],[-19,-12,1,3],
 [19,14,1,4],[0,20,7,1],[-22,0,1,5],[22,-3,1,5],[-3,2,1,2],[4,-2,1,2]
];

// ============================================================
// Three.js: خريطة مولدة برمجياً ونماذج خفيفة
// ============================================================

function ensureRenderer() {
 if(renderer)return;
 try {
  renderer=new THREE.WebGLRenderer({canvas:$("world"),antialias:localSettings.quality!=="low",alpha:false,powerPreference:"high-performance"});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,localSettings.quality==="high"?1.6:1.15));
  renderer.setSize(innerWidth,innerHeight);
  renderer.shadowMap.enabled=localSettings.quality==="high";
  renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  scene=new THREE.Scene();
  scene.background=new THREE.Color(0x101b20);
  scene.fog=new THREE.FogExp2(0x101b20,0.012);
  camera=new THREE.PerspectiveCamera(72,innerWidth/innerHeight,0.1,180);
  camera.position.set(0,4,8);
  buildWorld();
  animate(performance.now());
 } catch(err) {
  toast("تعذر تشغيل WebGL على هذا الجهاز",true);
 }
}

function mat(color,roughness=0.9,metalness=0.05) {
 return new THREE.MeshStandardMaterial({color,roughness,metalness});
}
function addBox(x,y,z,sx,sy,sz,material,cast=true) {
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(sx,sy,sz),material);
 mesh.position.set(x,y,z);mesh.castShadow=cast;mesh.receiveShadow=true;scene.add(mesh);return mesh;
}
function buildWorld() {
 const hemi=new THREE.HemisphereLight(0xa9d5cf,0x202a25,2.0);scene.add(hemi);
 const sun=new THREE.DirectionalLight(0xffe3b4,2.1);sun.position.set(-18,30,12);
 sun.castShadow=localSettings.quality==="high";sun.shadow.mapSize.set(1024,1024);scene.add(sun);
 const ground=addBox(0,-0.3,0,100,0.6,100,mat(0x39453c),false);
 const grid=new THREE.GridHelper(90,45,0x64756a,0x4c5c51);grid.position.y=0.015;scene.add(grid);

 // ممرات ومناطق ترابية بألوان مختلفة.
 addBox(0,0.015,0,5,0.03,100,mat(0x51544a),false);
 addBox(0,0.02,0,100,0.03,4,mat(0x51544a),false);
 addBox(0,0.03,0,5,0.03,5,mat(0x6b7448),false);

 OBSTACLE_DATA.forEach((o,i)=>{
  const colors=[0x515d56,0x454f4b,0x59635a,0x404c4a];
  const h=[2.7,2.4,3.2,3.0][i%4];
  addBox(o[0],h/2,o[1],o[2]*2,h,o[3]*2,mat(colors[i%colors.length]),true);
  if(i%3===0){
   addBox(o[0],h+0.08,o[1],o[2]*1.55,0.16,o[3]*1.55,mat(0x77775c),false);
  }
 });
 // حاويات عسكرية منخفضة.
 for(let i=0;i<7;i++){
  const x=-24+i*8;
  if(Math.abs(x)<8)continue;
  addBox(x,0.8,7,3.2,1.6,1.4,mat(i%2?0x394b48:0x59604b));
  for(let j=0;j<4;j++)addBox(x-1.1+j*.7,1.65,7,0.08,.05,1.42,mat(0x7c8b76),false);
 }
 // نقطة السيطرة: حلقة مرئية.
 const ring=new THREE.Mesh(new THREE.TorusGeometry(3,0.08,8,48),new THREE.MeshBasicMaterial({color:0xc7f36b}));
 ring.rotation.x=Math.PI/2;ring.position.set(0,0.08,0);scene.add(ring);
 const pole=addBox(0,1.4,0,.12,2.8,.12,mat(0xb3c4ad),false);
 const flag=addBox(0.55,2.25,0,1.1,.55,.06,mat(0xc7f36b),false);
 // صخور زخرفية ثابتة.
 for(let i=0;i<22;i++){
  const x=((i*17)%79)-39,z=((i*29)%79)-39;
  if(Math.abs(x)<8&&Math.abs(z)<8)continue;
  const rock=new THREE.Mesh(new THREE.DodecahedronGeometry(.45+(i%4)*.16,0),mat(i%2?0x515b51:0x3d4844));
  rock.position.set(x,.35,z);rock.scale.y=.65;rock.castShadow=true;scene.add(rock);
 }
 // سماء صناعية وأعمدة ضوء بعيدة.
 const horizon=addBox(0,2,-49,100,4,1,mat(0x243237),false);
 for(let i=0;i<16;i++){
  const x=-38+i*5;
  addBox(x,2.5,-35-(i%3)*2,.28,5,.28,mat(0x53645a),false);
 }
}

function createSoldier(slot) {
 const group=new THREE.Group();
 const color=[0x8da78d,0x6eaaa4,0xbba16a][slot]||0x8da78d;
 const bodyMat=mat(color), dark=mat(0x202a2c), armor=mat(0x45554b), skin=mat(0xc4a889);
 const torso=new THREE.Mesh(new THREE.BoxGeometry(.72,.8,.4),bodyMat);torso.position.y=1.12;torso.castShadow=true;group.add(torso);
 const vest=new THREE.Mesh(new THREE.BoxGeometry(.76,.48,.43),armor);vest.position.set(0,1.16,-.02);group.add(vest);
 const head=new THREE.Mesh(new THREE.SphereGeometry(.22,10,8),skin);head.position.y=1.72;head.castShadow=true;group.add(head);
 const helmet=new THREE.Mesh(new THREE.SphereGeometry(.245,10,6,0,Math.PI*2,0,Math.PI/2),dark);helmet.position.y=1.82;group.add(helmet);
 for(const side of [-1,1]){
  const leg=new THREE.Mesh(new THREE.BoxGeometry(.23,.65,.25),dark);leg.position.set(side*.2,.38,0);leg.castShadow=true;group.add(leg);
  const arm=new THREE.Mesh(new THREE.BoxGeometry(.2,.62,.23),bodyMat);arm.position.set(side*.46,1.12,-.02);group.add(arm);
 }
 // سلاح مرئي في الأمام.
 const gun=new THREE.Group();
 const barrel=new THREE.Mesh(new THREE.BoxGeometry(.13,.13,.85),dark);barrel.position.z=-.47;gun.add(barrel);
 const grip=new THREE.Mesh(new THREE.BoxGeometry(.12,.24,.16),dark);grip.position.set(0,-.15,-.2);gun.add(grip);
 gun.position.set(.34,1.18,-.25);group.add(gun);
 group.userData.gun=gun;group.userData.body=torso;
 scene.add(group);localMeshes.set(slot,group);return group;
}

function syncMeshes(d,dt) {
 const seen=new Set();
 d.players.forEach(p=>{
  if(!p.connected){const old=localMeshes.get(p.slot);if(old){scene.remove(old);localMeshes.delete(p.slot);}return;}
  seen.add(p.slot);
  let mesh=localMeshes.get(p.slot);
  if(!mesh)mesh=createSoldier(p.slot);
  mesh.visible=p.alive;
  const target=new THREE.Vector3(p.x,p.y,p.z);
  mesh.position.lerp(target,Math.min(1,dt*12));
  mesh.rotation.y=p.yaw;
  if(mesh.userData.body)mesh.userData.body.scale.y=p.crouch?.72:1;
  if(mesh.userData.gun)mesh.userData.gun.rotation.x=-p.pitch;
 });
 for(const [slot,mesh] of localMeshes){
  if(!seen.has(slot)){scene.remove(mesh);localMeshes.delete(slot);}
 }
 const me=d.players.find(p=>p.slot===playerSlot);
 if(me){
  const eyeY=me.y+(me.crouch?1.2:1.58);
  cameraYaw=me.yaw;
  const desired=new THREE.Vector3(
   me.x+Math.sin(cameraYaw)*4.2,
   eyeY+2.1-cameraPitch*2,
   me.z+Math.cos(cameraYaw)*4.2
  );
  camera.position.lerp(desired,Math.min(1,dt*8));
  const target=new THREE.Vector3(
   me.x-Math.sin(cameraYaw)*5,
   eyeY+cameraPitch*7,
   me.z-Math.cos(cameraYaw)*5
  );
  camera.lookAt(target);
 }
}

function spawnTracer(d) {
 if(!scene)return;
 const start=new THREE.Vector3(d.x,d.y,d.z);
 const end=new THREE.Vector3(d.x+d.dx*d.distance,d.y+d.dy*d.distance,d.z+d.dz*d.distance);
 const geometry=new THREE.BufferGeometry().setFromPoints([start,end]);
 const line=new THREE.Line(geometry,new THREE.LineBasicMaterial({color:d.hit!==null?0xffb66d:0xd9e6c7,transparent:true,opacity:.9}));
 scene.add(line);effects.push({obj:line,until:performance.now()+110});
 const flash=new THREE.Mesh(new THREE.SphereGeometry(.09,6,5),new THREE.MeshBasicMaterial({color:0xffd38c}));
 flash.position.copy(start);scene.add(flash);effects.push({obj:flash,until:performance.now()+75});
}
function spawnExplosion(x,z) {
 if(!scene)return;
 const mesh=new THREE.Mesh(new THREE.SphereGeometry(.5,10,8),new THREE.MeshBasicMaterial({color:0xff7b39,transparent:true,opacity:.75}));
 mesh.position.set(x,.8,z);scene.add(mesh);effects.push({obj:mesh,until:performance.now()+450,explode:true});
 playTone(65,.18,"sawtooth",.08);
}
function animate(ts) {
 requestAnimationFrame(animate);
 if(!renderer||!scene||!camera)return;
 const dt=Math.min(.05,(ts-lastFrame)/1000);lastFrame=ts;
 if(inGame&&latestSnapshot)syncMeshes(latestSnapshot,dt);
 for(let i=effects.length-1;i>=0;i--){
  const e=effects[i];
  if(e.explode){e.obj.scale.multiplyScalar(1+dt*5);e.obj.material.opacity=Math.max(0,e.obj.material.opacity-dt*1.8);}
  if(ts>=e.until){scene.remove(e.obj);e.obj.geometry?.dispose();e.obj.material?.dispose();effects.splice(i,1);}
 }
 renderer.render(scene,camera);
}
window.addEventListener("resize",()=>{
 if(renderer&&camera){camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);}
});
document.addEventListener("visibilitychange",()=>{
 if(document.hidden){control.fire=false;control.moveX=0;control.moveZ=0;sendInput(true);}
});

// ============================================================
// تحكم لمس متعدد: عصا الحركة والتصويب والأزرار المستمرة
// ============================================================

function bindStick(id,kind) {
 const el=$(id),knob=el.querySelector(".knob");
 let activeId=null,centerX=0,centerY=0,radius=45;
 function begin(e) {
  if(activeId!==null)return;
  e.preventDefault();activeId=e.pointerId;
  el.setPointerCapture?.(e.pointerId);
  const r=el.getBoundingClientRect();centerX=r.left+r.width/2;centerY=r.top+r.height/2;radius=r.width*.34;
  update(e);
 }
 function update(e) {
  if(e.pointerId!==activeId)return;
  const dx=e.clientX-centerX,dy=e.clientY-centerY;
  const length=Math.hypot(dx,dy),scale=length>radius?radius/length:1;
  const nx=dx*scale,ny=dy*scale;
  knob.style.left=`calc(50% + ${nx}px)`;knob.style.top=`calc(50% + ${ny}px)`;
  if(kind==="move"){control.moveX=nx/radius;control.moveZ=-ny/radius;}
  else {
   control.yawDelta=dx/radius*0.045*localSettings.sensitivity;
   control.pitchDelta=(localSettings.invertY?1:-1)*(-dy/radius)*0.035*localSettings.sensitivity;
  }
 }
 function end(e) {
  if(e.pointerId!==activeId)return;
  activeId=null;knob.style.left="50%";knob.style.top="50%";
  if(kind==="move"){control.moveX=0;control.moveZ=0;}
  else {control.yawDelta=0;control.pitchDelta=0;}
 }
 el.addEventListener("pointerdown",begin);
 el.addEventListener("pointermove",update);
 el.addEventListener("pointerup",end);
 el.addEventListener("pointercancel",end);
 el.addEventListener("lostpointercapture",end);
}
bindStick("moveStick","move");
bindStick("lookStick","look");

function holdButton(id,onStart,onEnd=()=>{}) {
 const el=$(id);let pointers=new Set();
 el.addEventListener("pointerdown",e=>{
  e.preventDefault();pointers.add(e.pointerId);el.setPointerCapture?.(e.pointerId);onStart();
 });
 const end=e=>{if(!pointers.has(e.pointerId))return;pointers.delete(e.pointerId);if(!pointers.size)onEnd();};
 el.addEventListener("pointerup",end);el.addEventListener("pointercancel",end);
 el.addEventListener("lostpointercapture",end);
}
holdButton("fireBtn",()=>control.fire=true,()=>control.fire=false);
holdButton("aimBtn",()=>control.aim=true,()=>control.aim=false);
holdButton("sprintBtn",()=>control.sprint=true,()=>control.sprint=false);
holdButton("crouchBtn",()=>control.crouch=true,()=>control.crouch=false);
holdButton("jumpBtn",()=>{control.jump=true;sendInput(true);control.jump=false;});
holdButton("reloadBtn",()=>{control.reload=true;sendInput(true);control.reload=false;});
holdButton("grenadeBtn",()=>{control.grenade=true;sendInput(true);control.grenade=false;});
holdButton("interactBtn",()=>{control.interact=true;sendInput(true);control.interact=false;});
holdButton("switchBtn",()=>{control.switchWeapon=true;sendInput(true);control.switchWeapon=false;});

function sendInput(force=false) {
 if(!socket.connected||!roomId||!role)return;
 const t=performance.now();
 if(!force&&t-lastInputSend<45)return;
 lastInputSend=t;
 const payload={
  room_id:roomId,seq:++inputSeq,
  move_x:control.moveX,move_z:control.moveZ,
  yaw_delta:control.yawDelta,pitch_delta:control.pitchDelta,
  fire:control.fire,aim:control.aim,sprint:control.sprint,crouch:control.crouch,
  jump:control.jump,reload:control.reload,grenade:control.grenade,
  interact:control.interact,switch_weapon:control.switchWeapon
 };
 socket.emit("input",payload);
 // استهلاك نبضات الإجراءات مرة واحدة فقط.
 control.yawDelta=0;control.pitchDelta=0;
 control.jump=false;control.reload=false;control.grenade=false;
 control.interact=false;control.switchWeapon=false;
}
setInterval(()=>{if(inGame)sendInput();},50);
window.addEventListener("pointerup",()=>{if(!inGame)return;sendInput(true);});
window.addEventListener("blur",()=>{
 control.fire=false;control.moveX=0;control.moveZ=0;
 control.aim=false;control.sprint=false;control.crouch=false;sendInput(true);
});
window.addEventListener("pagehide",()=>{
 control.fire=false;control.moveX=0;control.moveZ=0;sendInput(true);
});

function loadSettings() {
 try {
  const s=JSON.parse(localStorage.getItem("asadFrontlineSettings")||"{}");
  localSettings={...localSettings,...s};
 } catch(e){}
 $("sensRange").value=localSettings.sensitivity;
 $("sizeRange").value=localSettings.size;
 $("opacityRange").value=localSettings.opacity;
 $("qualitySelect").value=localSettings.quality;
 $("invertY").checked=localSettings.invertY;
 $("soundToggle").checked=localSettings.sound;
 updateSettingLabels();
}
function saveSettings() {
 try{localStorage.setItem("asadFrontlineSettings",JSON.stringify(localSettings));}catch(e){}
 applySettings();
}
function updateSettingLabels() {
 $("sensLabel").textContent=Number(localSettings.sensitivity).toFixed(1);
 $("sizeLabel").textContent=localSettings.size+"%";
 $("opacityLabel").textContent=localSettings.opacity+"%";
}
function applySettings() {
 document.querySelectorAll(".action,.stick").forEach(el=>{
  el.style.opacity=localSettings.opacity/100;
  el.style.scale=String(localSettings.size/100);
 });
 if(renderer){
  renderer.setPixelRatio(Math.min(devicePixelRatio||1,localSettings.quality==="high"?1.6:localSettings.quality==="medium"?1.15:.8));
  renderer.shadowMap.enabled=localSettings.quality==="high";
 }
}
["sensRange","sizeRange","opacityRange","qualitySelect","invertY","soundToggle"].forEach(id=>{
 $(id).addEventListener("input",()=>{
  localSettings.sensitivity=+$("sensRange").value;
  localSettings.size=+$("sizeRange").value;
  localSettings.opacity=+$("opacityRange").value;
  localSettings.quality=$("qualitySelect").value;
  localSettings.invertY=$("invertY").checked;
  localSettings.sound=$("soundToggle").checked;
  updateSettingLabels();saveSettings();
 });
});
loadSettings();

function playTone(freq,duration,type="sine",volume=.05) {
 if(!localSettings.sound)return;
 try {
  audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();
  if(audioContext.state==="suspended")audioContext.resume();
  const osc=audioContext.createOscillator(),gain=audioContext.createGain();
  osc.type=type;osc.frequency.value=freq;
  gain.gain.setValueAtTime(volume,audioContext.currentTime);
  gain.gain.exponentialRampToValueAtTime(.001,audioContext.currentTime+duration);
  osc.connect(gain);gain.connect(audioContext.destination);osc.start();osc.stop(audioContext.currentTime+duration);
 }catch(e){}
}
document.body.addEventListener("pointerdown",()=>{if(localSettings.sound)playTone(320,.025,"sine",.001);},{once:true});

socket.on("connect",()=>{if(role==="controller"&&roomId){/* لا تُعاد المصادقة تلقائياً برمز مستخدم */}});
window.addEventListener("contextmenu",e=>e.preventDefault());
document.addEventListener("selectstart",e=>e.preventDefault());

})();
</script>
</body>
</html>
"""


# ============================================================
# 4. مسارات HTTP
# ============================================================

@app.get("/")
def index():
    return render_template_string(PAGE)


@app.get("/health")
def health():
    with world_lock:
        return jsonify({
            "status": "ok",
            "game": GAME_NAME,
            "rooms_in_memory": len(rooms),
            "time": int(now()),
        }), 200


@app.get("/api/status")
def api_status():
    with world_lock:
        return jsonify({
            "game": GAME_NAME,
            "developer": DEVELOPER,
            "active_rooms": len(rooms),
            "transport": "Socket.IO",
        })


# ============================================================
# 5. أحداث Socket.IO وصلاحيات الغرف
# ============================================================

@socketio.on("connect")
def on_connect(auth=None):
    start_engine_once()
    emit("server_ready", {"ok": True, "game": GAME_NAME})


@socketio.on("disconnect")
def on_disconnect(reason=None):
    with world_lock:
        info = sid_index.pop(request.sid, None)
        rate_limits.pop((request.sid, "input"), None)
        if not info:
            return
        room_id, slot = info
        room = rooms.get(room_id)
        if not room:
            return
        p = room["players"].get(request.sid)
        if p:
            p["connected"] = False
            p["sid"] = None
            p["fire"] = False
            p["move_x"] = 0.0
            p["move_z"] = 0.0
            p["sprint"] = False
            p["aim"] = False
            p["last_input"] = 0.0
        # يحتفظ المقعد بهويته حتى انتهاء الغرفة؛ لا يُسند تلقائياً لجهاز غريب.
        room["last_active"] = now()
        update_room_status(room)


def fail(message):
    return {"ok": False, "error": message}


@socketio.on("create_room")
def on_create_room(data):
    data = data if isinstance(data, dict) else {}
    with world_lock:
        if request.sid in sid_index:
            return fail("هذا الاتصال مرتبط بغرفة بالفعل.")
        name = clean_name(data.get("name"), "ASAD_BATTLE")
        player_name = clean_name(data.get("player_name"), "ASAD")
        try:
            room = new_room(name, request.sid)
        except Exception:
            return fail("تعذر إنشاء الغرفة. حاول مرة أخرى.")
        p = room["players"][request.sid]
        p["name"] = player_name
        join_room(room["id"])
        room["last_active"] = now()
        update_room_status(room)
        return {
            "ok": True,
            "room": public_room(room),
            "codes": dict(room["codes"]),
        }


@socketio.on("join_controller")
def on_join_controller(data):
    data = data if isinstance(data, dict) else {}
    code = str(data.get("code", "")).strip().upper()
    name = clean_name(data.get("name"), "SOLDIER")
    if not re.fullmatch(r"[A-HJ-NP-Z2-9]{8}", code):
        return fail("صيغة الرمز غير صحيحة.")
    with world_lock:
        if request.sid in sid_index:
            return fail("هذا الاتصال مرتبط بغرفة بالفعل.")
        found = None
        slot = None
        for room in rooms.values():
            for role_name, expected in room["codes"].items():
                if secrets.compare_digest(code, expected):
                    found = room
                    slot = {"host": 0, "controller1": 1, "controller2": 2}[role_name]
                    break
            if found:
                break

        if not found:
            return fail("الرمز غير صحيح أو انتهت صلاحيته أو الغرفة غير موجودة.")
        room = found
        if now() - room["created"] > TOKEN_TTL:
            return fail("انتهت صلاحية الرمز. اطلب من المضيف تجديد الرموز.")
        if slot == 0:
            return fail("هذا رمز الجهاز الأساسي، وليس رمز وحدة تحكم.")
        if room["state"] in ("results", "closed"):
            return fail("الغرفة لا تقبل اتصالات جديدة في هذه الحالة.")
        if slot in room["used_codes"]:
            return fail("وحدة التحكم مستخدمة بالفعل. اطلب من المضيف تجديد الرموز.")
        if room["slots"][slot] is not None:
            return fail("مقعد وحدة التحكم محجوز بالفعل.")
        if sum(1 for s in room["slots"] if s is not None) >= MAX_PLAYERS:
            return fail("الغرفة ممتلئة. الحد الأقصى ثلاثة أجهزة.")

        p = fresh_player(slot, name, request.sid)
        room["slots"][slot] = request.sid
        room["players"][request.sid] = p
        room["used_codes"].add(slot)
        sid_index[request.sid] = (room["id"], slot)
        room["last_active"] = now()
        join_room(room["id"])
        update_room_status(room)
        return {
            "ok": True,
            "room": public_room(room),
            "slot": slot,
            "message": "تم الاتصال بنجاح",
        }


@socketio.on("start_match")
def on_start_match(data):
    data = data if isinstance(data, dict) else {}
    with world_lock:
        info = sid_index.get(request.sid)
        if not info or info[1] != 0:
            return fail("بدء المباراة متاح للمضيف فقط.")
        room = rooms.get(info[0])
        if not room or room["host_sid"] != request.sid:
            return fail("صلاحية المضيف غير صالحة.")
        ok, message = start_match(room)
        if not ok:
            return fail(message)
        room_emit(room, "match_started", {"ok": True})
        return {"ok": True, "message": message}


@socketio.on("enter_game")
def on_enter_game(data):
    data = data if isinstance(data, dict) else {}
    with world_lock:
        info = sid_index.get(request.sid)
        if not info or info[1] != 0:
            return fail("هذه العملية متاحة للمضيف فقط.")
        room = rooms.get(info[0])
        if not room or room["host_sid"] != request.sid:
            return fail("الغرفة غير موجودة أو انتهت الجلسة.")
        return {"ok": True, "room": public_room(room)}


@socketio.on("rotate_codes")
def on_rotate_codes(data):
    with world_lock:
        info = sid_index.get(request.sid)
        if not info or info[1] != 0:
            return fail("تجديد الرموز متاح للمضيف فقط.")
        room = rooms.get(info[0])
        if not room or room["host_sid"] != request.sid:
            return fail("صلاحية المضيف غير صالحة.")

        # فصل وحدات التحكم القديمة وإبطال رموزها.
        for slot in (1, 2):
            old_sid = room["slots"][slot]
            if old_sid:
                old = room["players"].get(old_sid)
                if old:
                    old["connected"] = False
                    old["sid"] = None
                sid_index.pop(old_sid, None)
                room["slots"][slot] = None
        room["codes"] = {
            "host": make_unique_code(),
            "controller1": make_unique_code(),
            "controller2": make_unique_code(),
        }
        room["used_codes"].clear()
        room["last_active"] = now()
        update_room_status(room)
        return {
            "ok": True,
            "codes": dict(room["codes"]),
            "room": public_room(room),
        }


@socketio.on("cancel_room")
def on_cancel_room(data):
    with world_lock:
        info = sid_index.get(request.sid)
        if not info or info[1] != 0:
            return fail("إلغاء الغرفة متاح للمضيف فقط.")
        room = rooms.get(info[0])
        if not room or room["host_sid"] != request.sid:
            return fail("صلاحية المضيف غير صالحة.")
        room["state"] = "closed"
        room_emit(room, "server_error", {"error": "ألغى المضيف الغرفة."})
        for sid in list(room["players"].keys()):
            sid_index.pop(sid, None)
        rooms.pop(room["id"], None)
        return {"ok": True}


@socketio.on("input")
def on_input(data):
    if not allowed_rate(request.sid, "input", 35, 1.0):
        return
    if not isinstance(data, dict):
        return

    with world_lock:
        info = sid_index.get(request.sid)
        if not info:
            return
        room_id, slot = info
        room = rooms.get(room_id)
        if not room or room["state"] != "playing":
            return
        p = room["players"].get(request.sid)
        if not p or p["slot"] != slot or room["slots"][slot] != request.sid:
            return
        if not p["connected"]:
            return

        # الخادم يحدد اللاعب من جلسة Socket.IO، لا من بيانات المتصفح.
        if data.get("room_id") != room_id:
            return

        try:
            seq = int(data.get("seq", 0))
        except (TypeError, ValueError):
            return
        if seq <= 0:
            return

        def number(key, lo, hi, default=0.0):
            try:
                value = float(data.get(key, default))
                if not math.isfinite(value):
                    return default
                return max(lo, min(hi, value))
            except (TypeError, ValueError):
                return default

        p["move_x"] = number("move_x", -1, 1)
        p["move_z"] = number("move_z", -1, 1)
        p["yaw"] = (p["yaw"] + number("yaw_delta", -0.25, 0.25)) % (math.pi * 2)
        p["pitch"] = max(-0.85, min(0.85, p["pitch"] + number("pitch_delta", -0.2, 0.2)))

        p["fire"] = bool(data.get("fire"))
        p["aim"] = bool(data.get("aim"))
        p["sprint"] = bool(data.get("sprint"))
        p["crouch"] = bool(data.get("crouch"))
        p["last_input"] = now()
        p["last_seen"] = now()
        room["last_active"] = now()

        if bool(data.get("jump")):
            p["jump_requested"] = True
        if bool(data.get("reload")):
            reload_weapon(p)
        if bool(data.get("grenade")):
            p["grenade"] = True
        if bool(data.get("switch_weapon")):
            p["weapon"] = "smg" if p["weapon"] == "rifle" else "rifle"
            w = WEAPONS[p["weapon"]]
            p["ammo"] = min(p["ammo"], w["mag"])
            p["reserve"] = min(p["reserve"], w["reserve"])
        # interact محجوز للتفاعل مع أهداف لاحقة، ولا يمنح امتيازاً.
        if bool(data.get("interact")):
            pass


@socketio.on("request_status")
def on_request_status(data=None):
    with world_lock:
        info = sid_index.get(request.sid)
        if not info:
            return fail("هذا الاتصال غير مرتبط بغرفة.")
        room = rooms.get(info[0])
        if not room:
            return fail("الغرفة غير موجودة.")
        return {"ok": True, "room": public_room(room)}


# ============================================================
# 6. التشغيل
# ============================================================

if __name__ == "__main__":
    start_engine_once()
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True,
    )
