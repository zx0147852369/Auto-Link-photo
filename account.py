# -*- coding: utf-8 -*-
"""
account.py — หน้าตั้งค่าโปรไฟล์และการยืนยันตัวตนสองชั้น
"""

import io
import os
import secrets

from flask import (
    Blueprint, redirect, render_template, request, session, url_for
)

import history
import imgguard
import security
import totp
import users

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AVATAR_DIR = os.path.join(BASE_DIR, "static", "avatars")

MAX_AVATAR_BYTES = 5 * 1024 * 1024
AVATAR_SIZE = 256

bp = Blueprint("account", __name__)


# ------------------------------------------------------------------ ช่วยเหลือ

def _me():
    return session.get("user") or {}


def _email():
    return (_me().get("email") or "").strip().lower()


def _refresh_session(email=None):
    """ดึงข้อมูลล่าสุดจากไฟล์มาใส่ session"""
    e = email or _email()
    u = users.get(e)
    if not u:
        return
    session["user"] = {
        "name": u.get("name", ""),
        "email": u.get("email", ""),
        "picture": u.get("picture", ""),
        "via": u.get("via", "email"),
    }


def _page(**kw):
    e = _email()
    u = users.get(e) or {}
    kw.setdefault("u", u)
    kw.setdefault("is_admin", not e)
    kw.setdefault("totp_on", bool(u.get("totp_enabled")))
    kw.setdefault("backup_left", len(u.get("backup") or []))
    kw.setdefault("min_password", users.MIN_PASSWORD)
    kw.setdefault("ok", "")
    kw.setdefault("err", "")
    kw.setdefault("setup", None)
    kw.setdefault("codes", None)
    kw.setdefault("focus", "")
    return render_template("account.html", **kw)


def _guard():
    """บัญชีผู้ดูแลที่ไม่มีอีเมลจะแก้โปรไฟล์ไม่ได้"""
    return None if _email() else _page(
        err="บัญชีผู้ดูแลไม่มีข้อมูลโปรไฟล์ให้แก้ไข กรุณาสมัครบัญชีผู้ใช้เพื่อใช้ส่วนนี้")


# ------------------------------------------------------------------ หน้าหลัก

@bp.get("/account")
def account():
    if not _email():
        return _page()
    _refresh_session()
    return _page(ok=request.args.get("ok", ""), focus=request.args.get("focus", ""))


# ------------------------------------------------------------------ ชื่อ

@bp.post("/account/name")
def set_name():
    g = _guard()
    if g:
        return g, 403
    ok, msg = users.set_name(_email(), request.form.get("name", ""))
    if not ok:
        return _page(err=msg, focus="profile"), 400
    _refresh_session()
    return redirect(url_for("account.account", ok="บันทึกชื่อใหม่แล้ว", focus="profile"))


# ------------------------------------------------------------------ รูปโปรไฟล์

def _save_avatar(data: bytes, email: str):
    """
    บันทึกรูปโปรไฟล์ — วาดใหม่ทั้งไฟล์ด้วย Pillow ถ้ามี
    การวาดใหม่จะตัดข้อมูลแฝงทุกอย่างที่ซ่อนมากับไฟล์ออกไปด้วย
    """
    os.makedirs(AVATAR_DIR, exist_ok=True)
    name = f"{secrets.token_hex(10)}.png"
    path = os.path.join(AVATAR_DIR, name)
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        im = im.convert("RGBA")
        w, h = im.size
        side = min(w, h)
        im = im.crop(((w - side) // 2, (h - side) // 2,
                      (w + side) // 2, (h + side) // 2))
        im = im.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        bg.convert("RGB").save(path, "PNG", optimize=True)
        return name, ""
    except ImportError:
        pass
    except Exception:
        return "", "เปิดไฟล์รูปนี้ไม่ได้ กรุณาลองไฟล์อื่น"

    # ไม่มี Pillow — เก็บไฟล์เดิมหลังผ่านการคัดกรองแล้ว
    ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    name = name.replace(".png", ext)
    try:
        with open(os.path.join(AVATAR_DIR, name), "wb") as f:
            f.write(data)
    except OSError:
        return "", "บันทึกไฟล์ไม่สำเร็จ"
    return name, ""


def _drop_avatar(filename):
    if not filename:
        return
    p = os.path.join(AVATAR_DIR, os.path.basename(filename))
    try:
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass


@bp.post("/account/picture")
def set_picture():
    g = _guard()
    if g:
        return g, 403
    f = request.files.get("picture")
    if not f or not f.filename:
        return _page(err="กรุณาเลือกไฟล์รูป", focus="profile"), 400

    data = f.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        return _page(err="ไฟล์ใหญ่เกิน 5 MB", focus="profile"), 400

    verdict = imgguard.screen(data, f.mimetype or "", f.filename)
    if verdict["level"] == imgguard.DANGER:
        return _page(err="ระบบคัดกรองพบสิ่งผิดปกติในไฟล์นี้ — "
                         + imgguard.summarize(verdict), focus="profile"), 400

    name, err = _save_avatar(data, _email())
    if err:
        return _page(err=err, focus="profile"), 400

    old = (users.get(_email()) or {}).get("picture")
    users.set_picture(_email(), name)
    _drop_avatar(old)
    _refresh_session()
    return redirect(url_for("account.account", ok="เปลี่ยนรูปโปรไฟล์แล้ว", focus="profile"))


@bp.post("/account/picture/remove")
def remove_picture():
    g = _guard()
    if g:
        return g, 403
    old = (users.get(_email()) or {}).get("picture")
    users.set_picture(_email(), "")
    _drop_avatar(old)
    _refresh_session()
    return redirect(url_for("account.account", ok="ลบรูปโปรไฟล์แล้ว", focus="profile"))


# ------------------------------------------------------------------ อีเมล

@bp.post("/account/email")
def set_email():
    g = _guard()
    if g:
        return g, 403
    old = _email()
    new = (request.form.get("email") or "").strip()[:254]
    pwd = request.form.get("password", "")[:128]

    ok, wait = security.rate_check("account", limit=10, window=600)
    if not ok:
        return _page(err=f"ทำรายการบ่อยเกินไป กรุณารออีก {wait} วินาที", focus="email"), 429

    ok, msg = users.change_email(old, new, pwd)
    if not ok:
        return _page(err=msg, focus="email"), 400

    history.move(old, new)          # ย้ายประวัติการค้นหาตามอีเมลใหม่
    _refresh_session(new)
    return redirect(url_for("account.account", ok="เปลี่ยนอีเมลแล้ว", focus="email"))


# ------------------------------------------------------------------ รหัสผ่าน

@bp.post("/account/password")
def set_pwd():
    g = _guard()
    if g:
        return g, 403
    cur = request.form.get("current", "")[:128]
    new = request.form.get("new", "")[:128]
    new2 = request.form.get("new2", "")[:128]

    ok, wait = security.rate_check("account", limit=10, window=600)
    if not ok:
        return _page(err=f"ทำรายการบ่อยเกินไป กรุณารออีก {wait} วินาที", focus="password"), 429
    if new != new2:
        return _page(err="รหัสผ่านใหม่ทั้งสองช่องไม่ตรงกัน", focus="password"), 400

    ok, msg = users.change_password(_email(), cur, new)
    if not ok:
        return _page(err=msg, focus="password"), 400
    return redirect(url_for("account.account", ok="เปลี่ยนรหัสผ่านแล้ว", focus="password"))


# ------------------------------------------------------- การยืนยันสองชั้น

@bp.post("/account/2fa/start")
def totp_start():
    g = _guard()
    if g:
        return g, 403
    e = _email()
    secret = users.start_totp(e)
    return _page(setup={"secret": secret,
                        "pretty": totp.pretty(secret),
                        "uri": totp.uri(secret, e),
                        "qr": totp.qr_svg(totp.uri(secret, e))},
                 focus="twofa")


@bp.post("/account/2fa/enable")
def totp_enable():
    g = _guard()
    if g:
        return g, 403
    e = _email()
    ok, msg, codes = users.enable_totp(e, request.form.get("code", ""))
    if not ok:
        u = users.get(e) or {}
        secret = u.get("totp_secret", "")
        return _page(err=msg, focus="twofa",
                     setup={"secret": secret, "pretty": totp.pretty(secret),
                            "uri": totp.uri(secret, e),
                            "qr": totp.qr_svg(totp.uri(secret, e))}), 400
    return _page(ok="เปิดการยืนยันสองชั้นแล้ว", codes=codes, focus="twofa")


@bp.post("/account/2fa/disable")
def totp_disable():
    g = _guard()
    if g:
        return g, 403
    ok, msg = users.disable_totp(_email(), request.form.get("password", "")[:128])
    if not ok:
        return _page(err=msg, focus="twofa"), 400
    return redirect(url_for("account.account", ok="ปิดการยืนยันสองชั้นแล้ว", focus="twofa"))


@bp.post("/account/2fa/backup")
def totp_backup():
    g = _guard()
    if g:
        return g, 403
    ok, msg, codes = users.regen_backup(_email(), request.form.get("password", "")[:128])
    if not ok:
        return _page(err=msg, focus="twofa"), 400
    return _page(ok="สร้างรหัสสำรองชุดใหม่แล้ว รหัสชุดเก่าใช้ไม่ได้อีก",
                 codes=codes, focus="twofa")
