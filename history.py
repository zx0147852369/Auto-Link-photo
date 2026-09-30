# -*- coding: utf-8 -*-
"""
history.py — ประวัติการค้นหาของผู้ใช้แต่ละคน

เก็บไว้ในไฟล์ history.json บนเครื่องผู้ใช้เท่านั้น แยกตามบัญชี
ผู้ใช้ลบทีละรายการหรือลบทั้งหมดได้ตลอดเวลา
"""

import json
import os
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_PATH = os.path.join(BASE_DIR, "history.json")

MAX_PER_USER = 80          # เก็บล่าสุดไม่เกินกี่รายการต่อบัญชี
_lock = threading.Lock()


def _read():
    if not os.path.exists(HISTORY_PATH):
        return {}
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def _write(data):
    tmp = HISTORY_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HISTORY_PATH)
    except OSError:
        pass


def key_of(user) -> str:
    """คีย์ประจำบัญชี — บัญชีผู้ดูแลที่ไม่มีอีเมลใช้คีย์เฉพาะ"""
    if not user:
        return ""
    return (user.get("email") or "").strip().lower() or "__admin__"


def add(user, url, title="", count=0, level=2, host=""):
    key = key_of(user)
    if not key or not url:
        return
    with _lock:
        data = _read()
        items = [i for i in data.get(key, []) if i.get("url") != url]
        items.insert(0, {
            "url": url,
            "title": (title or "")[:160],
            "host": host or "",
            "count": int(count or 0),
            "level": int(level or 2),
            "at": int(time.time()),
        })
        data[key] = items[:MAX_PER_USER]
        _write(data)


def items(user):
    key = key_of(user)
    if not key:
        return []
    return _read().get(key, [])


def remove(user, at):
    key = key_of(user)
    if not key:
        return
    with _lock:
        data = _read()
        data[key] = [i for i in data.get(key, []) if int(i.get("at", 0)) != int(at)]
        _write(data)


def clear(user):
    key = key_of(user)
    if not key:
        return
    with _lock:
        data = _read()
        data.pop(key, None)
        _write(data)
