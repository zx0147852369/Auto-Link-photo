# -*- coding: utf-8 -*-
"""
ตรวจความปลอดภัย.py — ชุดตรวจด่านกันการงัดระบบ

รัน:  python ตรวจความปลอดภัย.py

ตรวจเฉพาะเรื่องที่เคยเป็นช่องโหว่จริงหรือเป็นด่านที่ต้องไม่หลุด
ทุกอย่างทำบนสำเนาในหน่วยความจำ ไม่แตะข้อมูลจริงของผู้ใช้
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as A          # noqa: E402
import billing           # noqa: E402
import security          # noqa: E402
import sentry            # noqa: E402
import users             # noqa: E402

ok = bad = 0


def check(name, cond, note=""):
    global ok, bad
    if cond:
        ok += 1
        print("  ผ่าน  %s" % name)
    else:
        bad += 1
        print("  ตก    %s  %s" % (name, note))


A.app.config["TESTING"] = True
A.app.config.setdefault("APP_CONFIG", {})["allow_private_network"] = False

WHO = {"email": "ตรวจความปลอดภัย@local", "name": "ตรวจความปลอดภัย"}
try:
    users.create(WHO["email"], WHO["name"], "Abcdef12")
except Exception:
    pass
billing.grant(WHO, 9000000, "ชุดตรวจ")


def fresh(login=True):
    """เปิดผู้ใช้ใหม่หนึ่งราย ล้างสถานะยามเฝ้าระบบก่อนเสมอ"""
    sentry.reset_all()
    security._hits.clear()
    c = A.app.test_client()
    if login:
        with c.session_transaction() as ss:
            ss["user"] = WHO
            ss["fresh"] = True
    return c


def form_token(c):
    """โทเคนจากฟอร์มเข้าสู่ระบบจริง เหมือนที่เบราว์เซอร์ได้ไป"""
    html = c.get("/login").get_data(as_text=True)
    m = re.search(r'name="_csrf"[^>]*value="([^"]+)"', html) or \
        re.search(r'value="([^"]+)"[^>]*name="_csrf"', html)
    return m.group(1) if m else ""


# ------------------------------------------------------------------
print()
print("=== โทเคนกำกับคำขอ ต้องกันการยิงข้ามเว็บได้ ===")

c = fresh()
c.get("/app")                       # เปิดหน้าเว็บ เซสชันจึงมีโทเคน
with c.session_transaction() as ss:
    tok = ss.get("csrf")
check("เปิดหน้าเว็บแล้วเซสชันได้รับโทเคน", bool(tok))

r = c.post("/api/history-clear")
check("ลบประวัติโดยไม่แนบโทเคน ต้องถูกปฏิเสธ", r.status_code == 403, r.status_code)

r = c.post("/api/history-clear", headers={"X-CSRF-Token": "ของปลอม"})
check("แนบโทเคนผิด ต้องถูกปฏิเสธ", r.status_code == 403, r.status_code)

r = c.post("/api/history-clear", headers={"X-CSRF-Token": tok})
check("แนบโทเคนถูกต้อง ต้องผ่าน", r.status_code == 200, r.status_code)

# เส้นทางที่หัก Token ต้องกันด้วยเหมือนกัน ไม่ใช่แค่เส้นทางที่ลบข้อมูล
r = c.post("/api/clip-gif", json={"url": "https://example.com/a"})
check("สั่งงานที่หัก Token โดยไม่แนบโทเคน ต้องถูกปฏิเสธ",
      r.status_code == 403, r.status_code)


# ------------------------------------------------------------------
print()
print("=== ต้นทางคำขอ ===")

c = fresh()
c.get("/app")
with c.session_transaction() as ss:
    tok = ss.get("csrf")
r = c.post("/api/history-clear",
           headers={"X-CSRF-Token": tok, "Origin": "https://เว็บคนร้าย.tld"})
check("คำขอจากเว็บอื่น ต้องถูกปฏิเสธ", r.status_code == 403, r.status_code)


# ------------------------------------------------------------------
print()
print("=== กันการยิงเข้าเครือข่ายภายใน ===")

INSIDE = [
    "http://127.0.0.1:5000/app",
    "http://localhost:8080/",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/",
    "http://10.0.0.1/",
]
for target in INSIDE:
    c = fresh()
    c.get("/app")
    with c.session_transaction() as ss:
        tok = ss.get("csrf")
    r = c.post("/api/clip-open", json={"url": target},
               headers={"X-CSRF-Token": tok})
    check("ปิดกั้น %s" % target[:38], r.status_code == 400, r.status_code)

c = fresh()
r = c.get("/api/clip-play?url=http://127.0.0.1:5000/app")
check("ทางเล่นคลิปก็ปิดกั้นเครือข่ายภายใน", r.status_code == 400, r.status_code)


# ------------------------------------------------------------------
print()
print("=== เพดานขนาดไฟล์ที่ส่งเข้ามา ===")

check("ตั้งเพดานไว้ที่ตัวเว็บเซิร์ฟเวอร์",
      int(A.app.config.get("MAX_CONTENT_LENGTH") or 0) > 0,
      A.app.config.get("MAX_CONTENT_LENGTH"))

c = fresh()
c.get("/app")
with c.session_transaction() as ss:
    tok = ss.get("csrf")
huge = b"x" * (int(A.app.config["MAX_CONTENT_LENGTH"]) + 4096)
r = c.post("/api/upload-gif",
           data={"video": (io.BytesIO(huge), "ใหญ่เกิน.mp4")},
           content_type="multipart/form-data",
           headers={"X-CSRF-Token": tok})
check("ไฟล์เกินเพดาน ต้องตอบ 413 ไม่ใช่พังทั้งระบบ",
      r.status_code == 413, r.status_code)

c = fresh()
c.get("/app")
with c.session_transaction() as ss:
    tok = ss.get("csrf")
r = c.post("/api/upload-gif",
           data={"video": (io.BytesIO("ไม่ใช่วิดีโอจริง".encode("utf-8")),
                           "ปลอม.mp4")},
           content_type="multipart/form-data",
           headers={"X-CSRF-Token": tok})
check("ไฟล์ที่ไม่ใช่วิดีโอ ต้องถูกปฏิเสธ", r.status_code == 400, r.status_code)


# ------------------------------------------------------------------
print()
print("=== กันการไล่เดารหัสผ่าน ===")

c = fresh(login=False)
tok = form_token(c)
check("หน้าเข้าสู่ระบบแนบโทเคนมาให้", bool(tok))

# รหัสผ่านที่มีอักขระนอก ASCII เคยทำให้หน้าเข้าสู่ระบบพังทั้งหน้า
r = c.post("/login", data={"email": "", "password": "รหัสผ่านภาษาไทย",
                           "_csrf": tok})
check("รหัสผ่านภาษาไทย ต้องไม่ทำให้ระบบพัง",
      r.status_code != 500, r.status_code)

blocked_at = 0
for i in range(1, 16):
    r = c.post("/login", data={"email": "", "password": "เดา%d" % i,
                               "_csrf": tok})
    if sentry.blocked_for("127.0.0.1"):
        blocked_at = i
        break
check("เดารหัสผ่านซ้ำ ๆ แล้วถูกปิดกั้น", blocked_at > 0, "ไม่ถูกปิดกั้นเลย")
check("ปิดกั้นในจำนวนครั้งที่สมเหตุผล (4-10 ครั้ง)",
      4 <= blocked_at <= 10, "ครั้งที่ %d" % blocked_at)

check("ปิดกั้นแล้วเข้าหน้าเครื่องมือไม่ได้", c.get("/app").status_code == 429)
check("ปิดกั้นแล้วเข้าหน้าแนะนำก็ไม่ได้", c.get("/").status_code == 429)

sentry.release("127.0.0.1")
check("ผู้ดูแลปลดการปิดกั้นได้", sentry.blocked_for("127.0.0.1") == 0)


# ------------------------------------------------------------------
print()
print("=== ยามเฝ้าระบบ ===")

sentry.reset_all()
check("เริ่มต้นไม่มีใครถูกปิดกั้น", sentry.blocked_list() == [])

for _ in range(3):
    sentry.note("ssrf", "ทดสอบ", ip="203.0.113.9")
check("เหตุหนักสะสมถึงเกณฑ์แล้วปิดกั้น",
      sentry.blocked_for("203.0.113.9") > 0)

first = sentry.blocked_for("203.0.113.9")

# จำลองว่าพ้นช่วงปิดกั้นรอบแรกไปแล้ว แล้วกลับมาก่อเหตุซ้ำ
# (ต่างจากการที่ผู้ดูแลปลดให้เอง ซึ่งตั้งใจให้เริ่มนับใหม่หมด)
with sentry._lock:
    sentry._blocks["203.0.113.9"]["until"] = 0
for _ in range(3):
    sentry.note("ssrf", "ทดสอบ", ip="203.0.113.9")
second = sentry.blocked_for("203.0.113.9")
check("โดนซ้ำแล้วถูกปิดกั้นนานขึ้น", second > first,
      "ครั้งแรก %ds ครั้งสอง %ds" % (first, second))

sentry.release("203.0.113.9")
for _ in range(3):
    sentry.note("ssrf", "ทดสอบ", ip="203.0.113.9")
check("ผู้ดูแลปลดให้แล้ว ถือว่าเริ่มนับใหม่ ไม่สะสมโทษเดิม",
      sentry.blocked_for("203.0.113.9") <= first)

check("เหตุที่ไม่ถึงเกณฑ์ ยังไม่ปิดกั้น",
      not sentry.note("probe", "ครั้งเดียว", ip="203.0.113.77"))

sentry.reset_all()
c = fresh(login=False)
r = c.get("/.env")
check("เปิดเส้นทางที่เครื่องมือสแกนชอบลอง ถูกบันทึกไว้",
      any(e["kind"] == "probe" for e in sentry.recent(20)))

sentry.reset_all()


# ------------------------------------------------------------------
print()
print("=== คุกกี้เซสชัน ===")

check("คุกกี้อ่านจากสคริปต์ไม่ได้",
      A.app.config.get("SESSION_COOKIE_HTTPONLY") is True)
check("คุกกี้ไม่ถูกแนบไปกับคำขอจากเว็บอื่น",
      str(A.app.config.get("SESSION_COOKIE_SAMESITE") or "").lower()
      in ("lax", "strict"),
      A.app.config.get("SESSION_COOKIE_SAMESITE"))


# ------------------------------------------------------------------
print()
print("=== จำกัดความถี่งานที่กินทรัพยากร ===")

c = fresh()
c.get("/app")
with c.session_transaction() as ss:
    tok = ss.get("csrf")
codes = []
for _ in range(16):
    r = c.post("/api/clip-gif", json={"url": "https://example.com/a"},
               headers={"X-CSRF-Token": tok})
    codes.append(r.status_code)
check("สั่งงานแปลงไฟล์รัว ๆ แล้วโดนชะลอ", 429 in codes,
      "ไม่มีการชะลอเลย")
security._hits.clear()
sentry.reset_all()


# ------------------------------------------------------------------
print()
print("=== ส่วนหัวความปลอดภัยของหน้าเว็บ ===")

c = fresh()
r = c.get("/")
for head, want in (("X-Content-Type-Options", "nosniff"),
                   ("X-Frame-Options", "DENY"),
                   ("Referrer-Policy", "no-referrer")):
    check("มีส่วนหัว %s" % head, r.headers.get(head) == want,
          r.headers.get(head))


# ------------------------------------------------------------------
print()
print("=== หน้าผู้ดูแล ===")

sentry.reset_all()
c = fresh()                      # ผู้ใช้ธรรมดา ไม่ใช่ผู้ดูแล
r = c.get("/panel/admin")
check("ผู้ใช้ทั่วไปเข้าหน้าผู้ดูแลไม่ได้", r.status_code in (403, 302),
      r.status_code)
check("การพยายามเข้าหน้าผู้ดูแลถูกบันทึกไว้",
      any(e["kind"] == "admin" for e in sentry.recent(20)))
sentry.reset_all()


# ------------------------------------------------------------------
print()
print("  ผ่าน %d  ตก %d" % (ok, bad))
sys.exit(1 if bad else 0)
