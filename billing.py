# -*- coding: utf-8 -*-
"""
billing.py — แพ็กเกจ โควตา Token และการเติมเงิน

หลักการ
  • ทุกบัญชีมีแพ็กเกจหนึ่งแพ็กเกจ และมียอด Token คงเหลือ
  • การกระทำที่ใช้ทรัพยากรจะหัก Token ตามอัตราที่กำหนดไว้ในตาราง COSTS
  • แพ็กเกจแบบรายเดือนจะเติม Token ให้ใหม่ทุกรอบบิล
  • ทุกการหักและการเติมถูกบันทึกไว้ตรวจสอบย้อนหลังได้

ข้อมูลทั้งหมดเก็บในไฟล์ billing.json บนเครื่องที่ติดตั้งระบบ
"""

import json
import os
import secrets
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "billing.json")

_lock = threading.Lock()

PERIOD_DAYS = 30
LEDGER_KEEP = 300          # เก็บรายการเคลื่อนไหวล่าสุดต่อบัญชี


# ==================================================================
#  แพ็กเกจ
# ==================================================================

PLANS = {
    "free": {
        "id": "free", "name": "ฟรี", "price": 0, "tokens": 5_000,
        "tagline": "ทดลองใช้งาน",
        "perks": ["ค้นหาได้ครบทุกระดับ", "คัดกรองไฟล์ก่อนบันทึก",
                  "ประวัติการค้นหา", "เติม Token ใหม่ทุกเดือน"],
    },
    "starter": {
        "id": "starter", "name": "เริ่มต้น", "price": 259, "tokens": 250_000,
        "tagline": "เหมาะกับใช้งานส่วนตัว",
        "perks": ["ทุกอย่างในแพ็กเกจฟรี", "Token มากขึ้น 50 เท่า",
                  "บันทึกเป็นชุด ZIP ได้มากขึ้น", "รองรับการค้นหาต่อเนื่อง"],
    },
    "pro": {
        "id": "pro", "name": "มืออาชีพ", "price": 599, "tokens": 600_000,
        "tagline": "คุ้มค่าที่สุดต่อ Token",
        "best": True,
        "perks": ["ทุกอย่างในแพ็กเกจเริ่มต้น", "ค่า Token ต่อบาทถูกที่สุด",
                  "เหมาะกับงานที่ค้นทุกวัน", "ตามหน้าย่อยได้เต็มที่"],
    },
    "max": {
        "id": "max", "name": "สูงสุด", "price": 799, "tokens": 1_200_000,
        "tagline": "สำหรับงานปริมาณมาก",
        "perks": ["ทุกอย่างในแพ็กเกจมืออาชีพ", "Token สูงสุดในระบบ",
                  "รองรับงานทีมหรือเชิงพาณิชย์", "ค้นหาต่อเนื่องไม่ต้องกังวลโควตา"],
    },
}

PLAN_ORDER = ["free", "starter", "pro", "max"]
DEFAULT_PLAN = "free"


# ==================================================================
#  อัตราการหัก Token ต่อการกระทำ
# ==================================================================

COSTS = {
    "scan_1": 20,          # ค้นหาระดับเร็ว ต่อหนึ่งครั้ง
    "scan_2": 50,          # ค้นหาระดับปกติ
    "scan_3": 120,         # ค้นหาระดับละเอียดสูงสุด
    "scan_page": 40,       # หน้าย่อยที่ตามไปเพิ่ม ต่อหนึ่งหน้า
    "screen": 4,           # ตรวจความปลอดภัย ต่อหนึ่งไฟล์
    "download": 2,         # บันทึกไฟล์เดี่ยว ต่อหนึ่งไฟล์
    "zip": 3,              # บันทึกเป็นชุด ต่อหนึ่งไฟล์ที่ใส่ได้
}

COST_LABEL = {
    "scan_1": "ค้นหาระดับเร็ว",
    "scan_2": "ค้นหาระดับปกติ",
    "scan_3": "ค้นหาระดับละเอียดสูงสุด",
    "scan_page": "ตามหน้าย่อยเพิ่ม",
    "screen": "ตรวจความปลอดภัยไฟล์",
    "download": "บันทึกไฟล์",
    "zip": "บันทึกเป็นชุด ZIP",
    "topup": "เติม Token",
    "plan": "เปลี่ยนแพ็กเกจ",
    "renew": "เติมรอบบิลใหม่",
    "refund": "คืน Token",
}


def scan_cost(level: int, pages: int = 1) -> int:
    """ค่าใช้จ่ายของการค้นหาหนึ่งครั้ง"""
    base = COSTS.get(f"scan_{max(1, min(3, int(level or 2)))}", COSTS["scan_2"])
    extra = max(0, int(pages or 1) - 1) * COSTS["scan_page"]
    return base + extra


# ==================================================================
#  ที่เก็บข้อมูล
# ==================================================================

def _read():
    if not os.path.exists(DATA_PATH):
        return {"users": {}, "orders": {}, "codes": {}}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError
        d.setdefault("users", {})
        d.setdefault("orders", {})
        d.setdefault("codes", {})
        return d
    except (ValueError, OSError):
        return {"users": {}, "orders": {}, "codes": {}}


def _write(d):
    tmp = DATA_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_PATH)
    except OSError:
        pass


def key_of(user) -> str:
    """คีย์ประจำบัญชี — ผู้ดูแลที่ไม่มีอีเมลใช้คีย์เฉพาะ"""
    if not user:
        return ""
    return (user.get("email") or "").strip().lower() or "__admin__"


def _fresh(plan_id=DEFAULT_PLAN):
    p = PLANS.get(plan_id, PLANS[DEFAULT_PLAN])
    now = int(time.time())
    return {
        "plan": p["id"],
        "tokens": p["tokens"],
        "granted": p["tokens"],
        "used": 0,
        "period_start": now,
        "period_end": now + PERIOD_DAYS * 86400,
        "auto_renew": p["price"] == 0,      # แพ็กเกจฟรีต่ออายุเองอัตโนมัติ
        "ledger": [],
    }


def _log(rec, kind, amount, note=""):
    rec.setdefault("ledger", []).insert(0, {
        "id": secrets.token_hex(5),
        "kind": kind,
        "label": COST_LABEL.get(kind, kind),
        "amount": int(amount),
        "note": note[:160],
        "balance": int(rec.get("tokens", 0)),
        "at": int(time.time()),
    })
    del rec["ledger"][LEDGER_KEEP:]


def _renew_if_due(rec):
    """ถึงรอบบิลใหม่แล้วเติม Token ให้ตามแพ็กเกจ"""
    now = int(time.time())
    if now < int(rec.get("period_end", 0)):
        return False
    plan = PLANS.get(rec.get("plan"), PLANS[DEFAULT_PLAN])

    if plan["price"] > 0 and not rec.get("auto_renew"):
        # แพ็กเกจแบบจ่ายเงินหมดอายุแล้วและไม่ได้ต่อ ให้กลับไปใช้แพ็กเกจฟรี
        rec["plan"] = DEFAULT_PLAN
        plan = PLANS[DEFAULT_PLAN]

    rec["tokens"] = plan["tokens"]
    rec["granted"] = plan["tokens"]
    rec["used"] = 0
    rec["period_start"] = now
    rec["period_end"] = now + PERIOD_DAYS * 86400
    _log(rec, "renew", plan["tokens"], f"รอบบิลใหม่ แพ็กเกจ{plan['name']}")
    return True


def _get(d, key, create=True):
    rec = d["users"].get(key)
    if rec is None:
        if not create:
            return None
        rec = _fresh()
        d["users"][key] = rec
    return rec


# ==================================================================
#  อ่านสถานะ
# ==================================================================

def state(user):
    """ข้อมูลแพ็กเกจและยอดคงเหลือของบัญชี"""
    key = key_of(user)
    if not key:
        return None
    with _lock:
        d = _read()
        rec = _get(d, key)
        if _renew_if_due(rec):
            _write(d)
        plan = PLANS.get(rec["plan"], PLANS[DEFAULT_PLAN])
        return {
            "plan": plan["id"],
            "plan_name": plan["name"],
            "price": plan["price"],
            "tokens": int(rec["tokens"]),
            "granted": int(rec.get("granted") or plan["tokens"]),
            "used": int(rec.get("used", 0)),
            "period_start": int(rec.get("period_start", 0)),
            "period_end": int(rec.get("period_end", 0)),
            "auto_renew": bool(rec.get("auto_renew")),
            "days_left": max(0, int((rec.get("period_end", 0) - time.time()) // 86400)),
        }


def ledger(user, limit=40):
    key = key_of(user)
    if not key:
        return []
    with _lock:
        rec = _read()["users"].get(key) or {}
    return (rec.get("ledger") or [])[:limit]


def balance(user) -> int:
    st = state(user)
    return st["tokens"] if st else 0


# ==================================================================
#  หักและเติม Token
# ==================================================================

def quote(kind, units=1, level=None, pages=1) -> int:
    """คำนวณราคาก่อนทำรายการ"""
    if kind == "scan":
        return scan_cost(level, pages)
    return COSTS.get(kind, 0) * max(0, int(units))


def check(user, need: int):
    """
    ตรวจว่า Token พอหรือไม่ คืน (พอหรือไม่, ยอดคงเหลือ, ข้อความ)
    ไม่หัก Token ในขั้นนี้
    """
    st = state(user)
    if st is None:
        return True, 0, ""          # ไม่มีบัญชี เช่นยังไม่เข้าสู่ระบบ ให้ชั้นอื่นจัดการ
    if need <= 0:
        return True, st["tokens"], ""
    if st["tokens"] >= need:
        return True, st["tokens"], ""
    return False, st["tokens"], (
        f"Token คงเหลือไม่พอ ต้องใช้ {need:,} แต่เหลือ {st['tokens']:,} "
        f"— กรุณาเติม Token หรืออัปเกรดแพ็กเกจ")


def spend(user, kind, amount, note=""):
    """หัก Token คืน (สำเร็จ, ยอดคงเหลือ, ข้อความ)"""
    key = key_of(user)
    amount = int(amount)
    if not key or amount <= 0:
        return True, balance(user), ""
    with _lock:
        d = _read()
        rec = _get(d, key)
        _renew_if_due(rec)
        if rec["tokens"] < amount:
            left = int(rec["tokens"])
            _write(d)
            return False, left, (f"Token คงเหลือไม่พอ ต้องใช้ {amount:,} "
                                 f"แต่เหลือ {left:,}")
        rec["tokens"] -= amount
        rec["used"] = int(rec.get("used", 0)) + amount
        _log(rec, kind, -amount, note)
        _write(d)
        return True, int(rec["tokens"]), ""


def refund(user, amount, note=""):
    """คืน Token เมื่อรายการไม่สำเร็จ"""
    key = key_of(user)
    amount = int(amount)
    if not key or amount <= 0:
        return
    with _lock:
        d = _read()
        rec = _get(d, key)
        rec["tokens"] = int(rec["tokens"]) + amount
        rec["used"] = max(0, int(rec.get("used", 0)) - amount)
        _log(rec, "refund", amount, note)
        _write(d)


def grant(user, tokens, note="", kind="topup"):
    """เติม Token เข้าบัญชี"""
    key = key_of(user)
    tokens = int(tokens)
    if not key or tokens <= 0:
        return 0
    with _lock:
        d = _read()
        rec = _get(d, key)
        _renew_if_due(rec)
        rec["tokens"] = int(rec["tokens"]) + tokens
        rec["granted"] = int(rec.get("granted", 0)) + tokens
        _log(rec, kind, tokens, note)
        _write(d)
        return int(rec["tokens"])


def set_plan(user, plan_id, note="", add_tokens=True):
    """เปลี่ยนแพ็กเกจและเริ่มรอบบิลใหม่"""
    key = key_of(user)
    plan = PLANS.get(plan_id)
    if not key or not plan:
        return None
    now = int(time.time())
    with _lock:
        d = _read()
        rec = _get(d, key)
        rec["plan"] = plan["id"]
        if add_tokens:
            rec["tokens"] = int(rec.get("tokens", 0)) + plan["tokens"]
            rec["granted"] = int(rec.get("granted", 0)) + plan["tokens"]
        rec["period_start"] = now
        rec["period_end"] = now + PERIOD_DAYS * 86400
        rec["auto_renew"] = plan["price"] == 0
        _log(rec, "plan", plan["tokens"] if add_tokens else 0,
             note or f"เปลี่ยนเป็นแพ็กเกจ{plan['name']}")
        _write(d)
    return state(user)


# ==================================================================
#  คำสั่งซื้อ
# ==================================================================

def create_order(user, plan_id, provider="manual"):
    """สร้างคำสั่งซื้อสถานะรอชำระ"""
    key = key_of(user)
    plan = PLANS.get(plan_id)
    if not key or not plan or plan["price"] <= 0:
        return None
    oid = "ALP" + time.strftime("%y%m%d") + secrets.token_hex(3).upper()
    order = {
        "id": oid,
        "user": key,
        "plan": plan["id"],
        "plan_name": plan["name"],
        "amount": plan["price"],
        "tokens": plan["tokens"],
        "provider": provider,
        "status": "pending",
        "created": int(time.time()),
        "paid": 0,
        "ref": "",
    }
    with _lock:
        d = _read()
        d["orders"][oid] = order
        _write(d)
    return order


def get_order(oid):
    with _lock:
        return _read()["orders"].get(str(oid or ""))


def orders_of(user, limit=20):
    key = key_of(user)
    if not key:
        return []
    with _lock:
        all_o = list(_read()["orders"].values())
    mine = [o for o in all_o if o.get("user") == key]
    mine.sort(key=lambda o: o.get("created", 0), reverse=True)
    return mine[:limit]


def mark_paid(oid, ref=""):
    """
    ยืนยันว่าคำสั่งซื้อชำระแล้ว แล้วเติม Token ให้บัญชีนั้น
    เรียกจากเกตเวย์ที่ยืนยันลายเซ็นแล้ว หรือจากผู้ดูแล
    คืน (สำเร็จ, ข้อความ)
    """
    oid = str(oid or "")
    with _lock:
        d = _read()
        o = d["orders"].get(oid)
        if not o:
            return False, "ไม่พบคำสั่งซื้อนี้"
        if o["status"] == "paid":
            return False, "คำสั่งซื้อนี้ชำระเรียบร้อยแล้ว"
        o["status"] = "paid"
        o["paid"] = int(time.time())
        o["ref"] = str(ref)[:120]
        user_key = o["user"]
        plan = PLANS.get(o["plan"], PLANS[DEFAULT_PLAN])
        rec = _get(d, user_key)
        _renew_if_due(rec)
        now = int(time.time())
        rec["plan"] = plan["id"]
        rec["tokens"] = int(rec.get("tokens", 0)) + int(o["tokens"])
        rec["granted"] = int(rec.get("granted", 0)) + int(o["tokens"])
        rec["period_start"] = now
        rec["period_end"] = now + PERIOD_DAYS * 86400
        rec["auto_renew"] = False
        _log(rec, "topup", int(o["tokens"]),
             f"ชำระคำสั่งซื้อ {oid} แพ็กเกจ{plan['name']}")
        _write(d)
    return True, ""


def cancel_order(oid):
    with _lock:
        d = _read()
        o = d["orders"].get(str(oid or ""))
        if not o or o["status"] != "pending":
            return False
        o["status"] = "cancelled"
        _write(d)
    return True


# ==================================================================
#  รหัสเติม Token
# ==================================================================

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _norm_code(code: str) -> str:
    return "".join(c for c in (code or "").upper() if c in CODE_ALPHABET)


def make_codes(tokens, count=1, note=""):
    """สร้างรหัสเติม Token คืนรายการรหัสที่อ่านได้ (แสดงครั้งเดียว)"""
    tokens = int(tokens)
    if tokens <= 0 or count <= 0:
        return []
    out = []
    with _lock:
        d = _read()
        for _ in range(min(count, 200)):
            raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))
            pretty = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
            d["codes"][raw] = {"tokens": tokens, "note": note[:120],
                               "created": int(time.time()),
                               "used_by": "", "used_at": 0}
            out.append(pretty)
        _write(d)
    return out


def redeem(user, code):
    """ใช้รหัสเติม Token คืน (สำเร็จ, จำนวน Token, ข้อความ)"""
    key = key_of(user)
    raw = _norm_code(code)
    if not key:
        return False, 0, "กรุณาเข้าสู่ระบบก่อน"
    if len(raw) != 16:
        return False, 0, "รูปแบบรหัสไม่ถูกต้อง"
    with _lock:
        d = _read()
        c = d["codes"].get(raw)
        if not c:
            return False, 0, "ไม่พบรหัสนี้ในระบบ"
        if c.get("used_by"):
            return False, 0, "รหัสนี้ถูกใช้ไปแล้ว"
        c["used_by"] = key
        c["used_at"] = int(time.time())
        rec = _get(d, key)
        _renew_if_due(rec)
        rec["tokens"] = int(rec.get("tokens", 0)) + int(c["tokens"])
        rec["granted"] = int(rec.get("granted", 0)) + int(c["tokens"])
        _log(rec, "topup", int(c["tokens"]), "ใช้รหัสเติม Token")
        _write(d)
        return True, int(c["tokens"]), ""


def code_stats():
    with _lock:
        codes = _read()["codes"]
    used = sum(1 for c in codes.values() if c.get("used_by"))
    return {"total": len(codes), "used": used, "left": len(codes) - used}
