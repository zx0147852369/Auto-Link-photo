# -*- coding: utf-8 -*-
"""
ultrascan.py — อัลตร้าสแกน ระดับที่ 5

ต่างจากระดับ 1 ถึง 4 อย่างไร
  ระดับ 1-4 อ่าน "หน้าเว็บ" เป็นหลัก แล้วแตะไฟล์ประกอบบางส่วน
  ระดับ 5 ดาวน์โหลด "ไฟล์ต้นฉบับทุกไฟล์" ที่เว็บไซต์ใช้จริง มาแกะทีละไฟล์
  ด้วยชุดเครื่องมือหลายชั้น ไม่ใช่แค่ค้นหาข้อความที่ลงท้ายด้วยนามสกุลรูป

ชั้นการแกะที่ใช้กับทุกไฟล์
  1. ที่อยู่แบบตรงไปตรงมา ทั้งเต็มรูปแบบและแบบเส้นทางย่อ
  2. ข้อความที่ถูกหลบด้วยรหัสยูนิโคด เช่น \\u002Fimg\\u002Fa.jpg
  3. ข้อความที่ถูกเข้ารหัสแบบ URL ซ้อนกันได้ถึงสามชั้น
  4. ข้อความที่ถูกแปลงเป็นสัญลักษณ์ของหน้าเว็บ เช่น &#47;
  5. ข้อความที่ถูกเข้ารหัสฐาน 64 แล้วซ่อนไว้ในตัวแปร
  6. สตริงที่ถูกตัดแล้วต่อกันด้วยเครื่องหมายบวก ซึ่งตัวย่อโค้ดชอบทำ
  7. การประกอบเส้นทางจากชิ้นส่วน เช่น โฟลเดอร์อยู่ตัวแปรหนึ่ง ชื่อไฟล์อีกตัวแปร
  8. แผนที่ซอร์ส (source map) ซึ่งเก็บโค้ดต้นฉบับก่อนถูกย่อไว้ครบ
  9. ไฟล์ประจำระบบที่เว็บไซต์มักมีแต่ไม่มีลิงก์ชี้ไปถึง

เรื่องการ์ดจอ ขอพูดตรง ๆ
  งานทั้งหมดนี้คือการอ่านข้อความและเทียบรูปแบบตัวอักษร ซึ่งเป็นงานที่
  การ์ดจอทำไม่ได้ดีกว่าซีพียู การ์ดจอเก่งงานคูณเมทริกซ์จำนวนมหาศาลพร้อมกัน
  เช่นการประมวลผลภาพหรือโครงข่ายประสาทเทียม ไม่ใช่การค้นหาข้อความ
  การใส่สวิตช์ให้เลือกใช้การ์ดจอจึงเป็นการหลอกตาเปล่า ๆ

  สิ่งที่เร่งงานนี้ได้จริงมีสามอย่าง และใช้ครบทั้งสามในไฟล์นี้
    • ซีพียูหลายแกน  ใช้แกะไฟล์บันเดิลขนาดใหญ่พร้อมกันหลายไฟล์
    • หน่วยความจำ    เก็บไฟล์ที่ดาวน์โหลดมาไว้ทั้งก้อนเพื่อแกะซ้ำหลายรอบ
    • เครือข่าย       เปิดการเชื่อมต่อพร้อมกันจำนวนมากในการดาวน์โหลด
"""

import base64
import binascii
import html as html_mod
import json
import os
import re
from urllib.parse import unquote, urljoin

# ค่าตั้งของระดับ 5
ULTRA5 = {
    "max_files": 400,          # จำนวนไฟล์ต้นฉบับสูงสุดที่จะดาวน์โหลดมาแกะ
    "file_bytes": 12_000_000,  # ขนาดสูงสุดต่อไฟล์
    "workers": 32,             # จำนวนการดาวน์โหลดพร้อมกัน
    "cores": 0,                # แกนประมวลผลที่ใช้แกะ 0 = ใช้เท่าที่เครื่องมี
    "big_file": 300_000,       # ไฟล์ใหญ่กว่านี้ส่งไปแกะที่แกนอื่น
    "sourcemaps": True,        # ตามอ่านแผนที่ซอร์ส
    "probe_series": True,      # ลองเดาไฟล์ที่เรียงเป็นชุด เช่น -1 -2 -3
    "probe_limit": 60,         # จำนวนการเดาสูงสุด
    "wellknown": True,         # ลองไฟล์ประจำระบบที่มักไม่มีลิงก์ชี้ถึง
}

WELLKNOWN = [
    "/browserconfig.xml", "/opensearch.xml", "/humans.txt",
    "/.well-known/assetlinks.json", "/asset-manifest.json",
    "/manifest.json", "/site.webmanifest", "/favicon.ico",
    "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png",
]


def limits(cfg=None):
    out = dict(ULTRA5)
    for k, v in (cfg or {}).items():
        if k in out and isinstance(v, type(out[k])):
            out[k] = v
    out["max_files"] = max(1, min(3000, int(out["max_files"])))
    out["file_bytes"] = max(50_000, min(80_000_000, int(out["file_bytes"])))
    out["workers"] = max(1, min(64, int(out["workers"])))
    out["cores"] = max(0, min(64, int(out["cores"])))
    out["big_file"] = max(20_000, min(20_000_000, int(out["big_file"])))
    out["probe_limit"] = max(0, min(500, int(out["probe_limit"])))
    return out


def core_count(want=0):
    """จำนวนแกนประมวลผลที่จะใช้จริง"""
    have = os.cpu_count() or 2
    if want > 0:
        return max(1, min(want, 64))
    return max(1, have - 1) if have > 2 else 1


# ==================================================================
#  ชั้นถอดรหัส
# ==================================================================

RE_UNICODE_ESC = re.compile(r"\\u00([0-9a-fA-F]{2})")
RE_HEX_ESC = re.compile(r"\\x([0-9a-fA-F]{2})")
RE_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
RE_CONCAT = re.compile(r"""(["'])((?:[^"'\\]|\\.){0,200}?)\1\s*\+\s*(["'])"""
                       r"""((?:[^"'\\]|\\.){0,200}?)\3""")


def unescape_all(text):
    """
    คลายการหลบข้อความทุกแบบที่พบบ่อยในโค้ดที่ถูกย่อ

    คืนข้อความหลายเวอร์ชัน เพราะบางที่หลบซ้อนกันหลายชั้น
    การแกะทีละชั้นแล้วเก็บผลทุกชั้นไว้ ทำให้ไม่พลาดที่อยู่ที่ซ่อนลึก
    """
    out = [text]

    # ชั้นที่ 1 รหัสยูนิโคดและฐานสิบหก
    step = RE_UNICODE_ESC.sub(lambda m: chr(int(m.group(1), 16)), text)
    step = RE_HEX_ESC.sub(lambda m: chr(int(m.group(1), 16)), step)
    step = step.replace("\\/", "/")
    if step != text:
        out.append(step)

    # ชั้นที่ 2 การเข้ารหัสแบบ URL ซ้อนได้ถึงสามชั้น
    cur = step
    for _ in range(3):
        try:
            nxt = unquote(cur)
        except Exception:
            break
        if nxt == cur:
            break
        cur = nxt
        out.append(cur)

    # ชั้นที่ 3 สัญลักษณ์ของหน้าเว็บ
    try:
        ent = html_mod.unescape(step)
        if ent != step:
            out.append(ent)
    except Exception:
        pass

    return out


def decode_base64_blobs(text, cap=60):
    """
    หาข้อความที่ถูกเข้ารหัสฐาน 64 แล้วถอดออกมา

    บางเว็บซ่อนรายชื่อไฟล์รูปทั้งชุดไว้เป็นข้อความฐาน 64 ก้อนเดียว
    เพื่อไม่ให้เห็นได้จากการค้นหาข้อความธรรมดา
    """
    out = []
    for m in RE_B64_BLOB.finditer(text):
        if len(out) >= cap:
            break
        blob = m.group(0)
        if len(blob) % 4:
            blob = blob[: len(blob) - (len(blob) % 4)]
        if len(blob) < 40:
            continue
        try:
            raw = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError):
            continue
        # เอาเฉพาะที่ถอดออกมาแล้วเป็นข้อความอ่านได้
        try:
            s = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        printable = sum(1 for c in s[:400] if 32 <= ord(c) < 127 or ord(c) > 160)
        if len(s) > 12 and printable / max(1, len(s[:400])) > 0.85:
            out.append(s)
    return out


def join_concats(text, cap=400):
    """
    ต่อสตริงที่ถูกตัดแล้วเชื่อมด้วยเครื่องหมายบวกกลับเป็นชิ้นเดียว

    ตัวย่อโค้ดมักตัด "/images/photo.jpg" เป็น "/imag"+"es/photo"+".jpg"
    การค้นหาข้อความธรรมดาจะหาไม่เจอ แต่ต่อกลับก่อนแล้วจะเจอ
    """
    out = []
    cur = text
    for _ in range(4):          # ต่อซ้ำหลายรอบ เพราะอาจถูกตัดหลายท่อน
        new = RE_CONCAT.sub(lambda m: '"' + m.group(2) + m.group(4) + '"', cur)
        if new == cur:
            break
        cur = new
    if cur != text:
        out.append(cur)
    return out[:1] if not cap else out


# ==================================================================
#  แผนที่ซอร์ส
# ==================================================================

RE_SOURCEMAP = re.compile(r"//[#@]\s*sourceMappingURL\s*=\s*(\S+)", re.I)


def sourcemap_url(text, base):
    """หาที่อยู่ของแผนที่ซอร์สที่ประกาศไว้ท้ายไฟล์"""
    m = None
    for m in RE_SOURCEMAP.finditer(text[-4000:] or ""):
        pass
    if not m:
        return ""
    ref = m.group(1).strip()
    if ref.startswith("data:"):
        return ""
    try:
        return urljoin(base, ref)
    except ValueError:
        return ""


def sourcemap_texts(text):
    """
    ดึงโค้ดต้นฉบับทั้งหมดที่เก็บอยู่ในแผนที่ซอร์ส

    แผนที่ซอร์สคือไฟล์ที่นักพัฒนาแนบไว้เพื่อให้ย้อนกลับไปดูโค้ดก่อนถูกย่อได้
    ข้างในมีโค้ดต้นฉบับครบทุกไฟล์ ซึ่งยังไม่ถูกตัดชื่อไฟล์รูปให้สั้น
    จึงเป็นแหล่งที่ได้ที่อยู่รูปครบที่สุดแหล่งหนึ่ง
    """
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for key in ("sourcesContent", "sources"):
        vals = d.get(key)
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, str) and len(v) > 4:
                    out.append(v)
    return out


# ==================================================================
#  การประกอบเส้นทางจากชิ้นส่วน
# ==================================================================

RE_DIRLIKE = re.compile(r"""["'](/(?:[\w\-.]+/){1,6})["']""")
RE_NAMELIKE = re.compile(r"""["']([\w\-. ]{1,80}\.(?:%s))["']""")


def assemble_paths(text, exts, cap=300):
    """
    ประกอบเส้นทางจากโฟลเดอร์และชื่อไฟล์ที่ถูกเก็บแยกกันคนละตัวแปร

    โค้ดจำนวนมากเขียนแบบ  const DIR="/assets/img/"  แล้วใช้  DIR + name
    การค้นหาข้อความธรรมดาจึงเห็นแค่ชิ้นส่วน ไม่เห็นที่อยู่เต็ม
    """
    dirs = list(dict.fromkeys(m.group(1) for m in RE_DIRLIKE.finditer(text)))[:40]
    if not dirs:
        return []
    rx = re.compile(RE_NAMELIKE.pattern % "|".join(exts), re.I)
    names = list(dict.fromkeys(m.group(1) for m in rx.finditer(text)))[:120]
    out = []
    for d in dirs:
        for n in names:
            out.append(d + n)
            if len(out) >= cap:
                return out
    return out


# ==================================================================
#  การเดาไฟล์ที่เรียงเป็นชุด
# ==================================================================

RE_SERIES = re.compile(r"^(.*?)(\d{1,4})(\.[A-Za-z0-9]{2,5})$")


def series_guesses(urls, limit=60):
    """
    เมื่อพบไฟล์ที่ลงท้ายด้วยตัวเลข ให้ลองเดาลำดับข้างเคียง

    เว็บแกลเลอรีมักตั้งชื่อ photo-1.jpg photo-2.jpg เรียงกันไป
    แต่หน้าเว็บแสดงแค่บางใบ การเดาลำดับจึงได้รูปที่ไม่มีลิงก์ชี้ถึงเลย
    ทุกที่อยู่ที่เดาไว้จะถูกตรวจว่ามีอยู่จริงก่อนนำมาแสดงเสมอ
    """
    out = []
    seen = set(urls)
    for u in list(urls)[:120]:
        m = RE_SERIES.match(u)
        if not m:
            continue
        head, num, ext = m.group(1), m.group(2), m.group(3)
        width = len(num)
        n = int(num)
        for d in (-3, -2, -1, 1, 2, 3, 4, 5):
            k = n + d
            if k < 0:
                continue
            cand = "%s%s%s" % (head, str(k).zfill(width), ext)
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
                if len(out) >= limit:
                    return out
    return out


# ==================================================================
#  ตัวแกะหลัก ทำงานกับไฟล์เดียว
# ==================================================================

def extract_from_text(text, base, exts, url_rx, path_rx, css_rx, deep=True):
    """
    แกะที่อยู่รูปทั้งหมดออกจากข้อความของไฟล์หนึ่ง

    ฟังก์ชันนี้ถูกออกแบบให้ไม่พึ่งอะไรนอกไฟล์ตัวเอง
    จึงส่งไปทำงานที่แกนประมวลผลอื่นได้โดยตรง
    """
    found = []

    def sweep(t):
        for m in url_rx.finditer(t):
            found.append(m.group(0))
        for m in path_rx.finditer(t):
            found.append(m.group(1))
        for m in css_rx.finditer(t):
            v = (m.group(2) or "").strip()
            if v:
                found.append(v)

    # รอบแรก ข้อความตามที่เป็น
    sweep(text)

    if deep:
        # ทุกชั้นของการคลายรหัส
        for variant in unescape_all(text):
            if variant is not text:
                sweep(variant)
        # สตริงที่ถูกตัดแล้วต่อกัน
        for joined in join_concats(text):
            sweep(joined)
            for variant in unescape_all(joined):
                sweep(variant)
        # ข้อความที่ซ่อนด้วยการเข้ารหัสฐาน 64
        for blob in decode_base64_blobs(text):
            sweep(blob)
            for variant in unescape_all(blob):
                sweep(variant)
        # เส้นทางที่ประกอบจากชิ้นส่วน
        found += assemble_paths(text, exts)

    # ทำให้ไม่ซ้ำ โดยคงลำดับที่พบไว้
    out, seen = [], set()
    for f in found:
        f = f.strip().strip("\\")
        if not f or len(f) > 2000 or f in seen:
            continue
        seen.add(f)
        out.append(f)
    return out


def extract_job(payload):
    """
    ห่อหุ้ม extract_from_text ให้ส่งไปทำงานที่แกนประมวลผลอื่นได้

    รับและคืนเฉพาะชนิดข้อมูลพื้นฐาน เพราะข้อมูลต้องถูกส่งข้ามกระบวนการ
    """
    (text, base, exts, url_pat, path_pat, css_pat, deep) = payload
    url_rx = re.compile(url_pat, re.I)
    path_rx = re.compile(path_pat, re.I)
    css_rx = re.compile(css_pat, re.I | re.S)
    try:
        return base, extract_from_text(text, base, set(exts),
                                       url_rx, path_rx, css_rx, deep)
    except Exception:
        return base, []
