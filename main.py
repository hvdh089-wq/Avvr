# -*- coding: utf-8 -*-
"""
SPACE WAR ELITE - ملف واحد: خادم Flask + Socket.IO + واجهة HTML/CSS/JS (Three.js).
تشغيل محلي:   pip install flask flask-socketio simple-websocket   ثم   python main.py
نشر Render:   Build: pip install flask flask-socketio simple-websocket gunicorn
              Start: gunicorn -w 1 --threads 100 -b 0.0.0.0:$PORT main:app
(يجب عامل واحد فقط -w 1 لأن الغرف محفوظة في ذاكرة العملية.)
متغيرات اختيارية: DB_PATH (مسار قاعدة SQLite، استخدم قرصاً دائماً على Render), SECRET_KEY
"""
import os, re, time, math, json, random, secrets, sqlite3, hashlib, threading
from flask import Flask, Response, request
from flask_socketio import SocketIO, join_room, leave_room

DB_PATH = os.environ.get('DB_PATH', 'spacewar.db')
ARENA = 1600.0
TICK = 1.0 / 30
AL = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
sio = SocketIO(app, async_mode='threading', max_http_buffer_size=20000, ping_interval=10, ping_timeout=15)
L = threading.RLock()
DBL = threading.Lock()
ROOMS = {}
SIDS = {}
RL = {}
FAILS = {}

# ----------------------------------------------------------------- قاعدة البيانات
def dbq(sql, args=(), one=False, commit=False):
    with DBL:
        c = sqlite3.connect(DB_PATH, timeout=10)
        try:
            c.row_factory = sqlite3.Row
            cur = c.execute(sql, args)
            r = cur.fetchone() if one else cur.fetchall()
            if commit:
                c.commit()
            return r
        finally:
            c.close()

def init_db():
    dbq("""create table if not exists players(pid text primary key, nick text, wins int default 0,
        losses int default 0, kills int default 0, deaths int default 0, level int default 1,
        pts int default 0, settings text default '{}', created real)""", commit=True)
    dbq("""create table if not exists matches(id integer primary key autoincrement, ts real,
        mode text, winner text, loser text, score text)""", commit=True)

def pid_of(tok):
    if isinstance(tok, str) and re.fullmatch(r'[0-9a-f]{32}', tok):
        return hashlib.sha256(tok.encode()).hexdigest()
    return None

NICK_RE = re.compile(r'^[A-Za-z0-9_\u0600-\u06FF \-]{2,16}$')
def clean_nick(n):
    n = (n or '').strip() if isinstance(n, str) else ''
    return n if NICK_RE.match(n) else 'Pilot' + str(random.randint(100, 999))

def ensure_player(tok, nick):
    pid = pid_of(tok)
    if not pid:
        return None
    row = dbq('select nick from players where pid=?', (pid,), one=True)
    if not row:
        dbq('insert into players(pid,nick,created) values(?,?,?)', (pid, clean_nick(nick), time.time()), commit=True)
    elif isinstance(nick, str) and NICK_RE.match(nick.strip()) and row['nick'] != nick.strip():
        dbq('update players set nick=? where pid=?', (nick.strip(), pid), commit=True)
    return pid

def nick_of(pid):
    r = dbq('select nick from players where pid=?', (pid,), one=True)
    return r['nick'] if r else 'Pilot'

# ----------------------------------------------------------------- بيانات اللعبة
SHIPS = {
    'viper':  dict(n='فايبر',  d='مقاتلة خفيفة سريعة: سرعة وتحمل منخفض', sp=135, ac=95, ag=2.6, hp=60, sh=40, mi=4, sr=6, er=16, dm=.9, cd=.10),
    'falcon': dict(n='فالكون', d='مقاتلة متعددة المهام', sp=115, ac=80, ag=2.2, hp=80, sh=60, mi=6, sr=6, er=16, dm=1.0, cd=.11),
    'lancer': dict(n='لانسر',  d='اعتراضية: أسرع سفينة وأضعف درع', sp=150, ac=110, ag=2.4, hp=55, sh=35, mi=4, sr=6, er=18, dm=.95, cd=.10),
    'titan':  dict(n='تيتان',  d='هجومية ثقيلة: ضرر عالٍ وبطيئة', sp=85, ac=55, ag=1.4, hp=140, sh=110, mi=10, sr=5, er=15, dm=1.5, cd=.16),
    'ghost':  dict(n='غوست',   d='شبحية: طاقة تتجدد بسرعة', sp=125, ac=85, ag=2.3, hp=65, sh=30, mi=5, sr=5, er=26, dm=1.1, cd=.11),
    'aegis':  dict(n='إيجيس',  d='دعم: درع ضخم يتجدد بسرعة وضرر أقل', sp=100, ac=70, ag=1.9, hp=100, sh=130, mi=4, sr=14, er=16, dm=.8, cd=.11),
    'rookie': dict(n='رووكي',  d='متوازنة للمبتدئين', sp=110, ac=80, ag=2.0, hp=90, sh=70, mi=6, sr=7, er=17, dm=1.0, cd=.11),
}
ENV_N = ['حزام الكويكبات', 'مدار كوكب صحراوي', 'حطام سفن قديمة', 'قاعدة عسكرية فضائية', 'قرب نجم عملاق',
         'منطقة سديم كثيف', 'محطة تعدين', 'ممر فضائي ضيق', 'كوكب جليدي', 'ساحة حطام الأقمار']
ENV_AST = [40, 22, 36, 18, 30, 45, 26, 14, 20, 38]
SPAWNS = [(-520, 0, 0), (520, 0, 0)]
MISSIONS = []
for _i in range(20):
    _b = min(2 + _i // 2, 10)
    _t = 150 + _i * 8
    MISSIONS.append(dict(i=_i, env=_i % 10, n='%s%s' % (ENV_N[_i % 10], '' if _i < 10 else ' - تصعيد'), b=_b,
                         df=round(min(.95, .18 + _i * .04), 2), t=_t, rw=100 + _i * 30,
                         ds='دمّر %d مقاتلات معادية خلال %d ثانية دون أن تُدمَّر 3 مرات.' % (_b, _t)))

def clamp(x, a, b):
    return a if x < a else b if x > b else x
def qmul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return (aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw)
def qnorm(q):
    n = math.sqrt(sum(c*c for c in q)) or 1
    return tuple(c/n for c in q)
def qrot(q, v):
    w, x, y, z = q; vx, vy, vz = v
    tx = 2*(y*vz-z*vy); ty = 2*(z*vx-x*vz); tz = 2*(x*vy-y*vx)
    return (vx+w*tx+(y*tz-z*ty), vy+w*ty+(z*tx-x*tz), vz+w*tz+(x*ty-y*tx))
def qconj(q):
    return (q[0], -q[1], -q[2], -q[3])
def qrv(x, y, z):
    a = math.sqrt(x*x+y*y+z*z)
    if a < 1e-9:
        return (1, 0, 0, 0)
    s = math.sin(a/2)/a
    return (math.cos(a/2), x*s, y*s, z*s)
def qdir(d):
    n = math.sqrt(sum(c*c for c in d)) or 1
    dx, dy, dz = [c/n for c in d]
    return qnorm(qmul(qrv(0, math.atan2(-dx, -dz), 0), qrv(math.asin(clamp(dy, -1, 1)), 0, 0)))
def dist(a, b):
    return math.sqrt((a[0]-b[0])**2+(a[1]-b[1])**2+(a[2]-b[2])**2)
def seg_dist(a, b, p):
    ab = [b[i]-a[i] for i in range(3)]; ap = [p[i]-a[i] for i in range(3)]
    l2 = sum(c*c for c in ab) or 1e-9
    t = clamp(sum(ab[i]*ap[i] for i in range(3))/l2, 0, 1)
    return dist([a[i]+ab[i]*t for i in range(3)], p)

def make_obstacles(env, rnd):
    a = rnd.uniform(0, 6.283); el = rnd.uniform(-.3, .3)
    ob = [[round(math.cos(a)*math.cos(el)*1050), round(math.sin(el)*700), round(math.sin(a)*math.cos(el)*1050), round(rnd.uniform(220, 320))]]
    tries = 0
    while len(ob) < ENV_AST[env] + 1 and tries < 4000:
        tries += 1
        p = [rnd.uniform(-1, 1)*1100 for _ in range(3)]
        r = rnd.uniform(12, 45)
        if dist(p, (0, 0, 0)) > 1250:
            continue
        if any(dist(p, o[:3]) < o[3]+r+25 for o in ob):
            continue
        if min(dist(p, s) for s in SPAWNS) < r+160:
            continue
        ob.append([round(p[0]), round(p[1]), round(p[2]), round(r)])
    return ob

# ----------------------------------------------------------------- السفن والغرف
class Ship:
    def __init__(s, sid, kind, team, name, bot=False, diff=.5):
        s.id = sid; s.kind = kind; s.team = team; s.name = name; s.bot = bot; s.diff = diff
        s.d = SHIPS[kind]; s.kills = 0; s.deaths = 0; s.inp = [0]*9; s.rt = 0; s.alive = False
        s.alt = 0; s.over = False; s.boost = False; s.shl = False; s.ob = False; s.spd = 0
        s.p = [0, 0, 0]; s.v = [0, 0, 0]; s.q = (1, 0, 0, 0); s.cd = s.mcd = s.inv = 0; s.lh = -99
        s.hp = s.sh = s.en = s.mis = 0
    def spawn(s, pos, t):
        d = s.d
        s.p = [float(c) for c in pos]; s.v = [0, 0, 0]; s.q = qdir([-c for c in pos]) if any(pos) else (1, 0, 0, 0)
        s.hp = d['hp']; s.sh = d['sh']; s.en = 100; s.mis = d['mi']; s.alive = True; s.inv = 2.5
        s.over = False; s.lh = t

class Room:
    def __init__(s, mode, host, env, mission=-2):
        s.mode = mode; s.host = host; s.env = env; s.mission = mission
        s.seats = [None, None]; s.state = 'lobby'; s.revoked = False
        s.created = s.touched = time.time(); s.hconn = True; s.hdc = 0
        s.ships = {}; s.pr = []; s.ev = []; s.ob = []; s.t = 0.0; s.paused = False
        s.nid = 100; s.limit = 0; s.kt = 0; s.lives = 3; s.startp = None
        s.code = ''; s.key = ''; s.hst = secrets.token_hex(12)

def new_room(mode, sid, env, mission=-2):
    code = ''
    for _ in range(60):
        code = ''.join(secrets.choice(AL) for _ in range(6))
        if code not in ROOMS:
            break
    R = Room(mode, sid, env, mission)
    R.code = code
    R.key = ''.join(secrets.choice(AL) for _ in range(8))
    ROOMS[code] = R
    return R

def mkseat(sid, nick, pid, ship):
    return dict(sid=sid, nick=nick, pid=pid, ship=ship if ship in SHIPS else 'rookie', ready=False, conn=True,
                last=time.time(), st=secrets.token_hex(12), inp=[0]*9, dc=0)

def parts(R):
    out = []
    if R.mode == 'display':
        out.append((R.host, -1))
    for i, sd in enumerate(R.seats):
        if sd:
            out.append((sd['sid'], i))
    return out

def err(sid, msg):
    sio.emit('err', msg, to=sid)

def snap(R, sid, you):
    seats = [None if not sd else dict(n=sd['nick'], sh=sd['ship'], rd=sd['ready'], cn=sd['conn'],
             lg=0 if sd['conn'] else int(time.time()-sd['dc'])) for sd in R.seats]
    return dict(code=R.code, key=(R.key if (sid == R.host and not R.revoked) else None), mode=R.mode, state=R.state,
                host=(sid == R.host), you=you, seats=seats, env=R.env, mi=R.mission)

def push_room(R):
    for sid, you in parts(R):
        sio.emit('room', snap(R, sid, you), to=sid)

def allow(sid, lim):
    now = time.time()
    r = RL.get(sid)
    if not r or now - r[0] >= 1:
        RL[sid] = [now, 1]
        return True
    r[1] += 1
    return r[1] <= lim

def client_ip():
    xf = request.headers.get('X-Forwarded-For', '')
    return (xf.split(',')[0].strip() or request.remote_addr or '?')[:64]

def close_room(R, msg=''):
    for sid, _ in parts(R):
        sio.emit('closed', msg, to=sid)
        SIDS.pop(sid, None)
        try:
            leave_room(R.code, sid=sid)
        except Exception:
            pass
    ROOMS.pop(R.code, None)

def drop(sid):
    m = SIDS.pop(sid, None)
    if not m:
        return
    R = ROOMS.get(m[0]); idx = m[1]
    try:
        leave_room(m[0], sid=sid)
    except Exception:
        pass
    if not R:
        return
    if R.state == 'lobby':
        if idx == -1 or (idx == 0 and R.mode == 'pvp') or R.mode == 'solo':
            close_room(R, 'غادر المضيف')
            return
        if idx >= 0:
            R.seats[idx] = None
        push_room(R)
    elif R.state == 'playing':
        if R.mode == 'solo':
            close_room(R)
        elif idx >= 0:
            end_room(R, 1-idx, 'انسحب الخصم')
            R.seats[idx] = None
        else:
            close_room(R, 'غادر شاشة العرض')
    else:
        if idx >= 0:
            R.seats[idx] = None
        if not any(R.seats) or R.mode == 'solo' or idx == -1:
            close_room(R)
        else:
            push_room(R)

# ----------------------------------------------------------------- بدء المباراة والمحاكاة
def begin(R):
    R.revoked = True; R.state = 'playing'; R.t = 0.0; R.paused = False; R.pr = []; R.ev = []; R.nid = 100
    rnd = random.Random(secrets.randbits(32))
    R.ob = make_obstacles(R.env, rnd)
    R.ships = {}
    for i, sd in enumerate(R.seats):
        if sd:
            sh = Ship(i, sd['ship'], 0 if R.mode == 'solo' else i, sd['nick'])
            sh.spawn(SPAWNS[i], R.t)
            R.ships[i] = sh
    if R.mode == 'solo':
        if R.mission >= 0:
            m = MISSIONS[R.mission]; nb = m['b']; df = m['df']; R.limit = m['t']; R.kt = nb; R.lives = 3
        else:
            nb = 3; df = .45; R.limit = 0; R.kt = 0; R.lives = 99999
        for k in range(nb):
            b = Ship(2+k, rnd.choice(list(SHIPS)), 1, 'AI-%d' % (k+1), True, df)
            b.spawn(ring_pos(rnd), R.t)
            R.ships[b.id] = b
    else:
        R.limit = 240; R.kt = 5; R.lives = 99999
    R.startp = dict(env=R.env, ob=R.ob, lim=R.limit, kt=R.kt, mode=R.mode, mi=R.mission, lv=R.lives,
                    ships=[[s.id, s.kind, s.name, s.team, int(s.bot), s.d['hp'], s.d['sh']] for s in R.ships.values()])
    for sid, you in parts(R):
        sio.emit('start', dict(R.startp, you=you), to=sid)
    push_room(R)

def ring_pos(rnd):
    a = rnd.uniform(0, 6.283); r = rnd.uniform(650, 950)
    return (math.cos(a)*r, rnd.uniform(-150, 150), math.sin(a)*r)

def hurt(R, s, amt, src):
    if not s.alive or s.inv > 0:
        return
    if s.shl:
        amt *= .5
    s.lh = R.t
    a = min(s.sh, amt); s.sh -= a; amt -= a; s.hp -= amt
    if s.hp <= 0:
        s.alive = False; s.hp = 0; s.deaths += 1; s.rt = 3.5
        if src is not None and src is not s:
            src.kills += 1
        R.ev.append(['x', round(s.p[0]), round(s.p[1]), round(s.p[2]), 2])

def ai(R, b):
    i = [0]*9
    b.inp = i
    if not b.alive:
        return
    best = None; bd = 1e18
    for s in R.ships.values():
        if s.alive and s.team != b.team:
            d2 = (s.p[0]-b.p[0])**2+(s.p[1]-b.p[1])**2+(s.p[2]-b.p[2])**2
            if d2 < bd:
                bd = d2; best = s
    if not best:
        i[3] = .3
        return
    dd = math.sqrt(bd); df = b.diff; sk = .45+.55*df
    lead = dd/260*df
    to = [best.p[k]+best.v[k]*lead-b.p[k] for k in range(3)]
    flee = (b.hp+b.sh) < .28*(b.d['hp']+b.d['sh']) and df > .3
    if flee:
        to = [-c for c in to]
    lx, ly, lz = qrot(qconj(b.q), to)
    yaw = math.atan2(lx, -lz); pit = math.atan2(ly, math.hypot(lx, lz))
    i[0] = clamp(pit*2.5*sk, -1, 1); i[1] = clamp(yaw*2.5*sk, -1, 1); i[2] = clamp(yaw, -1, 1)*.6
    i[3] = 1 if (flee or dd > 320) else .5
    if flee and b.en > 30:
        i[6] = 1
    tol = .1+.12*(1-df)
    if not flee and abs(yaw) < tol and abs(pit) < tol and dd < 520 and random.random() < .55+.4*df:
        i[4] = 1
    if not flee and abs(yaw) < .25 and abs(pit) < .25 and 250 < dd < 1100 and b.mis > 0 and random.random() < .004+.015*df:
        i[5] = 1
    if R.t-b.lh < 1.5 and b.en > 30:
        i[8] = 1
    if R.t-b.lh < 2:
        i[0] += .5*math.sin(R.t*3+b.id); i[1] += .5*math.cos(R.t*2.3+b.id)
    for o in R.ob:
        if dist(b.p, o) < o[3]+110:
            ox, oy, oz = qrot(qconj(b.q), [o[0]-b.p[0], o[1]-b.p[1], o[2]-b.p[2]])
            i[1] = -1 if ox > 0 else 1; i[0] = -1 if oy > 0 else 1; i[3] = .6; i[4] = 0
            break
    if dist(b.p, (0, 0, 0)) > ARENA-150:
        ox, oy, oz = qrot(qconj(b.q), [-b.p[0], -b.p[1], -b.p[2]])
        i[1] = clamp(math.atan2(ox, -oz)*2, -1, 1); i[0] = clamp(math.atan2(oy, math.hypot(ox, oz))*2, -1, 1)
    for k in (0, 1, 2):
        i[k] = clamp(i[k], -1, 1)

def move(R, s, dt):
    d = s.d
    pit, yaw, rol, thr, fire, mis, boo, brk, shl = s.inp
    s.inv = max(0, s.inv-dt)
    s.boost = boo > .5 and s.en > 6
    s.shl = shl > .5 and s.en > 6
    s.en = clamp(s.en+(d['er']-(20 if s.boost else 0)-(11 if s.shl else 0))*dt, 0, 100)
    if s.over and s.en > 35:
        s.over = False
    ag = d['ag']*(.85 if s.boost else 1)
    s.q = qnorm(qmul(s.q, qrv(pit*ag*dt, -yaw*ag*dt, -rol*ag*1.3*dt)))
    fwd = qrot(s.q, (0, 0, -1))
    vmax = d['sp']*(1.7 if s.boost else 1); acc = d['ac']*(2 if s.boost else 1)
    thr = 1 if s.boost else clamp(thr, -.4, 1)
    vf = s.v[0]*fwd[0]+s.v[1]*fwd[1]+s.v[2]*fwd[2]
    lat = [s.v[k]-fwd[k]*vf for k in range(3)]
    dl = thr*vmax-vf
    rate = acc if dl > 0 else acc*(2.8 if brk > .5 else .8)
    vf += clamp(dl, -rate*dt, rate*dt)
    kk = max(0, 1-(1.4+(2.5 if brk > .5 else 0))*dt)
    s.v = [fwd[k]*vf+lat[k]*kk for k in range(3)]
    s.p = [s.p[k]+s.v[k]*dt for k in range(3)]
    s.spd = abs(vf)
    r = math.sqrt(sum(c*c for c in s.p)) or 1
    s.ob = r > ARENA
    if s.ob:
        s.v = [s.v[k]-s.p[k]/r*260*dt for k in range(3)]
        if r > ARENA+300:
            hurt(R, s, 25*dt, None)
    for o in R.ob:
        dx = s.p[0]-o[0]; dy = s.p[1]-o[1]; dz = s.p[2]-o[2]
        dd = math.sqrt(dx*dx+dy*dy+dz*dz) or .001; rr = o[3]+7
        if dd < rr:
            n = (dx/dd, dy/dd, dz/dd)
            s.p = [o[k]+n[k]*rr for k in range(3)]
            vn = s.v[0]*n[0]+s.v[1]*n[1]+s.v[2]*n[2]
            if vn < 0:
                s.v = [s.v[k]-n[k]*vn*1.6 for k in range(3)]
            hurt(R, s, max(8, abs(vn)*(.5 if o[3] > 150 else .22)), None)
            R.ev.append(['h', round(s.p[0]), round(s.p[1]), round(s.p[2]), s.id])
    if R.t-s.lh > 3:
        s.sh = min(d['sh'], s.sh+d['sr']*dt)
    s.cd -= dt; s.mcd -= dt
    if fire > .5 and s.cd <= 0 and not s.over and s.en >= 3:
        s.cd = d['cd']; s.en -= 2.5
        if s.en < 3:
            s.over = True
        s.alt ^= 1
        off = qrot(s.q, (2.2 if s.alt else -2.2, -.4, -6))
        pos = [s.p[k]+off[k] for k in range(3)]
        R.nid += 1
        R.pr.append([R.nid, 0, s.id, s.team, pos[0], pos[1], pos[2], fwd[0]*280+s.v[0]*.5, fwd[1]*280+s.v[1]*.5,
                     fwd[2]*280+s.v[2]*.5, 1.6, 9*d['dm'], None])
        R.ev.append(['l', round(pos[0]), round(pos[1]), round(pos[2])])
    if mis > .5 and s.mcd <= 0 and s.mis > 0:
        s.mcd = 1.2; s.mis -= 1
        tgt = None; bd = 1400
        for o in R.ships.values():
            if o.alive and o.team != s.team:
                v = [o.p[k]-s.p[k] for k in range(3)]; dd = math.sqrt(sum(c*c for c in v)) or 1
                if dd < bd and (v[0]*fwd[0]+v[1]*fwd[1]+v[2]*fwd[2])/dd > .8:
                    bd = dd; tgt = o.id
        R.nid += 1
        R.pr.append([R.nid, 1, s.id, s.team, s.p[0], s.p[1], s.p[2], fwd[0]*80+s.v[0], fwd[1]*80+s.v[1],
                     fwd[2]*80+s.v[2], 6.0, 38*d['dm'], tgt])
        R.ev.append(['m', round(s.p[0]), round(s.p[1]), round(s.p[2])])

def step(R, dt):
    R.t += dt
    ships = list(R.ships.values())
    for s in ships:
        if s.bot:
            ai(R, s)
        else:
            sd = R.seats[s.id]
            s.inp = sd['inp'] if (sd and sd['conn']) else [0]*9
    for s in ships:
        if s.alive:
            move(R, s, dt)
        else:
            s.rt -= dt
            if s.rt <= 0:
                if s.bot:
                    ok = R.mission == -1
                    pos = ring_pos(random)
                else:
                    ok = s.deaths < R.lives
                    pos = SPAWNS[s.id] if R.mode != 'solo' else (0, 0, 0) if False else SPAWNS[0]
                if ok:
                    s.spawn(pos, R.t)
    # تصادم السفن
    for a in range(len(ships)):
        for b in range(a+1, len(ships)):
            A, B = ships[a], ships[b]
            if A.alive and B.alive and dist(A.p, B.p) < 11:
                hurt(R, A, 14, B); hurt(R, B, 14, A)
                for k in range(3):
                    A.v[k], B.v[k] = -A.v[k]*.6, -B.v[k]*.6
    # المقذوفات
    keep = []
    for pj in R.pr:
        typ = pj[1]
        if typ == 1:
            t = R.ships.get(pj[12]) if pj[12] is not None else None
            sp = math.sqrt(pj[7]**2+pj[8]**2+pj[9]**2) or 1
            cur = (pj[7]/sp, pj[8]/sp, pj[9]/sp)
            if t and t.alive:
                to = [t.p[0]-pj[4], t.p[1]-pj[5], t.p[2]-pj[6]]; dl = math.sqrt(sum(c*c for c in to)) or 1
                k = min(1, 2.4*dt)
                nd = qnorm((0, cur[0]*(1-k)+to[0]/dl*k, cur[1]*(1-k)+to[1]/dl*k, cur[2]*(1-k)+to[2]/dl*k))[1:]
                cur = nd
            sp = min(175, sp+70*dt)
            pj[7], pj[8], pj[9] = cur[0]*sp, cur[1]*sp, cur[2]*sp
        ox, oy, oz = pj[4], pj[5], pj[6]
        pj[4] += pj[7]*dt; pj[5] += pj[8]*dt; pj[6] += pj[9]*dt; pj[10] -= dt
        a0 = (ox, oy, oz); a1 = (pj[4], pj[5], pj[6])
        hit = None
        for s in ships:
            if s.alive and s.team != pj[3] and seg_dist(a0, a1, s.p) < (8 if typ == 0 else 9):
                hit = s; break
        obh = False
        if not hit:
            for o in R.ob:
                if dist(a1, o) < o[3]:
                    obh = True; break
        owner = R.ships.get(pj[2])
        if hit:
            if typ == 0:
                hurt(R, hit, pj[11], owner)
                R.ev.append(['h', round(a1[0]), round(a1[1]), round(a1[2]), hit.id])
            else:
                for s in ships:
                    if s.alive and s.team != pj[3]:
                        dd = dist(a1, s.p)
                        if dd < 26:
                            hurt(R, s, pj[11]*(1-dd/26*.5), owner)
                R.ev.append(['x', round(a1[0]), round(a1[1]), round(a1[2]), 1])
            continue
        if obh:
            R.ev.append(['x' if typ else 'h', round(a1[0]), round(a1[1]), round(a1[2]), 0 if typ else -1])
            continue
        if pj[10] > 0:
            keep.append(pj)
        elif typ == 1:
            R.ev.append(['x', round(a1[0]), round(a1[1]), round(a1[2]), 0])
    R.pr = keep
    check_end(R)
    pk = [[s.id, round(s.p[0], 1), round(s.p[1], 1), round(s.p[2], 1), round(s.q[1], 4), round(s.q[2], 4),
           round(s.q[3], 4), round(s.q[0], 4), int(s.hp), int(s.sh), int(s.en), s.mis, int(s.alive), s.kills,
           s.deaths, int(s.ob), int(s.spd), int(s.boost)+2*int(s.shl), round(max(0, s.rt), 1)] for s in ships]
    msg = dict(s=pk, p=[[p[0], p[1], p[3], round(p[4]), round(p[5]), round(p[6])] for p in R.pr[:80]],
               e=R.ev[:40], tl=(round(max(0, R.limit-R.t), 1) if R.limit else -1))
    R.ev = []
    if R.state == 'playing':
        sio.emit('s', msg, to=R.code)

def check_end(R):
    if R.state != 'playing':
        return
    sh = R.ships
    if R.mode == 'solo':
        if R.mission < 0:
            return
        p = sh.get(0)
        if not any(s.alive or s.bot is False for s in []) and all((not s.alive) for s in sh.values() if s.bot):
            return end_room(R, 0, 'تم تدمير جميع الأهداف')
        if p and p.deaths >= R.lives:
            return end_room(R, 1, 'تم تدميرك 3 مرات')
        if R.limit and R.t >= R.limit:
            return end_room(R, 1, 'انتهى الوقت')
        return
    for s in sh.values():
        if s.kills >= R.kt:
            return end_room(R, s.id, 'وصل إلى %d قتلى' % R.kt)
    if R.t >= R.limit:
        a, b = sh[0], sh[1]
        if a.kills != b.kills:
            return end_room(R, 0 if a.kills > b.kills else 1, 'انتهى الوقت')
        sa, sb = a.hp+a.sh, b.hp+b.sh
        return end_room(R, -1 if abs(sa-sb) < 1 else (0 if sa > sb else 1), 'انتهى الوقت - تعادل في القتلى')

def end_room(R, w, why):
    if R.state != 'playing':
        return
    R.state = 'over'; R.touched = time.time()
    rw = MISSIONS[R.mission]['rw'] if (R.mode == 'solo' and R.mission >= 0 and w == 0) else 0
    st = [[s.id, s.name, s.kills, s.deaths] for s in R.ships.values()]
    try:
        record(R, w, rw)
    except Exception as e:
        print('record error', e)
    sio.emit('end', dict(w=w, why=why, st=st, mi=R.mission, rw=rw, mode=R.mode), to=R.code)
    push_room(R)

def record(R, w, rw):
    for i, sd in enumerate(R.seats):
        if not sd:
            continue
        sh = R.ships.get(i); k = sh.kills if sh else 0; dth = sh.deaths if sh else 0
        if R.mode == 'solo':
            if R.mission >= 0:
                if w == 0:
                    dbq('update players set wins=wins+1,kills=kills+?,deaths=deaths+?,pts=pts+?,level=max(level,?) where pid=?',
                        (k, dth, rw, min(21, R.mission+2), sd['pid']), commit=True)
                else:
                    dbq('update players set losses=losses+1,kills=kills+?,deaths=deaths+? where pid=?', (k, dth, sd['pid']), commit=True)
            else:
                dbq('update players set kills=kills+?,deaths=deaths+? where pid=?', (k, dth, sd['pid']), commit=True)
        else:
            col = 'wins=wins+1' if w == i else ('losses=losses+1' if w >= 0 else 'wins=wins')
            dbq('update players set %s,kills=kills+?,deaths=deaths+? where pid=?' % col, (k, dth, sd['pid']), commit=True)
    if R.mode != 'solo' and R.seats[0] and R.seats[1] and w >= 0:
        dbq('insert into matches(ts,mode,winner,loser,score) values(?,?,?,?,?)',
            (time.time(), R.mode, R.seats[w]['nick'], R.seats[1-w]['nick'],
             '%d-%d' % (R.ships[w].kills, R.ships[1-w].kills)), commit=True)

def clean(now):
    for code, R in list(ROOMS.items()):
        if code not in ROOMS:
            continue
        for i, sd in enumerate(R.seats):
            if sd and not sd['conn']:
                gone = now-sd['dc']
                if R.state == 'lobby' and gone > 20:
                    if i == 0 and R.mode == 'pvp':
                        close_room(R, 'انقطع المضيف'); break
                    R.seats[i] = None; push_room(R)
                elif R.state == 'playing' and gone > 25:
                    if R.mode == 'solo':
                        close_room(R); break
                    end_room(R, 1-i, 'انقطع اتصال الخصم')
                elif R.state == 'over' and gone > 60:
                    close_room(R); break
        if code not in ROOMS:
            continue
        if R.mode == 'display' and not R.hconn and now-R.hdc > 30:
            close_room(R, 'انقطعت شاشة العرض'); continue
        idle = now-R.touched
        if (R.state == 'lobby' and idle > 1800) or (R.state == 'over' and idle > 300) or \
           (not any(sd and sd['conn'] for sd in R.seats) and not (R.mode == 'display' and R.hconn) and idle > 90):
            close_room(R)
    for k in [k for k, v in FAILS.items() if now-v[0] > 60]:
        FAILS.pop(k, None)

def loop():
    nxt = time.time(); lc = 0
    while True:
        now = time.time()
        with L:
            for R in list(ROOMS.values()):
                if R.state == 'playing' and not R.paused:
                    if R.mode == 'solo' and R.seats[0] and not R.seats[0]['conn']:
                        continue
                    try:
                        step(R, TICK)
                    except Exception as e:
                        print('step error', repr(e))
                        end_room(R, -1, 'خطأ في الخادم')
            if now-lc > 3:
                lc = now
                try:
                    clean(now)
                except Exception as e:
                    print('clean error', repr(e))
        nxt += TICK
        sl = nxt-time.time()
        if sl > 0:
            time.sleep(sl)
        else:
            nxt = time.time()

# ----------------------------------------------------------------- أحداث الشبكة
def find(sid):
    m = SIDS.get(sid)
    if not m:
        return None, -2
    return ROOMS.get(m[0]), m[1]

@sio.on('disconnect')
def _disc(*a):
    sid = request.sid
    RL.pop(sid, None)
    with L:
        m = SIDS.get(sid)
        if not m:
            return
        R = ROOMS.get(m[0])
        if not R:
            SIDS.pop(sid, None); return
        now = time.time()
        if m[1] >= 0 and R.seats[m[1]] and R.seats[m[1]]['sid'] == sid:
            R.seats[m[1]]['conn'] = False; R.seats[m[1]]['dc'] = now
        elif m[1] == -1 and R.host == sid:
            R.hconn = False; R.hdc = now
        push_room(R)

@sio.on('profile')
def h_prof(d):
    d = d if isinstance(d, dict) else {}
    if not allow(request.sid, 10):
        return {'ok': 0}
    pid = ensure_player(d.get('tok'), d.get('nick'))
    if not pid:
        return {'ok': 0}
    r = dbq('select * from players where pid=?', (pid,), one=True)
    hist = [dict(w=x['winner'], l=x['loser'], s=x['score']) for x in
            dbq('select * from matches where winner=? or loser=? order by id desc limit 8', (r['nick'], r['nick']))]
    return dict(ok=1, nick=r['nick'], w=r['wins'], l=r['losses'], k=r['kills'], d=r['deaths'], lv=r['level'],
                pts=r['pts'], st=r['settings'], hist=hist, envs=ENV_N, ms=MISSIONS,
                ships=[dict(id=k, n=v['n'], d=v['d'], sp=v['sp'], ac=v['ac'], ag=v['ag'], hp=v['hp'], sh=v['sh'],
                            mi=v['mi'], dm=v['dm']) for k, v in SHIPS.items()])

@sio.on('save')
def h_save(d):
    d = d if isinstance(d, dict) else {}
    if not allow(request.sid, 5):
        return
    pid = pid_of(d.get('tok'))
    s = d.get('st')
    if not pid or not isinstance(s, str) or len(s) > 1500:
        return
    try:
        o = json.loads(s)
        if not isinstance(o, dict):
            return
    except Exception:
        return
    dbq('update players set settings=? where pid=?', (json.dumps(o)[:1500], pid), commit=True)

@sio.on('pg')
def h_pg(t):
    return t

@sio.on('create')
def h_create(d):
    sid = request.sid; d = d if isinstance(d, dict) else {}
    if not allow(sid, 5):
        return
    pid = ensure_player(d.get('tok'), d.get('nick'))
    if not pid:
        return err(sid, 'رمز اللاعب غير صالح')
    mode = 'display' if d.get('mode') == 'display' else 'pvp'
    try:
        env = int(d.get('env', 0)) % 10
    except Exception:
        env = 0
    with L:
        if len(ROOMS) >= 300:
            return err(sid, 'الخادم ممتلئ حالياً')
        drop(sid)
        R = new_room(mode, sid, env)
        if mode == 'pvp':
            R.seats[0] = mkseat(sid, nick_of(pid), pid, d.get('ship')); R.seats[0]['ready'] = True
            SIDS[sid] = (R.code, 0); tok = R.seats[0]['st']
        else:
            SIDS[sid] = (R.code, -1); tok = R.hst
        join_room(R.code, sid=sid)
        sio.emit('seat', dict(code=R.code, st=tok), to=sid)
        push_room(R)

@sio.on('join')
def h_join(d):
    sid = request.sid; d = d if isinstance(d, dict) else {}
    if not allow(sid, 5):
        return
    ip = client_ip()
    f = FAILS.get(ip)
    if f and time.time()-f[0] < 60 and f[1] >= 15:
        return err(sid, 'محاولات كثيرة، انتظر دقيقة')
    code = str(d.get('code', '')).strip().upper(); key = str(d.get('key', '')).strip().upper()
    pid = ensure_player(d.get('tok'), d.get('nick'))
    if not pid:
        return err(sid, 'رمز اللاعب غير صالح')
    with L:
        R = ROOMS.get(code) if re.fullmatch(r'[A-Z0-9]{6}', code) else None
        ok = bool(R) and re.fullmatch(r'[A-Z0-9]{8}', key) and secrets.compare_digest(R.key, key)
        if not ok or R.revoked or R.state != 'lobby' or R.mode == 'solo':
            fl = FAILS.get(ip)
            if not fl or time.time()-fl[0] > 60:
                FAILS[ip] = [time.time(), 1]
            else:
                fl[1] += 1
            return err(sid, 'رمز الغرفة أو رمز الدخول غير صالح أو منتهي')
        idx = -1
        for i in ([1] if R.mode == 'pvp' else [0, 1]):
            if R.seats[i] is None:
                idx = i; break
        if idx < 0:
            return err(sid, 'الغرفة مكتملة (لاعبان فقط)')
        drop(sid)
        R.seats[idx] = mkseat(sid, nick_of(pid), pid, d.get('ship'))
        R.touched = time.time()
        SIDS[sid] = (R.code, idx)
        join_room(R.code, sid=sid)
        sio.emit('seat', dict(code=R.code, st=R.seats[idx]['st']), to=sid)
        push_room(R)

@sio.on('rejoin')
def h_rejoin(d):
    sid = request.sid; d = d if isinstance(d, dict) else {}
    if not allow(sid, 5):
        return
    code = str(d.get('code', '')); st = str(d.get('st', ''))
    with L:
        R = ROOMS.get(code)
        if not R:
            return sio.emit('gone', '', to=sid)
        idx = None
        if R.mode == 'display' and secrets.compare_digest(R.hst, st):
            idx = -1; R.host = sid; R.hconn = True
        else:
            for i, sd in enumerate(R.seats):
                if sd and secrets.compare_digest(sd['st'], st):
                    idx = i; sd['sid'] = sid; sd['conn'] = True; sd['last'] = time.time()
                    if i == 0 and R.mode != 'display':
                        R.host = sid
        if idx is None:
            return sio.emit('gone', '', to=sid)
        old = [k for k, v in SIDS.items() if v[0] == code and v[1] == idx and k != sid]
        for k in old:
            SIDS.pop(k, None)
        SIDS[sid] = (code, idx)
        join_room(code, sid=sid)
        push_room(R)
        if R.state == 'playing' and R.startp:
            sio.emit('start', dict(R.startp, you=idx), to=sid)

@sio.on('ready')
def h_ready(v):
    sid = request.sid
    if not allow(sid, 10):
        return
    with L:
        R, idx = find(sid)
        if R and idx >= 0 and R.state == 'lobby' and R.seats[idx]:
            R.seats[idx]['ready'] = bool(v); push_room(R)

@sio.on('ship')
def h_ship(v):
    sid = request.sid
    if not allow(sid, 10):
        return
    with L:
        R, idx = find(sid)
        if R and idx >= 0 and R.state == 'lobby' and R.seats[idx] and v in SHIPS:
            R.seats[idx]['ship'] = v; push_room(R)

@sio.on('start')
def h_start(v=None):
    sid = request.sid
    if not allow(sid, 5):
        return
    with L:
        R, idx = find(sid)
        if not R or sid != R.host or R.state != 'lobby' or R.mode == 'solo':
            return
        if not all(sd and sd['conn'] and (sd['ready'] or i == 0 and R.mode == 'pvp') for i, sd in enumerate(R.seats)):
            return err(sid, 'يجب أن يكون اللاعبان متصلين وجاهزين')
        begin(R)

@sio.on('solo')
def h_solo(d):
    sid = request.sid; d = d if isinstance(d, dict) else {}
    if not allow(sid, 4):
        return
    pid = ensure_player(d.get('tok'), d.get('nick'))
    if not pid:
        return err(sid, 'رمز اللاعب غير صالح')
    try:
        mi = int(d.get('mission', -1))
    except Exception:
        mi = -1
    if mi < -1 or mi >= len(MISSIONS):
        return
    lv = dbq('select level from players where pid=?', (pid,), one=True)['level']
    if mi >= lv:
        return err(sid, 'المهمة مقفلة')
    with L:
        drop(sid)
        R = new_room('solo', sid, MISSIONS[mi]['env'] if mi >= 0 else random.randint(0, 9), mi)
        R.seats[0] = mkseat(sid, nick_of(pid), pid, d.get('ship')); R.seats[0]['ready'] = True
        SIDS[sid] = (R.code, 0)
        join_room(R.code, sid=sid)
        sio.emit('seat', dict(code=R.code, st=R.seats[0]['st']), to=sid)
        begin(R)

@sio.on('input')
def h_input(v):
    sid = request.sid
    if not allow(sid, 80):
        return
    if not isinstance(v, list) or len(v) != 9:
        return
    m = SIDS.get(sid)
    if not m or m[1] < 0:
        return
    R = ROOMS.get(m[0])
    if not R or not R.seats[m[1]]:
        return
    try:
        v = [float(x) for x in v]
    except Exception:
        return
    v = [x if x == x and abs(x) < 1e6 else 0 for x in v]
    R.seats[m[1]]['inp'] = [clamp(v[0], -1, 1), clamp(v[1], -1, 1), clamp(v[2], -1, 1), clamp(v[3], -.4, 1)] + \
                           [1 if x > .5 else 0 for x in v[4:]]
    R.seats[m[1]]['last'] = time.time()

@sio.on('pause')
def h_pause(v):
    sid = request.sid
    with L:
        R, idx = find(sid)
        if R and R.mode == 'solo' and R.state == 'playing':
            R.paused = bool(v)

@sio.on('rematch')
def h_rematch(v=None):
    sid = request.sid
    if not allow(sid, 5):
        return
    with L:
        R, idx = find(sid)
        if not R or sid != R.host or R.state != 'over' or R.mode == 'solo':
            return
        if not all(sd and sd['conn'] for sd in R.seats):
            return err(sid, 'أحد اللاعبين غير متصل')
        R.state = 'lobby'; R.touched = time.time()
        for sd in R.seats:
            sd['ready'] = False
        if R.mode == 'pvp':
            R.seats[0]['ready'] = True
        push_room(R)

@sio.on('leave')
def h_leave(v=None):
    with L:
        drop(request.sid)

@sio.on('close')
def h_close(v=None):
    sid = request.sid
    with L:
        R, idx = find(sid)
        if R and sid == R.host:
            close_room(R, 'أغلق المضيف الغرفة')

# ----------------------------------------------------------------- الصفحة
@app.route('/')
def index():
    r = Response(PAGE, mimetype='text/html')
    r.headers['Cache-Control'] = 'no-store'
    return r

@app.route('/health')
def health():
    return 'ok'

@app.after_request
def hdr(r):
    r.headers['X-Content-Type-Options'] = 'nosniff'
    r.headers['Referrer-Policy'] = 'no-referrer'
    r.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self' data: blob:; media-src 'self' blob:")
    return r

PAGE = r'''<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#05070d"><title>SPACE WAR ELITE</title>
<style>
:root{--a:#38e1ff;--p:rgba(8,16,30,.8);--bs:1;--bo:.85}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
html,body{margin:0;height:100%;overflow:hidden;background:#000;color:#dff6ff;font:15px/1.5 'Segoe UI',Tahoma,Arial,sans-serif;touch-action:none}
input,select{user-select:text;-webkit-user-select:text;touch-action:manipulation}
#gl{position:fixed;inset:0;width:100%;height:100%;display:block}
.scr{position:fixed;inset:0;display:none;overflow:auto;padding:max(12px,env(safe-area-inset-top)) 14px 20px;touch-action:pan-y;z-index:10;align-items:center;justify-content:center;flex-direction:column}
.scr.on{display:flex}
.pn{background:var(--p);border:1px solid rgba(56,225,255,.35);border-radius:14px;padding:14px;backdrop-filter:blur(8px);max-width:600px;width:100%;box-shadow:0 0 30px rgba(56,225,255,.12);margin:auto}
h1{margin:0 0 4px;text-align:center;font-size:30px;letter-spacing:4px;background:linear-gradient(90deg,#38e1ff,#fff,#ff9a3a);-webkit-background-clip:text;background-clip:text;color:transparent;font-family:Impact,'Segoe UI',sans-serif}
h2{margin:0 0 8px;font-size:18px;color:var(--a)}
.sub{text-align:center;opacity:.7;font-size:12px;margin-bottom:10px}
.b{display:block;width:100%;padding:11px;margin:5px 0;border:1px solid var(--a);background:linear-gradient(180deg,rgba(56,225,255,.2),rgba(56,225,255,.05));color:#dff6ff;border-radius:10px;font:inherit;font-weight:700;cursor:pointer}
.b:active{background:var(--a);color:#001018}.b[disabled]{opacity:.35}
.b.d{border-color:#ff4f6d;background:rgba(255,79,109,.14)}.b.g{border-color:#3dff9a;background:rgba(61,255,154,.14)}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
input[type=text],select{width:100%;padding:10px;margin:4px 0;background:rgba(0,0,0,.45);border:1px solid rgba(56,225,255,.4);border-radius:8px;color:#fff;font:inherit;text-align:center}
input[type=range]{width:100%;accent-color:var(--a)}
.row{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:6px 0}
.code{font:700 26px monospace;letter-spacing:4px;color:#fff;text-align:center;background:rgba(0,0,0,.4);border-radius:8px;padding:6px;direction:ltr}
.seat{display:flex;justify-content:space-between;align-items:center;padding:8px;margin:5px 0;border:1px solid rgba(56,225,255,.25);border-radius:8px;background:rgba(0,0,0,.3)}
.tag{padding:2px 8px;border-radius:9px;font-size:12px;background:#234}.tag.ok{background:#0a5a35}.tag.no{background:#6a1a2a}
.card{padding:9px;margin:5px 0;border:1px solid rgba(56,225,255,.25);border-radius:9px;background:rgba(0,0,0,.3);cursor:pointer}
.card.sel{border-color:#3dff9a;box-shadow:0 0 12px rgba(61,255,154,.4)}.card.lk{opacity:.4}
.bar{height:6px;background:#123;border-radius:3px;overflow:hidden;margin:2px 0}.bar i{display:block;height:100%;background:var(--a)}
#toast{position:fixed;top:12px;left:50%;transform:translateX(-50%) translateY(-80px);background:#06121f;border:1px solid var(--a);padding:8px 16px;border-radius:10px;z-index:99;transition:.3s;max-width:90%;text-align:center}
#toast.on{transform:translateX(-50%) translateY(0)}
#fatal{position:fixed;inset:0;background:#000d;z-index:100;display:none;align-items:center;justify-content:center;padding:30px;text-align:center;font-size:18px}
.ic{width:60%;height:60%;fill:none;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
#hud,#ctl{position:fixed;inset:0;display:none;pointer-events:none;z-index:5}
#hud.on,#ctl.on{display:block}
#hb{position:absolute;top:max(8px,env(safe-area-inset-top));left:8px;width:150px;font-size:11px}
.hb{display:flex;align-items:center;gap:5px;margin:2px 0}.hb span{width:44px}.hb i{flex:1;height:7px;background:rgba(0,0,0,.5);border:1px solid rgba(255,255,255,.2)}.hb b{display:block;height:100%}
#hs{margin-top:3px;font:700 14px monospace;direction:ltr;text-align:left}
#ht{position:absolute;top:max(8px,env(safe-area-inset-top));left:50%;transform:translateX(-50%);text-align:center;font:700 16px monospace;text-shadow:0 0 6px #000;direction:ltr}
#mm{position:absolute;top:max(44px,calc(env(safe-area-inset-top) + 36px));right:8px;width:96px;height:96px;opacity:.9}
#cn{position:absolute;top:max(8px,env(safe-area-inset-top));right:60px;font-size:11px;opacity:.8;direction:ltr}
#tg{position:absolute;width:44px;height:44px;margin:-22px;border:2px solid #ff4f6d;transform:rotate(45deg) scale(.6);display:none;box-shadow:0 0 8px #ff4f6d}
#td{position:absolute;font:700 11px monospace;color:#ff8097;display:none;direction:ltr}
#cross{position:absolute;left:50%;top:50%;width:26px;height:26px;margin:-13px;border:1.5px solid rgba(56,225,255,.6);border-radius:50%}
#vig{position:absolute;inset:0;box-shadow:inset 0 0 120px 30px rgba(255,0,40,.7);opacity:0;transition:opacity .35s}
#msg{position:absolute;top:30%;left:0;right:0;text-align:center;font:700 22px 'Segoe UI';text-shadow:0 0 10px #000}
#vh{position:absolute;bottom:10px;left:0;right:0;display:none;justify-content:center;gap:30px;font-size:14px}
.stk{position:absolute;bottom:calc(16px*var(--bs) + env(safe-area-inset-bottom));width:calc(124px*var(--bs));height:calc(124px*var(--bs));border-radius:50%;border:2px solid rgba(56,225,255,.55);background:rgba(8,16,30,.35);pointer-events:auto;opacity:var(--bo);touch-action:none}
.stk i{position:absolute;left:50%;top:50%;width:46%;height:46%;margin:-23%;border-radius:50%;background:radial-gradient(#8ff,#1aa);box-shadow:0 0 12px var(--a)}
#sl{left:14px}#sr{right:14px}
.fb,.xb{position:absolute;border-radius:50%;border:2px solid var(--a);background:rgba(8,16,30,.45);color:#dff6ff;display:flex;align-items:center;justify-content:center;pointer-events:auto;opacity:var(--bo);touch-action:none}
.fb.dn,.xb.dn{background:var(--a);color:#001018}
.dia{position:absolute;right:calc(150px*var(--bs));bottom:calc(14px*var(--bs) + env(safe-area-inset-bottom));width:calc(138px*var(--bs));height:calc(138px*var(--bs))}
.fb{width:calc(50px*var(--bs));height:calc(50px*var(--bs))}
#bf{bottom:0;left:50%;margin-left:calc(-25px*var(--bs));border-color:#4da6ff}#bm{right:0;top:50%;margin-top:calc(-25px*var(--bs));border-color:#ff4f6d}
#bs{left:0;top:50%;margin-top:calc(-25px*var(--bs));border-color:#ff8ad8}#bb{top:0;left:50%;margin-left:calc(-25px*var(--bs));border-color:#3dff9a}
.xb{width:calc(46px*var(--bs));height:calc(46px*var(--bs))}
#bk{left:calc(16px*var(--bs));bottom:calc(150px*var(--bs) + env(safe-area-inset-bottom))}
#bp{right:10px;top:max(8px,env(safe-area-inset-top));width:40px;height:40px}
#bk2{left:calc(72px*var(--bs));bottom:calc(150px*var(--bs) + env(safe-area-inset-bottom))}
.st{width:100%;border-collapse:collapse;font-size:13px}.st td,.st th{padding:4px;border-bottom:1px solid #234;text-align:center}
@media (max-height:430px){h1{font-size:22px}.b{padding:7px;margin:3px 0}.scr{padding-top:6px}}
</style></head><body>
<canvas id="gl"></canvas>
<svg width="0" height="0" style="position:absolute"><defs>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M5 5l14 14M19 5L5 19"/></symbol>
<symbol id="i-o" viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/></symbol>
<symbol id="i-sq" viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="1"/></symbol>
<symbol id="i-tr" viewBox="0 0 24 24"><path d="M12 4l9 15H3z"/></symbol>
<symbol id="i-bk" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14M4 12h16"/></symbol>
<symbol id="i-rl" viewBox="0 0 24 24"><path d="M4 12a8 8 0 1 0 3-6M4 4v5h5"/></symbol>
<symbol id="i-ps" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></symbol>
</defs></svg>
<div id="fatal"></div><div id="toast"></div>

<section class="scr on" id="home"><div class="pn">
<h1>SPACE WAR ELITE</h1><div class="sub">حرب فضائية ثلاثية الأبعاد - لاعبان أونلاين</div>
<input type="text" id="nick" maxlength="16" placeholder="اسم الطيار">
<div class="g2"><button class="b g" id="bCamp">الحملة (20 مهمة)</button><button class="b" id="bTrain">تدريب ضد الذكاء الاصطناعي</button>
<button class="b" id="bRooms">غرفة لاعبين</button><button class="b" id="bShips">اختيار المركبة</button>
<button class="b" id="bStats">السجل والإحصائيات</button><button class="b" id="bSet">الإعدادات</button></div>
<button class="b" id="bHelp">المساعدة وطريقة اللعب</button></div></section>

<section class="scr" id="camp"><div class="pn"><h2>الحملة</h2><div id="mlist"></div><button class="b" data-go="home">رجوع</button></div></section>

<section class="scr" id="rooms"><div class="pn"><h2>إنشاء غرفة</h2>
<select id="cmode"><option value="pvp">أنا لاعب (جهازي هو اللاعب الأول)</option><option value="display">شاشة كبيرة + هاتفان (جهازي للعرض فقط)</option></select>
<select id="cenv"></select><button class="b g" id="bCreate">إنشاء غرفة جديدة</button>
<h2 style="margin-top:12px">الانضمام إلى غرفة</h2>
<input type="text" id="jc" maxlength="6" placeholder="رمز الغرفة" style="direction:ltr;text-transform:uppercase">
<input type="text" id="jk" maxlength="8" placeholder="رمز الدخول" style="direction:ltr;text-transform:uppercase">
<button class="b" id="bJoin">انضمام</button><button class="b" data-go="home">رجوع</button></div></section>

<section class="scr" id="lobby"><div class="pn"><h2 id="lt">الغرفة</h2>
<div id="lcodes"><div class="sub">رمز الغرفة</div><div class="code" id="lc"></div><button class="b" id="cc">نسخ رمز الغرفة</button>
<div class="sub">رمز الدخول (منفصل)</div><div class="code" id="lk"></div><button class="b" id="ck">نسخ رمز الدخول</button>
<button class="b" id="cl">نسخ رابط الانضمام</button></div>
<div class="row"><b id="lp"></b><span id="lm" class="sub"></span></div><div id="seats"></div>
<select id="lship"></select><button class="b" id="bReady">جاهز</button>
<button class="b g" id="bStart">بدء المباراة</button><button class="b d" id="bLeave">مغادرة</button><button class="b d" id="bClose">إغلاق الغرفة</button></div></section>

<section class="scr" id="ships"><div class="pn"><h2>المركبات</h2><div id="slist"></div><button class="b" data-go="home">رجوع</button></div></section>
<section class="scr" id="stats"><div class="pn"><h2>سجل الطيار</h2><div id="sbody"></div><button class="b" data-go="home">رجوع</button></div></section>

<section class="scr" id="set"><div class="pn"><h2>الإعدادات</h2>
<div class="row">مستوى الصوت<input type="range" min="0" max="1" step=".05" data-k="vol"></div>
<div class="row">الموسيقى<input type="range" min="0" max="1" step=".05" data-k="mus"></div>
<div class="row">كتم الصوت<input type="checkbox" data-k="mute"></div>
<div class="row">الحساسية<input type="range" min=".4" max="2" step=".1" data-k="sens"></div>
<div class="row">اهتزاز الكاميرا<input type="range" min="0" max="2" step=".1" data-k="shake"></div>
<div class="row">عكس المحور الرأسي<input type="checkbox" data-k="inv"></div>
<div class="row">حجم أزرار التحكم<input type="range" min=".7" max="1.4" step=".05" data-k="bs"></div>
<div class="row">شفافية الأزرار<input type="range" min=".3" max="1" step=".05" data-k="bo"></div>
<div class="row">جودة الرسومات (عند بدء المعركة)<select data-k="q" style="width:auto"><option value="low">منخفضة</option><option value="med">متوسطة</option><option value="high">عالية</option></select></div>
<button class="b" id="bReset">إعادة ضبط التحكم</button><button class="b" data-go="home">رجوع</button></div></section>

<section class="scr" id="help"><div class="pn"><h2>طريقة اللعب</h2><div style="font-size:13px;line-height:1.8">
العصا اليسرى: للأعلى تسارع، للأسفل فرملة/رجوع، يميناً ويساراً دوران جانبي.<br>
العصا اليمنى: توجيه السفينة (يمين/يسار) ورفع وخفض المقدمة.<br>
الأزرار: X إطلاق ليزر، Circle صاروخ موجه، Square درع (يستهلك طاقة)، Triangle تعزيز سرعة، زر الفرملة.<br>
لوحة المفاتيح: الأسهم للتوجيه، Q/E دوران، W/S سرعة، Space ليزر، F صاروخ، Shift تعزيز، C درع، X فرملة، Esc إيقاف.<br>
الليزر يستهلك الطاقة، فإذا نفدت يسخن السلاح لحظات. الدرع يتجدد إذا لم تُصَب 3 ثوانٍ.<br>
المباراة: أول من يصل إلى 5 قتلى أو الأكثر قتلاً بعد 4 دقائق.<br>
لعبة أونلاين: أنشئ غرفة وأرسل الرمزين أو الرابط للاعب الآخر. وضع الشاشة الكبيرة: افتح اللعبة على الحاسوب واختر وضع العرض، ثم ينضم هاتفان كجهازي تحكم.</div>
<button class="b" data-go="home">رجوع</button></div></section>

<section class="scr" id="res"><div class="pn"><h1 id="rt" style="font-size:34px">-</h1><div class="sub" id="rw"></div>
<table class="st" id="rs"></table><div class="sub" id="rr"></div>
<button class="b g" id="bAgain">مباراة جديدة</button><button class="b d" id="bExit">خروج</button></div></section>

<section class="scr" id="pause" style="background:rgba(0,0,0,.6);z-index:20"><div class="pn"><h2>إيقاف مؤقت</h2>
<div class="row">مستوى الصوت<input type="range" min="0" max="1" step=".05" data-k="vol"></div>
<div class="row">الموسيقى<input type="range" min="0" max="1" step=".05" data-k="mus"></div>
<div class="row">كتم الصوت<input type="checkbox" data-k="mute"></div>
<div class="row">اهتزاز الكاميرا<input type="range" min="0" max="2" step=".1" data-k="shake"></div>
<button class="b g" id="bResume">استئناف</button><button class="b d" id="bQuit">خروج من المباراة</button></div></section>

<div id="hud"><div id="hb">
<div class="hb"><span>الهيكل</span><i><b id="bh" style="background:#3dff9a"></b></i></div>
<div class="hb"><span>الدرع</span><i><b id="bsh" style="background:#38e1ff"></b></i></div>
<div class="hb"><span>الطاقة</span><i><b id="ben" style="background:#ffd23a"></b></i></div>
<div id="hs"></div></div>
<div id="ht"></div><canvas id="mm" width="96" height="96"></canvas><div id="cn"></div>
<div id="cross"></div><div id="tg"></div><div id="td"></div><div id="vig"></div><div id="msg"></div><div id="vh"></div></div>

<div id="ctl">
<div class="stk" id="sl"><i></i></div><div class="stk" id="sr"><i></i></div>
<div class="dia"><div class="fb" id="bf" title="ليزر"><svg class="ic"><use href="#i-x"/></svg></div>
<div class="fb" id="bm" title="صاروخ"><svg class="ic"><use href="#i-o"/></svg></div>
<div class="fb" id="bs" title="درع"><svg class="ic"><use href="#i-sq"/></svg></div>
<div class="fb" id="bb" title="تعزيز"><svg class="ic"><use href="#i-tr"/></svg></div></div>
<div class="xb" id="bk" title="فرملة"><svg class="ic"><use href="#i-bk"/></svg></div>
<div class="xb" id="bp" style="pointer-events:auto"><svg class="ic"><use href="#i-ps"/></svg></div></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
<script>
(()=>{'use strict';
const $=s=>document.querySelector(s),$$=s=>document.querySelectorAll(s);
const clamp=(x,a,b)=>x<a?a:x>b?b:x;
function toast(m,t){const e=$('#toast');e.textContent=m;e.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(()=>e.classList.remove('on'),t||2800)}
function fatal(m){const f=$('#fatal');f.style.display='flex';f.textContent=m}
let cur='home';
function show(id){$$('.scr').forEach(s=>s.classList.toggle('on',s.id===id));cur=id}
let TOK=localStorage.swe_tok;if(!TOK){TOK=[...crypto.getRandomValues(new Uint8Array(16))].map(b=>b.toString(16).padStart(2,'0')).join('');localStorage.swe_tok=TOK}
const DEF={vol:.8,mus:.5,mute:false,q:'med',sens:1,shake:1,inv:false,bs:1,bo:.85,ship:'rookie'};
let ST=Object.assign({},DEF);try{Object.assign(ST,JSON.parse(localStorage.swe_st||'{}'))}catch(e){}
let stT=0;
function saveST(){localStorage.swe_st=JSON.stringify(ST);applyST();clearTimeout(stT);stT=setTimeout(()=>sock&&sock.emit('save',{tok:TOK,st:JSON.stringify(ST)}),700)}
function syncUI(){$$('[data-k]').forEach(e=>{const k=e.dataset.k;if(e.type==='checkbox')e.checked=!!ST[k];else e.value=ST[k]})}
function applyST(){document.documentElement.style.setProperty('--bs',ST.bs);document.documentElement.style.setProperty('--bo',ST.bo);A.vol()}
$$('[data-k]').forEach(e=>e.addEventListener('input',()=>{const k=e.dataset.k;ST[k]=e.type==='checkbox'?e.checked:(e.tagName==='SELECT'?e.value:+e.value);syncUI();saveST()}));
$('#bReset').onclick=()=>{ST.bs=1;ST.bo=.85;syncUI();saveST();toast('تمت إعادة ضبط التحكم')};
$$('[data-go]').forEach(b=>b.onclick=()=>{A.click();show(b.dataset.go)});

// ================= الصوت =================
const A={ctx:null,intense:false};
A.init=()=>{if(A.ctx){if(A.ctx.state==='suspended')A.ctx.resume();return}
 const C=window.AudioContext||window.webkitAudioContext;if(!C)return;const c=A.ctx=new C();
 A.m=c.createGain();A.m.connect(c.destination);A.sx=c.createGain();A.sx.connect(A.m);A.mu=c.createGain();A.mu.connect(A.m);
 const n=c.createBuffer(1,c.sampleRate*2,c.sampleRate),d=n.getChannelData(0);for(let i=0;i<d.length;i++)d[i]=Math.random()*2-1;A.nb=n;
 A.eo=c.createOscillator();A.eo.type='sawtooth';A.eo.frequency.value=48;const f=c.createBiquadFilter();f.type='lowpass';f.frequency.value=260;A.eg=c.createGain();A.eg.gain.value=0;
 A.eo.connect(f);f.connect(A.eg);A.eg.connect(A.sx);A.eo.start();A.vol();A.music()};
A.vol=()=>{if(!A.ctx)return;A.m.gain.value=ST.mute?0:ST.vol;A.mu.gain.value=ST.mus*.45};
A.tone=(f0,f1,d,ty,g)=>{if(!A.ctx)return;const c=A.ctx,t=c.currentTime,o=c.createOscillator(),v=c.createGain();o.type=ty;o.frequency.setValueAtTime(f0,t);o.frequency.exponentialRampToValueAtTime(Math.max(1,f1),t+d);v.gain.setValueAtTime(g,t);v.gain.exponentialRampToValueAtTime(.001,t+d);o.connect(v);v.connect(A.sx);o.start(t);o.stop(t+d+.02)};
A.noise=(d,g,f0,f1)=>{if(!A.ctx)return;const c=A.ctx,t=c.currentTime,s=c.createBufferSource(),f=c.createBiquadFilter(),v=c.createGain();s.buffer=A.nb;f.type='lowpass';f.frequency.setValueAtTime(f0,t);f.frequency.exponentialRampToValueAtTime(f1,t+d);v.gain.setValueAtTime(g,t);v.gain.exponentialRampToValueAtTime(.001,t+d);s.connect(f);f.connect(v);v.connect(A.sx);s.start(t);s.stop(t+d)};
A.laser=v=>A.tone(1000,220,.16,'sawtooth',.09*v);A.missile=v=>{A.noise(.7,.18*v,3000,300);A.tone(220,70,.5,'sawtooth',.07*v)};
A.boom=(v,b)=>{A.noise(b?1.4:.8,.5*v,1600,50);A.tone(95,22,b?1:.6,'sine',.45*v)};
A.hit=v=>A.tone(320,90,.14,'square',.14*v);A.click=()=>A.tone(600,900,.05,'triangle',.08);
A.alarm=()=>{A.tone(880,880,.1,'square',.07);setTimeout(()=>A.tone(880,880,.1,'square',.07),180)};
A.win=()=>[523,659,784,1047].forEach((f,i)=>setTimeout(()=>A.tone(f,f,.35,'triangle',.2),i*140));
A.lose=()=>[392,330,262,196].forEach((f,i)=>setTimeout(()=>A.tone(f,f*.97,.45,'sawtooth',.12),i*200));
A.music=()=>{const c=A.ctx,bt=60/84/2,CH=[[57,60,64],[53,57,60],[48,52,55],[55,59,62]],F=n=>440*Math.pow(2,(n-69)/12);let next=c.currentTime+.1,bar=0,st=0;
 const note=(f,t,d,ty,g,fl)=>{const o=c.createOscillator(),v=c.createGain(),l=c.createBiquadFilter();o.type=ty;o.frequency.value=f;l.type='lowpass';l.frequency.value=fl;v.gain.setValueAtTime(0,t);v.gain.linearRampToValueAtTime(g,t+Math.min(.9,d*.3));v.gain.linearRampToValueAtTime(0,t+d);o.connect(l);l.connect(v);v.connect(A.mu);o.start(t);o.stop(t+d+.05)};
 setInterval(()=>{while(next<c.currentTime+.6){const ch=CH[bar%4];
  if(st%8===0)ch.forEach(n=>{note(F(n),next,bt*8,'triangle',.07,900);note(F(n)*1.004,next,bt*8,'sawtooth',.018,600)});
  if(st%4===0)note(F(ch[0]-24),next,bt*3.5,'sine',.22,300);
  if(st%2===0&&(A.intense||Math.random()<.5))note(F(ch[(st>>1)%3]+12+((st&4)?12:0)),next,bt*1.6,'triangle',.05,2200);
  if(A.intense&&st%4===0){const t=next-c.currentTime;setTimeout(()=>A.tone(130,40,.15,'sine',.3),Math.max(0,t*1000))}
  st++;if(st%8===0)bar++;next+=bt}},200)};
document.addEventListener('pointerdown',()=>A.init(),{once:false});document.addEventListener('keydown',()=>A.init());

// ================= الرسوم ثلاثية الأبعاد =================
const h3=(x,y,z)=>{const h=Math.sin(x*127.1+y*311.7+z*74.7)*43758.5453;return h-Math.floor(h)};
const lp=(a,b,t)=>a+(b-a)*t;
function n3(x,y,z){const xi=Math.floor(x),yi=Math.floor(y),zi=Math.floor(z),xf=x-xi,yf=y-yi,zf=z-zi,u=xf*xf*(3-2*xf),v=yf*yf*(3-2*yf),w=zf*zf*(3-2*zf);
 return lp(lp(lp(h3(xi,yi,zi),h3(xi+1,yi,zi),u),lp(h3(xi,yi+1,zi),h3(xi+1,yi+1,zi),u),v),lp(lp(h3(xi,yi,zi+1),h3(xi+1,yi,zi+1),u),lp(h3(xi,yi+1,zi+1),h3(xi+1,yi+1,zi+1),u),v),w)}
function fb3(x,y,z,o){let a=.5,s=0;for(let i=0;i<o;i++){s+=a*n3(x,y,z);x*=2.1;y*=2.1;z*=2.1;a*=.5}return s}
const RGB=h=>[h>>16&255,h>>8&255,h&255];
const E=(sd,sun,p1,p2,p3,n1,n2,st,na)=>({sd,sun,pl:[p1,p2,p3],neb:[n1,n2],st,na});
const ENV=[E([.6,.3,.5],0xfff2dd,0x3a2d24,0x8a7358,0xb9a98c,'#3b2a7a','#0b4a6a',0,.25),E([.7,.2,.4],0xffe2b0,0x7a3a1a,0xd08a4a,0xf0c890,'#6a2a1a','#7a4a1a',0,.3),
E([.3,.5,.7],0xdfe8ff,0x2a2d33,0x6a7078,0x9aa0a8,'#1a2a4a','#2a1a4a',0,.25),E([.5,.4,.6],0xffffff,0x233044,0x5a7090,0x9ab4d0,'#142a4a','#0a3a3a',1,.2),
E([.8,.1,.3],0xffb060,0x502010,0xc05a20,0xffc080,'#7a2a0a','#6a1a2a',0,.35),E([.4,.4,.6],0xd8e8ff,0x1a2a40,0x2a6a8a,0x6ab0d0,'#7a1a7a','#0a6a8a',0,.65),
E([.6,.5,.4],0xfff0d0,0x3a3328,0x7a6a50,0xa09070,'#3a2a1a','#1a3a2a',1,.25),E([.5,.2,.8],0xeaf2ff,0x2a2830,0x605a68,0x8a8490,'#2a1a5a','#1a3a5a',0,.4),
E([.7,.4,.3],0xf0f8ff,0x5a7a9a,0xc0daf0,0xffffff,'#1a3a6a','#2a5a7a',0,.3),E([.4,.3,.8],0xfff8ee,0x30302e,0x6a6a66,0xa0a09a,'#2a2a3a','#3a2a2a',0,.2)];
const SV={viper:{L:15,r:1.5,sp:10,ch:5,col:0x9fb4c8,en:1,sw:.45},falcon:{L:19,r:2.1,sp:13,ch:7,col:0xb9c2ca,en:2,sw:.25},lancer:{L:23,r:1.3,sp:8,ch:6,col:0x7d8fb0,en:2,sw:1},
titan:{L:25,r:3.6,sp:19,ch:10,col:0x6c7076,en:4,sw:0},ghost:{L:19,r:1.1,sp:16,ch:11,col:0x1b2027,en:1,sw:.8,flat:1},aegis:{L:21,r:2.8,sp:15,ch:6,col:0xcfd8de,en:2,sw:0,ring:1},rookie:{L:17,r:2.2,sp:12,ch:7,col:0xaab4a2,en:2,sw:.35}};
const TC=[0x38e1ff,0xffa23a,0xff3d5a];
let GL=null;
function glowTex(){const c=document.createElement('canvas');c.width=c.height=64;const x=c.getContext('2d'),g=x.createRadialGradient(32,32,0,32,32,32);g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.25,'rgba(255,255,255,.55)');g.addColorStop(1,'rgba(255,255,255,0)');x.fillStyle=g;x.fillRect(0,0,64,64);return new THREE.CanvasTexture(c)}
function initGL(){
 try{const T=THREE,cv=$('#gl'),r=new T.WebGLRenderer({canvas:cv,antialias:ST.q!=='low',powerPreference:'high-performance'});
 r.toneMapping=T.ACESFilmicToneMapping;r.toneMappingExposure=1.15;r.outputEncoding=T.sRGBEncoding;
 const sc=new T.Scene(),cam=new T.PerspectiveCamera(70,1,.5,9000);sc.add(cam);
 const g={T,r,sc,cam,glow:glowTex(),world:new T.Group(),sky:new T.Group(),ships:new T.Group(),pj:new T.Group()};
 sc.add(g.world,g.sky,g.ships,g.pj);
 // بيئة انعكاسية
 const ec=document.createElement('canvas');ec.width=512;ec.height=256;const ex=ec.getContext('2d'),gr=ex.createLinearGradient(0,0,0,256);gr.addColorStop(0,'#1a2a50');gr.addColorStop(.5,'#05070d');gr.addColorStop(1,'#10151f');ex.fillStyle=gr;ex.fillRect(0,0,512,256);
 ex.fillStyle='#fff';ex.fillRect(60,70,90,18);ex.fillStyle='#ffd9a0';ex.fillRect(300,90,40,40);for(let i=0;i<80;i++)ex.fillRect(Math.random()*512,Math.random()*256,2,2);
 const es=new T.Scene(),em=new T.Mesh(new T.SphereGeometry(50,32,16),new T.MeshBasicMaterial({map:new T.CanvasTexture(ec),side:T.BackSide}));es.add(em);
 const pm=new T.PMREMGenerator(r);sc.environment=pm.fromScene(es,.02).texture;
 sc.add(new T.HemisphereLight(0x223355,0x080808,.45));
 g.sun=new T.DirectionalLight(0xffffff,2.4);sc.add(g.sun);
 // جزيئات
 const NP=420,geo=new T.BufferGeometry();g.P={pos:new Float32Array(NP*3),col:new Float32Array(NP*4),siz:new Float32Array(NP),vel:new Float32Array(NP*3),life:new Float32Array(NP),max:new Float32Array(NP),i:0,cap:150,N:NP};
 geo.setAttribute('position',new T.BufferAttribute(g.P.pos,3));geo.setAttribute('aC',new T.BufferAttribute(g.P.col,4));geo.setAttribute('aS',new T.BufferAttribute(g.P.siz,1));
 g.pmat=new T.ShaderMaterial({transparent:true,depthWrite:false,blending:T.AdditiveBlending,uniforms:{uK:{value:600}},
  vertexShader:'attribute vec4 aC;attribute float aS;varying vec4 vC;uniform float uK;void main(){vC=aC;vec4 mv=modelViewMatrix*vec4(position,1.);gl_PointSize=aS*uK/(-mv.z);gl_Position=projectionMatrix*mv;}',
  fragmentShader:'varying vec4 vC;void main(){float d=length(gl_PointCoord-.5)*2.;float a=smoothstep(1.,0.,d);gl_FragColor=vec4(vC.rgb,a*vC.a);}'});
 g.pts=new T.Points(geo,g.pmat);g.pts.frustumCulled=false;sc.add(g.pts);g.pgeo=geo;
 return g}catch(e){console.error(e);return null}}
function clearGroup(gr){while(gr.children.length){const c=gr.children.pop();c.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material){if(o.material.map)o.material.map.dispose();o.material.dispose()}})}}
function planetTex(env,q){const w=q==='low'?256:512,h=w/2,c=document.createElement('canvas');c.width=w;c.height=h;const x=c.getContext('2d'),im=x.createImageData(w,h),p=env.pl.map(RGB),dp=im.data;
 for(let j=0;j<h;j++){const la=(j/h-.5)*Math.PI,cy=Math.cos(la),sy=Math.sin(la);for(let i=0;i<w;i++){const lo=i/w*6.2832,X=cy*Math.cos(lo),Z=cy*Math.sin(lo),n=fb3(X*3,sy*3,Z*3,q==='low'?3:5),t=clamp((n-.3)/.4,0,1),k=(j*w+i)*4;
  const ice=Math.abs(sy)>.88?clamp((Math.abs(sy)-.88)*12,0,1)*(env.pl[2]>0x909090?1:.5):0;
  for(let a=0;a<3;a++){let v=t<.5?lp(p[0][a],p[1][a],t*2):lp(p[1][a],p[2][a],(t-.5)*2);v=lp(v,235,ice);dp[k+a]=v}dp[k+3]=255}}
 x.putImageData(im,0,0);return new THREE.CanvasTexture(c)}
function buildWorld(ei,obs){const T=THREE,g=GL,env=ENV[ei],q=ST.q;clearGroup(g.world);clearGroup(g.sky);
 g.sun.color.setHex(env.sun);g.sun.position.set(env.sd[0],env.sd[1],env.sd[2]).multiplyScalar(1000);
 const ns=q==='low'?2500:q==='med'?5000:9000,sp=new Float32Array(ns*3),sc=new Float32Array(ns*3);
 for(let i=0;i<ns;i++){const u=Math.random()*2-1,a=Math.random()*6.283,r=Math.sqrt(1-u*u),R=6000;sp[i*3]=r*Math.cos(a)*R;sp[i*3+1]=u*R;sp[i*3+2]=r*Math.sin(a)*R;const t=Math.random(),b=.5+Math.random()*.5;sc[i*3]=b*(t>.8?1:.8+t*.2);sc[i*3+1]=b*(.85+t*.1);sc[i*3+2]=b*(t<.3?1:.9)}
 const sg=new T.BufferGeometry();sg.setAttribute('position',new T.BufferAttribute(sp,3));sg.setAttribute('color',new T.BufferAttribute(sc,3));
 g.sky.add(new T.Points(sg,new T.PointsMaterial({size:1.7,sizeAttenuation:false,vertexColors:true,fog:false})));
 for(let i=0;i<7;i++){const c=document.createElement('canvas');c.width=c.height=128;const x=c.getContext('2d'),gr=x.createRadialGradient(64,64,0,64,64,64);gr.addColorStop(0,env.neb[i%2]);gr.addColorStop(1,'rgba(0,0,0,0)');x.globalAlpha=1;x.fillStyle=gr;x.fillRect(0,0,128,128);
  const s=new T.Sprite(new T.SpriteMaterial({map:new T.CanvasTexture(c),transparent:true,opacity:env.na*(.5+Math.random()*.6),blending:T.AdditiveBlending,depthWrite:false,fog:false}));
  const a=Math.random()*6.283,e=(Math.random()-.5)*1.2;s.position.set(Math.cos(a)*5200,e*3000,Math.sin(a)*5200);s.scale.setScalar(3500+Math.random()*3500);g.sky.add(s)}
 const sf=new T.Sprite(new T.SpriteMaterial({map:g.glow,color:env.sun,blending:T.AdditiveBlending,depthWrite:false,transparent:true,fog:false}));sf.position.set(env.sd[0],env.sd[1],env.sd[2]).normalize().multiplyScalar(5500);sf.scale.setScalar(ei===4?2600:900);g.sky.add(sf);
 // كوكب وكويكبات
 const tx=planetTex(env,q),pl=obs[0];
 const pm=new T.Mesh(new T.SphereGeometry(pl[3],q==='low'?32:64,q==='low'?20:40),new T.MeshStandardMaterial({map:tx,bumpMap:tx,bumpScale:3,roughness:.92,metalness:0}));pm.position.set(pl[0],pl[1],pl[2]);g.world.add(pm);
 const at=new T.Mesh(new T.SphereGeometry(pl[3]*1.05,32,20),new T.ShaderMaterial({transparent:true,blending:T.AdditiveBlending,depthWrite:false,uniforms:{c:{value:new T.Color(env.pl[2])}},
  vertexShader:'varying vec3 n;varying vec3 v;void main(){n=normalize(normalMatrix*normal);v=normalize(-(modelViewMatrix*vec4(position,1.)).xyz);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
  fragmentShader:'uniform vec3 c;varying vec3 n;varying vec3 v;void main(){float f=pow(1.-abs(dot(n,v)),3.);gl_FragColor=vec4(c*1.3,f*.8);}'}));at.position.copy(pm.position);g.world.add(at);
 const gs=[0,1,2].map(k=>{const geo=new T.IcosahedronGeometry(1,q==='low'?1:2),pa=geo.attributes.position;for(let i=0;i<pa.count;i++){const x=pa.getX(i),y=pa.getY(i),z=pa.getZ(i),n=.7+.6*fb3(x*1.7+k*9,y*1.7,z*1.7,3);pa.setXYZ(i,x*n,y*n*(.8+k*.1),z*n)}geo.computeVertexNormals();return geo});
 const am=new T.MeshStandardMaterial({color:ei===8?0xaac4d8:0x6f6459,roughness:1,metalness:.05,flatShading:true});
 for(let i=1;i<obs.length;i++){const o=obs[i],m=new T.Mesh(gs[i%3],am);m.position.set(o[0],o[1],o[2]);m.scale.setScalar(o[3]);m.rotation.set(i,i*2,i*3);g.world.add(m)}
 if(env.st){const st=new T.Group(),mm=new T.MeshStandardMaterial({color:0x8a949c,metalness:.9,roughness:.4}),ma=new T.MeshBasicMaterial({color:0x38e1ff});
  const tor=new T.Mesh(new T.TorusGeometry(40,3,10,40),mm);st.add(tor);const hub=new T.Mesh(new T.CylinderGeometry(9,9,50,16),mm);hub.rotation.x=Math.PI/2;st.add(hub);
  for(let k=0;k<4;k++){const sp=new T.Mesh(new T.BoxGeometry(80,2,2),mm);sp.rotation.z=k*Math.PI/4;st.add(sp)}for(let k=0;k<20;k++){const l=new T.Mesh(new T.BoxGeometry(2,2,2),ma);const a=k/20*6.283;l.position.set(Math.cos(a)*40,Math.sin(a)*40,3);st.add(l)}
  st.position.set(0,180,-700);st.rotation.set(.4,.3,0);g.station=st;g.world.add(st)}
 const nd=q==='low'?150:400,dp=new Float32Array(nd*3);for(let i=0;i<nd*3;i++)dp[i]=(Math.random()-.5)*600;const dg=new T.BufferGeometry();dg.setAttribute('position',new T.BufferAttribute(dp,3));
 g.dust=new T.Points(dg,new T.PointsMaterial({size:1.4,sizeAttenuation:false,color:0x9fc8ff,transparent:true,opacity:.55}));g.dust.frustumCulled=false;g.world.add(g.dust);
 g.P.cap=q==='low'?150:q==='med'?280:420;applyQ()}
function applyQ(){const g=GL,pr={low:1,med:Math.min(devicePixelRatio,1.5),high:Math.min(devicePixelRatio,2)}[ST.q];g.r.setPixelRatio(pr);resize()}
function resize(){if(!GL)return;const w=innerWidth,h=innerHeight;GL.r.setSize(w,h,false);GL.cam.aspect=w/h;GL.cam.updateProjectionMatrix();GL.pmat.uniforms.uK.value=h*GL.r.getPixelRatio()*.75}
addEventListener('resize',resize);
function makeShip(kind,ti){const T=THREE,v=SV[kind]||SV.rookie,g=new T.Group(),acc=TC[ti]!==undefined?TC[ti]:TC[2];
 const mb=new T.MeshStandardMaterial({color:v.col,metalness:.92,roughness:.3,side:T.DoubleSide}),ma=new T.MeshBasicMaterial({color:acc});
 const body=new T.Mesh(new T.ConeGeometry(v.r,v.L,v.flat?4:16),mb);body.rotation.x=-Math.PI/2;body.scale.set(v.flat?1.6:1.15,1,v.flat?.35:.7);g.add(body);
 const rear=new T.Mesh(new T.CylinderGeometry(v.r*.8,v.r*.95,v.L*.3,16),mb);rear.rotation.x=Math.PI/2;rear.position.z=v.L*.4;rear.scale.set(1.1,1,.75);g.add(rear);
 const sh=new T.Shape();sh.moveTo(0,0);sh.lineTo(v.sp,v.sw*v.sp*.9);sh.lineTo(v.sp,v.sw*v.sp*.9+v.ch*.3);sh.lineTo(0,v.ch);
 const wg=new T.ExtrudeGeometry(sh,{depth:.35,bevelEnabled:false});
 for(const s of[-1,1]){const w=new T.Mesh(wg,mb);w.rotation.x=Math.PI/2;w.scale.x=s;w.position.set(s*v.r*.5,-.1,v.L*.5-v.ch*1.05);g.add(w);
  const st=new T.Mesh(new T.BoxGeometry(.35,.35,v.ch*.5),ma);st.position.set(s*(v.r*.5+v.sp),0,v.L*.5-v.ch*1.05+v.sw*v.sp*.9+v.ch*.2);g.add(st)}
 const fin=new T.Mesh(new T.BoxGeometry(.3,v.r*1.7,v.ch*.7),mb);fin.position.set(0,v.r*.8,v.L*.36);g.add(fin);
 const ck=new T.Mesh(new T.SphereGeometry(v.r*.55,14,10),new T.MeshStandardMaterial({color:0x061018,metalness:1,roughness:.08,emissive:0x0a2030}));ck.scale.set(1,.7,1.9);ck.position.set(0,v.r*.45,-v.L*.1);g.add(ck);
 if(v.ring){const rg=new T.Mesh(new T.TorusGeometry(v.r*2.3,.3,8,30),ma);rg.position.z=v.L*.1;g.add(rg)}
 const fl=[];for(let k=0;k<v.en;k++){const xx=v.en===1?0:(k-(v.en-1)/2)*v.r*(v.en>2?.75:1.7);const nz=new T.Mesh(new T.CylinderGeometry(v.r*.38,v.r*.5,2,12),new T.MeshStandardMaterial({color:0x222222,metalness:1,roughness:.4}));nz.rotation.x=Math.PI/2;nz.position.set(xx,0,v.L*.5+.5);g.add(nz);
  const s=new T.Sprite(new T.SpriteMaterial({map:GL.glow,color:acc,blending:T.AdditiveBlending,depthWrite:false,transparent:true}));s.position.set(xx,0,v.L*.5+2);s.scale.setScalar(v.r*3);g.add(s);fl.push(s)}
 g.userData={fl,r:v.r,acc};return g}
function emit(x,y,z,vx,vy,vz,life,size,r,gg,b){const P=GL.P;if(P.cap<=0)return;const i=P.i=(P.i+1)%P.cap;P.pos[i*3]=x;P.pos[i*3+1]=y;P.pos[i*3+2]=z;P.vel[i*3]=vx;P.vel[i*3+1]=vy;P.vel[i*3+2]=vz;P.life[i]=P.max[i]=life;P.siz[i]=size;P.col[i*4]=r;P.col[i*4+1]=gg;P.col[i*4+2]=b;P.col[i*4+3]=1}
function updP(dt){const P=GL.P;for(let i=0;i<P.N;i++){if(P.life[i]>0){P.life[i]-=dt;P.pos[i*3]+=P.vel[i*3]*dt;P.pos[i*3+1]+=P.vel[i*3+1]*dt;P.pos[i*3+2]+=P.vel[i*3+2]*dt;const k=Math.max(0,P.life[i]/P.max[i]);P.col[i*4+3]=k*k;P.siz[i]*=1+dt*.6}else P.col[i*4+3]=0}
 GL.pgeo.attributes.position.needsUpdate=GL.pgeo.attributes.aC.needsUpdate=GL.pgeo.attributes.aS.needsUpdate=true}
const rn=()=>Math.random()*2-1;
function explode(x,y,z,big){const n=Math.floor((ST.q==='low'?18:ST.q==='med'?32:55)*(big>=2?1.6:big?1:.5));
 emit(x,y,z,0,0,0,.28,big>=2?110:55,1,.9,.7);
 for(let i=0;i<n;i++){const s=20+Math.random()*(big?90:50);emit(x,y,z,rn()*s,rn()*s,rn()*s,.6+Math.random()*.9,5+Math.random()*(big?16:8),1,.35+Math.random()*.6,Math.random()*.25)}
 if(big)for(let i=0;i<8;i++){const s=12;emit(x,y,z,rn()*s,rn()*s,rn()*s,1.8,14+Math.random()*10,.16,.13,.1)}}
function spark(x,y,z,c){for(let i=0;i<7;i++){const s=40;emit(x,y,z,rn()*s,rn()*s,rn()*s,.3+Math.random()*.2,2.5,c[0],c[1],c[2])}}

// ================= حالة المباراة =================
let M=null,RM=null,PF=null,sock=null,shake=0,ping=0,lastSend=0,lastAlarm=0,paused=false;
const INP={pit:0,yaw:0,rol:0,thr:.4,f:0,m:0,b:0,k:0,s:0},TS={lx:0,ly:0,rx:0,ry:0,on:false},KS={};
const tcol=t=>M&&M.mode==='solo'?(t?2:0):t;
function beginMatch(m){
 if(!GL)return fatal('المتصفح لا يدعم WebGL أو تعذر تحميل Three.js. تحقق من الإنترنت.');
 M={mode:m.mode,you:m.you,env:m.env,mi:m.mi,lim:m.lim,kt:m.kt,sh:{},pr:{},tl:m.lim,over:false,noRender:(m.you>=0&&m.mode==='display'),lv:m.lv};
 buildWorld(m.env,m.ob);clearGroup(GL.ships);clearGroup(GL.pj);
 m.ships.forEach(s=>{const mesh=makeShip(s[1],m.mode==='solo'?(s[3]?2:0):s[3]);GL.ships.add(mesh);mesh.visible=false;M.sh[s[0]]={id:s[0],kind:s[1],name:s[2],team:s[3],bot:s[4],hpm:s[5],shm:s[6],mesh,tp:new THREE.Vector3(),tq:new THREE.Quaternion(),hp:s[5],sh:s[6],en:100,ms:0,al:0,k:0,d:0,ob:0,sp:0,fl:0,rt:0}});
 $$('.scr').forEach(s=>s.classList.remove('on'));$('#hud').classList.add('on');$('#ctl').classList.toggle('on',m.you>=0);$('#vh').style.display=m.you<0?'flex':'none';
 $('#cross').style.display=m.you>=0?'block':'none';A.intense=true;paused=false;$('#msg').textContent='';
 if(M.noRender)GL.r.setClearColor(0x05070d)}
function fmt(t){t=Math.max(0,Math.ceil(t));return Math.floor(t/60)+':'+String(t%60).padStart(2,'0')}
function onState(m){if(!M||M.over)return;M.tl=m.tl;
 m.s.forEach(a=>{const o=M.sh[a[0]];if(!o)return;o.tp.set(a[1],a[2],a[3]);o.tq.set(a[4],a[5],a[6],a[7]);o.hp=a[8];o.sh=a[9];o.en=a[10];o.ms=a[11];
  if(a[12]&&!o.al){o.mesh.position.copy(o.tp);o.mesh.quaternion.copy(o.tq)}o.al=a[12];o.k=a[13];o.d=a[14];o.ob=a[15];o.sp=a[16];o.fl=a[17];o.rt=a[18];o.mesh.visible=!!a[12]});
 const seen={};
 m.p.forEach(p=>{seen[p[0]]=1;let o=M.pr[p[0]];if(!o){const T=THREE,col=TC[tcol(p[2])];const g=new T.Group();
   if(p[1]===0){const b=new T.Mesh(new T.BoxGeometry(.5,.5,14),new T.MeshBasicMaterial({color:col}));g.add(b)}
   else{const b=new T.Mesh(new T.CylinderGeometry(.7,.9,6,8),new T.MeshStandardMaterial({color:0xdddddd,metalness:.8,roughness:.3}));b.rotation.x=Math.PI/2;g.add(b)}
   const s=new T.Sprite(new T.SpriteMaterial({map:GL.glow,color:col,blending:T.AdditiveBlending,depthWrite:false,transparent:true}));s.scale.setScalar(p[1]?10:8);g.add(s);g.position.set(p[3],p[4],p[5]);GL.pj.add(g);o=M.pr[p[0]]={g,tp:new THREE.Vector3(),last:new THREE.Vector3(p[3],p[4],p[5]),t:p[1]}}
  o.tp.set(p[3],p[4],p[5]);const d=o.tp.clone().sub(o.last);if(d.lengthSq()>.01){o.g.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,-1),d.normalize());o.last.copy(o.tp)}});
 for(const k in M.pr)if(!seen[k]){GL.pj.remove(M.pr[k].g);M.pr[k].g.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material)o.material.dispose()});delete M.pr[k]}
 const me=M.sh[M.you],cp=GL.cam.position;
 m.e.forEach(e=>{const dx=e[1]-cp.x,dy=e[2]-cp.y,dz=e[3]-cp.z,v=clamp(1-Math.sqrt(dx*dx+dy*dy+dz*dz)/1300,.08,1);
  if(e[0]==='l')A.laser(v);else if(e[0]==='m')A.missile(v);
  else if(e[0]==='x'){explode(e[1],e[2],e[3],e[4]);A.boom(v,e[4]>=2);if(me&&v>.6)shake=Math.max(shake,(e[4]>=2?1.4:.6)*v)}
  else if(e[0]==='h'){spark(e[1],e[2],e[3],[1,.8,.4]);if(e[4]===M.you){A.hit(1);shake=Math.max(shake,.7);const vg=$('#vig');vg.style.opacity=1;setTimeout(()=>vg.style.opacity=0,150)}else A.hit(v*.5)}})}
function fin(m){if(!M)return;M.over=true;A.intense=false;$('#ctl').classList.remove('on');
 const win=m.w===M.you,draw=m.w===-1;
 setTimeout(()=>{$('#hud').classList.remove('on');show('res');
  $('#rt').textContent=M.you<0?'انتهت المباراة':draw?'تعادل':win?'انتصار':'هزيمة';$('#rt').style.color=draw?'#fff':win||M.you<0?'#3dff9a':'#ff4f6d';
  $('#rw').textContent=m.rw?'المكافأة: '+m.rw+' نقطة':'';$('#rr').textContent=m.why||'';
  const t=$('#rs');t.innerHTML='<tr><th>الطيار</th><th>قتل</th><th>موت</th></tr>';m.st.forEach(r=>{const tr=document.createElement('tr');[r[1],r[2],r[3]].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.appendChild(td)});t.appendChild(tr)});
  $('#bAgain').style.display=(m.mode==='solo'||(RM&&RM.host))?'block':'none';
  if(M.you>=0)(win?A.win:draw?A.click:A.lose)();if(m.mode==='solo')prof()},1500)}
// ================= الشبكة =================
function nick(){return($('#nick').value||localStorage.swe_nick||'').trim()}
function net(){
 if(!window.io){fatal('تعذر تحميل مكتبة الاتصال. تحقق من الإنترنت ثم أعد تحميل الصفحة.');return}
 sock=io({transports:['websocket','polling'],reconnectionDelay:500,reconnectionDelayMax:3000});
 sock.on('connect',()=>{prof();const sv=sessionStorage.swe_seat;if(sv){try{sock.emit('rejoin',JSON.parse(sv))}catch(e){}}});
 sock.on('err',m=>toast(m));
 sock.on('seat',d=>sessionStorage.swe_seat=JSON.stringify(d));
 sock.on('gone',()=>{sessionStorage.removeItem('swe_seat');if(M&&!M.over)leaveUI()});
 sock.on('closed',m=>{sessionStorage.removeItem('swe_seat');RM=null;if(m)toast(m);leaveUI()});
 sock.on('room',r=>{RM=r;if(r.state==='lobby'&&r.mode!=='solo'){if(M){$('#hud').classList.remove('on');$('#ctl').classList.remove('on');M=null}show('lobby');drawLobby()}else if(cur==='lobby'&&r.state!=='lobby'){}});
 sock.on('start',beginMatch);sock.on('s',onState);sock.on('end',fin);
 setInterval(()=>{if(sock.connected){const t=Date.now();sock.emit('pg',t,v=>ping=Date.now()-v)}},2500)}
function leaveUI(){M=null;RM=null;$('#hud').classList.remove('on');$('#ctl').classList.remove('on');$('#pause').classList.remove('on');A.intense=false;GL&&menuWorld();show('home')}
function prof(cb){if(!sock)return;sock.emit('profile',{tok:TOK,nick:nick()},r=>{if(r&&r.ok){PF=r;if(!localStorage.swe_st){try{Object.assign(ST,JSON.parse(r.st||'{}'));syncUI();applyST()}catch(e){}}if(!$('#nick').value)$('#nick').value=r.nick;localStorage.swe_nick=r.nick;fillStatic()}cb&&cb()})}
// ================= الواجهات =================
function fillStatic(){if(!PF||$('#cenv').children.length)return;PF.envs.forEach((n,i)=>{const o=document.createElement('option');o.value=i;o.textContent=n;$('#cenv').appendChild(o)});
 PF.ships.forEach(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.n;$('#lship').appendChild(o)})}
function needNick(){const n=nick();if(n.length<2){toast('اكتب اسماً من حرفين على الأقل');return false}localStorage.swe_nick=n;return true}
function copy(t){if(navigator.clipboard)navigator.clipboard.writeText(t).then(()=>toast('تم النسخ'),()=>toast('تعذر النسخ'));else toast('النسخ غير مدعوم')}
function drawLobby(){const r=RM;if(!r)return;const dsp=r.mode==='display';
 $('#lt').textContent=dsp?'غرفة - شاشة كبيرة + هاتفان':'غرفة لاعبين';$('#lc').textContent=r.code;$('#lk').textContent=r.key||'-';$('#lcodes').style.display=r.host?'block':'none';
 const n=r.seats.filter(Boolean).length;$('#lp').textContent='اللاعبون '+n+'/2';$('#lm').textContent=dsp?'جهاز العرض لا يُحسب لاعباً':'المضيف هو اللاعب الأول';
 const sd=$('#seats');sd.innerHTML='';r.seats.forEach((s,i)=>{const d=document.createElement('div');d.className='seat';const nm=document.createElement('span');
  if(!s)nm.textContent='اللاعب '+(i+1)+': بانتظار الاتصال';else{const sn=PF&&PF.ships.find(x=>x.id===s.sh);nm.textContent=s.n+' - '+(sn?sn.n:s.sh)+(i===0&&!dsp?' - المضيف':'')}
  const t=document.createElement('span');t.className='tag '+(s&&s.cn?(s.rd?'ok':''):'no');t.textContent=!s?'فارغ':!s.cn?'إعادة اتصال '+s.lg+'ث':s.rd?'جاهز':'متصل';d.append(nm,t);sd.appendChild(d)});
 const me=r.you>=0;$('#lship').style.display=me?'block':'none';$('#bReady').style.display=me&&!(r.you===0&&!dsp)?'block':'none';
 if(me&&r.seats[r.you])$('#lship').value=r.seats[r.you].sh;$('#bReady').textContent=me&&r.seats[r.you]&&r.seats[r.you].rd?'إلغاء الجاهزية':'جاهز';
 $('#bStart').style.display=r.host?'block':'none';$('#bClose').style.display=r.host?'block':'none'}
$('#cc').onclick=()=>copy(RM.code);$('#ck').onclick=()=>copy(RM.key||'');$('#cl').onclick=()=>copy(location.origin+'/#c='+RM.code+'&k='+RM.key);
$('#lship').onchange=e=>sock.emit('ship',e.target.value);
$('#bReady').onclick=()=>{const s=RM.seats[RM.you];sock.emit('ready',!(s&&s.rd))};
$('#bStart').onclick=()=>sock.emit('start');$('#bLeave').onclick=()=>{sock.emit('leave');sessionStorage.removeItem('swe_seat');leaveUI()};$('#bClose').onclick=()=>sock.emit('close');
$('#bCreate').onclick=()=>{if(!needNick())return;sock.emit('create',{tok:TOK,nick:nick(),ship:ST.ship,mode:$('#cmode').value,env:+$('#cenv').value})};
$('#bJoin').onclick=()=>{if(!needNick())return;sock.emit('join',{tok:TOK,nick:nick(),ship:ST.ship,code:$('#jc').value,key:$('#jk').value})};
$('#bRooms').onclick=()=>{A.click();show('rooms')};
$('#bTrain').onclick=()=>{if(needNick())sock.emit('solo',{tok:TOK,nick:nick(),ship:ST.ship,mission:-1})};
$('#bCamp').onclick=()=>{A.click();prof(()=>{drawCamp();show('camp')})};
function drawCamp(){const l=$('#mlist');l.innerHTML='';if(!PF)return;PF.ms.forEach(m=>{const d=document.createElement('div'),lk=m.i>=PF.lv;d.className='card'+(lk?' lk':'');
 const t=document.createElement('b');t.textContent=(m.i+1)+'. '+m.n+(lk?' (مقفلة)':'');const s=document.createElement('div');s.className='sub';s.style.textAlign='right';s.textContent=m.ds+' الصعوبة: '+Math.round(m.df*100)+'% - المكافأة: '+m.rw;d.append(t,s);
 if(!lk)d.onclick=()=>{if(needNick())sock.emit('solo',{tok:TOK,nick:nick(),ship:ST.ship,mission:m.i})};l.appendChild(d)})}
$('#bShips').onclick=()=>{A.click();prof(()=>{drawShips();show('ships')})};
function drawShips(){const l=$('#slist');l.innerHTML='';if(!PF)return;PF.ships.forEach(s=>{const d=document.createElement('div');d.className='card'+(ST.ship===s.id?' sel':'');
 const t=document.createElement('b');t.textContent=s.n+' - '+s.d;d.appendChild(t);
 [['السرعة',s.sp/150],['التسارع',s.ac/110],['المناورة',s.ag/2.6],['الهيكل',s.hp/140],['الدرع',s.sh/130],['الضرر',s.dm/1.5]].forEach(x=>{const r=document.createElement('div');r.className='row';r.style.margin='1px 0';const a=document.createElement('span');a.textContent=x[0];a.style.fontSize='11px';const b=document.createElement('div');b.className='bar';b.style.width='65%';const i=document.createElement('i');i.style.width=Math.round(clamp(x[1],.05,1)*100)+'%';b.appendChild(i);r.append(a,b);d.appendChild(r)});
 d.onclick=()=>{ST.ship=s.id;saveST();drawShips();setShowcase(s.id);A.click()};l.appendChild(d)})}
$('#bStats').onclick=()=>{A.click();prof(()=>{const b=$('#sbody');b.innerHTML='';if(!PF)return;const rows=[['الاسم',PF.nick],['الانتصارات',PF.w],['الهزائم',PF.l],['القتلى',PF.k],['مرات الموت',PF.d],['النقاط',PF.pts],['مستوى الحملة',Math.min(PF.lv,20)+'/20']];
 const t=document.createElement('table');t.className='st';rows.forEach(r=>{const tr=document.createElement('tr');r.forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.appendChild(td)});t.appendChild(tr)});b.appendChild(t);
 const h=document.createElement('h2');h.textContent='آخر المباريات';h.style.marginTop='10px';b.appendChild(h);if(!PF.hist.length){const p=document.createElement('div');p.className='sub';p.textContent='لا توجد مباريات بعد';b.appendChild(p)}
 PF.hist.forEach(x=>{const p=document.createElement('div');p.className='seat';p.textContent=x.w+' فاز على '+x.l+' ('+x.s+')';b.appendChild(p)});show('stats')})};
$('#bSet').onclick=()=>{A.click();syncUI();show('set')};$('#bHelp').onclick=()=>{A.click();show('help')};
$('#bAgain').onclick=()=>{if(M&&M.mode==='solo'){sock.emit('leave');sock.emit('solo',{tok:TOK,nick:nick(),ship:ST.ship,mission:M.mi})}else sock.emit('rematch')};
$('#bExit').onclick=()=>{sock.emit('leave');sessionStorage.removeItem('swe_seat');leaveUI()};
function setPause(v){if(!M||M.you<0||M.over)return;paused=v;$('#pause').classList.toggle('on',v);if(M.mode==='solo')sock.emit('pause',v)}
$('#bp').addEventListener('pointerdown',()=>setPause(true));$('#bResume').onclick=()=>setPause(false);
$('#bQuit').onclick=()=>{if(confirm('هل تريد الخروج من المباراة؟')){$('#pause').classList.remove('on');sock.emit('leave');sessionStorage.removeItem('swe_seat');leaveUI()}};
// ================= التحكم =================
function stick(id,cb){const e=$(id),k=e.firstElementChild;let pid=null;const up=ev=>{if(ev.pointerId!==pid)return;pid=null;k.style.transform='';cb(0,0,false)};
 const mv=ev=>{if(ev.pointerId!==pid)return;const r=e.getBoundingClientRect(),R=r.width/2;let x=(ev.clientX-r.left-R)/R,y=(ev.clientY-r.top-R)/R;const l=Math.hypot(x,y);if(l>1){x/=l;y/=l}
  k.style.transform='translate('+x*R*.5+'px,'+y*R*.5+'px)';const dz=.12,f=v=>Math.abs(v)<dz?0:(v-Math.sign(v)*dz)/(1-dz);cb(f(x),f(y),true)};
 e.addEventListener('pointerdown',ev=>{if(pid!==null)return;pid=ev.pointerId;e.setPointerCapture(pid);mv(ev)});e.addEventListener('pointermove',mv);e.addEventListener('pointerup',up);e.addEventListener('pointercancel',up);e.addEventListener('lostpointercapture',up)}
stick('#sl',(x,y,on)=>{TS.lx=x;TS.ly=y;TS.on=on});stick('#sr',(x,y)=>{TS.rx=x;TS.ry=y});
function btn(id,key){const e=$(id);const dn=ev=>{e.setPointerCapture(ev.pointerId);INP[key]=1;e.classList.add('dn');A.click()},up=()=>{INP[key]=0;e.classList.remove('dn')};
 e.addEventListener('pointerdown',dn);e.addEventListener('pointerup',up);e.addEventListener('pointercancel',up);e.addEventListener('lostpointercapture',up)}
btn('#bf','f');btn('#bm','m');btn('#bs','s');btn('#bb','b');btn('#bk','k');
const KM={KeyW:1,KeyS:1,ArrowUp:1,ArrowDown:1,ArrowLeft:1,ArrowRight:1,KeyQ:1,KeyE:1,Space:1,KeyF:1,ShiftLeft:1,KeyX:1,KeyC:1};
addEventListener('keydown',e=>{if(e.code==='Escape'){setPause(!paused);return}if(KM[e.code]&&M){KS[e.code]=1;e.preventDefault()}});addEventListener('keyup',e=>{KS[e.code]=0});
function readInput(){const k=c=>KS[c]?1:0,s=ST.sens,inv=ST.inv?-1:1;
 const pit=clamp((-TS.ry*inv+(k('ArrowUp')-k('ArrowDown'))*inv)*s,-1,1),yaw=clamp((TS.rx+k('ArrowRight')-k('ArrowLeft'))*s,-1,1),rol=clamp(TS.lx+k('KeyE')-k('KeyQ'),-1,1);
 let thr=TS.on?(TS.ly<0?.4-TS.ly*.6:.4-TS.ly*1):.4;if(k('KeyW'))thr=1;else if(k('KeyS'))thr=-.4;
 return[+pit.toFixed(2),+yaw.toFixed(2),+rol.toFixed(2),+thr.toFixed(2),(INP.f||k('Space'))?1:0,(INP.m||k('KeyF'))?1:0,(INP.b||k('ShiftLeft'))?1:0,(INP.k||k('KeyX'))?1:0,(INP.s||k('KeyC'))?1:0]}
setInterval(()=>{if(!M||M.you<0||M.over||paused||!sock||!sock.connected)return;const v=readInput(),j=v.join(),now=performance.now();if(j!==lastSend.j||now-lastSend.t>150){sock.emit('input',v);lastSend={j,t:now}}},33);
// ================= الحلقة الرئيسية =================
let showcase=null,last=0,menuT=0;
function setShowcase(kind){if(!GL)return;if(showcase)GL.ships.remove(showcase);showcase=makeShip(kind,0);GL.ships.add(showcase)}
function menuWorld(){clearGroup(GL.ships);showcase=null;clearGroup(GL.pj);const ob=[[-420,-120,-1100,300]];for(let i=0;i<10;i++){const a=i*1.7;ob.push([Math.cos(a)*(120+i*25),Math.sin(a*2)*60,-150-i*60,6+i%4*4])}buildWorld(0,ob);setShowcase(ST.ship)}
const mmc=$('#mm').getContext('2d'),ca={};
function hudSet(id,v){if(ca[id]!==v){ca[id]=v;$(id).textContent=v}}
function hudW(id,p){const v=Math.round(clamp(p,0,1)*100)+'%';if(ca[id]!==v){ca[id]=v;$(id).style.width=v}}
const V=()=>new THREE.Vector3();const tmp=V(),tmp2=V(),qi=new THREE.Quaternion();
function frame(t){requestAnimationFrame(frame);if(!GL)return;const dt=Math.min(.05,(t-last)/1000||.016);last=t;const T=THREE,cam=GL.cam;
 GL.sky.position.copy(cam.position);
 if(!M){menuT+=dt;if(showcase){showcase.rotation.y=menuT*.4;showcase.rotation.x=Math.sin(menuT*.5)*.12;showcase.userData.fl.forEach(f=>f.scale.setScalar(showcase.userData.r*(3+Math.sin(menuT*20)*.4)))}
  cam.position.set(Math.sin(menuT*.15)*8,5,32);cam.lookAt(0,0,0);cam.fov=60;cam.updateProjectionMatrix();if(GL.station)GL.station.rotation.z+=dt*.1;
  GL.r.render(GL.sc,cam);return}
 const k=1-Math.exp(-dt*22);let me=M.sh[M.you];
 for(const id in M.sh){const o=M.sh[id];if(!o.al)continue;o.mesh.position.lerp(o.tp,k);o.mesh.quaternion.slerp(o.tq,k);
  const r=clamp(o.sp/120,0,1.6)*(o.fl&1?1.6:1),fs=o.mesh.userData.r*(2+r*3)*(.9+Math.random()*.2);o.mesh.userData.fl.forEach(f=>f.scale.setScalar(fs));
  if(Math.random()<.5&&r>.2){tmp.set(0,0,10).applyQuaternion(o.mesh.quaternion).add(o.mesh.position);const c=o.mesh.userData.acc;emit(tmp.x,tmp.y,tmp.z,0,0,0,.45,2.2+r,(c>>16&255)/255,(c>>8&255)/255,(c&255)/255)}}
 for(const id in M.pr){const o=M.pr[id];o.g.position.lerp(o.tp,1-Math.exp(-dt*30));if(o.t===1&&Math.random()<.8){emit(o.g.position.x,o.g.position.y,o.g.position.z,rn()*3,rn()*3,rn()*3,.7,3,1,.6,.2)}}
 updP(dt);
 if(GL.dust){const p=GL.dust.geometry.attributes.position,c=cam.position;for(let i=0;i<p.count;i++){for(let a=0;a<3;a++){const cc=a===0?c.x:a===1?c.y:c.z;let v=p.array[i*3+a];v=((v-cc+300)%600+600)%600-300+cc;p.array[i*3+a]=v}}p.needsUpdate=true}
 if(GL.station)GL.station.rotation.z+=dt*.05;
 // الكاميرا
 if(M.you>=0&&me){const q=me.mesh.quaternion;tmp.set(0,4,15).applyQuaternion(q).add(me.mesh.position);cam.position.lerp(tmp,1-Math.exp(-dt*9));cam.quaternion.slerp(q,1-Math.exp(-dt*10));
  const tf=70+clamp(me.sp/200,0,1)*14;if(Math.abs(cam.fov-tf)>.1){cam.fov+=(tf-cam.fov)*.1;cam.updateProjectionMatrix()}}
 else if(M.you<0){tmp.set(0,0,0);let n=0,sep=300;const al=Object.values(M.sh).filter(o=>o.al);al.forEach(o=>{tmp.add(o.mesh.position);n++});if(n)tmp.divideScalar(n);if(al.length>1)sep=al[0].mesh.position.distanceTo(al[1].mesh.position);
  const a=t*.00008,d=Math.max(90,sep*1.1);tmp2.set(Math.sin(a)*d,d*.35,Math.cos(a)*d).add(tmp);cam.position.lerp(tmp2,.03);cam.lookAt(tmp);if(cam.fov!==65){cam.fov=65;cam.updateProjectionMatrix()}}
 if(shake>.01){const s=shake*ST.shake*1.4;cam.position.x+=rn()*s;cam.position.y+=rn()*s;shake*=Math.exp(-dt*6)}
 // صوت المحرك
 if(A.ctx&&me){const r=clamp(me.sp/200,0,1);A.eo.frequency.value=40+r*70+(me.fl&1?25:0);A.eg.gain.value=me.al?.03+r*.07:0}
 // HUD
 const tl=M.tl;hudSet('#ht',M.you<0?(tl<0?'':fmt(tl)):(tl<0?'تدريب':fmt(tl)));
 if(M.you>=0&&me){hudW('#bh',me.hp/me.hpm);hudW('#bsh',me.sh/me.shm);hudW('#ben',me.en/100);
  const oth=Object.values(M.sh).filter(o=>o.id!==me.id&&!(M.mode==='solo'&&!o.bot&&false));hudSet('#hs',me.sp+' | صواريخ '+me.ms+' | قتل '+me.k+' موت '+me.d+(M.mode==='solo'&&M.lv<1000?'/'+M.lv:''));
  if(!me.al){hudSet('#msg',M.mode==='solo'&&me.d>=M.lv?'':'تم تدميرك - إعادة الظهور '+Math.ceil(me.rt)+'ث')}else if(me.ob){hudSet('#msg','عد إلى ساحة المعركة')}else hudSet('#msg','');
  if(me.al&&(me.hp+me.sh)/(me.hpm+me.shm)<.25&&t-lastAlarm>1500){lastAlarm=t;A.alarm()}
  // الهدف
  let best=null,bd=1e9;oth.forEach(o=>{if(o.al&&o.team!==me.team){const d=o.mesh.position.distanceTo(me.mesh.position);if(d<bd){bd=d;best=o}}});
  const tg=$('#tg'),td=$('#td');if(best){tmp.copy(best.mesh.position).project(cam);let x=tmp.x,y=tmp.y;if(tmp.z>1){x=-x;y=-y}const out=Math.abs(x)>.92||Math.abs(y)>.88||tmp.z>1;x=clamp(x,-.92,.92);y=clamp(y,-.88,.88);
   const px=(x+1)/2*innerWidth,py=(1-y)/2*innerHeight;tg.style.display=td.style.display='block';tg.style.left=px+'px';tg.style.top=py+'px';tg.style.opacity=out?.5:1;td.style.left=(px+18)+'px';td.style.top=(py-8)+'px';td.textContent=Math.round(bd)+'م '+best.name}else tg.style.display=td.style.display='none'}
 else if(M.you<0){const a=M.sh[0],b=M.sh[1];if(a&&b)hudSet('#vh',a.name+' '+a.k+'  -  '+b.k+' '+b.name+'   |   '+a.name+': '+(a.hp+a.sh)+'  '+b.name+': '+(b.hp+b.sh));$('#tg').style.display=$('#td').style.display='none'}
 hudSet('#cn',sock&&sock.connected?ping+'ms':'إعادة الاتصال...');
 // الخريطة المصغرة
 const c=mmc;c.clearRect(0,0,96,96);c.strokeStyle='rgba(56,225,255,.5)';c.fillStyle='rgba(5,12,22,.55)';c.beginPath();c.arc(48,48,46,0,7);c.fill();[46,30,14].forEach(r=>{c.beginPath();c.arc(48,48,r,0,7);c.stroke()});
 const R=M.you>=0?900:1800;if(M.you>=0&&me)qi.copy(me.mesh.quaternion).invert();else qi.identity();const cp=me?me.mesh.position:tmp2.set(0,0,0);
 for(const id in M.sh){const o=M.sh[id];if(!o.al||o===me)continue;tmp.copy(o.mesh.position).sub(cp).applyQuaternion(qi);let x=tmp.x/R*46,y=tmp.z/R*46;const l=Math.hypot(x,y);if(l>44){x*=44/l;y*=44/l}
  c.fillStyle=M.you>=0?(o.team!==me.team?'#ff4f6d':'#3dff9a'):(o.team?'#ffa23a':'#38e1ff');c.beginPath();c.arc(48+x,48+y,3,0,7);c.fill();c.strokeStyle=c.fillStyle;c.beginPath();c.moveTo(48+x,48+y);c.lineTo(48+x,48+y-clamp(tmp.y/R*46,-9,9));c.stroke()}
 if(M.you>=0){c.fillStyle='#fff';c.beginPath();c.moveTo(48,42);c.lineTo(44,53);c.lineTo(52,53);c.fill()}
 if(!M.noRender)GL.r.render(GL.sc,cam)}
// ================= بدء التشغيل =================
$('#nick').value=localStorage.swe_nick||'';
GL=initGL();
if(!GL)fatal('تعذر تشغيل الرسوميات ثلاثية الأبعاد. تأكد من اتصال الإنترنت (لتحميل Three.js) ودعم WebGL.');
else{menuWorld();resize()}
syncUI();applyST();net();requestAnimationFrame(frame);
const hm=location.hash.match(/c=([A-Za-z0-9]{6})&k=([A-Za-z0-9]{8})/);if(hm){$('#jc').value=hm[1];$('#jk').value=hm[2];show('rooms');toast('تم تعبئة بيانات الانضمام، اكتب اسمك ثم اضغط انضمام')}
})();
</script></body></html>'''

init_db()
sio.start_background_task(loop)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print('SPACE WAR ELITE  ->  http://localhost:%d   (للشبكة المحلية: http://<IP-الهاتف>:%d)' % (port, port))
    sio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
