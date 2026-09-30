# -*- coding: utf-8 -*-
"""
imgguard.py — ระบบคัดกรองไฟล์รูปภาพ

หลักการทำงาน
  1. อ่านโครงสร้างไฟล์ตามมาตรฐานของแต่ละชนิด เพื่อหาว่า "ข้อมูลภาพจริงจบตรงไหน"
  2. ตรวจเฉพาะส่วนที่ควรตรวจ คือส่วนหัว ส่วนข้อความกำกับ และส่วนที่ต่อท้ายหลังภาพจบ
  3. ไม่ค้นหาลายเซ็นสั้น ๆ ทั่วทั้งไฟล์ เพราะข้อมูลภาพที่ถูกบีบอัดมีลักษณะคล้ายข้อมูลสุ่ม
     ทำให้ไบต์ชุดสั้นปรากฏขึ้นเองได้เสมอ ซึ่งจะกลายเป็นการแจ้งเตือนผิดพลาด
  4. เมื่อพบสิ่งที่คล้ายไฟล์อื่นแฝงอยู่ จะตรวจโครงสร้างของสิ่งนั้นซ้ำอีกชั้น
     เพื่อยืนยันว่าเป็นไฟล์นั้นจริง ไม่ใช่ไบต์ที่บังเอิญตรงกัน

หมายเหตุ: ไม่ใช่โปรแกรมป้องกันไวรัส แต่ตรวจรูปแบบการแฝงตัวที่มากับไฟล์ภาพได้ครอบคลุม
"""

import re
import struct

OK, WARN, DANGER = "ok", "warn", "danger"
RANK = {OK: 0, WARN: 1, DANGER: 2}
LABEL = {OK: "ปลอดภัย", WARN: "ควรระวัง", DANGER: "อันตราย"}

# ยอมให้มีข้อมูลส่วนเกินท้ายไฟล์ได้เท่านี้ โดยไม่ถือว่าผิดปกติ
# กล้องและโปรแกรมแต่งภาพหลายตัวเติมไบต์ว่างท้ายไฟล์เป็นเรื่องปกติ
TRAILER_OK = 512
TRAILER_WARN = 64 * 1024


# ==================================================================
#  ตรวจชนิดไฟล์จากส่วนหัว
# ==================================================================

SVG_HINT = re.compile(rb"<\s*svg", re.I)
XML_HINT = re.compile(rb"^\s*(?:<\?xml|<!DOCTYPE\s+svg|<\s*svg)", re.I)
HTML_HINT = re.compile(rb"^\s*(?:<!DOCTYPE\s+html|<html|<head|<body|<script|<!--)", re.I)


def detect_format(data: bytes) -> str:
    h = data[:32]
    if h.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h.startswith(b"GIF87a") or h.startswith(b"GIF89a"):
        return "gif"
    if h.startswith(b"BM"):
        return "bmp"
    if h.startswith(b"II*\x00") or h.startswith(b"MM\x00*"):
        return "tiff"
    if h[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"):
        return "ico"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic"
    if XML_HINT.match(data[:512]) and SVG_HINT.search(data[:4096]):
        return "svg"
    return ""


# ==================================================================
#  หาตำแหน่งที่ข้อมูลภาพจริงสิ้นสุด (คืน None ถ้าอ่านโครงสร้างไม่ได้)
# ==================================================================

def _end_jpeg(d: bytes):
    """เดินตามเครื่องหมายแบ่งส่วนของ JPEG จนถึงเครื่องหมายจบภาพ"""
    n, i = len(d), 2
    while i + 1 < n:
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m == 0xD9:                       # จบภาพ
            return i + 2
        if m in (0x01, 0xFF) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        if i + 3 >= n:
            return None
        seg = struct.unpack(">H", d[i + 2:i + 4])[0]
        if seg < 2:
            return None
        i += 2 + seg
        if m == 0xDA:                       # เริ่มข้อมูลภาพ — ข้ามไบต์ที่ถูกแทรก
            while i + 1 < n:
                if d[i] == 0xFF and d[i + 1] != 0x00 and not (0xD0 <= d[i + 1] <= 0xD7):
                    break
                i += 1
    return None


def _end_png(d: bytes):
    """เดินตามบล็อกข้อมูลของ PNG จนถึงบล็อกปิดท้าย"""
    n, i, texts = len(d), 8, []
    while i + 8 <= n:
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        if ln > n:
            return None, texts
        if typ in (b"tEXt", b"iTXt", b"zTXt"):
            texts.append(d[i + 8:i + 8 + min(ln, 65536)])
        i += 12 + ln
        if typ == b"IEND":
            return i, texts
    return None, texts


def _end_gif(d: bytes):
    """เดินตามบล็อกของ GIF จนถึงไบต์ปิดท้าย"""
    n = len(d)
    i = 13
    flags = d[10]
    if flags & 0x80:                        # มีตารางสีรวม
        i += 3 * (2 ** ((flags & 7) + 1))

    def skip_sub(p):
        while p < n:
            ln = d[p]
            p += 1
            if ln == 0:
                return p
            p += ln
        return None

    while i < n:
        b = d[i]
        if b == 0x3B:                       # ไบต์ปิดท้าย
            return i + 1
        if b == 0x21:                       # บล็อกส่วนขยาย
            if i + 2 > n:
                return None
            i = skip_sub(i + 2)
        elif b == 0x2C:                     # บล็อกภาพ
            if i + 10 > n:
                return None
            lf = d[i + 9]
            i += 10
            if lf & 0x80:                   # ตารางสีเฉพาะภาพ
                i += 3 * (2 ** ((lf & 7) + 1))
            i += 1                          # ขนาดรหัสขั้นต่ำ
            i = skip_sub(i)
        else:
            return None
        if i is None:
            return None
    return None


def _end_riff(d: bytes):
    if len(d) < 8:
        return None
    return 8 + struct.unpack("<I", d[4:8])[0]


def _end_bmp(d: bytes):
    if len(d) < 6:
        return None
    return struct.unpack("<I", d[2:6])[0]


def image_end(data: bytes, fmt: str):
    """คืน (ตำแหน่งจบของภาพ, ข้อความกำกับที่พบ) — ตำแหน่งเป็น None ถ้าอ่านไม่ได้"""
    try:
        if fmt == "jpeg":
            return _end_jpeg(data), []
        if fmt == "png":
            return _end_png(data)
        if fmt == "gif":
            return _end_gif(data), []
        if fmt == "webp":
            return _end_riff(data), []
        if fmt == "bmp":
            return _end_bmp(data), []
    except (struct.error, IndexError, ValueError):
        return None, []
    return None, []


# ==================================================================
#  ตรวจว่าไบต์ที่พบเป็นไฟล์อื่นจริงหรือแค่บังเอิญตรงกัน
# ==================================================================

ZIP_METHODS = {0, 1, 6, 8, 9, 12, 14, 93, 94, 95, 96, 97, 98}


def _is_real_zip(d: bytes, pos: int) -> bool:
    """ส่วนหัวของ zip ต้องมีค่าที่สมเหตุสมผลตามมาตรฐาน จึงจะนับว่าเป็น zip จริง"""
    if pos + 30 > len(d):
        return False
    try:
        ver, flags, method = struct.unpack("<HHH", d[pos + 4:pos + 10])
        nlen, elen = struct.unpack("<HH", d[pos + 26:pos + 30])
    except struct.error:
        return False
    if ver > 63 or method not in ZIP_METHODS:
        return False
    if not (1 <= nlen <= 512) or elen > 8192:
        return False
    if pos + 30 + nlen > len(d):
        return False
    name = d[pos + 30:pos + 30 + nlen]
    # ชื่อไฟล์ภายใน zip ต้องเป็นอักขระที่พิมพ์ได้
    return all(0x20 <= c < 0x7F or c >= 0x80 for c in name)


def _is_real_pe(d: bytes) -> bool:
    """ไฟล์โปรแกรมของวินโดวส์ต้องมีส่วนหัว PE ที่ตำแหน่งซึ่งระบุไว้ในส่วนหัวแรก"""
    if len(d) < 0x40 or d[:2] != b"MZ":
        return False
    try:
        off = struct.unpack("<I", d[0x3C:0x40])[0]
    except struct.error:
        return False
    return 0 < off < len(d) - 4 and d[off:off + 4] == b"PE\x00\x00"


def _is_real_rar(d: bytes, pos: int) -> bool:
    return d[pos:pos + 7] in (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01")


def _is_real_gzip(d: bytes, pos: int) -> bool:
    # ไบต์ที่สี่คือค่าสถานะ ซึ่งใช้เพียงห้าบิตล่าง
    return pos + 10 <= len(d) and d[pos + 3] < 0x20 and d[pos + 8] < 0x10


EMBEDDED = [
    (b"PK\x03\x04", "ไฟล์บีบอัด zip", _is_real_zip),
    (b"Rar!\x1a\x07", "ไฟล์บีบอัด rar", _is_real_rar),
    (b"7z\xbc\xaf\x27\x1c", "ไฟล์บีบอัด 7z", lambda d, p: True),
    (b"\x1f\x8b\x08", "ไฟล์บีบอัด gzip", _is_real_gzip),
    (b"%PDF-", "ไฟล์ PDF", lambda d, p: True),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "เอกสาร Office รุ่นเก่า", lambda d, p: True),
]


def _find_embedded(chunk: bytes, base: bytes, offset: int):
    """หาไฟล์อื่นที่แฝงอยู่ในส่วนที่กำหนด พร้อมตรวจโครงสร้างซ้ำ"""
    for sig, name, verify in EMBEDDED:
        p = chunk.find(sig)
        while p != -1:
            if verify(base, offset + p):
                return name
            p = chunk.find(sig, p + 1)
    return None


# ==================================================================
#  ตรวจเนื้อหาที่เป็นข้อความ
# ==================================================================

SCRIPT_PATTERNS = [
    (rb"<\s*script[\s>]", "โค้ดสคริปต์"),
    (rb"<\s*iframe[\s>]", "เฟรมฝังเว็บอื่น"),
    (rb"<\s*embed[\s>]", "การฝังไฟล์ภายนอก"),
    (rb"javascript\s*:", "ลิงก์เรียกใช้สคริปต์"),
    (rb"\bdocument\s*\.\s*(?:write|cookie|location)\b", "คำสั่งเข้าถึงข้อมูลหน้าเว็บ"),
    (rb"\bpowershell\b[^\n]{0,80}(?:-enc|-e |-command|iex|downloadstring)",
     "คำสั่ง PowerShell ที่น่าสงสัย"),
    (rb"\bcmd\.exe\b", "คำสั่งเรียกหน้าต่างคำสั่ง"),
    (rb"\bActiveXObject\s*\(", "การเรียกใช้ ActiveX"),
    (rb"FromBase64String\s*\(", "การถอดรหัสโค้ดที่ซ่อนไว้"),
    (rb"\beval\s*\(\s*(?:atob|unescape|String\.fromCharCode|function)",
     "คำสั่งรันโค้ดที่ถูกอำพราง"),
    (rb"<\?php\b", "สคริปต์ PHP"),
]

SVG_PATTERNS = [
    (rb"<\s*script[\s>]", "แท็กสคริปต์"),
    (rb"\son(?:load|error|click|mouseover|animationstart|begin)\s*=",
     "คำสั่งที่ทำงานเมื่อเกิดเหตุการณ์"),
    (rb"javascript\s*:", "ลิงก์เรียกใช้สคริปต์"),
    (rb"<\s*foreignObject[\s>]", "การฝังเนื้อหา HTML ในภาพ"),
    (rb"<\s*iframe[\s>]", "เฟรมฝังเว็บอื่น"),
    (rb"<\s*embed[\s>]", "การฝังไฟล์ภายนอก"),
    (rb"<\s*(?:use|image)[^>]{0,200}?href\s*=\s*[\"']\s*(?:https?:|//)",
     "การดึงเนื้อหาจากเว็บอื่น"),
    (rb"data\s*:\s*text/html", "การฝังหน้าเว็บในรูปแบบข้อมูล"),
    (rb"<\s*set[^>]+attributeName\s*=\s*[\"']href", "การเปลี่ยนลิงก์ระหว่างแสดงผล"),
]


def _scan_text(blob: bytes, patterns):
    found = []
    for pat, name in patterns:
        if re.search(pat, blob, re.I):
            found.append(name)
    return found


# ==================================================================
#  ฟังก์ชันหลัก
# ==================================================================

def screen(data: bytes, content_type: str = "", url: str = "", partial: bool = False):
    """
    ตรวจไฟล์ คืน dict:
      level  : ok / warn / danger
      label  : คำอธิบายระดับ
      format : ชนิดไฟล์จริงที่ตรวจพบ
      issues : รายการสิ่งที่พบ
    ตั้ง partial=True เมื่อข้อมูลที่ส่งมาไม่ครบทั้งไฟล์
    """
    data = data or b""
    issues, level = [], OK

    def bump(new, msg):
        nonlocal level
        if RANK[new] > RANK[level]:
            level = new
        if msg not in [i["text"] for i in issues]:
            issues.append({"level": new, "text": msg})

    def done():
        if not issues:
            issues.append({"level": OK, "text": "ตรวจแล้วไม่พบสิ่งผิดปกติ"})
        return {"level": level, "label": LABEL[level], "format": fmt or "ไม่ทราบ",
                "issues": issues, "url": url, "partial": partial}

    if not data:
        fmt = ""
        bump(WARN, "ไม่มีข้อมูลไฟล์ให้ตรวจ")
        return done()

    fmt = detect_format(data)
    ctype = (content_type or "").split(";")[0].strip().lower()

    # ---------- 1) ไฟล์ที่ไม่ใช่ภาพ แต่ถูกส่งมาในชื่อไฟล์ภาพ ----------
    if HTML_HINT.match(data[:512]) and fmt != "svg":
        bump(DANGER, "ไฟล์นี้เป็นหน้าเว็บ ไม่ใช่ไฟล์ภาพ")
        return done()

    if _is_real_pe(data):
        bump(DANGER, "ไฟล์นี้เป็นโปรแกรมของวินโดวส์ ไม่ใช่ไฟล์ภาพ")
        return done()

    if not fmt:
        head_name = _find_embedded(data[:64], data, 0)
        if head_name:
            bump(DANGER, f"ไฟล์นี้เป็น{head_name} ไม่ใช่ไฟล์ภาพ")
            return done()
        if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
            bump(DANGER, "ไฟล์นี้เป็นโปรแกรม ไม่ใช่ไฟล์ภาพ")
            return done()
        if data[:7] == b"#!/bin/" or data[:2] == b"#!":
            bump(DANGER, "ไฟล์นี้เป็นสคริปต์ ไม่ใช่ไฟล์ภาพ")
            return done()
        bump(WARN, "ตรวจไม่พบลายเซ็นของไฟล์ภาพที่รู้จัก จึงยืนยันชนิดไฟล์ไม่ได้")
        return done()

    # ---------- 2) ไฟล์ SVG ----------
    if fmt == "svg":
        found = _scan_text(data[:600000], SVG_PATTERNS)
        if found:
            bump(DANGER, "ไฟล์ SVG มี" + " และ".join(found[:3]) +
                 " ซึ่งทำงานทันทีเมื่อเปิดในเบราว์เซอร์")
        else:
            bump(WARN, "เป็นไฟล์ SVG ซึ่งเปิดแล้วรันโค้ดได้ ควรเปิดด้วยความระมัดระวัง")
        return done()

    # ---------- 3) ชนิดที่ปลายทางแจ้ง ตรงกับไฟล์จริงหรือไม่ ----------
    if ctype.startswith("image/"):
        declared = ctype.split("/", 1)[1]
        alias = {
            "jpg": "jpeg", "pjpeg": "jpeg", "x-png": "png",
            "svg+xml": "svg", "x-icon": "ico", "vnd.microsoft.icon": "ico",
            "x-ms-bmp": "bmp", "x-bmp": "bmp", "tif": "tiff",
            "heif": "heic", "x-webp": "webp",
        }
        declared = alias.get(declared, declared)
        if declared != fmt and declared not in ("*", ""):
            bump(WARN, f"ปลายทางแจ้งว่าเป็น {declared} แต่ไฟล์จริงเป็น {fmt}")

    # ---------- 4) หาจุดจบของภาพ แล้วตรวจเฉพาะส่วนที่ต่อท้าย ----------
    end, texts = image_end(data, fmt)

    if end is not None and end > len(data):
        if not partial:
            bump(WARN, "ไฟล์ถูกส่งมาไม่ครบตามที่ระบุไว้ในส่วนหัว")
        end = None

    if end is None:
        if not partial:
            bump(WARN, "อ่านโครงสร้างภายในไฟล์ไม่สำเร็จ ไฟล์อาจเสียหาย")
    elif not partial:
        extra = len(data) - end
        tail = data[end:end + 200000] if extra > 0 else b""

        if extra > TRAILER_OK:
            name = _find_embedded(tail, data, end)
            if name:
                bump(DANGER, f"มี{name}ต่อท้ายหลังจุดจบของภาพ "
                             f"ซึ่งเป็นวิธีซ่อนไฟล์ที่พบบ่อย")
            elif tail[:2] == b"MZ" or tail[:4] == b"\x7fELF":
                bump(DANGER, "มีไฟล์โปรแกรมต่อท้ายหลังจุดจบของภาพ")
            else:
                found = _scan_text(tail, SCRIPT_PATTERNS)
                if found:
                    bump(DANGER, "พบ" + " และ".join(found[:2]) +
                                 "ต่อท้ายหลังจุดจบของภาพ")
                elif extra > TRAILER_WARN:
                    bump(WARN, f"มีข้อมูลส่วนเกินท้ายไฟล์ {extra:,} ไบต์ "
                               f"ซึ่งไม่ใช่ส่วนหนึ่งของภาพ")

    # ---------- 5) ข้อความกำกับที่ฝังอยู่ในไฟล์ ----------
    meta = b"".join(texts)[:200000]
    if fmt == "jpeg":
        # เก็บเฉพาะส่วนคำอธิบายและ XMP ซึ่งเป็นข้อความ ไม่ใช่ข้อมูลภาพ
        for m in re.finditer(rb"\xff\xfe(..)", data[:400000], re.S):
            try:
                ln = struct.unpack(">H", m.group(1))[0]
                meta += data[m.end():m.end() + min(ln, 65536)]
            except struct.error:
                pass
        x = data.find(b"<x:xmpmeta")
        if x != -1:
            meta += data[x:x + 65536]

    if meta:
        found = _scan_text(meta, SCRIPT_PATTERNS)
        if found:
            bump(DANGER, "พบ" + " และ".join(found[:2]) + "ฝังอยู่ในข้อความกำกับของไฟล์")

    if partial and level == OK:
        bump(OK, "ตรวจจากส่วนต้นของไฟล์แล้วไม่พบสิ่งผิดปกติ")

    return done()


def summarize(result) -> str:
    return " · ".join(i["text"] for i in result.get("issues", []))
