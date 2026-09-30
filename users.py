# -*- coding: utf-8 -*-
"""
users.py — ที่เก็บบัญชีผู้ใช้ (ไฟล์ users.json)
รหัสผ่านถูกเข้ารหัสด้วย hash แบบทางเดียว ไม่มีการเก็บรหัสผ่านจริง
"""

import json
import os
import re
import threading
import time

from werkzeug.security import check_password_hash, generate_password_hash

import totp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_PATH = os.path.join(BASE_DIR, "users.json")

_lock = threading.Lock()

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MIN_PASSWORD = 8


def valid_email(email: str) -> bool:
    email = (email or "").strip()
    return bool(EMAIL_RE.match(email)) and len(email) <= 254


def password_rules(pwd: str):
    """ผลการตรวจแต่ละข้อ — ใช้ร่วมกันทั้งฝั่งเซิร์ฟเวอร์และหน้าเว็บ"""
    pwd = pwd or ""
    return {
        "length": len(pwd) >= MIN_PASSWORD,
        "upper": bool(re.search(r"[A-Z]", pwd)),
        "lower": bool(re.search(r"[a-z]", pwd)),
    }


def password_problem(pwd: str):
    """คืนข้อความปัญหา หรือ None ถ้ารหัสผ่านใช้ได้"""
    pwd = pwd or ""
    if len(pwd) > 128:
        return "รหัสผ่านยาวเกินไป"
    r = password_rules(pwd)
    if not r["length"]:
        return f"รหัสผ่านต้องมีอย่างน้อย {MIN_PASSWORD} ตัวอักษร"
    if not r["upper"]:
        return "รหัสผ่านต้องมีตัวอักษรพิมพ์ใหญ่อย่างน้อย 1 ตัว"
    if not r["lower"]:
        return "รหัสผ่านต้องมีตัวอักษรพิมพ์เล็กอย่างน้อย 1 ตัว"
    return None


def _read():
    if not os.path.exists(USERS_PATH):
        return {}
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _write(data):
    tmp = USERS_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, USERS_PATH)
    except OSError:
        pass


def norm(email: str) -> str:
    return (email or "").strip().lower()


def get(email: str):
    return _read().get(norm(email))


def exists(email: str) -> bool:
    return norm(email) in _read()


def count() -> int:
    return len(_read())


def create(email: str, name: str, password: str, via: str = "email"):
    """สร้างบัญชีใหม่ คืน (สำเร็จ, ข้อความ)"""
    key = norm(email)
    with _lock:
        data = _read()
        if key in data:
            return False, "อีเมลนี้ถูกใช้สมัครไว้แล้ว"
        data[key] = {
            "email": key,
            "name": (name or key.split("@")[0]).strip()[:60],
            "password": generate_password_hash(password) if password else "",
            "picture": "",
            "via": via,
            "totp_secret": "",
            "totp_enabled": False,
            "backup": [],
            "created": int(time.time()),
            "last_login": 0,
        }
        _write(data)
    return True, ""


def verify(email: str, password: str):
    """ตรวจอีเมลกับรหัสผ่าน คืนข้อมูลผู้ใช้ หรือ None"""
    u = get(email)
    if not u or not u.get("password"):
        return None
    if not check_password_hash(u["password"], password or ""):
        return None
    touch(email)
    return u


def set_password(email: str, password: str) -> bool:
    key = norm(email)
    with _lock:
        data = _read()
        if key not in data:
            return False
        data[key]["password"] = generate_password_hash(password)
        _write(data)
    return True


def touch(email: str):
    key = norm(email)
    with _lock:
        data = _read()
        if key in data:
            data[key]["last_login"] = int(time.time())
            _write(data)


def ensure_google_user(email: str, name: str, picture: str = ""):
    """สร้างบัญชีอัตโนมัติเมื่อเข้าครั้งแรกด้วย Google"""
    key = norm(email)
    with _lock:
        data = _read()
        if key not in data:
            data[key] = {
                "email": key, "name": (name or key.split("@")[0])[:60],
                "password": "", "via": "google",
                "created": int(time.time()), "last_login": int(time.time()),
            }
        else:
            data[key]["last_login"] = int(time.time())
            if name and not data[key].get("name"):
                data[key]["name"] = name[:60]
        _write(data)


# ------------------------------------------------------------ ตั้งค่าโปรไฟล์

def _update(email, fn):
    key = norm(email)
    with _lock:
        data = _read()
        if key not in data:
            return False
        fn(data[key], data)
        _write(data)
    return True


def set_name(email, name):
    name = (name or "").strip()[:60]
    if not name:
        return False, "กรุณากรอกชื่อที่ต้องการแสดง"
    ok = _update(email, lambda u, d: u.update(name=name))
    return (True, "") if ok else (False, "ไม่พบบัญชีนี้")


def set_picture(email, filename):
    return _update(email, lambda u, d: u.update(picture=filename or ""))


def change_password(email, current, new):
    u = get(email)
    if not u:
        return False, "ไม่พบบัญชีนี้"
    if u.get("password") and not check_password_hash(u["password"], current or ""):
        return False, "รหัสผ่านปัจจุบันไม่ถูกต้อง"
    problem = password_problem(new)
    if problem:
        return False, problem
    set_password(email, new)
    return True, ""


def change_email(old_email, new_email, current_password):
    """เปลี่ยนอีเมล คืน (สำเร็จ, ข้อความ)"""
    old, new = norm(old_email), norm(new_email)
    if old == new:
        return False, "อีเมลใหม่ซ้ำกับอีเมลเดิม"
    if not valid_email(new):
        return False, "รูปแบบอีเมลไม่ถูกต้อง"
    u = get(old)
    if not u:
        return False, "ไม่พบบัญชีนี้"
    if u.get("password") and not check_password_hash(u["password"], current_password or ""):
        return False, "รหัสผ่านไม่ถูกต้อง"
    with _lock:
        data = _read()
        if new in data:
            return False, "อีเมลนี้ถูกใช้กับบัญชีอื่นแล้ว"
        rec = data.pop(old, None)
        if not rec:
            return False, "ไม่พบบัญชีนี้"
        rec["email"] = new
        data[new] = rec
        _write(data)
    return True, ""


# ------------------------------------------------------- การยืนยันสองชั้น

def start_totp(email):
    """สร้างกุญแจใหม่ไว้รอยืนยัน (ยังไม่เปิดใช้จนกว่าจะกรอกรหัสถูก)"""
    secret = totp.new_secret()
    _update(email, lambda u, d: u.update(totp_secret=secret, totp_enabled=False))
    return secret


def enable_totp(email, code):
    """ยืนยันรหัสแล้วเปิดใช้งาน คืน (สำเร็จ, ข้อความ, รหัสสำรอง)"""
    u = get(email)
    if not u or not u.get("totp_secret"):
        return False, "ยังไม่ได้เริ่มตั้งค่า กรุณาเริ่มใหม่อีกครั้ง", []
    if not totp.verify(u["totp_secret"], code):
        return False, "รหัสยืนยันไม่ถูกต้อง กรุณาลองใหม่", []
    codes = totp.new_backup_codes()
    hashed = [totp.hash_backup(c) for c in codes]
    _update(email, lambda x, d: x.update(totp_enabled=True, backup=hashed,
                                         totp_at=int(time.time())))
    return True, "", codes


def disable_totp(email, password):
    u = get(email)
    if not u:
        return False, "ไม่พบบัญชีนี้"
    if u.get("password") and not check_password_hash(u["password"], password or ""):
        return False, "รหัสผ่านไม่ถูกต้อง"
    _update(email, lambda x, d: x.update(totp_enabled=False, totp_secret="", backup=[]))
    return True, ""


def regen_backup(email, password):
    u = get(email)
    if not u or not u.get("totp_enabled"):
        return False, "ยังไม่ได้เปิดการยืนยันสองชั้น", []
    if u.get("password") and not check_password_hash(u["password"], password or ""):
        return False, "รหัสผ่านไม่ถูกต้อง", []
    codes = totp.new_backup_codes()
    hashed = [totp.hash_backup(c) for c in codes]
    _update(email, lambda x, d: x.update(backup=hashed))
    return True, "", codes


def totp_on(email) -> bool:
    u = get(email)
    return bool(u and u.get("totp_enabled") and u.get("totp_secret"))


def check_totp(email, code) -> bool:
    u = get(email)
    if not u or not u.get("totp_enabled"):
        return False
    return totp.verify(u.get("totp_secret", ""), code)


def use_backup(email, code) -> bool:
    """ใช้รหัสสำรองหนึ่งครั้ง แล้วตัดออกจากรายการทันที"""
    h = totp.hash_backup(code)
    if not totp.normalize_backup(code):
        return False
    key = norm(email)
    with _lock:
        data = _read()
        u = data.get(key)
        if not u or not u.get("totp_enabled"):
            return False
        left = list(u.get("backup") or [])
        if h not in left:
            return False
        left.remove(h)
        u["backup"] = left
        _write(data)
    return True


def backup_left(email) -> int:
    u = get(email)
    return len(u.get("backup") or []) if u else 0


# ------------------------------------------------------------ งานผู้ดูแลระบบ

def all_users():
    """รายชื่อบัญชีทั้งหมด สำหรับหน้าผู้ดูแล — ไม่ส่งค่าที่เป็นความลับออกไป"""
    out = []
    for u in _read().values():
        out.append({
            "email": u.get("email", ""),
            "name": u.get("name", ""),
            "picture": u.get("picture", ""),
            "via": u.get("via", "email"),
            "created": int(u.get("created") or 0),
            "last_login": int(u.get("last_login") or 0),
            "totp_enabled": bool(u.get("totp_enabled")),
            "backup_left": len(u.get("backup") or []),
            "suspended": bool(u.get("suspended")),
            "suspend_reason": u.get("suspend_reason", ""),
            "suspended_at": int(u.get("suspended_at") or 0),
            "note": u.get("note", ""),
        })
    out.sort(key=lambda x: x["created"], reverse=True)
    return out


def public(email):
    """ข้อมูลบัญชีเดียว ในรูปแบบเดียวกับ all_users"""
    key = norm(email)
    for u in all_users():
        if u["email"] == key:
            return u
    return None


def is_suspended(email) -> bool:
    u = get(email)
    return bool(u and u.get("suspended"))


def set_suspended(email, on: bool, reason: str = ""):
    """ระงับหรือคืนสิทธิ์การใช้งานของบัญชี"""
    def fn(u, d):
        u["suspended"] = bool(on)
        u["suspend_reason"] = (reason or "").strip()[:200] if on else ""
        u["suspended_at"] = int(time.time()) if on else 0
    ok = _update(email, fn)
    return (True, "") if ok else (False, "ไม่พบบัญชีนี้")


def admin_set_password(email, new_password):
    """
    ผู้ดูแลตั้งรหัสผ่านใหม่ให้บัญชี โดยไม่ต้องใช้รหัสเดิม

    ใช้เมื่อผู้ใช้เข้าระบบไม่ได้จริง ๆ การกระทำนี้จะถูกบันทึกไว้ในประวัติของผู้ดูแล
    """
    if not exists(email):
        return False, "ไม่พบบัญชีนี้"
    problem = password_problem(new_password)
    if problem:
        return False, problem
    set_password(email, new_password)
    return True, ""


def set_note(email, note):
    """บันทึกภายในของผู้ดูแล ผู้ใช้มองไม่เห็น"""
    ok = _update(email, lambda u, d: u.update(note=(note or "").strip()[:500]))
    return (True, "") if ok else (False, "ไม่พบบัญชีนี้")


def admin_delete(email):
    """ลบบัญชีถาวร"""
    key = norm(email)
    with _lock:
        data = _read()
        if key not in data:
            return False, "ไม่พบบัญชีนี้"
        del data[key]
        _write(data)
    return True, ""


def stats():
    """ตัวเลขสรุปสำหรับหน้าแรกของผู้ดูแล"""
    now = int(time.time())
    users = _read().values()
    day = now - 86400
    week = now - 7 * 86400
    return {
        "total": len(users),
        "new_today": sum(1 for u in users if int(u.get("created") or 0) >= day),
        "new_week": sum(1 for u in users if int(u.get("created") or 0) >= week),
        "active_week": sum(1 for u in users if int(u.get("last_login") or 0) >= week),
        "with_2fa": sum(1 for u in users if u.get("totp_enabled")),
        "suspended": sum(1 for u in users if u.get("suspended")),
    }
