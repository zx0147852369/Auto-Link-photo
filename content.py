# -*- coding: utf-8 -*-
"""
content.py — เนื้อหาของหน้าแนะนำระบบที่แก้ไขได้จากหลังบ้าน

ข้อความและภาพทั้งหมดที่ผู้ดูแลแก้ได้ ถูกเก็บไว้ในไฟล์ content.json
ถ้ายังไม่เคยแก้ ระบบจะใช้ค่าตั้งต้นในไฟล์นี้แทน
จึงเปิดใช้งานได้ทันทีโดยไม่ต้องตั้งค่าอะไรก่อน

โครงสร้างค่าที่เก็บเป็นชั้นเดียวตื้น ๆ ด้วยเจตนา เพื่อให้แบบฟอร์มในหน้าผู้ดูแล
ตรงไปตรงมาและตรวจสอบค่าที่รับเข้ามาได้ครบทุกช่อง
"""

import json
import os
import secrets
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "content.json")
BANNER_DIR = os.path.join(BASE_DIR, "static", "banners")

_lock = threading.Lock()


# ==================================================================
#  ค่าตั้งต้น — ตรงกับข้อความที่ใช้อยู่บนหน้าเว็บตอนนี้
# ==================================================================

DEFAULTS = {
    # ---------- ส่วนหัวเรื่อง ----------
    "hero_title_1": "ที่อยู่ไฟล์ภาพต้นฉบับ",
    "hero_title_2": "อยู่ลึกกว่าที่ตาเห็นเสมอ",
    "hero_lead": "เว็บสมัยใหม่ซ่อนรูปไว้หลายชั้น และย่อขนาดก่อนแสดงเพื่อให้โหลดเร็ว "
                 "เครื่องมือนี้อ่านทุกชั้นเหล่านั้น คืนที่อยู่ไฟล์เต็มให้คุณ "
                 "พร้อมคัดกรองไฟล์ที่ไม่น่าไว้ใจออกก่อนถึงมือ",
    "hero_cta_guest": "เริ่มใช้งาน",
    "hero_cta_user": "เข้าใช้งานเครื่องมือ",

    # ---------- แบนเนอร์โปรโมชัน ----------
    "banner_on": True,
    "banner_seconds": 5,
    "banner_builtin_on": True,

    # ---------- ส่วนความสามารถ ----------
    "what_kick": "ความสามารถ",
    "what_h2": "ค้นได้ลึกกว่าการคลิกขวาบันทึกรูป",

    # ---------- ส่วนแนวปฏิบัติด้านข้อมูล ----------
    "policy_kick": "แนวปฏิบัติด้านข้อมูล",
    "policy_h2": "ข้อมูลของคุณอยู่กับคุณ",

    # ---------- ส่วนระดับการค้นหา ----------
    "levels_kick": "ระดับการค้นหา",
    "levels_h2": "เลือกความลึกให้พอดีกับงาน",

    # ---------- ส่วนแพ็กเกจ ----------
    "price_kick": "แพ็กเกจการใช้งาน",
    "price_h2": "เลือกแพ็กเกจให้พอดีกับปริมาณงาน",
    "price_p": "คิดตามการใช้งานจริงด้วยหน่วย Token เติมใหม่ทุกรอบเดือน "
               "เริ่มต้นใช้ฟรีได้ทันทีโดยไม่ต้องผูกบัตร",

    # ---------- ส่วนคำถาม ----------
    "faq_kick": "คำถามที่พบบ่อย",
    "faq_h2": "เรื่องที่คนถามบ่อยที่สุด",

    # ---------- ส่วนปิดท้าย ----------
    "end_h2": "เริ่มใช้งานได้เลย",
    "end_p": "สมัครครั้งเดียว ใช้ได้ทันที ไม่ต้องยืนยันอีเมล ไม่มีค่าใช้จ่าย",

    # ---------- ข้อมูลติดต่อท้ายหน้า ----------
    "site_name": "Auto Link Photo",
    "contact_web": "",
    "contact_line": "",
    "contact_email": "",
    "footer_note": "",
}

# ช่องที่เป็นข้อความยาว ใช้กำหนดขนาดกล่องกรอกในหน้าผู้ดูแล
LONG_FIELDS = {"hero_lead", "price_p", "end_p", "footer_note"}

# ความยาวสูงสุดของแต่ละช่อง กันไม่ให้มีคนยัดข้อความมหาศาลเข้ามา
MAX_LEN = {
    "hero_lead": 400, "price_p": 400, "end_p": 300, "footer_note": 300,
}
DEFAULT_MAX = 160

# หมวดหมู่สำหรับจัดกลุ่มในหน้าผู้ดูแล
GROUPS = [
    ("ส่วนหัวเรื่อง", ["hero_title_1", "hero_title_2", "hero_lead",
                       "hero_cta_guest", "hero_cta_user"]),
    ("หัวข้อแต่ละส่วน", ["what_kick", "what_h2", "policy_kick", "policy_h2",
                          "levels_kick", "levels_h2", "faq_kick", "faq_h2"]),
    ("ส่วนแพ็กเกจ", ["price_kick", "price_h2", "price_p"]),
    ("ส่วนปิดท้าย", ["end_h2", "end_p"]),
    ("ข้อมูลติดต่อ", ["site_name", "contact_web", "contact_line",
                       "contact_email", "footer_note"]),
]

LABELS = {
    "hero_title_1": "หัวเรื่องบรรทัดแรก",
    "hero_title_2": "หัวเรื่องบรรทัดที่สอง (ตัวไล่สี)",
    "hero_lead": "คำอธิบายใต้หัวเรื่อง",
    "hero_cta_guest": "ปุ่มหลัก สำหรับผู้ที่ยังไม่เข้าสู่ระบบ",
    "hero_cta_user": "ปุ่มหลัก สำหรับผู้ที่เข้าสู่ระบบแล้ว",
    "what_kick": "ส่วนความสามารถ — คำนำ",
    "what_h2": "ส่วนความสามารถ — หัวข้อ",
    "policy_kick": "ส่วนแนวปฏิบัติด้านข้อมูล — คำนำ",
    "policy_h2": "ส่วนแนวปฏิบัติด้านข้อมูล — หัวข้อ",
    "levels_kick": "ส่วนระดับการค้นหา — คำนำ",
    "levels_h2": "ส่วนระดับการค้นหา — หัวข้อ",
    "faq_kick": "ส่วนคำถาม — คำนำ",
    "faq_h2": "ส่วนคำถาม — หัวข้อ",
    "price_kick": "ส่วนแพ็กเกจ — คำนำ",
    "price_h2": "ส่วนแพ็กเกจ — หัวข้อ",
    "price_p": "ส่วนแพ็กเกจ — คำอธิบาย",
    "end_h2": "ส่วนปิดท้าย — หัวข้อ",
    "end_p": "ส่วนปิดท้าย — คำอธิบาย",
    "site_name": "ชื่อระบบที่แสดงในหน้าเว็บ",
    "contact_web": "เว็บไซต์ (เว้นว่างได้)",
    "contact_line": "บัญชี LINE (เว้นว่างได้)",
    "contact_email": "อีเมลติดต่อ (เว้นว่างได้)",
    "footer_note": "ข้อความเพิ่มเติมท้ายหน้า (เว้นว่างได้)",
}


# ==================================================================
#  อ่านเขียนไฟล์
# ==================================================================

def _read():
    if not os.path.exists(DATA_PATH):
        return {}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def _write(d):
    tmp = DATA_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_PATH)
        return True
    except OSError:
        return False


def all_text():
    """ค่าข้อความทั้งหมด รวมค่าตั้งต้นที่ยังไม่เคยแก้"""
    d = _read()
    saved = d.get("text") or {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in saved and isinstance(saved[k], type(DEFAULTS[k])):
            out[k] = saved[k]
    return out


def get(key, default=""):
    return all_text().get(key, default)


def save_text(values, changed_by=""):
    """
    บันทึกข้อความที่แก้ไข คืน (สำเร็จ, จำนวนช่องที่เปลี่ยน)

    รับเฉพาะชื่อช่องที่รู้จักเท่านั้น ค่าที่ไม่รู้จักจะถูกทิ้งไป
    เพื่อไม่ให้มีใครยัดข้อมูลแปลกปลอมเข้าไฟล์ตั้งค่า
    """
    cur = all_text()
    clean = {}
    changed = 0
    for k, default in DEFAULTS.items():
        if k not in values:
            clean[k] = cur[k]
            continue
        v = values[k]
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int):
            try:
                v = max(2, min(60, int(v)))
            except (TypeError, ValueError):
                v = cur[k]
        else:
            v = str(v if v is not None else "").strip()
            v = v[:MAX_LEN.get(k, DEFAULT_MAX)]
        clean[k] = v
        if v != cur[k]:
            changed += 1

    with _lock:
        d = _read()
        d["text"] = clean
        d["updated"] = int(time.time())
        d["updated_by"] = (changed_by or "")[:120]
        ok = _write(d)
    return ok, changed


def reset_text():
    """คืนข้อความทั้งหมดกลับเป็นค่าตั้งต้น"""
    with _lock:
        d = _read()
        d.pop("text", None)
        d["updated"] = int(time.time())
        return _write(d)


# ==================================================================
#  ภาพแบนเนอร์โปรโมชัน
# ==================================================================

DEFAULT_SLIDES = [
    {"id": "promo1", "file": "promo-1", "alt": "แบนเนอร์โปรโมชัน Auto Link Photo",
     "link": "", "on": True},
    {"id": "promo2", "file": "promo-2", "alt": "แพ็กเกจรายเดือน Auto Link Photo",
     "link": "", "on": True},
]


def slides(only_on=False):
    """รายการภาพแบนเนอร์ตามลำดับที่จะแสดง"""
    d = _read()
    got = d.get("slides")
    if not isinstance(got, list):
        got = [dict(s) for s in DEFAULT_SLIDES]
    out = []
    for s in got:
        if not isinstance(s, dict) or not s.get("file"):
            continue
        item = {
            "id": str(s.get("id") or secrets.token_hex(4)),
            "file": str(s.get("file"))[:80],
            "alt": str(s.get("alt") or "")[:200],
            "link": str(s.get("link") or "")[:200],
            "on": bool(s.get("on", True)),
        }
        item["exists"] = has_file(item["file"])
        if only_on and (not item["on"] or not item["exists"]):
            continue
        out.append(item)
    return out


def has_file(name) -> bool:
    """มีไฟล์ภาพของสไลด์นี้อยู่จริงหรือไม่ (อย่างน้อยหนึ่งรูปแบบ)"""
    base = safe_slide_name(name)
    if not base:
        return False
    return any(os.path.exists(os.path.join(BANNER_DIR, base + e))
               for e in (".webp", ".jpg"))


def safe_slide_name(name) -> str:
    """
    ยอมรับเฉพาะชื่อไฟล์ที่ปลอดภัย

    อนุญาตแค่ตัวอักษรอังกฤษ ตัวเลข ขีด และขีดล่าง
    จึงเป็นไปไม่ได้ที่ชื่อจะพาออกไปนอกโฟลเดอร์ที่กำหนดไว้
    """
    s = str(name or "").strip()
    if not s or len(s) > 60:
        return ""
    ok = all(c.isalnum() or c in "-_" for c in s)
    return s if ok else ""


def save_slides(items):
    """บันทึกรายการภาพแบนเนอร์ทั้งชุด"""
    clean = []
    seen = set()
    for s in items or []:
        base = safe_slide_name(s.get("file"))
        if not base or base in seen:
            continue
        seen.add(base)
        clean.append({
            "id": str(s.get("id") or secrets.token_hex(4))[:24],
            "file": base,
            "alt": str(s.get("alt") or "")[:200].strip(),
            "link": str(s.get("link") or "")[:200].strip(),
            "on": bool(s.get("on", True)),
        })
    with _lock:
        d = _read()
        d["slides"] = clean
        d["updated"] = int(time.time())
        return _write(d)


def add_slide(base, alt="", link=""):
    cur = slides()
    cur.append({"id": secrets.token_hex(4), "file": base,
                "alt": alt, "link": link, "on": True})
    return save_slides(cur)


def remove_slide(sid):
    cur = [s for s in slides() if s["id"] != sid]
    return save_slides(cur)


def move_slide(sid, delta):
    cur = slides()
    for i, s in enumerate(cur):
        if s["id"] == sid:
            j = max(0, min(len(cur) - 1, i + delta))
            if i != j:
                cur.insert(j, cur.pop(i))
            break
    return save_slides(cur)


def toggle_slide(sid, on):
    cur = slides()
    for s in cur:
        if s["id"] == sid:
            s["on"] = bool(on)
    return save_slides(cur)


def update_slide(sid, alt=None, link=None):
    cur = slides()
    for s in cur:
        if s["id"] == sid:
            if alt is not None:
                s["alt"] = alt
            if link is not None:
                s["link"] = link
    return save_slides(cur)


def delete_files(base):
    """ลบไฟล์ภาพของสไลด์ออกจากเครื่อง"""
    base = safe_slide_name(base)
    if not base:
        return
    for e in (".webp", ".jpg"):
        p = os.path.join(BANNER_DIR, base + e)
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def info():
    d = _read()
    return {
        "updated": int(d.get("updated") or 0),
        "updated_by": d.get("updated_by", ""),
        "customised": bool(d.get("text")),
        "slide_count": len(slides()),
        "slide_on": len(slides(only_on=True)),
    }
