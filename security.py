# -*- coding: utf-8 -*-
"""
security.py — ส่วนรักษาความปลอดภัยส่วนกลาง

  • โทเคน CSRF สำหรับฟอร์มทุกใบ
  • จำกัดจำนวนครั้งการพยายามเข้าสู่ระบบและการสมัคร
  • ป้องกันการยิงคำขอไปยังเครือข่ายภายใน (SSRF)
  • ส่วนหัวความปลอดภัยของหน้าเว็บ
"""

import hmac
import ipaddress
import secrets
import socket
import threading
import time
from urllib.parse import urlparse

from flask import request, session

# ------------------------------------------------------------------ CSRF

CSRF_FIELD = "_csrf"


def csrf_token() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["csrf"] = tok
    return tok


def csrf_valid() -> bool:
    sent = request.form.get(CSRF_FIELD) or request.headers.get("X-CSRF-Token") or ""
    have = session.get("csrf") or ""
    if not have:
        return False
    # เทียบเป็นไบต์ เพราะโทเคนที่ส่งมาอาจมีอักขระนอก ASCII
    return hmac.compare_digest(str(sent).encode("utf-8", "replace"),
                               str(have).encode("utf-8", "replace"))


def rotate_csrf():
    """เปลี่ยนโทเคนใหม่หลังเข้าสู่ระบบสำเร็จ"""
    session["csrf"] = secrets.token_urlsafe(32)


# ------------------------------------------- จำกัดจำนวนครั้ง (rate limit)

_hits = {}
_hits_lock = threading.Lock()


def _client_ip() -> str:
    return (request.remote_addr or "unknown")[:45]


def rate_check(bucket: str, limit: int, window: int, key: str = ""):
    """
    คืน (ผ่านหรือไม่, วินาทีที่ต้องรอ)
    นับแยกตามหมายเลขเครื่องผู้ใช้ + คีย์เพิ่มเติม
    """
    now = time.time()
    ident = f"{bucket}|{_client_ip()}|{key}"
    with _hits_lock:
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or v[-1] < now - 3600]:
                _hits.pop(k, None)
        times = [t for t in _hits.get(ident, []) if t > now - window]
        if len(times) >= limit:
            return False, int(window - (now - times[0])) + 1
        times.append(now)
        _hits[ident] = times
    return True, 0


def rate_reset(bucket: str, key: str = ""):
    with _hits_lock:
        _hits.pop(f"{bucket}|{_client_ip()}|{key}", None)


# ------------------------------------------------------------------ SSRF

class BlockedTarget(Exception):
    """ปลายทางอยู่ในเครือข่ายภายใน จึงไม่อนุญาตให้เข้าถึง"""


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def check_url(url: str, allow_private: bool = False) -> str:
    """
    ตรวจว่า URL ปลอดภัยพอจะให้เซิร์ฟเวอร์ไปดึงข้อมูล
    คืน URL เดิมถ้าผ่าน มิฉะนั้นโยน BlockedTarget
    """
    p = urlparse(url or "")
    if p.scheme not in ("http", "https"):
        raise BlockedTarget("รองรับเฉพาะที่อยู่ที่ขึ้นต้นด้วย http:// หรือ https://")
    host = p.hostname
    if not host:
        raise BlockedTarget("รูปแบบที่อยู่ไม่ถูกต้อง")
    if allow_private:
        return url

    low = host.lower()
    if low == "localhost" or low.endswith(".localhost") or low.endswith(".local"):
        raise BlockedTarget("ไม่อนุญาตให้เข้าถึงเครื่องภายในเครือข่าย")

    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise BlockedTarget("ไม่พบชื่อเว็บไซต์ปลายทาง")

    for info in infos:
        if _ip_blocked(info[4][0]):
            raise BlockedTarget("ไม่อนุญาตให้เข้าถึงเครื่องภายในเครือข่าย")
    return url


def guard_response_chain(resp, allow_private: bool = False):
    """ตรวจทุกปลายทางที่ถูก redirect ไป กันการเปลี่ยนเส้นทางเข้าเครือข่ายภายใน"""
    if allow_private:
        return
    for r in list(getattr(resp, "history", [])) + [resp]:
        check_url(r.url, allow_private=False)


# ------------------------------------------------------- ส่วนหัวความปลอดภัย

def apply_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy",
                            "geolocation=(), microphone=(), camera=()")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    return resp


LOCAL_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}


def _hostname(h: str) -> str:
    """ดึงเฉพาะชื่อโฮสต์ ตัดพอร์ตทิ้ง"""
    h = (h or "").strip().lower()
    if h.startswith("[") and "]" in h:                  # IPv6 เช่น [::1]:5000
        return h.partition("]")[0] + "]"
    return h.partition(":")[0]


def _same_host(a: str, b: str) -> bool:
    """
    เทียบชื่อโฮสต์ โดยไม่สนพอร์ต และถือว่า 127.0.0.1 กับ localhost คือเครื่องเดียวกัน

    ไม่เทียบพอร์ตเพราะเบราว์เซอร์และค่าที่เซิร์ฟเวอร์มองเห็นอาจไม่ตรงกันได้
    ในบางสถานการณ์ ส่วนการกันคำขอปลอมข้ามเว็บใช้โทเคนเป็นด่านหลักอยู่แล้ว
    """
    na, nb = _hostname(a), _hostname(b)
    if not na or not nb:
        return True
    if na == nb:
        return True
    return na in LOCAL_NAMES and nb in LOCAL_NAMES


def same_origin_request() -> bool:
    """
    ตรวจว่าคำขอมาจากหน้าเว็บของเราเอง

    ปฏิเสธเฉพาะกรณีที่ระบุต้นทางมาชัดเจนแล้วไม่ตรงกันจริง ๆ
    ส่วนกรณีที่เบราว์เซอร์ไม่ส่งต้นทางมา (หรือส่งเป็น null) จะปล่อยผ่าน
    เพราะมีโทเคน CSRF เป็นด่านหลักอยู่แล้ว
    """
    origin = (request.headers.get("Origin") or "").strip()
    if origin and origin.lower() != "null":
        return _same_host(urlparse(origin).netloc, request.host)

    ref = (request.headers.get("Referer") or "").strip()
    if ref:
        netloc = urlparse(ref).netloc
        if netloc:
            return _same_host(netloc, request.host)
    return True
