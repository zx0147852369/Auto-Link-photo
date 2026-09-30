# -*- coding: utf-8 -*-
"""
sentry.py — ยามเฝ้าระบบ

นับพฤติกรรมที่ส่อว่ามีคนพยายามงัดเข้าระบบ แล้วปิดประตูใส่ชั่วคราวเมื่อทำซ้ำหลายครั้ง

หลักคิดที่ยึด
  • นับแยกตามหมายเลขเครื่องผู้ใช้ ไม่ผูกกับบัญชี เพราะคนร้ายยังไม่มีบัญชี
  • เหตุแต่ละชนิดมีน้ำหนักไม่เท่ากัน เดารหัสผ่านหนักกว่าเปิดหน้าที่ไม่มีอยู่
  • บล็อกเป็นช่วงเวลา ไม่บล็อกถาวร คนใช้จริงที่พลาดเองจะกลับมาได้เสมอ
  • ยิ่งโดนบล็อกซ้ำ ยิ่งบล็อกนานขึ้น คนร้ายที่ดื้อจะเสียเวลามากขึ้นเรื่อย ๆ
  • เก็บทุกอย่างไว้ในหน่วยความจำ ไม่แตะไฟล์ข้อมูลของผู้ใช้
"""

import threading
import time

from flask import request

# น้ำหนักของแต่ละเหตุ ยิ่งมากยิ่งเข้าใกล้การถูกบล็อก
WEIGHTS = {
    # คนใช้จริงพิมพ์รหัสผิดเองได้หลายครั้ง ตั้งไว้ให้ถูกปิดกั้นเมื่อผิดครบหกครั้ง
    # ซึ่งอยู่ในเกณฑ์ปกติของระบบทั่วไป ไม่ใจร้ายกับคนที่แค่จำรหัสไม่ได้
    "login": 2,        # รหัสผ่านผิด
    "twofa": 4,        # รหัสยืนยันสองชั้นผิด
    "csrf": 5,         # โทเคนกำกับคำขอไม่ถูกต้อง
    "origin": 5,       # คำขอมาจากเว็บอื่น
    "ssrf": 8,         # พยายามให้เซิร์ฟเวอร์ไปดึงเครือข่ายภายใน
    "probe": 2,        # เปิดเส้นทางที่ไม่มีอยู่จริงแบบส่อเจตนา
    "admin": 6,        # พยายามเข้าหน้าผู้ดูแลโดยไม่มีสิทธิ์
    "upload": 4,       # ส่งไฟล์ที่ไม่ถูกต้องเข้ามา
}

# สะสมครบเท่านี้ภายในกรอบเวลา แล้วบล็อก
LIMIT = 12
WINDOW = 600            # กรอบเวลาสะสม (วินาที)
BLOCK_BASE = 900        # บล็อกครั้งแรกนานเท่านี้ (วินาที)
BLOCK_MAX = 6 * 3600    # เพดานการบล็อก

# เส้นทางที่คนทั่วไปไม่เปิด แต่เครื่องมือสแกนช่องโหว่ชอบลอง
PROBE_HINTS = (
    "/.env", "/.git", "/wp-admin", "/wp-login", "/phpmyadmin",
    "/vendor/", "/.aws", "/.ssh", "/config.json", "/backup",
    "/actuator", "/cgi-bin/", "/shell", "/xmlrpc.php", "/.well-known/security",
)

_lock = threading.Lock()
_events = {}      # ip -> [(เวลา, น้ำหนัก), ...]
_blocks = {}      # ip -> {"until": เวลา, "times": จำนวนครั้งที่เคยโดน}
_log = []         # บันทึกไว้ให้ผู้ดูแลดูย้อนหลัง
LOG_MAX = 300


def client_ip() -> str:
    """หมายเลขเครื่องของผู้ขอ"""
    return (request.remote_addr or "unknown")[:45]


def _sweep(now):
    """เก็บกวาดของเก่าที่หมดอายุแล้ว เรียกตอนถือล็อกอยู่เท่านั้น"""
    for ip in [k for k, v in _events.items()
               if not v or v[-1][0] < now - WINDOW]:
        _events.pop(ip, None)
    for ip in [k for k, v in _blocks.items()
               if v["until"] < now - 24 * 3600]:
        _blocks.pop(ip, None)


def note(kind: str, detail: str = "", ip: str = "") -> bool:
    """
    บันทึกเหตุน่าสงสัยหนึ่งครั้ง คืน True ถ้าเหตุนี้ทำให้ถูกบล็อกพอดี

    เรียกได้จากทุกที่ที่ตรวจเจอความผิดปกติ ไม่ต้องสนใจว่าถึงเกณฑ์หรือยัง
    """
    weight = WEIGHTS.get(kind, 2)
    now = time.time()
    ip = ip or client_ip()

    with _lock:
        _sweep(now)
        hits = [(t, w) for t, w in _events.get(ip, []) if t > now - WINDOW]
        hits.append((now, weight))
        _events[ip] = hits
        total = sum(w for _t, w in hits)

        _log.append({"at": now, "ip": ip, "kind": kind,
                     "detail": str(detail)[:160], "score": total})
        if len(_log) > LOG_MAX:
            del _log[:len(_log) - LOG_MAX]

        if total < LIMIT:
            return False

        # ถึงเกณฑ์แล้ว ปิดประตูใส่ และล้างแต้มเพื่อเริ่มนับใหม่หลังพ้นช่วงบล็อก
        prev = _blocks.get(ip) or {"times": 0}
        times = int(prev.get("times") or 0) + 1
        span = min(BLOCK_BASE * (2 ** (times - 1)), BLOCK_MAX)
        _blocks[ip] = {"until": now + span, "times": times}
        _events.pop(ip, None)
        _log.append({"at": now, "ip": ip, "kind": "block",
                     "detail": "ปิดกั้นชั่วคราว %d นาที" % (span // 60),
                     "score": total})
        return True


def blocked_for(ip: str = "") -> int:
    """เหลือเวลาถูกปิดกั้นอีกกี่วินาที คืน 0 ถ้าไม่ได้ถูกปิดกั้น"""
    ip = ip or client_ip()
    now = time.time()
    with _lock:
        got = _blocks.get(ip)
        if not got:
            return 0
        left = int(got["until"] - now)
        if left <= 0:
            return 0
        return left


def note_path_probe() -> bool:
    """ดูว่าเส้นทางที่ขอมาเข้าข่ายการไล่สแกนช่องโหว่ไหม ถ้าใช่ก็บันทึกให้"""
    low = (request.path or "").lower()
    if any(h in low for h in PROBE_HINTS):
        return note("probe", request.path[:120])
    return False


def recent(limit: int = 80):
    """รายการเหตุล่าสุด ใหม่สุดอยู่บน สำหรับหน้าผู้ดูแล"""
    with _lock:
        return list(reversed(_log[-int(limit):]))


def blocked_list():
    """รายชื่อที่กำลังถูกปิดกั้นอยู่ตอนนี้"""
    now = time.time()
    with _lock:
        return [{"ip": ip, "left": int(v["until"] - now), "times": v["times"]}
                for ip, v in sorted(_blocks.items())
                if v["until"] > now]


def release(ip: str):
    """ปลดการปิดกั้นด้วยมือ สำหรับผู้ดูแลที่เห็นว่าเป็นการเข้าใจผิด"""
    with _lock:
        _blocks.pop(ip, None)
        _events.pop(ip, None)


def reset_all():
    """ล้างทั้งหมด ใช้ในชุดตรวจเท่านั้น"""
    with _lock:
        _events.clear()
        _blocks.clear()
        del _log[:]
