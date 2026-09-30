# -*- coding: utf-8 -*-
"""
panel.py — หน้าจัดการระบบสำหรับผู้ดูแล

ทางเข้า  /panel/admin

สิ่งที่ทำได้
  • ดูภาพรวมของระบบ จำนวนผู้ใช้ ยอด Token และรายได้
  • จัดการบัญชีผู้ใช้ ระงับ คืนสิทธิ์ ตั้งรหัสผ่านใหม่ ปิดการยืนยันสองชั้น
  • จัดการ Token เติมให้โดยตรง เปลี่ยนแพ็กเกจ ดูประวัติการใช้
  • จัดการการเติมเงิน ยืนยันคำสั่งซื้อ ออกรหัสเติม Token
  • แก้ไขข้อความและภาพแบนเนอร์ของหน้าแนะนำระบบ
  • ตั้งค่าระบบและดูบันทึกการกระทำของผู้ดูแล

หลักความปลอดภัยที่ใช้ในไฟล์นี้
  • ทุกเส้นทางต้องผ่านด่านตรวจสิทธิ์ก่อนเสมอ ไม่มีข้อยกเว้น
  • ทุกคำสั่งที่เปลี่ยนแปลงข้อมูลต้องมาจากแบบฟอร์มของระบบเองพร้อมโทเคนกำกับ
  • ทุกการกระทำถูกบันทึกไว้ว่าใครทำอะไรกับบัญชีใดเมื่อใด
  • ไม่มีการแสดงข้อมูลเชิงเทคนิคของเครื่องหรือของซอฟต์แวร์ออกทางหน้าเว็บ
"""

import io
import json
import os
import secrets
import threading
import time

from flask import (
    Blueprint, current_app, redirect, render_template, request,
    send_from_directory, session, url_for
)

import billing
import content
import gateway
import security
import users

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "panel_log.json")
BANNER_DIR = os.path.join(BASE_DIR, "static", "banners")

MAX_LOG = 800
MAX_UPLOAD = 8 * 1024 * 1024          # ภาพแบนเนอร์ไม่เกิน 8 MB

bp = Blueprint("panel", __name__, url_prefix="/panel")

_log_lock = threading.Lock()


# ==================================================================
#  สิทธิ์การเข้าใช้
# ==================================================================

def _cfg():
    return current_app.config.get("APP_CONFIG") or {}


def admin_emails():
    raw = _cfg().get("admin_emails") or []
    return [str(e).strip().lower() for e in raw if str(e).strip()]


def me():
    return session.get("user") or {}


def my_email():
    return str(me().get("email") or "").strip().lower()


def is_admin() -> bool:
    """
    บัญชีที่เข้าอยู่มีสิทธิ์ผู้ดูแลหรือไม่

    มีสองทางคือ เป็นบัญชีผู้ดูแลที่เข้าด้วยรหัสผ่านผู้ดูแล
    หรือเป็นบัญชีผู้ใช้ที่อีเมลถูกระบุไว้ในรายชื่อผู้ดูแล
    """
    u = me()
    if not u:
        return False
    if u.get("admin"):
        return True
    e = my_email()
    return bool(e) and e in admin_emails()


def _deny():
    """ปฏิเสธการเข้าถึงโดยไม่บอกว่าหน้านี้มีอยู่จริงหรือไม่"""
    if not me():
        return redirect(url_for("auth.login", next="/panel/admin"))
    return render_template("oops.html",
                           msg="คุณไม่มีสิทธิ์เข้าถึงส่วนนี้"), 403


@bp.before_request
def _guard():
    # ด่านแรก ต้องเป็นผู้ดูแลเท่านั้น
    if not is_admin():
        return _deny()
    # ด่านสอง ทุกคำสั่งที่เปลี่ยนข้อมูลต้องมาจากแบบฟอร์มของระบบเอง
    if request.method == "POST":
        if not security.same_origin_request() or not security.csrf_valid():
            return render_template(
                "oops.html", msg="คำขอไม่ถูกต้อง หรือหน้าเปิดค้างไว้นานเกินไป"), 400
    return None


# ==================================================================
#  บันทึกการกระทำของผู้ดูแล
# ==================================================================

def _read_log():
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (ValueError, OSError):
        return []


def log(action, target="", detail=""):
    """จดว่าใครทำอะไร ใช้ตรวจย้อนหลังเมื่อมีข้อสงสัย"""
    rec = {
        "id": secrets.token_hex(5),
        "at": int(time.time()),
        "who": my_email() or "ผู้ดูแลระบบ",
        "action": str(action)[:80],
        "target": str(target)[:120],
        "detail": str(detail)[:300],
    }
    with _log_lock:
        items = _read_log()
        items.insert(0, rec)
        del items[MAX_LOG:]
        tmp = LOG_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            os.replace(tmp, LOG_PATH)
        except OSError:
            pass


# ==================================================================
#  ตัวช่วยทั่วไป
# ==================================================================

MENU = [
    ("panel.home",     "ภาพรวม",            "M4 11l8-6.5 8 6.5M6.5 10v9.5h11V10"),
    ("panel.people",   "บัญชีผู้ใช้",        "M12 8a3.6 3.6 0 100-7.2M4.5 20a7.5 7.5 0 0115 0"),
    ("panel.tokens",   "Token และแพ็กเกจ",   "M3.5 6h17v12h-17zM3.5 10.5h17"),
    ("panel.money",    "การเติมเงิน",        "M12 3.5v17M8 7.5h6.5a2.5 2.5 0 010 5H9a2.5 2.5 0 000 5h7"),
    ("panel.codes",    "รหัสเติม Token",     "M8 12h8M4.5 12a3.5 3.5 0 117 0 3.5 3.5 0 11-7 0M19.5 12a3.5 3.5 0 10-7 0"),
    ("panel.texts",    "ข้อความหน้าแนะนำ",   "M5 6.5h14M5 12h14M5 17.5h8"),
    ("panel.banners",  "ภาพแบนเนอร์",        "M3.5 5.5h17v13h-17zM3.5 15l4.5-4 4 3.5 3.5-3 5 4.5"),
    ("panel.settings", "ตั้งค่าระบบ",        "M12 15.2a3.2 3.2 0 100-6.4 3.2 3.2 0 000 6.4M12 2.5l1.6 2.4 2.8-.6.6 2.8 2.4 1.6-1.4 2.5 1.4 2.5-2.4 1.6-.6 2.8-2.8-.6L12 21.5l-1.6-2.4-2.8.6-.6-2.8L4.6 15 6 12.5 4.6 10l2.4-1.6.6-2.8 2.8.6z"),
    ("panel.logs",     "บันทึกการทำงาน",     "M7 4.5h10v15H7zM10 9h4M10 12.5h4M10 16h2"),
]


def page(tpl, **kw):
    kw.setdefault("menu", MENU)
    kw.setdefault("here", request.endpoint)
    kw.setdefault("admin_name", me().get("name") or "ผู้ดูแลระบบ")
    kw.setdefault("admin_email", my_email())
    return render_template("panel/" + tpl, **kw)


def back(where, ok="", err=""):
    """กลับไปหน้าเดิมพร้อมข้อความแจ้งผล"""
    q = {}
    if ok:
        q["ok"] = ok
    if err:
        q["err"] = err
    return redirect(url_for(where, **q))


def form_str(name, limit=200):
    return (request.form.get(name) or "").strip()[:limit]


def form_int(name, default=0, lo=None, hi=None):
    try:
        v = int(str(request.form.get(name) or default).replace(",", "").strip())
    except (TypeError, ValueError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _u(email):
    return {"email": email}


# ==================================================================
#  ภาพรวม
# ==================================================================

@bp.get("/admin")
def home():
    us = users.stats()
    everyone = users.all_users()

    total_tokens = 0
    total_used = 0
    paid_users = 0
    for u in everyone:
        st = billing.state(_u(u["email"]))
        if not st:
            continue
        total_tokens += st["tokens"]
        total_used += st["used"]
        if st["plan"] != "free":
            paid_users += 1

    cs = billing.code_stats()
    orders = _all_orders()
    paid = [o for o in orders if o.get("status") == "paid"]
    pending = [o for o in orders if o.get("status") == "pending"]
    month_ago = int(time.time()) - 30 * 86400
    income_month = sum(o.get("amount", 0) for o in paid
                       if int(o.get("paid_at") or 0) >= month_ago)

    return page("home.html",
                us=us, paid_users=paid_users,
                total_tokens=total_tokens, total_used=total_used,
                codes=cs, orders_pending=len(pending),
                income_all=sum(o.get("amount", 0) for o in paid),
                income_month=income_month,
                recent_orders=orders[:6],
                recent_users=everyone[:6],
                recent_log=_read_log()[:8],
                gateway_ready=gateway.is_ready(_cfg()),
                gateway_name=gateway.provider_name(_cfg()),
                content_info=content.info())


# ==================================================================
#  บัญชีผู้ใช้
# ==================================================================

@bp.get("/admin/users")
def people():
    q = (request.args.get("q") or "").strip().lower()
    only = request.args.get("only") or ""
    rows = users.all_users()

    if q:
        rows = [u for u in rows if q in u["email"] or q in (u["name"] or "").lower()]
    if only == "suspended":
        rows = [u for u in rows if u["suspended"]]
    elif only == "paid":
        rows = [u for u in rows
                if (billing.state(_u(u["email"])) or {}).get("plan", "free") != "free"]
    elif only == "twofa":
        rows = [u for u in rows if u["totp_enabled"]]

    for u in rows:
        st = billing.state(_u(u["email"])) or {}
        u["plan"] = st.get("plan", "free")
        u["plan_name"] = st.get("plan_name", "ฟรี")
        u["tokens"] = st.get("tokens", 0)
        u["granted"] = st.get("granted", 0)

    return page("users.html", rows=rows, q=q, only=only,
                total=users.count(), plans=billing.PLANS,
                plan_order=billing.PLAN_ORDER)


@bp.get("/admin/users/<path:email>")
def person(email):
    u = users.public(email)
    if not u:
        return page("missing.html", what="บัญชีผู้ใช้"), 404
    st = billing.state(_u(email)) or {}
    return page("user.html", u=u, st=st,
                ledger=billing.ledger(_u(email), 40),
                orders=billing.orders_of(_u(email), 20),
                plans=[billing.PLANS[p] for p in billing.PLAN_ORDER],
                min_password=users.MIN_PASSWORD)


@bp.post("/admin/users/<path:email>/suspend")
def person_suspend(email):
    on = request.form.get("on") == "1"
    reason = form_str("reason", 200)
    if on and my_email() and users.norm(email) == my_email():
        return back("panel.people", err="ระงับบัญชีของตัวเองไม่ได้")
    ok, msg = users.set_suspended(email, on, reason)
    if not ok:
        return back("panel.people", err=msg)
    log("ระงับการใช้งาน" if on else "คืนสิทธิ์การใช้งาน", email, reason)
    return redirect(url_for("panel.person", email=users.norm(email),
                            ok="ระงับบัญชีแล้ว" if on else "คืนสิทธิ์แล้ว"))


@bp.post("/admin/users/<path:email>/password")
def person_password(email):
    pw = request.form.get("password") or ""
    pw2 = request.form.get("password2") or ""
    if pw != pw2:
        return redirect(url_for("panel.person", email=users.norm(email),
                                err="รหัสผ่านทั้งสองช่องไม่ตรงกัน"))
    ok, msg = users.admin_set_password(email, pw)
    if not ok:
        return redirect(url_for("panel.person", email=users.norm(email), err=msg))
    log("ตั้งรหัสผ่านใหม่ให้ผู้ใช้", email)
    return redirect(url_for("panel.person", email=users.norm(email),
                            ok="ตั้งรหัสผ่านใหม่เรียบร้อย แจ้งรหัสให้เจ้าของบัญชีด้วย"))


@bp.post("/admin/users/<path:email>/name")
def person_name(email):
    ok, msg = users.set_name(email, form_str("name", 60))
    if ok:
        log("แก้ชื่อที่แสดง", email, form_str("name", 60))
    return redirect(url_for("panel.person", email=users.norm(email),
                            ok="บันทึกชื่อแล้ว" if ok else "", err="" if ok else msg))


@bp.post("/admin/users/<path:email>/note")
def person_note(email):
    ok, msg = users.set_note(email, form_str("note", 500))
    if ok:
        log("บันทึกหมายเหตุภายใน", email)
    return redirect(url_for("panel.person", email=users.norm(email),
                            ok="บันทึกหมายเหตุแล้ว" if ok else "",
                            err="" if ok else msg))


@bp.post("/admin/users/<path:email>/2fa-off")
def person_2fa_off(email):
    u = users.get(email)
    if not u:
        return back("panel.people", err="ไม่พบบัญชีนี้")

    def fn(x, d):
        x["totp_enabled"] = False
        x["totp_secret"] = ""
        x["backup"] = []
    users._update(email, fn)
    log("ปิดการยืนยันสองชั้นให้ผู้ใช้", email, "ผู้ใช้แจ้งว่าเข้าถึงแอปยืนยันตัวตนไม่ได้")
    return redirect(url_for("panel.person", email=users.norm(email),
                            ok="ปิดการยืนยันสองชั้นแล้ว แจ้งให้ผู้ใช้ตั้งใหม่ด้วย"))


@bp.post("/admin/users/<path:email>/delete")
def person_delete(email):
    if users.norm(email) == my_email():
        return back("panel.people", err="ลบบัญชีของตัวเองไม่ได้")
    if form_str("confirm", 200) != users.norm(email):
        return redirect(url_for("panel.person", email=users.norm(email),
                                err="พิมพ์อีเมลให้ตรงเพื่อยืนยันการลบ"))
    ok, msg = users.admin_delete(email)
    if not ok:
        return back("panel.people", err=msg)
    log("ลบบัญชีถาวร", email)
    return back("panel.people", ok="ลบบัญชีเรียบร้อยแล้ว")


# ==================================================================
#  Token และแพ็กเกจ
# ==================================================================

@bp.get("/admin/tokens")
def tokens():
    rows = []
    for u in users.all_users():
        st = billing.state(_u(u["email"]))
        if not st:
            continue
        rows.append({**u, **st})
    rows.sort(key=lambda r: r.get("used", 0), reverse=True)
    return page("tokens.html", rows=rows,
                plans=[billing.PLANS[p] for p in billing.PLAN_ORDER],
                costs=billing.COSTS, labels=billing.COST_LABEL,
                period=billing.PERIOD_DAYS)


@bp.post("/admin/tokens/grant")
def tokens_grant():
    email = form_str("email", 120)
    amount = form_int("amount", 0, -10_000_000, 10_000_000)
    note = form_str("note", 200) or "ผู้ดูแลปรับยอดให้"
    if not users.exists(email):
        return back("panel.tokens", err="ไม่พบบัญชีนี้")
    if amount == 0:
        return back("panel.tokens", err="กรุณากรอกจำนวน Token")
    left = billing.grant(_u(email), amount, note=note)
    log("เติม Token" if amount > 0 else "หัก Token", email,
        "%+d Token · %s" % (amount, note))
    return back("panel.tokens",
                ok="ปรับยอดให้ %s แล้ว คงเหลือ %s Token"
                   % (email, format(left, ",")))


@bp.post("/admin/tokens/plan")
def tokens_plan():
    email = form_str("email", 120)
    plan = form_str("plan", 20)
    add = request.form.get("add_tokens") == "1"
    if plan not in billing.PLANS:
        return back("panel.tokens", err="แพ็กเกจไม่ถูกต้อง")
    if not users.exists(email):
        return back("panel.tokens", err="ไม่พบบัญชีนี้")
    st = billing.set_plan(_u(email), plan, note="ผู้ดูแลเปลี่ยนแพ็กเกจ",
                          add_tokens=add)
    log("เปลี่ยนแพ็กเกจ", email,
        "เป็น %s%s" % (billing.PLANS[plan]["name"],
                       " พร้อมเติม Token" if add else " โดยไม่เติม Token"))
    return back("panel.tokens",
                ok="เปลี่ยนแพ็กเกจของ %s เป็น%s แล้ว"
                   % (email, billing.PLANS[plan]["name"]))


# ==================================================================
#  การเติมเงิน
# ==================================================================

def _all_orders():
    if not os.path.exists(billing.DATA_PATH):
        return []
    try:
        with open(billing.DATA_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (ValueError, OSError):
        return []
    rows = list((d.get("orders") or {}).values())
    rows.sort(key=lambda o: o.get("created", 0), reverse=True)
    return rows


@bp.get("/admin/money")
def money():
    status = request.args.get("status") or ""
    rows = _all_orders()
    if status in ("pending", "paid", "cancelled"):
        rows = [o for o in rows if o.get("status") == status]
    paid = [o for o in _all_orders() if o.get("status") == "paid"]
    return page("money.html", rows=rows[:300], status=status,
                count_all=len(_all_orders()),
                count_pending=sum(1 for o in _all_orders()
                                  if o.get("status") == "pending"),
                income_all=sum(o.get("amount", 0) for o in paid),
                gateway_ready=gateway.is_ready(_cfg()),
                gateway_name=gateway.provider_name(_cfg()),
                plans=[billing.PLANS[p] for p in billing.PLAN_ORDER])


@bp.post("/admin/money/pay")
def money_pay():
    oid = form_str("oid", 40)
    ref = form_str("ref", 80) or "ยืนยันโดยผู้ดูแล"
    ok, msg = billing.mark_paid(oid, ref)
    if not ok:
        return back("panel.money", err=msg)
    o = billing.get_order(oid) or {}
    log("ยืนยันการชำระเงิน", o.get("user", ""),
        "คำสั่งซื้อ %s · %s บาท · %s" % (oid, o.get("amount", 0), ref))
    return back("panel.money", ok="ยืนยันแล้ว เติม Token ให้เรียบร้อย")


@bp.post("/admin/money/cancel")
def money_cancel():
    oid = form_str("oid", 40)
    ok, msg = billing.cancel_order(oid)
    if not ok:
        return back("panel.money", err=msg)
    log("ยกเลิกคำสั่งซื้อ", (billing.get_order(oid) or {}).get("user", ""), oid)
    return back("panel.money", ok="ยกเลิกคำสั่งซื้อแล้ว")


@bp.post("/admin/money/new")
def money_new():
    email = form_str("email", 120)
    plan = form_str("plan", 20)
    if not users.exists(email):
        return back("panel.money", err="ไม่พบบัญชีนี้")
    if plan not in billing.PLANS or billing.PLANS[plan]["price"] <= 0:
        return back("panel.money", err="แพ็กเกจไม่ถูกต้อง")
    o = billing.create_order(_u(email), plan, provider="manual")
    if not o:
        return back("panel.money", err="สร้างคำสั่งซื้อไม่สำเร็จ")
    log("ออกคำสั่งซื้อให้ผู้ใช้", email, "%s · %s บาท" % (o["id"], o["amount"]))
    return back("panel.money", ok="ออกคำสั่งซื้อ %s แล้ว" % o["id"])


# ==================================================================
#  รหัสเติม Token
# ==================================================================

@bp.get("/admin/codes")
def codes():
    fresh = session.pop("panel_codes", None)
    return page("codes.html", stats=billing.code_stats(), fresh=fresh)


@bp.post("/admin/codes/make")
def codes_make():
    tokens_each = form_int("tokens", 0, 1, 10_000_000)
    count = form_int("count", 1, 1, 100)
    note = form_str("note", 120) or "ออกโดยผู้ดูแล"
    if tokens_each <= 0:
        return back("panel.codes", err="กรุณากรอกจำนวน Token ต่อหนึ่งรหัส")
    made = billing.make_codes(tokens_each, count, note)
    if not made:
        return back("panel.codes", err="ออกรหัสไม่สำเร็จ")
    session["panel_codes"] = {"tokens": tokens_each, "list": made, "note": note}
    log("ออกรหัสเติม Token", "",
        "%d ใบ ใบละ %s Token · %s" % (len(made), format(tokens_each, ","), note))
    return redirect(url_for("panel.codes"))


# ==================================================================
#  ข้อความหน้าแนะนำ
# ==================================================================

@bp.get("/admin/content")
def texts():
    return page("texts.html", values=content.all_text(),
                groups=content.GROUPS, labels=content.LABELS,
                long_fields=content.LONG_FIELDS,
                info=content.info())


@bp.post("/admin/content")
def texts_save():
    vals = {}
    for k, default in content.DEFAULTS.items():
        if isinstance(default, bool):
            vals[k] = request.form.get(k) == "1"
        else:
            vals[k] = request.form.get(k, content.get(k))
    ok, changed = content.save_text(vals, changed_by=my_email())
    if not ok:
        return back("panel.texts", err="บันทึกไม่สำเร็จ")
    log("แก้ข้อความหน้าแนะนำ", "", "เปลี่ยน %d ช่อง" % changed)
    return back("panel.texts", ok="บันทึกแล้ว เปลี่ยน %d ช่อง" % changed)


@bp.post("/admin/content/reset")
def texts_reset():
    content.reset_text()
    log("คืนข้อความหน้าแนะนำเป็นค่าตั้งต้น")
    return back("panel.texts", ok="คืนค่าตั้งต้นเรียบร้อย")


# ==================================================================
#  ภาพแบนเนอร์
# ==================================================================

@bp.get("/admin/banners")
def banners():
    return page("banners.html", slides=content.slides(),
                values=content.all_text(), max_mb=MAX_UPLOAD // (1024 * 1024))


def _save_banner_image(stream, base):
    """
    รับภาพที่อัปโหลด ครอบเป็นจัตุรัส แล้ววาดไฟล์ใหม่ทั้งใบ

    การวาดใหม่ทำให้ข้อมูลแฝงที่อาจซ่อนมาในไฟล์เดิมหายไปทั้งหมด
    เพราะไฟล์ที่ได้ถูกสร้างจากจุดสีล้วน ๆ ไม่ได้คัดลอกเนื้อไฟล์เดิมมา
    """
    from PIL import Image
    raw = stream.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        return False, "ไฟล์ใหญ่เกิน %d MB" % (MAX_UPLOAD // (1024 * 1024))
    if not raw:
        return False, "ไม่พบไฟล์ที่เลือก"
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return False, "อ่านไฟล์ภาพไม่ได้ กรุณาเลือกไฟล์ภาพที่ถูกต้อง"

    im = im.convert("RGB")
    w, h = im.size
    if w < 200 or h < 200:
        return False, "ภาพเล็กเกินไป ควรมีด้านละอย่างน้อย 200 จุด"

    # ครอบตรงกลางให้เป็นจัตุรัส แล้วย่อเป็น 1080x1080
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))
    im = im.resize((1080, 1080), Image.LANCZOS)

    os.makedirs(BANNER_DIR, exist_ok=True)
    try:
        im.save(os.path.join(BANNER_DIR, base + ".webp"), quality=90, method=6)
        im.save(os.path.join(BANNER_DIR, base + ".jpg"),
                quality=90, optimize=True, progressive=True)
    except OSError:
        return False, "บันทึกไฟล์ไม่สำเร็จ"
    return True, ""


@bp.post("/admin/banners/add")
def banners_add():
    f = request.files.get("image")
    if not f or not f.filename:
        return back("panel.banners", err="กรุณาเลือกไฟล์ภาพ")
    base = "b" + secrets.token_hex(5)
    ok, msg = _save_banner_image(f.stream, base)
    if not ok:
        return back("panel.banners", err=msg)
    content.add_slide(base, alt=form_str("alt", 200), link=form_str("link", 200))
    log("เพิ่มภาพแบนเนอร์", base)
    return back("panel.banners", ok="เพิ่มภาพแบนเนอร์แล้ว")


@bp.post("/admin/banners/replace")
def banners_replace():
    sid = form_str("id", 24)
    target = next((s for s in content.slides() if s["id"] == sid), None)
    if not target:
        return back("panel.banners", err="ไม่พบภาพที่เลือก")
    f = request.files.get("image")
    if not f or not f.filename:
        return back("panel.banners", err="กรุณาเลือกไฟล์ภาพ")
    ok, msg = _save_banner_image(f.stream, target["file"])
    if not ok:
        return back("panel.banners", err=msg)
    log("เปลี่ยนภาพแบนเนอร์", target["file"])
    return back("panel.banners", ok="เปลี่ยนภาพเรียบร้อย")


@bp.post("/admin/banners/edit")
def banners_edit():
    sid = form_str("id", 24)
    content.update_slide(sid, alt=form_str("alt", 200), link=form_str("link", 200))
    log("แก้คำอธิบายภาพแบนเนอร์", sid)
    return back("panel.banners", ok="บันทึกแล้ว")


@bp.post("/admin/banners/move")
def banners_move():
    content.move_slide(form_str("id", 24), form_int("delta", 0, -1, 1))
    return back("panel.banners", ok="สลับลำดับแล้ว")


@bp.post("/admin/banners/toggle")
def banners_toggle():
    sid = form_str("id", 24)
    on = request.form.get("on") == "1"
    content.toggle_slide(sid, on)
    log("เปิดใช้ภาพแบนเนอร์" if on else "ซ่อนภาพแบนเนอร์", sid)
    return back("panel.banners", ok="เปิดใช้แล้ว" if on else "ซ่อนแล้ว")


@bp.post("/admin/banners/delete")
def banners_delete():
    sid = form_str("id", 24)
    target = next((s for s in content.slides() if s["id"] == sid), None)
    if not target:
        return back("panel.banners", err="ไม่พบภาพที่เลือก")
    content.remove_slide(sid)
    content.delete_files(target["file"])
    log("ลบภาพแบนเนอร์", target["file"])
    return back("panel.banners", ok="ลบภาพแล้ว")


@bp.post("/admin/banners/options")
def banners_options():
    vals = content.all_text()
    vals["banner_on"] = request.form.get("banner_on") == "1"
    vals["banner_builtin_on"] = request.form.get("banner_builtin_on") == "1"
    vals["banner_seconds"] = form_int("banner_seconds", 5, 2, 60)
    content.save_text(vals, changed_by=my_email())
    log("ตั้งค่าการแสดงแบนเนอร์", "",
        "แสดง=%s · แผ่นสำเร็จรูป=%s · %d วินาที"
        % (vals["banner_on"], vals["banner_builtin_on"], vals["banner_seconds"]))
    return back("panel.banners", ok="บันทึกการตั้งค่าแล้ว")


# ==================================================================
#  ตั้งค่าระบบ
# ==================================================================

@bp.get("/admin/settings")
def settings():
    cfg = _cfg()
    pay = gateway.conf(cfg)
    return page("settings.html",
                admins=admin_emails(),
                allow_signup=bool(cfg.get("allow_signup", True)),
                allow_lan=bool(cfg.get("allow_lan", False)),
                session_days=int(cfg.get("session_days", 14)),
                allowed_emails=cfg.get("allowed_emails") or [],
                pay_provider=pay["provider"],
                pay_currency=pay["currency"],
                pay_return=pay["return_url"],
                has_public=bool(pay["public_key"]),
                has_secret=bool(pay["secret_key"]),
                has_hook=bool(pay["webhook_secret"]),
                gateway_ready=gateway.is_ready(cfg),
                gateway_names=gateway.KNOWN,
                plans=[billing.PLANS[p] for p in billing.PLAN_ORDER])


def _save_cfg(changes):
    import auth
    cfg = _cfg()
    cfg.update(changes)
    auth.save_config(cfg)
    current_app.config["APP_CONFIG"] = cfg
    return cfg


@bp.post("/admin/settings/general")
def settings_general():
    _save_cfg({
        "allow_signup": request.form.get("allow_signup") == "1",
        "allow_lan": request.form.get("allow_lan") == "1",
        "session_days": form_int("session_days", 14, 1, 365),
    })
    log("แก้ตั้งค่าทั่วไป")
    return back("panel.settings",
                ok="บันทึกแล้ว การเปิดใช้จากเครือข่ายภายในจะมีผลเมื่อเปิดระบบใหม่")


@bp.post("/admin/settings/admins")
def settings_admins():
    raw = (request.form.get("emails") or "").replace(",", "\n")
    got = []
    for line in raw.splitlines():
        e = users.norm(line)
        if e and users.valid_email(e) and e not in got:
            got.append(e)
    mine = my_email()
    if mine and mine not in got and not me().get("admin"):
        return back("panel.settings",
                    err="ต้องมีอีเมลของคุณอยู่ในรายชื่อ มิฉะนั้นคุณจะเข้าหน้านี้ไม่ได้อีก")
    _save_cfg({"admin_emails": got})
    log("แก้รายชื่อผู้ดูแล", "", "เหลือ %d รายชื่อ" % len(got))
    return back("panel.settings", ok="บันทึกรายชื่อผู้ดูแลแล้ว")


@bp.post("/admin/settings/payment")
def settings_payment():
    cfg = _cfg()
    pay = dict(gateway.conf(cfg))
    pay["provider"] = form_str("provider", 30)
    pay["currency"] = form_str("currency", 8) or "THB"
    pay["return_url"] = form_str("return_url", 200)
    # ช่องที่เว้นว่างไว้ แปลว่าไม่ต้องการเปลี่ยนค่าเดิม
    for field, name in (("public_key", "public_key"),
                        ("secret_key", "secret_key"),
                        ("webhook_secret", "webhook_secret")):
        v = (request.form.get(name) or "").strip()
        if v:
            pay[field] = v[:200]
    if request.form.get("clear_keys") == "1":
        pay["public_key"] = pay["secret_key"] = pay["webhook_secret"] = ""
    _save_cfg({"payment": pay})
    log("แก้ตั้งค่าระบบรับชำระเงิน", "", "ผู้ให้บริการ %s" % (pay["provider"] or "ยังไม่ตั้ง"))
    return back("panel.settings", ok="บันทึกการตั้งค่าการชำระเงินแล้ว")


@bp.post("/admin/settings/plans")
def settings_plans():
    changed = []
    for pid in billing.PLAN_ORDER:
        p = billing.PLANS[pid]
        price = form_int("price_" + pid, p["price"], 0, 1_000_000)
        toks = form_int("tokens_" + pid, p["tokens"], 0, 100_000_000)
        name = form_str("name_" + pid, 40) or p["name"]
        if price != p["price"] or toks != p["tokens"] or name != p["name"]:
            changed.append("%s %d บาท %s Token" % (name, price, format(toks, ",")))
        p["price"] = price
        p["tokens"] = toks
        p["name"] = name
    billing.save_plans()
    log("แก้ราคาและ Token ของแพ็กเกจ", "", " · ".join(changed)[:280])
    return back("panel.settings", ok="บันทึกแพ็กเกจแล้ว")


# ==================================================================
#  บันทึกการทำงาน
# ==================================================================

@bp.get("/admin/logs")
def logs():
    q = (request.args.get("q") or "").strip().lower()
    rows = _read_log()
    if q:
        rows = [r for r in rows
                if q in r["who"].lower() or q in r["action"].lower()
                or q in r["target"].lower() or q in r["detail"].lower()]
    return page("logs.html", rows=rows[:400], q=q, total=len(_read_log()))
