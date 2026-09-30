# -*- coding: utf-8 -*-
"""
auth.py — ระบบเข้าสู่ระบบ
  • เข้าด้วยบัญชี Google (OAuth 2.0)
  • เข้าด้วยรหัสผ่านเดียวที่ตั้งไว้ในไฟล์ config.json

ค่าตั้งทั้งหมดอยู่ในไฟล์ config.json ซึ่งจะถูกสร้างอัตโนมัติเมื่อรันครั้งแรก
"""

import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint, redirect, render_template, request, session, url_for, jsonify
)

import mailer
import security
import users

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

CODE_MINUTES = 10          # อายุรหัสยืนยัน
CODE_MAX_TRY = 5           # จำนวนครั้งที่กรอกรหัสผิดได้
RESEND_WAIT = 60           # วินาทีที่ต้องรอก่อนขอรหัสใหม่
PENDING_MAX = 200          # จำนวนคำขอที่ค้างไว้พร้อมกันสูงสุด

_pending = {}              # token -> ข้อมูลการสมัครที่รอยืนยัน

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

DEFAULT_CONFIG = {
    "_อ่านก่อน": "ตั้งค่า Google ดูไฟล์ คู่มือตั้งค่า-Google.md · ตั้งค่าอีเมลดูไฟล์ คู่มือตั้งค่า-อีเมล.md",
    "secret_key": "",
    "access_password": "1234",
    "google_client_id": "",
    "google_client_secret": "",
    "allowed_emails": [],
    "session_days": 14,
    "allow_signup": True,
    "smtp": {
        "host": "smtp.gmail.com",
        "port": 465,
        "user": "",
        "password": "",
        "sender_name": "Auto Link Photo",
    },
}

# เส้นทางที่เข้าได้โดยไม่ต้องเข้าสู่ระบบ
PUBLIC_ENDPOINTS = {
    "auth.login", "auth.do_login", "auth.google_start",
    "auth.google_callback", "auth.logout", "static",
    "auth.register", "auth.do_register", "auth.verify",
    "auth.do_verify", "auth.resend",
}

bp = Blueprint("auth", __name__)


# ------------------------------------------------------------------ config

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (ValueError, OSError):
            pass
    if not cfg.get("secret_key"):
        cfg["secret_key"] = secrets.token_hex(32)
        save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def google_ready(cfg):
    return bool(cfg.get("google_client_id") and cfg.get("google_client_secret"))


def email_allowed(cfg, email):
    allow = cfg.get("allowed_emails") or []
    if not allow:
        return True                     # ว่าง = อนุญาตทุกบัญชี
    email = (email or "").lower()
    for rule in allow:
        rule = str(rule).strip().lower()
        if not rule:
            continue
        if rule.startswith("@") and email.endswith(rule):
            return True                 # ทั้งโดเมน เช่น @company.com
        if rule == email:
            return True
    return False


# ------------------------------------------------------------------ guard

def current_user():
    return session.get("user")


def install(app):
    """ผูกระบบเข้าสู่ระบบเข้ากับแอป"""
    cfg = load_config()
    app.secret_key = cfg["secret_key"]
    app.permanent_session_lifetime = 60 * 60 * 24 * int(cfg.get("session_days", 14))
    app.config["APP_CONFIG"] = cfg
    app.register_blueprint(bp)

    @app.before_request
    def _require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if current_user():
            return None
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "กรุณาเข้าสู่ระบบก่อนใช้งาน"}), 401
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    @app.context_processor
    def _inject_user():
        # หน้าเว็บทุกหน้าที่มีฟอร์มต้องแนบโทเคนกำกับไปด้วย
        # จึงส่งตัวสร้างโทเคนเข้าไปให้เทมเพลตเรียกใช้ได้เอง
        return {"user": current_user(), "csrf_token": security.csrf_token}


def _login_ok(profile, remember=True):
    session.permanent = bool(remember)
    session["user"] = profile
    session.pop("oauth_state", None)


def _safe_next(raw):
    """กันการเปลี่ยนเส้นทางไปเว็บภายนอก"""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


# ------------------------------------------------------------------ routes

def _login_page(cfg, **kw):
    kw.setdefault("google_ready", google_ready(cfg))
    kw.setdefault("allow_signup", bool(cfg.get("allow_signup", True)))
    kw.setdefault("error", "")
    kw.setdefault("info", "")
    kw.setdefault("email", "")
    kw.setdefault("next", "/")
    return render_template("login.html", **kw)


@bp.get("/login")
def login():
    cfg = load_config()
    if current_user():
        return redirect("/")
    return _login_page(cfg,
                       error=request.args.get("error", ""),
                       info=request.args.get("info", ""),
                       next=request.args.get("next", "/"))


@bp.post("/login")
def do_login():
    cfg = load_config()
    email = (request.form.get("email") or "").strip()
    pwd = request.form.get("password", "")
    nxt = _safe_next(request.form.get("next", "/"))
    remember = bool(request.form.get("remember"))

    # 1) รหัสผ่านผู้ดูแล (เว้นช่องอีเมลไว้)
    master = str(cfg.get("access_password") or "")
    if not email and master and hmac.compare_digest(pwd, master):
        _login_ok({"name": "ผู้ดูแล", "email": "", "picture": "", "via": "password"},
                  remember=remember)
        return redirect(nxt)

    # 2) บัญชีที่สมัครไว้
    if email:
        u = users.verify(email, pwd)
        if u:
            _login_ok({"name": u["name"], "email": u["email"],
                       "picture": "", "via": "email"}, remember=remember)
            return redirect(nxt)
        if users.exists(email) and not (users.get(email) or {}).get("password"):
            return _login_page(cfg, email=email, next=nxt,
                               error="บัญชีนี้สมัครไว้ด้วย Google กรุณากดปุ่มเข้าสู่ระบบด้วย Google"), 401

    return _login_page(cfg, email=email, next=nxt,
                       error="อีเมลหรือรหัสผ่านไม่ถูกต้อง"), 401


# --------------------------------------------------------- สมัครสมาชิก

def _cleanup_pending():
    now = time.time()
    for k in [k for k, v in _pending.items() if v["expire"] < now]:
        _pending.pop(k, None)
    while len(_pending) > PENDING_MAX:
        oldest = min(_pending, key=lambda k: _pending[k]["expire"])
        _pending.pop(oldest, None)


def _new_code():
    return f"{secrets.randbelow(1000000):06d}"


def _send_or_show(cfg, entry):
    """ส่งรหัสทางอีเมล คืน (ข้อความแจ้ง, รหัสที่ต้องแสดงบนหน้าจอถ้าส่งไม่ได้)"""
    if not mailer.is_ready(cfg):
        return "", entry["code"]
    ok, err = mailer.send_code(cfg, entry["email"], entry["code"],
                               entry["name"], CODE_MINUTES)
    if ok:
        return f"ส่งรหัสยืนยันไปที่ {entry['email']} แล้ว", ""
    return err, ""


@bp.get("/register")
def register():
    cfg = load_config()
    if current_user():
        return redirect("/")
    if not cfg.get("allow_signup", True):
        return redirect(url_for("auth.login", error="ระบบปิดรับสมัครสมาชิกใหม่"))
    return render_template("register.html", error="", form={})


@bp.post("/register")
def do_register():
    cfg = load_config()
    if not cfg.get("allow_signup", True):
        return redirect(url_for("auth.login", error="ระบบปิดรับสมัครสมาชิกใหม่"))

    form = {
        "name": (request.form.get("name") or "").strip(),
        "email": (request.form.get("email") or "").strip(),
    }
    pwd = request.form.get("password", "")
    pwd2 = request.form.get("password2", "")

    def fail(msg):
        return render_template("register.html", error=msg, form=form), 400

    if not form["name"]:
        return fail("กรุณากรอกชื่อที่ต้องการแสดง")
    if not users.valid_email(form["email"]):
        return fail("รูปแบบอีเมลไม่ถูกต้อง")
    if users.exists(form["email"]):
        return fail("อีเมลนี้ถูกใช้สมัครไว้แล้ว — กรุณาเข้าสู่ระบบแทน")
    problem = users.password_problem(pwd)
    if problem:
        return fail(problem)
    if pwd != pwd2:
        return fail("รหัสผ่านทั้งสองช่องไม่ตรงกัน")
    if not email_allowed(cfg, form["email"]):
        return fail("อีเมลนี้ไม่ได้รับอนุญาตให้สมัครใช้งาน")

    _cleanup_pending()
    token = secrets.token_urlsafe(24)
    entry = {
        "email": users.norm(form["email"]),
        "name": form["name"],
        "password": pwd,
        "code": _new_code(),
        "expire": time.time() + CODE_MINUTES * 60,
        "tries": 0,
        "last_sent": time.time(),
    }
    _pending[token] = entry
    session["pending"] = token

    note, show = _send_or_show(cfg, entry)
    return redirect(url_for("auth.verify", note=note, show=show))


@bp.get("/register/verify")
def verify():
    token = session.get("pending")
    entry = _pending.get(token or "")
    if not entry:
        return redirect(url_for("auth.register"))
    return render_template("verify.html", email=entry["email"],
                           error="", note=request.args.get("note", ""),
                           show=request.args.get("show", ""),
                           minutes=CODE_MINUTES)


@bp.post("/register/verify")
def do_verify():
    token = session.get("pending")
    entry = _pending.get(token or "")
    if not entry:
        return redirect(url_for("auth.register"))

    def page(msg, status=400):
        return render_template("verify.html", email=entry["email"], error=msg,
                               note="", show="", minutes=CODE_MINUTES), status

    if time.time() > entry["expire"]:
        _pending.pop(token, None)
        session.pop("pending", None)
        return redirect(url_for("auth.register"))

    code = re_digits(request.form.get("code", ""))
    entry["tries"] += 1
    if entry["tries"] > CODE_MAX_TRY:
        _pending.pop(token, None)
        session.pop("pending", None)
        return redirect(url_for("auth.register"))

    if not code or not hmac.compare_digest(code, entry["code"]):
        left = CODE_MAX_TRY - entry["tries"] + 1
        return page(f"รหัสยืนยันไม่ถูกต้อง เหลืออีก {left} ครั้ง")

    ok, err = users.create(entry["email"], entry["name"], entry["password"])
    _pending.pop(token, None)
    session.pop("pending", None)
    if not ok:
        return redirect(url_for("auth.login", error=err))

    _login_ok({"name": entry["name"], "email": entry["email"],
               "picture": "", "via": "email"}, remember=True)
    return redirect("/")


@bp.post("/register/resend")
def resend():
    cfg = load_config()
    token = session.get("pending")
    entry = _pending.get(token or "")
    if not entry:
        return redirect(url_for("auth.register"))

    wait = int(RESEND_WAIT - (time.time() - entry["last_sent"]))
    if wait > 0:
        return render_template("verify.html", email=entry["email"],
                               error=f"กรุณารออีก {wait} วินาทีก่อนขอรหัสใหม่",
                               note="", show="", minutes=CODE_MINUTES), 429

    entry["code"] = _new_code()
    entry["expire"] = time.time() + CODE_MINUTES * 60
    entry["tries"] = 0
    entry["last_sent"] = time.time()
    note, show = _send_or_show(cfg, entry)
    return redirect(url_for("auth.verify", note=note or "ส่งรหัสใหม่แล้ว", show=show))


def re_digits(s):
    return "".join(ch for ch in (s or "") if ch.isdigit())[:6]


@bp.get("/auth/google")
def google_start():
    cfg = load_config()
    if not google_ready(cfg):
        return redirect(url_for("auth.login", error="ยังไม่ได้ตั้งค่าการเข้าสู่ระบบด้วย Google"))

    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    session["oauth_next"] = _safe_next(request.args.get("next", "/"))

    params = {
        "client_id": cfg["google_client_id"],
        "redirect_uri": url_for("auth.google_callback", _external=True),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return redirect(GOOGLE_AUTH_URL + "?" + urlencode(params))


@bp.get("/auth/google/callback")
def google_callback():
    cfg = load_config()

    if request.args.get("error"):
        return redirect(url_for("auth.login", error="ยกเลิกการเข้าสู่ระบบด้วย Google"))

    state = request.args.get("state", "")
    if not state or state != session.pop("oauth_state", None):
        return redirect(url_for("auth.login", error="คำขอไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง"))

    code = request.args.get("code", "")
    if not code:
        return redirect(url_for("auth.login", error="ไม่ได้รับรหัสยืนยันจาก Google"))

    try:
        tok = requests.post(GOOGLE_TOKEN_URL, timeout=20, data={
            "code": code,
            "client_id": cfg["google_client_id"],
            "client_secret": cfg["google_client_secret"],
            "redirect_uri": url_for("auth.google_callback", _external=True),
            "grant_type": "authorization_code",
        })
        tok.raise_for_status()
        access_token = tok.json().get("access_token")
        if not access_token:
            raise ValueError

        info = requests.get(GOOGLE_USERINFO_URL, timeout=20,
                            headers={"Authorization": "Bearer " + access_token})
        info.raise_for_status()
        data = info.json()
    except (requests.exceptions.RequestException, ValueError):
        return redirect(url_for("auth.login",
                                error="ติดต่อ Google ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"))

    email = data.get("email", "")
    if not data.get("email_verified", True):
        return redirect(url_for("auth.login", error="อีเมลนี้ยังไม่ได้ยืนยันกับ Google"))
    if not email_allowed(cfg, email):
        return redirect(url_for("auth.login", error="บัญชีนี้ไม่ได้รับอนุญาตให้เข้าใช้งาน"))

    name = data.get("name") or email.split("@")[0]
    users.ensure_google_user(email, name, data.get("picture", ""))

    _login_ok({
        "name": name,
        "email": email,
        "picture": data.get("picture", ""),
        "via": "google",
    })
    return redirect(_safe_next(session.pop("oauth_next", "/")))


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
