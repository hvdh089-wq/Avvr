#Laxo — تطبيق Python 3 بملف واحد

# -*- coding: utf-8 -*-
"""
LAXO
Single-file Python 3 application
HTML + CSS + JavaScript embedded inside Python.

Run:
    python3 laxo.py

Then open:
    http://127.0.0.1:8765

On Android/Termux:
    python3 laxo.py

The UI is completely contained in this one file.
"""

import http.server
import socketserver
import webbrowser
import threading
import os
import sys

HOST = "127.0.0.1"
PORT = 8765


HTML = r'''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">

<meta name="theme-color" content="#050807">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">

<title>Laxo</title>

<style>

*{
    box-sizing:border-box;
    -webkit-tap-highlight-color:transparent;
}

:root{
    --bg:#050807;
    --bg2:#090d0b;
    --panel:#0d1310;
    --panel2:#111914;
    --green:#18d66b;
    --green2:#0fa957;
    --green3:#8dffba;
    --text:#f3f7f4;
    --muted:#87928b;
    --border:#1b2921;
    --danger:#ff4d5e;
    --bubble:#17231c;
}

html,
body{
    width:100%;
    height:100%;
    margin:0;
    background:#000;
    color:var(--text);
    font-family:
      -apple-system,
      BlinkMacSystemFont,
      "Segoe UI",
      Roboto,
      Arial,
      sans-serif;
    overflow:hidden;
}

button,
input,
textarea{
    font:inherit;
}

button{
    border:0;
    outline:0;
    cursor:pointer;
}

#app{
    width:100%;
    height:100%;
    max-width:600px;
    margin:auto;
    background:var(--bg);
    position:relative;
    overflow:hidden;
}

/* ---------------- SPLASH ---------------- */

.screen{
    position:absolute;
    inset:0;
    display:none;
    flex-direction:column;
    background:
      radial-gradient(circle at 50% 10%,rgba(24,214,107,.09),transparent 35%),
      var(--bg);
}

.screen.active{
    display:flex;
}

.splash{
    padding:
      calc(env(safe-area-inset-top) + 25px)
      22px
      calc(env(safe-area-inset-bottom) + 18px);
}

.logo{
    color:var(--green);
    font-size:40px;
    font-weight:900;
    letter-spacing:-2px;
    text-align:center;
    margin-top:10px;
}

.splash-title{
    text-align:center;
    font-size:27px;
    font-weight:800;
    margin:25px 0 25px;
}

.messages{
    flex:1;
    display:flex;
    flex-direction:column;
    justify-content:center;
    gap:13px;
    max-width:450px;
    width:100%;
    margin:auto;
}

.bubble{
    width:max-content;
    max-width:88%;
    background:var(--bubble);
    border:1px solid var(--border);
    border-radius:18px;
    padding:13px 16px;
    color:#e8eee9;
    animation:appear .45s ease both;
}

.bubble:nth-child(2){
    animation-delay:.15s;
}

.bubble:nth-child(3){
    animation-delay:.3s;
}

.bubble:nth-child(4){
    background:linear-gradient(135deg,var(--green),#0ca854);
    color:#031309;
    font-weight:800;
    margin-right:auto;
    animation-delay:.45s;
}

@keyframes appear{
    from{
        opacity:0;
        transform:translateY(12px) scale(.97);
    }
    to{
        opacity:1;
        transform:none;
    }
}

.actions{
    display:flex;
    flex-direction:column;
    gap:11px;
    padding-top:15px;
}

.primary{
    background:linear-gradient(135deg,var(--green),#0cae58);
    color:#021008;
    font-weight:900;
    min-height:55px;
    border-radius:16px;
    box-shadow:0 8px 30px rgba(24,214,107,.16);
}

.secondary{
    background:transparent;
    border:1px solid #207341;
    color:var(--green3);
    min-height:55px;
    border-radius:16px;
    font-weight:700;
}

.footer{
    color:#66736b;
    font-size:11px;
    text-align:center;
    line-height:1.7;
    padding-top:15px;
}

/* ---------------- GENERIC ---------------- */

.topbar{
    height:70px;
    min-height:70px;
    display:flex;
    align-items:center;
    justify-content:space-between;
    padding:
      calc(env(safe-area-inset-top) + 8px)
      16px
      5px;
    border-bottom:1px solid var(--border);
    background:rgba(5,8,7,.94);
    backdrop-filter:blur(18px);
}

.top-title{
    font-size:20px;
    font-weight:850;
}

.icon-btn{
    width:44px;
    height:44px;
    border-radius:14px;
    background:transparent;
    color:#dce8df;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:21px;
}

.icon-btn:active{
    background:#142019;
}

.content{
    flex:1;
    overflow:auto;
    padding:22px;
    scrollbar-width:none;
}

.content::-webkit-scrollbar{
    display:none;
}

.center{
    display:flex;
    align-items:center;
    justify-content:center;
    text-align:center;
}

/* ---------------- FORMS ---------------- */

.form-title{
    font-size:28px;
    font-weight:900;
    margin:20px 0 12px;
}

.form-text{
    color:var(--muted);
    line-height:1.8;
    font-size:14px;
    margin-bottom:25px;
}

.field{
    width:100%;
    min-height:55px;
    border-radius:15px;
    background:#0c120f;
    border:1px solid var(--border);
    color:white;
    outline:none;
    padding:0 16px;
    margin-bottom:13px;
}

.field:focus{
    border-color:#25834b;
    box-shadow:0 0 0 3px rgba(24,214,107,.08);
}

textarea.field{
    padding-top:15px;
    min-height:100px;
    resize:none;
}

.bottom-action{
    margin-top:auto;
    padding:15px 22px calc(env(safe-area-inset-bottom) + 15px);
    border-top:1px solid var(--border);
}

/* ---------------- TABS ---------------- */

.tabs{
    display:flex;
    background:#0b100d;
    border:1px solid var(--border);
    border-radius:15px;
    padding:4px;
    margin-bottom:20px;
}

.tab{
    flex:1;
    min-height:43px;
    background:transparent;
    color:var(--muted);
    border-radius:11px;
}

.tab.active{
    background:#183022;
    color:var(--green3);
    font-weight:800;
}

/* ---------------- OPTIONS ---------------- */

.option{
    padding:17px;
    border:1px solid var(--border);
    border-radius:17px;
    margin-bottom:12px;
    background:#0a100d;
    position:relative;
}

.option.selected{
    border-color:#269953;
    background:#0d1b13;
}

.option-title{
    font-weight:850;
    margin-bottom:6px;
}

.option-text{
    color:var(--muted);
    font-size:13px;
    line-height:1.7;
}

.badge{
    position:absolute;
    left:13px;
    top:13px;
    background:#153a24;
    color:var(--green3);
    border-radius:20px;
    padding:5px 9px;
    font-size:10px;
}

/* ---------------- HOME ---------------- */

.home{
    background:
      radial-gradient(circle at 50% 45%,rgba(24,214,107,.07),transparent 35%),
      var(--bg);
}

.home-empty{
    flex:1;
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    padding:35px;
    text-align:center;
}

.confetti{
    width:105px;
    height:105px;
    border-radius:35px;
    background:#102017;
    border:1px solid #1d3928;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:48px;
    margin-bottom:24px;
}

.home-empty h2{
    font-size:21px;
    margin:0 0 10px;
}

.home-empty p{
    color:var(--muted);
    line-height:1.8;
    font-size:14px;
    margin:0;
}

.fab{
    position:absolute;
    bottom:25px;
    left:22px;
    width:62px;
    height:62px;
    border-radius:50%;
    background:var(--green);
    color:#031108;
    font-size:31px;
    font-weight:500;
    box-shadow:0 10px 35px rgba(24,214,107,.25);
}

/* ---------------- SHEET ---------------- */

.overlay{
    position:absolute;
    inset:0;
    background:rgba(0,0,0,.68);
    z-index:50;
    display:none;
    align-items:flex-end;
}

.overlay.show{
    display:flex;
}

.sheet{
    width:100%;
    background:#0b110e;
    border:1px solid var(--border);
    border-radius:25px 25px 0 0;
    padding:13px 18px calc(env(safe-area-inset-bottom) + 20px);
    animation:sheetUp .25s ease;
    max-height:88%;
    overflow:auto;
}

@keyframes sheetUp{
    from{transform:translateY(100%)}
    to{transform:none}
}

.grabber{
    width:40px;
    height:4px;
    background:#35423a;
    border-radius:5px;
    margin:0 auto 20px;
}

.sheet h3{
    margin:0 0 15px;
    font-size:21px;
}

.action-row{
    display:flex;
    align-items:center;
    gap:14px;
    padding:15px 7px;
    border-bottom:1px solid #152019;
}

.action-icon{
    width:44px;
    height:44px;
    border-radius:13px;
    background:#142219;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:21px;
}

.action-row strong{
    display:block;
}

.action-row small{
    color:var(--muted);
}

/* ---------------- QR ---------------- */

.qr{
    width:190px;
    height:190px;
    background:white;
    padding:10px;
    border-radius:17px;
    margin:20px auto;
    display:grid;
    grid-template-columns:repeat(21,1fr);
    grid-template-rows:repeat(21,1fr);
    gap:1px;
}

.qr span{
    background:white;
}

.qr span.on{
    background:#000;
}

.account-id{
    direction:ltr;
    text-align:center;
    word-break:break-all;
    color:#9ba99f;
    font-family:monospace;
    font-size:11px;
    line-height:1.7;
}

/* ---------------- SETTINGS ---------------- */

.profile-header{
    padding:20px 0;
    display:flex;
    align-items:center;
    gap:13px;
}

.avatar{
    width:58px;
    height:58px;
    border-radius:19px;
    background:linear-gradient(135deg,#19d86d,#0b8b47);
    color:#021108;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:25px;
    font-weight:900;
}

.profile-info{
    flex:1;
}

.profile-name{
    font-size:20px;
    font-weight:900;
}

.profile-id{
    color:var(--muted);
    font-size:11px;
    direction:ltr;
    margin-top:4px;
    overflow:hidden;
    text-overflow:ellipsis;
}

.setting-group{
    margin-top:12px;
}

.setting-item{
    min-height:63px;
    display:flex;
    align-items:center;
    gap:13px;
    border-bottom:1px solid #121b16;
}

.setting-icon{
    width:40px;
    height:40px;
    border-radius:12px;
    background:#101a14;
    display:flex;
    align-items:center;
    justify-content:center;
}

.setting-info{
    flex:1;
}

.setting-title{
    font-weight:700;
    font-size:14px;
}

.setting-sub{
    color:#68756d;
    font-size:11px;
    margin-top:3px;
}

.toggle{
    width:47px;
    height:27px;
    background:#27342c;
    border-radius:30px;
    position:relative;
}

.toggle.on{
    background:#149a4e;
}

.toggle:after{
    content:"";
    position:absolute;
    width:21px;
    height:21px;
    top:3px;
    right:3px;
    background:white;
    border-radius:50%;
    transition:.2s;
}

.toggle.on:after{
    right:23px;
}

/* ---------------- CHAT ---------------- */

.chat-header{
    display:flex;
    align-items:center;
    gap:9px;
    flex:1;
}

.chat-avatar{
    width:42px;
    height:42px;
    border-radius:14px;
    background:#173423;
    color:var(--green3);
    display:flex;
    align-items:center;
    justify-content:center;
    font-weight:900;
}

.chat-name{
    font-weight:850;
}

.chat-status{
    color:#65746a;
    font-size:10px;
    margin-top:3px;
}

.chat-body{
    flex:1;
    overflow:auto;
    padding:18px 15px 10px;
    display:flex;
    flex-direction:column;
    gap:8px;
}

.message{
    max-width:78%;
    padding:10px 13px;
    border-radius:17px;
    line-height:1.6;
    font-size:14px;
}

.message.me{
    align-self:flex-start;
    background:#135c32;
    border-bottom-left-radius:5px;
}

.message.them{
    align-self:flex-end;
    background:#131b16;
    border:1px solid var(--border);
    border-bottom-right-radius:5px;
}

.message-time{
    display:block;
    color:#9bb0a1;
    font-size:9px;
    margin-top:3px;
}

.composer{
    display:flex;
    align-items:center;
    gap:7px;
    padding:8px 10px calc(env(safe-area-inset-bottom) + 8px);
    border-top:1px solid var(--border);
    background:#080d0a;
}

.composer-input{
    flex:1;
    min-height:45px;
    max-height:100px;
    resize:none;
    border:1px solid var(--border);
    background:#111813;
    color:white;
    border-radius:17px;
    outline:none;
    padding:11px 14px;
}

.send{
    width:45px;
    height:45px;
    border-radius:15px;
    background:var(--green);
    color:#031108;
    font-size:19px;
}

.attach{
    width:40px;
    height:40px;
    background:transparent;
    color:#9ca9a1;
    font-size:20px;
}

/* ---------------- MODAL ---------------- */

.modal{
    position:absolute;
    inset:0;
    background:rgba(0,0,0,.76);
    z-index:100;
    display:none;
    align-items:center;
    justify-content:center;
    padding:25px;
}

.modal.show{
    display:flex;
}

.modal-card{
    width:100%;
    background:#0d1410;
    border:1px solid var(--border);
    border-radius:23px;
    padding:22px;
    box-shadow:0 20px 70px rgba(0,0,0,.55);
}

.modal-title{
    font-size:20px;
    font-weight:900;
    margin-bottom:9px;
}

.modal-text{
    color:var(--muted);
    line-height:1.8;
    font-size:13px;
    margin-bottom:20px;
}

.modal-buttons{
    display:flex;
    gap:9px;
}

.modal-buttons button{
    flex:1;
    min-height:49px;
    border-radius:14px;
}

/* ---------------- CAMERA ---------------- */

#cameraVideo{
    width:100%;
    max-height:65vh;
    border-radius:18px;
    background:#000;
    object-fit:cover;
}

.camera-box{
    position:relative;
}

.camera-guide{
    position:absolute;
    width:190px;
    height:190px;
    border:2px solid var(--green);
    border-radius:20px;
    top:50%;
    left:50%;
    transform:translate(-50%,-50%);
    box-shadow:0 0 0 9999px rgba(0,0,0,.28);
}

/* ---------------- TOAST ---------------- */

.toast{
    position:absolute;
    z-index:300;
    left:50%;
    bottom:30px;
    transform:translate(-50%,30px);
    opacity:0;
    pointer-events:none;
    background:#eaf4ed;
    color:#07120b;
    padding:11px 17px;
    border-radius:13px;
    font-size:13px;
    font-weight:700;
    transition:.25s;
    white-space:nowrap;
}

.toast.show{
    opacity:1;
    transform:translate(-50%,0);
}

/* ---------------- LIGHT ---------------- */

.light{
    --bg:#f4f7f5;
    --bg2:#fff;
    --panel:#fff;
    --panel2:#eef3ef;
    --text:#101611;
    --muted:#68746c;
    --border:#dce5df;
    --bubble:#e9f0eb;
}

.light .screen,
.light .topbar,
.light .sheet,
.light .modal-card{
    background:var(--bg);
}

.light .field,
.light .composer-input,
.light .option{
    background:#fff;
}

.light .message.them{
    background:#fff;
}

.light .composer{
    background:#f4f7f5;
}

/* ---------------- RESPONSIVE ---------------- */

@media(min-width:601px){
    #app{
        box-shadow:
          0 0 0 1px #111,
          0 0 80px rgba(0,0,0,.5);
    }
}

</style>
</head>

<body>

<div id="app">

<!-- ================= WELCOME ================= -->

<section id="welcome" class="screen splash active">

    <div class="logo">Laxo</div>

    <div class="splash-title">
        الخصوصية في جيبك.
    </div>

    <div class="messages">
        <div class="bubble">
            مرحباً بكم في Laxo 👋
        </div>

        <div class="bubble">
            Laxo صُمم لحماية خصوصيتكم.
        </div>

        <div class="bubble">
            لا تحتاجوا إلى رقم هاتف للتسجيل.
        </div>

        <div class="bubble">
            إنشاء حساب فوري، مجاني، ومجهول 🤫
        </div>
    </div>

    <div class="actions">
        <button class="primary" onclick="showCreate()">
            إنشاء حساب
        </button>

        <button class="secondary" onclick="showRecovery()">
            لدي حساب
        </button>
    </div>

    <div class="footer">
        باستخدام هذه الخدمة، أنتم توافقون على شروط الخدمة
        و سياسة الخصوصية
    </div>

</section>


<!-- ================= RECOVERY ================= -->

<section id="recovery" class="screen">

    <div class="topbar">
        <button class="icon-btn" onclick="goWelcome()">‹</button>
        <div class="top-title">تحميل الحساب</div>
        <div style="width:44px"></div>
    </div>

    <div class="content">

        <div class="tabs">
            <button id="recoveryPassTab"
                    class="tab active"
                    onclick="recoveryTab('pass')">
                كلمة مرور الاسترداد
            </button>

            <button id="recoveryQrTab"
                    class="tab"
                    onclick="recoveryTab('qr')">
                مسح QR
            </button>
        </div>

        <div id="recoveryPass">

            <div class="form-title">
                استعادة حسابكم
            </div>

            <div class="form-text">
                إدخال كلمة مرور الاسترجاع لتحميل حسابكم.
                إذا لم تحفظوها، يمكنكم العثور عليها في إعدادات التطبيق.
            </div>

            <input
                id="recoveryInput"
                class="field"
                type="password"
                placeholder="أدخل كلمة مرور الاسترجاع">

        </div>

        <div id="recoveryQr" style="display:none">

            <div class="form-title">
                استعادة بواسطة QR
            </div>

            <div class="form-text">
                امسح رمز QR الخاص بحسابكم باستخدام الكاميرا.
            </div>

            <button class="primary"
                    onclick="openCamera()">
                فتح الكاميرا ومسح QR
            </button>

        </div>

    </div>

    <div class="bottom-action">
        <button class="primary"
                onclick="recoverAccount()">
            استمرار
        </button>
    </div>

</section>


<!-- ================= CREATE NAME ================= -->

<section id="createName" class="screen">

    <div class="topbar">
        <button class="icon-btn" onclick="goWelcome()">‹</button>
        <div class="top-title">إنشاء حساب</div>
        <div style="width:44px"></div>
    </div>

    <div class="content">

        <div class="form-title">
            اختيار اسم العرض الخاص بكم
        </div>

        <div class="form-text">
            يمكن أن يكون اسمكم الحقيقي، أو لقب، أو أي شيء آخر
            تفضلون - ويمكنكم تغييره في أي وقت.
        </div>

        <input
            id="displayName"
            class="field"
            maxlength="40"
            placeholder="أدخل اسم العرض">

    </div>

    <div class="bottom-action">
        <button class="primary" onclick="nextCreateName()">
            استمرار
        </button>
    </div>

</section>


<!-- ================= NOTIFICATION MODE ================= -->

<section id="notifyMode" class="screen">

    <div class="topbar">
        <button class="icon-btn" onclick="showScreen('createName')">‹</button>
        <div class="top-title">إشعارات الرسالة</div>
        <div style="width:44px"></div>
    </div>

    <div class="content">

        <div class="form-title">
            إشعارات الرسالة
        </div>

        <div class="form-text">
            هناك طريقتان يمكن لـ Laxo من خلالهما إشعاركم
            بالرسائل الجديدة.
        </div>

        <div id="fastOption"
             class="option selected"
             onclick="selectNotify('fast')">

            <span class="badge">موصى به</span>

            <div class="option-title">
                ⚡ الوضع السريع
            </div>

            <div class="option-text">
                سيتم إعلامكم بالرسائل الجديدة بشكل موثوق وفوري
                باستخدام خوادم إشعارات Google.
            </div>

        </div>

        <div id="slowOption"
             class="option"
             onclick="selectNotify('slow')">

            <div class="option-title">
                🐢 الوضع البطيء
            </div>

            <div class="option-text">
                Laxo سيتحقق بشكل دوري من وجود رسائل جديدة
                في الخلفية.
            </div>

        </div>

    </div>

    <div class="bottom-action">
        <button class="primary" onclick="nextPermissions()">
            استمرار
        </button>
    </div>

</section>


<!-- ================= PERMISSIONS ================= -->

<section id="permissions" class="screen">

    <div class="topbar">
        <button class="icon-btn" onclick="showScreen('notifyMode')">‹</button>
        <div class="top-title">الأذونات</div>
        <div style="width:44px"></div>
    </div>

    <div class="content">

        <div class="form-title">
            الأذونات
        </div>

        <div class="form-text">
            سنطلب الأذونات اللازمة لتقديم تجربة Laxo.
        </div>

        <div class="option">
            <div class="option-title">
                🔔 إشعارات الرسائل
            </div>

            <div class="option-text">
                هل تريد السماح لتطبيق Laxo بإرسال إشعارات إليك؟
            </div>

            <button class="secondary"
                    style="width:100%;margin-top:13px"
                    onclick="requestNotifications()">
                السماح بالإشعارات
            </button>
        </div>

        <div id="backgroundPermission"
             class="option"
             style="display:none">

            <div class="option-title">
                🔋 التشغيل في الخلفية
            </div>

            <div class="option-text">
                يمكن أن يؤدي تشغيل Laxo في الخلفية إلى تقليل
                عمر البطارية.
            </div>

            <button class="secondary"
                    style="width:100%;margin-top:13px"
                    onclick="backgroundPermission()">
                السماح
            </button>

        </div>

    </div>

    <div class="bottom-action">
        <button class="primary" onclick="finishRegistration()">
            إنهاء وإنشاء الحساب
        </button>
    </div>

</section>


<!-- ================= HOME ================= -->

<section id="home" class="screen home">

    <div class="topbar">

        <button class="icon-btn" onclick="openSettings()">
            👤
        </button>

        <div class="top-title">
            Laxo
        </div>

        <button class="icon-btn" onclick="searchChats()">
            🔍
        </button>

    </div>

    <div class="home-empty">

        <div class="confetti">
            🎉
        </div>

        <h2>
            تم إنشاء الحساب! مرحباً بكم في Laxo 👋
        </h2>

        <p>
            ليس لديكم أي محادثات حتى الآن.
            اضغطوا على زر الإضافة لبدء محادثة،
            إنشاء مجموعة، أو الانضمام إلى مجتمع رسمي.
        </p>

    </div>

    <button class="fab" onclick="openStartSheet()">
        +
    </button>

</section>


<!-- ================= SETTINGS ================= -->

<section id="settings" class="screen">

    <div class="topbar">

        <button class="icon-btn" onclick="showScreen('home')">
            ‹
        </button>

        <div class="top-title">
            الإعدادات
        </div>

        <button class="icon-btn" onclick="showQR()">
            ▣
        </button>

    </div>

    <div class="content">

        <div class="profile-header">

            <div id="settingsAvatar"
                 class="avatar">
                L
            </div>

            <div class="profile-info">

                <div id="settingsName"
                     class="profile-name">
                    Laxo
                </div>

                <div id="settingsId"
                     class="profile-id">
                    ...
                </div>

            </div>

            <button class="icon-btn"
                    onclick="editName()">
                ✎
            </button>

        </div>

        <div class="option">

            <div style="text-align:center;font-weight:800">
                معرف حسابكم
            </div>

            <div id="fullAccountId"
                 class="account-id"
                 style="margin-top:10px">
            </div>

            <div style="display:flex;gap:9px;margin-top:15px">

                <button class="secondary"
                        style="flex:1"
                        onclick="copyAccountId()">
                    نسخ
                </button>

                <button class="secondary"
                        style="flex:1"
                        onclick="shareAccountId()">
                    مشاركة
                </button>

            </div>

        </div>

        <div class="setting-group">

            <div class="setting-item"
                 onclick="inviteFriend()">
                <div class="setting-icon">👤</div>
                <div class="setting-info">
                    <div class="setting-title">دعوة صديق</div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="donate()">
                <div class="setting-icon">♥</div>
                <div class="setting-info">
                    <div class="setting-title">التبرع</div>
                </div>
            </div>

            <div class="setting-item">

                <div class="setting-icon">↔</div>

                <div class="setting-info">
                    <div class="setting-title">مسار</div>
                    <div class="setting-sub">
                        تشغيل الاتصال والمسارات
                    </div>
                </div>

                <div id="routeToggle"
                     class="toggle on"
                     onclick="toggleSetting(this)">
                </div>

            </div>

            <div class="setting-item"
                 onclick="networkInfo()">
                <div class="setting-icon">☁</div>
                <div class="setting-info">
                    <div class="setting-title">Laxo Network</div>
                    <div class="setting-sub">
                        إعدادات الشبكة والاتصال
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="privacySettings()">
                <div class="setting-icon">🔒</div>
                <div class="setting-info">
                    <div class="setting-title">الخصوصية</div>
                    <div class="setting-sub">
                        متصل الآن، مؤشرات القراءة، قفل التطبيق
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="notificationSettings()">
                <div class="setting-icon">🔔</div>
                <div class="setting-info">
                    <div class="setting-title">الإشعارات</div>
                    <div class="setting-sub">
                        النغمات والتنبيهات
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="chatSettings()">
                <div class="setting-icon">💬</div>
                <div class="setting-info">
                    <div class="setting-title">المحادثات</div>
                    <div class="setting-sub">
                        الوسائط وحجم الخط
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="toggleTheme()">
                <div class="setting-icon">🎨</div>
                <div class="setting-info">
                    <div class="setting-title">المظهر</div>
                    <div class="setting-sub">
                        داكن / فاتح
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="messageRequests()">
                <div class="setting-icon">✉</div>
                <div class="setting-info">
                    <div class="setting-title">طلبات المراسلة</div>
                    <div class="setting-sub">
                        الرسائل من الغرباء
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="showRecoveryPassword()">
                <div class="setting-icon">🛡</div>
                <div class="setting-info">
                    <div class="setting-title">
                        كلمة مرور الاسترداد
                    </div>
                    <div class="setting-sub">
                        مهمة جداً لاستعادة الحساب
                    </div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="help()">
                <div class="setting-icon">?</div>
                <div class="setting-info">
                    <div class="setting-title">المساعدة</div>
                </div>
            </div>

            <div class="setting-item"
                 onclick="deleteData()">

                <div class="setting-icon"
                     style="color:var(--danger)">
                    🗑
                </div>

                <div class="setting-info">
                    <div class="setting-title"
                         style="color:var(--danger)">
                        مسح البيانات
                    </div>
                </div>

            </div>

        </div>

        <div style="
            text-align:center;
            color:#56635a;
            font-size:10px;
            padding:30px 0 20px;
        ">
            Laxo v1.0.0
        </div>

    </div>

</section>


<!-- ================= CHAT ================= -->

<section id="chat" class="screen">

    <div class="topbar">

        <button class="icon-btn" onclick="showScreen('home')">
            ‹
        </button>

        <div class="chat-header">

            <div id="chatAvatar"
                 class="chat-avatar">
                L
            </div>

            <div>

                <div id="chatName"
                     class="chat-name">
                    ملاحظة لنفسي
                </div>

                <div id="chatStatus"
                     class="chat-status">
                    متصل الآن
                </div>

            </div>

        </div>

        <button class="icon-btn"
                onclick="startCall('audio')">
            ☎
        </button>

        <button class="icon-btn"
                onclick="startCall('video')">
            ▣
        </button>

    </div>

    <div id="chatBody"
         class="chat-body">

        <div class="message them">
            مرحباً بك في Laxo 👋
            <span class="message-time">
                مشفر
            </span>
        </div>

    </div>

    <div class="composer">

        <button class="attach"
                onclick="attachFile()">
            📎
        </button>

        <button class="attach"
                onclick="cameraMessage()">
            📷
        </button>

        <textarea id="messageInput"
                  class="composer-input"
                  rows="1"
                  placeholder="اكتب رسالة..."
                  onkeydown="messageKey(event)"></textarea>

        <button class="send"
                onclick="sendMessage()">
            ➤
        </button>

        <input id="fileInput"
               type="file"
               hidden
               onchange="fileSelected(event)">

        <input id="cameraInput"
               type="file"
               accept="image/*"
               capture="environment"
               hidden
               onchange="cameraSelected(event)">

    </div>

</section>


<!-- ================= START SHEET ================= -->

<div id="startSheet"
     class="overlay"
     onclick="closeSheet(event)">

    <div class="sheet">

        <div class="grabber"></div>

        <h3>
            بدأ محادثة
        </h3>

        <div class="action-row"
             onclick="newMessage()">

            <div class="action-icon">✉</div>

            <div>
                <strong>رسالة جديدة</strong>
                <small>لبدء شات خاص</small>
            </div>

        </div>

        <div class="action-row"
             onclick="createGroup()">

            <div class="action-icon">👥</div>

            <div>
                <strong>إنشاء مجموعة</strong>
                <small>لعمل جروب محادثة</small>
            </div>

        </div>

        <div class="action-row"
             onclick="joinCommunity()">

            <div class="action-icon">🌐</div>

            <div>
                <strong>الانضمام إلى المجتمع</strong>
                <small>مجتمعات وقنوات عامة</small>
            </div>

        </div>

        <div class="action-row"
             onclick="inviteFriend()">

            <div class="action-icon">➕</div>

            <div>
                <strong>دعوة صديق</strong>
            </div>

        </div>

        <div class="option"
             style="margin-top:18px;text-align:center">

            <strong>
                معرّف حسابكم
            </strong>

            <div id="sheetQR"
                 class="qr">
            </div>

            <div class="option-text">
                يمكن للأصدقاء إرسال رسائل إليكم
                عن طريق مسح رمز QR الخاص بكم.
            </div>

        </div>

    </div>

</div>


<!-- ================= QR MODAL ================= -->

<div id="qrModal"
     class="modal">

    <div class="modal-card">

        <div class="modal-title">
            رمز حسابكم
        </div>

        <div id="modalQR"
             class="qr">
        </div>

        <div id="modalAccountId"
             class="account-id">
        </div>

        <div class="modal-buttons"
             style="margin-top:20px">

            <button class="secondary"
                    onclick="closeQR()">
                إغلاق
            </button>

            <button class="primary"
                    onclick="copyAccountId()">
                نسخ المعرف
            </button>

        </div>

    </div>

</div>


<!-- ================= CAMERA MODAL ================= -->

<div id="cameraModal"
     class="modal">

    <div class="modal-card">

        <div class="modal-title">
            مسح رمز QR
        </div>

        <div class="modal-text">
            اسمح للكاميرا ثم وجّهها نحو رمز حساب Laxo.
        </div>

        <div class="camera-box">

            <video id="cameraVideo"
                   autoplay
                   playsinline>
            </video>

            <div class="camera-guide"></div>

        </div>

        <div class="modal-buttons"
             style="margin-top:15px">

            <button class="secondary"
                    onclick="closeCamera()">
                إلغاء
            </button>

            <button class="primary"
                    onclick="simulateQRScan()">
                اختبار المسح
            </button>

        </div>

    </div>

</div>


<!-- ================= CUSTOM MODAL ================= -->

<div id="customModal"
     class="modal">

    <div class="modal-card">

        <div id="customTitle"
             class="modal-title">
            Laxo
        </div>

        <div id="customText"
             class="modal-text">
        </div>

        <div id="customContent">
        </div>

        <div class="modal-buttons"
             style="margin-top:15px">

            <button class="secondary"
                    onclick="closeCustomModal()">
                إغلاق
            </button>

            <button id="customConfirm"
                    class="primary"
                    onclick="customConfirmAction()">
                موافق
            </button>

        </div>

    </div>

</div>


<div id="toast"
     class="toast">
</div>

</div>


<script>

/* =========================================================
   LAXO APPLICATION CORE
   ========================================================= */

let state = {
    name: "",
    accountId: "",
    recoveryPassword: "",
    notifyMode: "fast",
    registered: false,
    messages: [],
    theme: "dark"
};

let cameraStream = null;
let customAction = null;


/* ---------------- STORAGE ---------------- */

function saveState(){

    localStorage.setItem(
        "LAXO_STATE",
        JSON.stringify(state)
    );

}

function loadState(){

    try{

        const raw =
            localStorage.getItem("LAXO_STATE");

        if(raw){

            const saved =
                JSON.parse(raw);

            state = {
                ...state,
                ...saved
            };

        }

    }catch(e){

        console.log(e);

    }

}


/* ---------------- SCREEN ---------------- */

function showScreen(id){

    document
        .querySelectorAll(".screen")
        .forEach(s => s.classList.remove("active"));

    const screen =
        document.getElementById(id);

    if(screen)
        screen.classList.add("active");

}

function goWelcome(){
    showScreen("welcome");
}

function showCreate(){
    showScreen("createName");
}

function showRecovery(){
    showScreen("recovery");
}


/* ---------------- RECOVERY TABS ---------------- */

function recoveryTab(tab){

    const pass =
        document.getElementById("recoveryPass");

    const qr =
        document.getElementById("recoveryQr");

    const passTab =
        document.getElementById("recoveryPassTab");

    const qrTab =
        document.getElementById("recoveryQrTab");

    if(tab === "pass"){

        pass.style.display = "";
        qr.style.display = "none";

        passTab.classList.add("active");
        qrTab.classList.remove("active");

    }else{

        pass.style.display = "none";
        qr.style.display = "";

        passTab.classList.remove("active");
        qrTab.classList.add("active");

    }

}


/* ---------------- CREATE ---------------- */

function nextCreateName(){

    const name =
        document
            .getElementById("displayName")
            .value
            .trim();

    if(!name){

        toast("يرجى إدخال اسم العرض");

        return;

    }

    state.name = name;

    saveState();

    showScreen("notifyMode");

}

function selectNotify(mode){

    state.notifyMode = mode;

    document
        .getElementById("fastOption")
        .classList.toggle(
            "selected",
            mode === "fast"
        );

    document
        .getElementById("slowOption")
        .classList.toggle(
            "selected",
            mode === "slow"
        );

}

function nextPermissions(){

    const bg =
        document.getElementById(
            "backgroundPermission"
        );

    if(state.notifyMode === "slow")
        bg.style.display = "";
    else
        bg.style.display = "none";

    showScreen("permissions");

}


/* ---------------- NOTIFICATIONS ---------------- */

async function requestNotifications(){

    if(!("Notification" in window)){

        toast("الإشعارات غير مدعومة في هذا المتصفح");

        return;

    }

    try{

        const result =
            await Notification.requestPermission();

        if(result === "granted"){

            toast("تم السماح بالإشعارات ✓");

            try{

                new Notification(
                    "Laxo",
                    {
                        body:"تم تفعيل إشعارات Laxo."
                    }
                );

            }catch(e){}

        }else{

            toast("لم يتم السماح بالإشعارات");

        }

    }catch(e){

        toast("تعذر طلب إذن الإشعارات");

    }

}

function backgroundPermission(){

    toast("تم اختيار تشغيل Laxo في الخلفية");

}


/* ---------------- ACCOUNT ---------------- */

async function createAccountId(name){

    const random =
        crypto.getRandomValues(
            new Uint8Array(32)
        );

    const base =
        name +
        Date.now() +
        Array.from(random).join(",");

    if(crypto.subtle){

        const data =
            new TextEncoder().encode(base);

        const hash =
            await crypto.subtle.digest(
                "SHA-256",
                data
            );

        return Array
            .from(new Uint8Array(hash))
            .map(
                b =>
                    b.toString(16).padStart(2,"0")
            )
            .join("");

    }

    return Array
        .from(random)
        .map(
            b =>
                b.toString(16).padStart(2,"0")
        )
        .join("");

}

function generateRecoveryPassword(){

    const chars =
        "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

    let result = "";

    const bytes =
        crypto.getRandomValues(
            new Uint8Array(20)
        );

    for(let i=0;i<20;i++){

        result +=
            chars[
                bytes[i] % chars.length
            ];

    }

    return result;

}

async function finishRegistration(){

    if(!state.name){

        toast("اسم الحساب غير موجود");

        showCreate();

        return;

    }

    state.accountId =
        await createAccountId(state.name);

    state.recoveryPassword =
        generateRecoveryPassword();

    state.registered = true;

    saveState();

    updateUI();

    showScreen("home");

    setTimeout(
        () => {
            showRecoveryPassword();
        },
        700
    );

}

function recoverAccount(){

    const value =
        document
            .getElementById("recoveryInput")
            .value
            .trim();

    if(!value){

        toast("أدخل كلمة مرور الاسترداد");

        return;

    }

    if(!state.recoveryPassword){

        toast("لا يوجد حساب محفوظ على هذا الجهاز");

        return;

    }

    if(value !== state.recoveryPassword){

        toast("كلمة مرور الاسترداد غير صحيحة");

        return;

    }

    state.registered = true;

    saveState();

    updateUI();

    showScreen("home");

    toast("تم تحميل الحساب بنجاح ✓");

}


/* ---------------- UI UPDATE ---------------- */

function updateUI(){

    const first =
        state.name
            ? state.name.trim().charAt(0).toUpperCase()
            : "L";

    document
        .getElementById("settingsAvatar")
        .textContent = first;

    document
        .getElementById("settingsName")
        .textContent =
            state.name || "Laxo";

    document
        .getElementById("settingsId")
        .textContent =
            state.accountId || "...";

    document
        .getElementById("fullAccountId")
        .textContent =
            state.accountId || "لم يتم إنشاء المعرف بعد";

    document
        .getElementById("modalAccountId")
        .textContent =
            state.accountId || "";

    document
        .getElementById("chatAvatar")
        .textContent = first;

    if(state.name){

        document
            .getElementById("chatName")
            .textContent =
                "ملاحظة لنفسي";

    }

    createQR(
        document.getElementById("sheetQR"),
        state.accountId || "LAXO"
    );

    createQR(
        document.getElementById("modalQR"),
        state.accountId || "LAXO"
    );

}


/* ---------------- SETTINGS ---------------- */

function openSettings(){

    updateUI();

    showScreen("settings");

}

function editName(){

    const newName =
        prompt(
            "أدخل اسم العرض الجديد:",
            state.name
        );

    if(!newName)
        return;

    state.name =
        newName.trim();

    saveState();

    updateUI();

    toast("تم تحديث الاسم ✓");

}

function copyAccountId(){

    if(!state.accountId){

        toast("لا يوجد معرف");

        return;

    }

    navigator.clipboard
        ?.writeText(state.accountId)
        .then(
            () => toast("تم نسخ معرف الحساب ✓")
        )
        .catch(
            () => toast("تعذر النسخ")
        );

}

async function shareAccountId(){

    const text =
        "Laxo Account ID:\n" +
        state.accountId;

    if(navigator.share){

        try{

            await navigator.share({
                title:"Laxo",
                text
            });

        }catch(e){}

    }else{

        copyAccountId();

    }

}

function showQR(){

    updateUI();

    document
        .getElementById("qrModal")
        .classList.add("show");

}

function closeQR(){

    document
        .getElementById("qrModal")
        .classList.remove("show");

}


/* ---------------- QR GENERATOR ---------------- */

/*
   Lightweight visual QR-like identity code.
   It intentionally does not claim to be a standards-compliant
   QR decoder. It gives each account a deterministic scannable-looking
   identity graphic without external libraries.
*/

function createQR(container,text){

    if(!container)
        return;

    container.innerHTML = "";

    const size = 21;

    let hash = 2166136261;

    for(let i=0;i<text.length;i++){

        hash ^= text.charCodeAt(i);
        hash =
            Math.imul(hash,16777619);

    }

    function rand(){

        hash += 0x6D2B79F5;

        let t = hash;

        t =
            Math.imul(
                t ^ t >>> 15,
                t | 1
            );

        t ^= t +
            Math.imul(
                t ^ t >>> 7,
                t | 61
            );

        return (
            (t ^ t >>> 14) >>> 0
        ) / 4294967296;

    }

    function finder(x,y){

        for(let dy=0;dy<7;dy++){

            for(let dx=0;dx<7;dx++){

                const cell =
                    document.createElement("span");

                let on = false;

                if(
                    dx===0 ||
                    dx===6 ||
                    dy===0 ||
                    dy===6
                ){
                    on = true;
                }

                if(
                    dx>=2 &&
                    dx<=4 &&
                    dy>=2 &&
                    dy<=4
                ){
                    on = true;
                }

                cell.className =
                    on ? "on" : "";

                cell.dataset.x =
                    x + dx;

                cell.dataset.y =
                    y + dy;

                container.appendChild(cell);

            }

        }

    }

    const cells = [];

    for(let y=0;y<size;y++){

        for(let x=0;x<size;x++){

            const cell =
                document.createElement("span");

            let reserved = false;

            if(
                x<7 && y<7 ||
                x>=14 && y<7 ||
                x<7 && y>=14
            ){
                reserved = true;
            }

            let on =
                reserved
                ? false
                : rand() > .54;

            cell.className =
                on ? "on" : "";

            cells.push(cell);

            container.appendChild(cell);

        }

    }

    const children =
        Array.from(container.children);

    function setFinder(x,y){

        for(let dy=0;dy<7;dy++){

            for(let dx=0;dx<7;dx++){

                const index =
                    (y+dy)*size +
                    (x+dx);

                if(!children[index])
                    continue;

                const on =
                    dx===0 ||
                    dx===6 ||
                    dy===0 ||
                    dy===6 ||
                    (
                        dx>=2 &&
                        dx<=4 &&
                        dy>=2 &&
                        dy<=4
                    );

                children[index]
                    .className =
                    on ? "on" : "";

            }

        }

    }

    setFinder(0,0);
    setFinder(14,0);
    setFinder(0,14);

}


/* ---------------- START SHEET ---------------- */

function openStartSheet(){

    updateUI();

    document
        .getElementById("startSheet")
        .classList.add("show");

}

function closeSheet(event){

    if(event.target.id === "startSheet"){

        document
            .getElementById("startSheet")
            .classList.remove("show");

    }

}

function closeStartSheet(){

    document
        .getElementById("startSheet")
        .classList.remove("show");

}


/* ---------------- NEW CHAT ---------------- */

function newMessage(){

    closeStartSheet();

    setTimeout(
        () => {

            const name =
                prompt(
                    "اكتب اسم الشخص:"
                );

            if(!name)
                return;

            document
                .getElementById("chatName")
                .textContent =
                    name;

            document
                .getElementById("chatStatus")
                .textContent =
                    "آخر ظهور مؤخراً";

            showScreen("chat");

        },
        200
    );

}

function createGroup(){

    closeStartSheet();

    setTimeout(
        () => {

            const name =
                prompt(
                    "اسم المجموعة:"
                );

            if(name)
                toast(
                    "تم إنشاء مساحة مجموعة: " +
                    name
                );

        },
        200
    );

}

function joinCommunity(){

    closeStartSheet();

    toast(
        "قسم المجتمعات جاهز للربط مع الخادم"
    );

}


/* ---------------- INVITE ---------------- */

async function inviteFriend(){

    closeStartSheet();

    const text =
        "انضم إليّ على Laxo\n" +
        "معرف الحساب:\n" +
        state.accountId;

    if(navigator.share){

        try{

            await navigator.share({
                title:"دعوة إلى Laxo",
                text
            });

        }catch(e){}

    }else{

        if(navigator.clipboard){

            await navigator.clipboard
                .writeText(text);

            toast("تم نسخ الدعوة ✓");

        }

    }

}


/* ---------------- CHAT ---------------- */

function sendMessage(){

    const input =
        document.getElementById(
            "messageInput"
        );

    const value =
        input.value.trim();

    if(!value)
        return;

    addMessage(
        value,
        "me"
    );

    input.value = "";

    setTimeout(
        () => {

            if(
                document
                    .getElementById("chatName")
                    .textContent ===
                "ملاحظة لنفسي"
            ){

                addMessage(
                    value,
                    "me"
                );

            }

        },
        350
    );

}

function addMessage(text,type){

    const body =
        document.getElementById(
            "chatBody"
        );

    const div =
        document.createElement("div");

    div.className =
        "message " + type;

    div.textContent = text;

    const time =
        document.createElement("span");

    time.className =
        "message-time";

    time.textContent =
        "الآن • تشفير واجهة";

    div.appendChild(time);

    body.appendChild(div);

    body.scrollTop =
        body.scrollHeight;

}

function messageKey(event){

    if(
        event.key === "Enter" &&
        !event.shiftKey
    ){

        event.preventDefault();

        sendMessage();

    }

}

function attachFile(){

    document
        .getElementById("fileInput")
        .click();

}

function cameraMessage(){

    document
        .getElementById("cameraInput")
        .click();

}

function fileSelected(event){

    const file =
        event.target.files[0];

    if(!file)
        return;

    addMessage(
        "📎 " + file.name,
        "me"
    );

    toast(
        "تم اختيار الملف: " +
        file.name
    );

}

function cameraSelected(event){

    const file =
        event.target.files[0];

    if(!file)
        return;

    addMessage(
        "📷 صورة: " + file.name,
        "me"
    );

}


/* ---------------- CALLS ---------------- */

function startCall(type){

    const title =
        type === "video"
        ? "مكالمة فيديو"
        : "مكالمة صوتية";

    showCustom(
        title,
        "هذه واجهة المكالمة. الاتصال الحقيقي P2P/WebRTC يحتاج خادم إشارة ومستخدماً آخر متصلاً.",
        null,
        null
    );

}


/* ---------------- CAMERA / QR ---------------- */

async function openCamera(){

    document
        .getElementById("cameraModal")
        .classList.add("show");

    try{

        if(!navigator.mediaDevices ||
           !navigator.mediaDevices.getUserMedia){

            toast(
                "الكاميرا تحتاج HTTPS أو localhost"
            );

            return;

        }

        cameraStream =
            await navigator.mediaDevices.getUserMedia({
                video:{
                    facingMode:{
                        ideal:"environment"
                    }
                },
                audio:false
            });

        document
            .getElementById("cameraVideo")
            .srcObject =
                cameraStream;

    }catch(error){

        toast(
            "تم رفض إذن الكاميرا أو أنها غير متاحة"
        );

    }

}

function closeCamera(){

    if(cameraStream){

        cameraStream
            .getTracks()
            .forEach(
                track =>
                    track.stop()
            );

        cameraStream = null;

    }

    document
        .getElementById("cameraModal")
        .classList.remove("show");

}

function simulateQRScan(){

    /*
       In a production application replace this
       with BarcodeDetector / ZXing / native QR scanner.
    */

    closeCamera();

    if(state.accountId){

        toast(
            "تم التقاط رمز QR تجريبياً"
        );

        setTimeout(
            () => {

                showScreen("home");

            },
            600
        );

    }

}


/* ---------------- SEARCH ---------------- */

function searchChats(){

    showCustom(
        "بحث",
        "",
        `
        <input id="searchInput"
               class="field"
               placeholder="ابحث عن محادثة أو شخص..."
               autofocus>
        `,
        null
    );

}


/* ---------------- SETTINGS ACTIONS ---------------- */

function toggleSetting(el){

    el.classList.toggle("on");

    toast(
        el.classList.contains("on")
        ? "تم التفعيل"
        : "تم الإيقاف"
    );

}

function privacySettings(){

    showCustom(
        "الخصوصية",
        "من هنا يمكن لاحقاً التحكم في آخر ظهور، حالة الاتصال، مؤشرات القراءة وقفل التطبيق.",
        null,
        null
    );

}

function notificationSettings(){

    showCustom(
        "الإشعارات",
        "إعدادات إشعارات الرسائل والمكالمات والنغمات.",
        null,
        null
    );

}

function chatSettings(){

    showCustom(
        "المحادثات",
        "إعدادات الحفظ التلقائي للوسائط وحجم الخط.",
        null,
        null
    );

}

function messageRequests(){

    showCustom(
        "طلبات المراسلة",
        "يمكنك التحكم في قبول أو رفض الرسائل من الحسابات غير المعروفة.",
        null,
        null
    );

}

function networkInfo(){

    showCustom(
        "Laxo Network",
        "هذه النسخة تعمل محلياً. ربط الخادم الحقيقي يحتاج Backend وAPI.",
        null,
        null
    );

}

function donate(){

    showCustom(
        "التبرع",
        "يمكن ربط هذا القسم لاحقاً ببوابة دفع قانونية.",
        null,
        null
    );

}

function help(){

    showCustom(
        "المساعدة",
        "Laxo — الخصوصية في جيبك.\n\nهذه نسخة واجهة محلية تجريبية.",
        null,
        null
    );

}

function showRecoveryPassword(){

    if(!state.recoveryPassword){

        toast("لا توجد كلمة استرداد");

        return;

    }

    showCustom(
        "كلمة مرور الاسترداد",
        "احفظ هذه الكلمة في مكان آمن. لا تشاركها مع أي شخص.",
        `
        <div class="option"
             style="direction:ltr;text-align:center;font-family:monospace;font-size:18px;color:#8dffba">
            ${escapeHTML(state.recoveryPassword)}
        </div>
        `,
        null
    );

}

function deleteData(){

    showCustom(
        "مسح البيانات",
        "سيؤدي هذا إلى حذف حساب Laxo المحلي وبياناته من هذا الجهاز.",
        null,
        () => {

            localStorage.removeItem(
                "LAXO_STATE"
            );

            location.reload();

        }
    );

}


/* ---------------- EDIT THEME ---------------- */

function toggleTheme(){

    const app =
        document.getElementById("app");

    app.classList.toggle("light");

    state.theme =
        app.classList.contains("light")
        ? "light"
        : "dark";

    saveState();

    toast(
        state.theme === "light"
        ? "تم تفعيل المظهر الفاتح"
        : "تم تفعيل المظهر الداكن"
    );

}


/* ---------------- CUSTOM MODAL ---------------- */

function showCustom(
    title,
    text,
    content,
    action
){

    document
        .getElementById("customTitle")
        .textContent =
            title;

    document
        .getElementById("customText")
        .textContent =
            text || "";

    document
        .getElementById("customContent")
        .innerHTML =
            content || "";

    customAction =
        action;

    document
        .getElementById("customModal")
        .classList.add("show");

}

function closeCustomModal(){

    document
        .getElementById("customModal")
        .classList.remove("show");

    customAction = null;

}

function customConfirmAction(){

    if(customAction){

        const fn =
            customAction;

        customAction = null;

        closeCustomModal();

        fn();

    }else{

        closeCustomModal();

    }

}


/* ---------------- TOAST ---------------- */

let toastTimer;

function toast(message){

    const el =
        document.getElementById("toast");

    el.textContent =
        message;

    el.classList.add("show");

    clearTimeout(toastTimer);

    toastTimer =
        setTimeout(
            () =>
                el.classList.remove("show"),
            2600
        );

}


/* ---------------- ESCAPE ---------------- */

function escapeHTML(value){

    return String(value)
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;")
        .replaceAll('"',"&quot;")
        .replaceAll("'","&#039;");

}


/* ---------------- INIT ---------------- */

function init(){

    loadState();

    const app =
        document.getElementById("app");

    if(state.theme === "light")
        app.classList.add("light");

    updateUI();

    if(state.registered){

        /*
           Existing account:
           stay on welcome initially so user can
           choose the desired route.
        */

    }

}


/* ---------------- PWA-LIKE KEY HANDLING ---------------- */

document.addEventListener(
    "keydown",
    event => {

        if(event.key === "Escape"){

            document
                .querySelectorAll(
                    ".modal.show,.overlay.show"
                )
                .forEach(
                    element =>
                        element.classList.remove("show")
                );

        }

    }
);

window.addEventListener(
    "beforeunload",
    () => {

        if(cameraStream){

            cameraStream
                .getTracks()
                .forEach(
                    track =>
                        track.stop()
                );

        }

    }
);

init();

</script>

</body>
</html>
'''


class LaxoHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path in ("/", "/index.html"):

            data = HTML.encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(data))
            )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.end_headers()

            self.wfile.write(data)

        else:

            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_server():

    class ReusableTCPServer(
        socketserver.TCPServer
    ):
        allow_reuse_address = True

    with ReusableTCPServer(
        (HOST, PORT),
        LaxoHandler
    ) as server:

        url = f"http://{HOST}:{PORT}"

        print()
        print("=" * 55)
        print("                 LAXO")
        print("=" * 55)
        print()
        print("Laxo يعمل الآن.")
        print()
        print("افتح في المتصفح:")
        print(url)
        print()
        print("اضغط Ctrl+C لإيقاف التطبيق.")
        print("=" * 55)
        print()

        try:
            server.serve_forever()

        except KeyboardInterrupt:

            print("\nتم إيقاف Laxo.")

        finally:

            server.server_close()


if __name__ == "__main__":

    server_thread = threading.Thread(
        target=start_server,
        daemon=True
    )

    server_thread.start()

    # محاولة فتح المتصفح تلقائياً
    try:

        webbrowser.open(
            f"http://{HOST}:{PORT}"
        )

    except Exception:
        pass

    try:

        server_thread.join()

    except KeyboardInterrupt:

        sys.exit(0)
