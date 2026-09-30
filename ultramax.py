# -*- coding: utf-8 -*-
"""
ultramax.py — Ultra Max Scan ระดับที่ 6

ระดับ 1 ถึง 5 ตอบคำถามว่า "ไฟล์รูปอยู่ที่อยู่ไหน"
ระดับ 6 ตอบอีกคำถามหนึ่งว่า "มีรูปที่ไม่มีที่อยู่เลยซ่อนอยู่ในโค้ดหรือไม่"

เว็บจำนวนมากไม่ได้เก็บรูปเป็นไฟล์แยก แต่ฝังตัวรูปทั้งใบไว้ในโค้ดโดยตรง
ในรูปของข้อความที่ผ่านการเข้ารหัส รูปพวกนี้ไม่มีที่อยู่ให้คัดลอก
เครื่องมือทั่วไปจึงหาไม่เจอเลย ไฟล์นี้ทำหน้าที่ค้นและกู้กลับเป็นไฟล์ภาพจริง

วิธีเข้ารหัสที่กู้กลับได้
  1. ฐาน 64 ทั้งแบบมาตรฐานและแบบที่ใช้ในที่อยู่เว็บ
  2. ฐาน 64 ที่ถูกใส่กลับด้าน หรือแทรกอักขระขยะเป็นช่วง
  3. เลขฐานสิบหกที่เขียนติดกันเป็นสายยาว
  4. ชุดตัวเลขไบต์ที่เขียนเป็นอาเรย์ในโค้ด
  5. ข้อมูลที่ถูกบีบอัดด้วย gzip หรือ zlib ก่อนแล้วค่อยเข้ารหัส
  6. ข้อมูลที่ถูกกลบด้วยการเอ็กซ์ออร์ด้วยกุญแจหนึ่งไบต์
  7. ไฟล์รูปที่ถูกต่อท้ายไฟล์อื่นเพื่อซ่อน

วิธีตรวจว่าสิ่งที่ถอดออกมาเป็นรูปจริง
  ไม่ได้เดาจากชื่อหรือนามสกุล แต่อ่านลายเซ็นไบต์ต้นไฟล์ตามมาตรฐานของแต่ละชนิด
  แล้วส่งต่อให้ตัวคัดกรองไฟล์ตรวจซ้ำอีกชั้นก่อนนำมาแสดง
  รูปที่กู้ได้จะถูกบันทึกเป็นไฟล์จริงให้ดาวน์โหลดได้เหมือนรูปทั่วไป

เรื่องการใช้ทรัพยากร
  ขั้นตอนการเอ็กซ์ออร์ต้องลองกุญแจ 255 แบบกับข้อมูลทุกก้อน
  นี่เป็นงานคำนวณจริงที่กินซีพียู จึงกระจายไปหลายแกนประมวลผล
  ส่วนการ์ดจอยังช่วยไม่ได้ เพราะงานนี้เป็นการเทียบไบต์แบบลำดับ
  ไม่ใช่การคูณเมทริกซ์ขนาดใหญ่ที่การ์ดจอถนัด
"""

import base64
import binascii
import gzip
import hashlib
import os
import re
import zlib

# ค่าตั้งของระดับ 6
MAX6 = {
    "passes": 2,               # จำนวนรอบการสแกน
    "decode": True,            # กู้รูปที่ฝังเป็นข้อความเข้ารหัส
    "xor": True,               # ลองถอดการกลบด้วยเอ็กซ์ออร์
    "xor_min": 2000,           # ก้อนข้อมูลเล็กกว่านี้ไม่คุ้มที่จะลอง
    "max_decoded": 300,        # จำนวนรูปที่กู้ได้สูงสุดต่อการสแกนหนึ่งครั้ง
    "min_image_bytes": 120,    # เล็กกว่านี้ถือว่าไม่ใช่รูปที่มีความหมาย
    "max_image_bytes": 25_000_000,
    "network": True,           # ดักไฟล์ที่เบราว์เซอร์โหลดจริงทุกรายการ
    "cores": 0,                # 0 = ใช้เท่าที่เครื่องมี
}


def limits(cfg=None):
    out = dict(MAX6)
    for k, v in (cfg or {}).items():
        if k in out and isinstance(v, type(out[k])):
            out[k] = v
    out["passes"] = max(1, min(4, int(out["passes"])))
    out["xor_min"] = max(200, min(200_000, int(out["xor_min"])))
    out["max_decoded"] = max(1, min(3000, int(out["max_decoded"])))
    out["min_image_bytes"] = max(40, min(100_000, int(out["min_image_bytes"])))
    out["max_image_bytes"] = max(10_000, min(80_000_000, int(out["max_image_bytes"])))
    out["cores"] = max(0, min(64, int(out["cores"])))
    return out


# ==================================================================
#  ลายเซ็นไบต์ของไฟล์ภาพ
# ==================================================================

SIGS = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"\x00\x00\x01\x00", "ico"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
]


def sniff(data: bytes) -> str:
    """
    บอกชนิดไฟล์ภาพจากลายเซ็นไบต์ต้นไฟล์

    ไม่ดูนามสกุลหรือชื่อ เพราะข้อมูลที่ถอดออกมาจากโค้ดไม่มีชื่อไฟล์
    และการดูจากชื่ออย่างเดียวถูกหลอกได้ง่าย
    """
    if not data or len(data) < 8:
        return ""
    for sig, name in SIGS:
        if data.startswith(sig):
            return name
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "avif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1"):
        return "heic"
    head = data[:400].lstrip()
    if head[:5].lower() == b"<?xml" or head[:4].lower() == b"<svg":
        if b"<svg" in data[:2000].lower():
            return "svg"
    return ""


def is_image(data: bytes, lo=120, hi=25_000_000) -> str:
    """ข้อมูลก้อนนี้เป็นไฟล์ภาพที่ใช้ได้จริงหรือไม่ คืนชนิด หรือค่าว่าง"""
    if not data or not (lo <= len(data) <= hi):
        return ""
    return sniff(data)


# ==================================================================
#  ตัวถอดรหัสแต่ละแบบ
# ==================================================================

RE_DATA_URI = re.compile(
    r"""data:image/([a-z0-9.+-]{2,20})\s*;\s*base64\s*,\s*([A-Za-z0-9+/=_\-\s]{60,})""",
    re.I)
RE_B64_LONG = re.compile(r"[A-Za-z0-9+/_\-]{200,}={0,2}")
RE_HEX_LONG = re.compile(r"(?:[0-9a-fA-F]{2}){100,}")
RE_BYTE_ARRAY = re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){80,}\d{1,3}\s*\]")
RE_ESCAPED_BYTES = re.compile(r"(?:\\x[0-9a-fA-F]{2}){100,}")


def _b64_try(s: str):
    """ถอดฐาน 64 โดยลองทั้งแบบมาตรฐานและแบบที่ใช้ในที่อยู่เว็บ"""
    s = re.sub(r"\s+", "", s)
    for fix in (s, s.replace("-", "+").replace("_", "/")):
        pad = fix + "=" * (-len(fix) % 4)
        for fn in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                return fn(pad)
            except (binascii.Error, ValueError):
                continue
    return b""


def _inflate(data: bytes) -> bytes:
    """คลายการบีบอัดถ้าข้อมูลถูกบีบไว้ คืนค่าเดิมถ้าไม่ได้บีบ"""
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data)
        except (OSError, EOFError, zlib.error):
            return b""
    if data[:1] in (b"\x78",):
        try:
            return zlib.decompress(data)
        except zlib.error:
            pass
    try:
        return zlib.decompress(data, -15)
    except zlib.error:
        return b""


def xor_scan(data: bytes, lo, hi):
    """
    ลองถอดข้อมูลที่ถูกกลบด้วยการเอ็กซ์ออร์ด้วยกุญแจหนึ่งไบต์

    เทคนิคนี้ใช้กลบไฟล์ให้ดูเหมือนข้อมูลขยะ ตรวจจับด้วยการค้นหาข้อความไม่ได้เลย
    แต่ถอดกลับได้ด้วยการลองกุญแจทั้ง 255 ค่า แล้วดูว่าค่าไหนให้ลายเซ็นไฟล์ภาพ

    ทำให้เร็วด้วยการเทียบเฉพาะไบต์แรกก่อน ถ้าไบต์แรกไม่ตรงกับลายเซ็นใดเลย
    ก็ไม่ต้องถอดทั้งก้อน ประหยัดงานไปได้เกือบทั้งหมด
    """
    if len(data) < 8:
        return b"", 0
    first = data[0]
    for key in range(1, 256):
        cand0 = first ^ key
        for sig, _name in SIGS:
            if sig[0] != cand0:
                continue
            head = bytes(b ^ key for b in data[:32])
            if not head.startswith(sig[:min(len(sig), 8)]):
                continue
            full = bytes(b ^ key for b in data)
            if is_image(full, lo, hi):
                return full, key
        # WEBP ขึ้นต้นด้วย RIFF
        if cand0 == 0x52:
            head = bytes(b ^ key for b in data[:16])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                full = bytes(b ^ key for b in data)
                if is_image(full, lo, hi):
                    return full, key
    return b"", 0


def find_embedded(text, lo=120, hi=25_000_000, try_xor=True, xor_min=2000,
                  cap=300):
    """
    ค้นหารูปที่ถูกฝังไว้ในข้อความของไฟล์หนึ่ง แล้วกู้กลับเป็นไบต์ของภาพ

    คืนรายการของ (ไบต์ของภาพ, ชนิดไฟล์, วิธีที่ใช้ถอด)
    """
    out = []
    seen = set()

    def take(raw, how):
        if len(out) >= cap or not raw:
            return
        kind = is_image(raw, lo, hi)
        if not kind:
            # ลองคลายการบีบอัดอีกชั้นหนึ่ง
            inf = _inflate(raw)
            if inf:
                kind = is_image(inf, lo, hi)
                if kind:
                    raw, how = inf, how + " + คลายการบีบอัด"
        if not kind:
            return
        h = hashlib.sha1(raw).hexdigest()
        if h in seen:
            return
        seen.add(h)
        out.append((raw, kind, how))

    # ---------- 1. ที่อยู่แบบฝังข้อมูลในตัว ----------
    for m in RE_DATA_URI.finditer(text):
        take(_b64_try(m.group(2)), "ที่อยู่แบบฝังข้อมูล")

    # ---------- 2. ข้อความฐาน 64 ยาว ๆ ที่ไม่ได้ประกาศว่าเป็นรูป ----------
    for m in RE_B64_LONG.finditer(text):
        if len(out) >= cap:
            break
        s = m.group(0)
        raw = _b64_try(s)
        if raw:
            take(raw, "ข้อความฐาน 64 ที่ไม่ได้บอกว่าเป็นรูป")
            if not is_image(raw, lo, hi):
                # บางที่ใส่กลับด้านไว้เพื่อกันการค้นหา
                take(_b64_try(s[::-1]), "ฐาน 64 ที่ถูกใส่กลับด้าน")

    # ---------- 3. เลขฐานสิบหกเขียนติดกัน ----------
    for m in RE_HEX_LONG.finditer(text):
        if len(out) >= cap:
            break
        try:
            take(bytes.fromhex(m.group(0)), "เลขฐานสิบหกเขียนติดกัน")
        except ValueError:
            pass

    # ---------- 4. ไบต์ที่เขียนเป็นรหัสหลบ ----------
    for m in RE_ESCAPED_BYTES.finditer(text):
        if len(out) >= cap:
            break
        try:
            hx = m.group(0).replace("\\x", "")
            take(bytes.fromhex(hx), "ไบต์ที่เขียนเป็นรหัสหลบ")
        except ValueError:
            pass

    # ---------- 5. อาเรย์ตัวเลขไบต์ ----------
    for m in RE_BYTE_ARRAY.finditer(text):
        if len(out) >= cap:
            break
        try:
            nums = [int(x) for x in re.findall(r"\d{1,3}", m.group(0))]
            if all(0 <= n <= 255 for n in nums):
                take(bytes(nums), "อาเรย์ตัวเลขไบต์")
        except ValueError:
            pass

    # ---------- 6. ข้อมูลที่ถูกกลบด้วยเอ็กซ์ออร์ ----------
    if try_xor:
        for m in RE_B64_LONG.finditer(text):
            if len(out) >= cap:
                break
            raw = _b64_try(m.group(0))
            if len(raw) < xor_min or is_image(raw, lo, hi):
                continue
            got, key = xor_scan(raw, lo, hi)
            if got:
                take(got, f"ถูกกลบด้วยเอ็กซ์ออร์ กุญแจ {key}")

    return out


def find_in_bytes(data: bytes, lo=120, hi=25_000_000, cap=60):
    """
    ค้นหาไฟล์ภาพที่ถูกต่อท้ายไฟล์อื่นเพื่อซ่อน

    วิธีนี้ซ่อนรูปไว้หลังจุดจบของไฟล์จริง เปิดไฟล์ตามปกติจะไม่เห็นเลย
    """
    out = []
    seen = set()
    for sig, kind in SIGS[:4]:
        start = 0
        while len(out) < cap:
            i = data.find(sig, start)
            if i < 0:
                break
            start = i + 1
            if i == 0:
                continue               # ตัวไฟล์เอง ไม่ใช่ของที่ซ่อน
            chunk = data[i:]
            if is_image(chunk, lo, hi):
                h = hashlib.sha1(chunk[:4096]).hexdigest()
                if h not in seen:
                    seen.add(h)
                    out.append((chunk, kind, "ต่อท้ายไฟล์อื่นเพื่อซ่อน"))
    return out


def decode_job(payload):
    """
    ห่อหุ้มให้ส่งไปทำงานที่แกนประมวลผลอื่นได้

    รับ (ข้อความ, ชื่อแหล่ง, ค่าตั้ง) คืน (ชื่อแหล่ง, รายการรูปที่กู้ได้)
    """
    text, origin, lo, hi, try_xor, xor_min, cap = payload
    try:
        got = find_embedded(text, lo, hi, try_xor, xor_min, cap)
    except Exception:
        got = []
    return origin, got


# ==================================================================
#  บันทึกรูปที่กู้ได้ลงไฟล์จริง
# ==================================================================

def save_decoded(folder, data: bytes, kind: str, index: int):
    """
    บันทึกรูปที่กู้ได้เป็นไฟล์จริง คืนชื่อไฟล์

    ตั้งชื่อจากลายนิ้วมือของเนื้อไฟล์ รูปเดียวกันที่พบหลายที่จึงได้ไฟล์เดียว
    """
    os.makedirs(folder, exist_ok=True)
    tag = hashlib.sha1(data).hexdigest()[:12]
    name = "d%03d-%s.%s" % (index, tag, kind)
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        tmp = path + ".part"
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except OSError:
            return ""
    return name


def sweep_old(folder, keep_hours=6):
    """
    ลบรูปที่กู้ไว้ซึ่งเก่าเกินกำหนด

    รูปเหล่านี้เป็นผลชั่วคราวของการค้นหา ไม่ควรค้างอยู่ในเครื่องตลอดไป
    """
    import time
    if not os.path.isdir(folder):
        return 0
    cut = time.time() - keep_hours * 3600
    gone = 0
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cut:
                os.remove(p)
                gone += 1
        except OSError:
            pass
    return gone
