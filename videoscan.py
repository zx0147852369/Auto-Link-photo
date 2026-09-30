# -*- coding: utf-8 -*-
"""
videoscan.py — ค้นหาและถอดรหัสวิดีโอ

วิดีโอบนเว็บต่างจากรูปภาพโดยสิ้นเชิง รูปคือไฟล์เดียวจบ แต่วิดีโอสมัยใหม่
ถูกหั่นเป็นชิ้นย่อยหลักพันชิ้น แล้วมีไฟล์รายการกำกับว่าชิ้นไหนมาก่อนหลัง
การ "หาวิดีโอ" จึงไม่ใช่การหาไฟล์เดียว แต่คือการหาไฟล์รายการ
แล้วไล่อ่านว่ามันชี้ไปที่ชิ้นไหนบ้าง

รูปแบบที่รองรับ
  1. ไฟล์เดียวจบ  mp4 webm mov mkv ogv m4v flv
  2. HLS          ไฟล์รายการ m3u8 ซึ่งเป็นมาตรฐานที่ใช้กันมากที่สุด
  3. DASH         ไฟล์รายการ mpd ซึ่งเป็นมาตรฐานอีกตัวที่ใช้คู่กัน
  4. ฝังในโค้ด    ไบต์ของวิดีโอถูกเขียนปนอยู่ในโค้ดแบบเดียวกับรูป

เรื่องการเข้ารหัส ต้องแยกให้ชัดว่ามีสองแบบที่ต่างกันสิ้นเชิง

  แบบที่ถอดได้   HLS แบบ AES-128 ซึ่งเป็นส่วนหนึ่งของมาตรฐาน
                 กุญแจถูกวางไว้ให้ดาวน์โหลดตามที่อยู่ที่ระบุในไฟล์รายการ
                 ใครเปิดดูวิดีโอได้ก็หยิบกุญแจได้ ไม่ใช่การเจาะระบบ
                 จุดประสงค์ของมันคือกันคนที่ไม่ได้ผ่านหน้าเว็บ ไม่ใช่กันการทำสำเนา

  แบบที่ถอดไม่ได้ ระบบจัดการสิทธิ์ดิจิทัล เช่น Widevine PlayReady FairPlay
                 กุญแจไม่เคยออกมาถึงหน้าเว็บ อยู่ในส่วนที่ปิดผนึกของเบราว์เซอร์
                 ระบบนี้จะตรวจพบแล้วแจ้งว่าทำไม่ได้ ไม่พยายามหลบเลี่ยง
                 เพราะการหลบเลี่ยงมาตรการคุ้มครองลิขสิทธิ์ผิดกฎหมายในหลายประเทศ
"""

import base64
import binascii
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

# ==================================================================
#  ค่าตั้ง
# ==================================================================

VIDEO_EXTS = {
    "mp4", "m4v", "webm", "mov", "mkv", "ogv", "ogg", "avi", "flv",
    "wmv", "mpg", "mpeg", "3gp", "ts", "m2ts",
}
LIST_EXTS = {"m3u8", "mpd"}

CFG = {
    "max_lists": 40,          # จำนวนไฟล์รายการที่ตามอ่านสูงสุด
    "max_variants": 24,       # จำนวนความละเอียดต่อหนึ่งรายการ
    "max_segments": 8000,     # จำนวนชิ้นย่อยสูงสุดต่อหนึ่งวิดีโอ
    "workers": 16,
    "decrypt": True,          # ถอดรหัส HLS แบบ AES-128
    "probe": True,            # ยิงตรวจว่าไฟล์มีอยู่จริง
    "embedded": True,         # ค้นวิดีโอที่ฝังไบต์ไว้ในโค้ด
    "max_embedded": 40,
    "min_bytes": 20_000,      # เล็กกว่านี้ไม่ถือว่าเป็นวิดีโอที่มีความหมาย
    "max_bytes": 400_000_000,
}


def limits(cfg=None):
    out = dict(CFG)
    for k, v in (cfg or {}).items():
        if k in out and isinstance(v, type(out[k])):
            out[k] = v
    out["max_lists"] = max(1, min(500, int(out["max_lists"])))
    out["max_variants"] = max(1, min(200, int(out["max_variants"])))
    out["max_segments"] = max(1, min(200_000, int(out["max_segments"])))
    out["workers"] = max(1, min(64, int(out["workers"])))
    out["max_embedded"] = max(1, min(500, int(out["max_embedded"])))
    out["min_bytes"] = max(1_000, min(50_000_000, int(out["min_bytes"])))
    return out


# ==================================================================
#  ลายเซ็นไบต์ของไฟล์วิดีโอ
# ==================================================================

def sniff(data: bytes) -> str:
    """
    บอกชนิดไฟล์วิดีโอจากไบต์ต้นไฟล์

    ใช้ตอนแกะวิดีโอที่ถูกฝังไว้ในโค้ด ซึ่งไม่มีชื่อไฟล์ให้ดู
    """
    if not data or len(data) < 12:
        return ""
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand[:3] in (b"qt ", b"qt"):
            return "mov"
        if brand in (b"M4A ", b"M4B "):
            return "m4a"
        return "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        # ทั้ง webm และ mkv ใช้โครงเดียวกัน ต่างกันที่ชื่อรูปแบบข้างใน
        head = data[:600]
        if b"webm" in head:
            return "webm"
        return "mkv"
    if data[:3] == b"FLV":
        return "flv"
    if data[:4] == b"OggS":
        return "ogv"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "avi"
    if data[:1] == b"\x47" and len(data) > 188 and data[188:189] == b"\x47":
        return "ts"          # MPEG-TS ขึ้นต้นทุก 188 ไบต์ด้วยค่าเดิม
    return ""


def is_video(data: bytes, lo=20_000, hi=400_000_000) -> str:
    if not data or not (lo <= len(data) <= hi):
        return ""
    return sniff(data)


# ==================================================================
#  ค้นหาที่อยู่วิดีโอจากข้อความ
# ==================================================================

RE_VIDEO_URL = re.compile(
    r"""(?:https?:)?\\?/\\?/[^\s"'<>()\\]+?\.(?:%s)(?:\?[^\s"'<>()]*)?"""
    % "|".join(sorted(VIDEO_EXTS | LIST_EXTS)), re.I)
RE_VIDEO_PATH = re.compile(
    r"""["'](\\?/[^"'\s<>]+?\.(?:%s)(?:\?[^"']*)?)["']"""
    % "|".join(sorted(VIDEO_EXTS | LIST_EXTS)), re.I)
RE_DATA_VIDEO = re.compile(
    r"""data:video/([a-z0-9.+-]{2,20})\s*;\s*base64\s*,\s*([A-Za-z0-9+/=_\-\s]{200,})""",
    re.I)


def kind_of(url: str) -> str:
    """บอกว่าที่อยู่นี้เป็นไฟล์เดียวจบ หรือเป็นไฟล์รายการแบบใด"""
    path = urlparse((url or "").split("?")[0]).path.lower()
    ext = path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext == "m3u8":
        return "hls"
    if ext == "mpd":
        return "dash"
    if ext in VIDEO_EXTS:
        return "file"
    return ""


def find_urls(text, base, cap=400):
    """
    ค้นที่อยู่วิดีโอทุกแบบจากข้อความหนึ่งก้อน

    คืนรายการ (ที่อยู่เต็ม, ชนิด) โดยไม่ซ้ำกัน
    """
    out, seen = [], set()

    def take(raw):
        if not raw or len(out) >= cap:
            return
        u = raw.strip().strip("'\"")
        u = u.replace("\\/", "/")
        u = re.sub(r"\\u002[fF]", "/", u)
        if u.startswith("//"):
            u = "https:" + u
        try:
            full = urljoin(base, u).split("#")[0]
        except ValueError:
            return
        if urlparse(full).scheme not in ("http", "https"):
            return
        k = kind_of(full)
        if not k or full in seen:
            return
        seen.add(full)
        out.append((full, k))

    for m in RE_VIDEO_URL.finditer(text or ""):
        take(m.group(0))
    for m in RE_VIDEO_PATH.finditer(text or ""):
        take(m.group(1))
    return out


def find_embedded(text, lo=20_000, hi=400_000_000, cap=40):
    """
    ค้นวิดีโอที่ถูกฝังไบต์ไว้ในโค้ดโดยตรง

    พบไม่บ่อยเท่ารูป เพราะวิดีโอมีขนาดใหญ่เกินกว่าจะฝังได้สะดวก
    แต่คลิปสั้นอย่างภาพเคลื่อนไหวประกอบหน้าเว็บก็ยังพบอยู่
    คืนรายการ (ไบต์, ชนิด, วิธีที่ใช้ถอด, ตำแหน่ง)
    """
    out, seen = [], set()
    for m in RE_DATA_VIDEO.finditer(text or ""):
        if len(out) >= cap:
            break
        raw = _b64(m.group(2))
        kind = is_video(raw, lo, hi)
        if not kind:
            continue
        import hashlib
        h = hashlib.sha1(raw[:65536]).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        out.append((raw, kind, "ที่อยู่แบบฝังข้อมูล", (m.start(), m.end() - m.start())))
    return out


def _b64(s: str) -> bytes:
    s = re.sub(r"\s+", "", s or "")
    for fix in (s, s.replace("-", "+").replace("_", "/")):
        pad = fix + "=" * (-len(fix) % 4)
        try:
            return base64.b64decode(pad)
        except (binascii.Error, ValueError):
            continue
    return b""


# ==================================================================
#  อ่านไฟล์รายการแบบ HLS
# ==================================================================

# วิธีเข้ารหัสที่ไม่ใช่การคุ้มครองลิขสิทธิ์ ถอดได้ตามมาตรฐาน
OPEN_METHODS = {"AES-128", "AES-256"}

# ตัวบ่งชี้ว่าเป็นระบบจัดการสิทธิ์ดิจิทัล ซึ่งจะไม่ยุ่งด้วย
DRM_MARKS = (
    "urn:uuid:edef8ba9",              # Widevine
    "urn:uuid:9a04f079",              # PlayReady
    "com.apple.streamingkeydelivery",  # FairPlay
    "urn:uuid:f239e769",              # Adobe Primetime
    "skd://",
)
DRM_METHODS = {"SAMPLE-AES", "SAMPLE-AES-CTR", "SAMPLE-AES-CENC"}


def _attrs(line: str):
    """อ่านคู่ชื่อกับค่าในบรรทัดแท็กของไฟล์รายการ"""
    out = {}
    for m in re.finditer(r'([A-Z0-9-]+)=("([^"]*)"|[^,]*)', line):
        out[m.group(1)] = m.group(3) if m.group(3) is not None else m.group(2)
    return out


def parse_master(text, base, cap=24):
    """
    อ่านไฟล์รายการหลักของ HLS ซึ่งไม่มีตัววิดีโอ มีแต่รายชื่อความละเอียด

    คืนรายการความละเอียด เรียงจากคุณภาพสูงไปต่ำ
    """
    out = []
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        a = _attrs(line)
        url = ""
        for j in range(i + 1, min(i + 4, len(lines))):
            nxt = lines[j].strip()
            if nxt and not nxt.startswith("#"):
                url = urljoin(base, nxt)
                break
        if not url:
            continue
        try:
            bw = int(a.get("BANDWIDTH") or a.get("AVERAGE-BANDWIDTH") or 0)
        except ValueError:
            bw = 0
        out.append({
            "url": url,
            "bandwidth": bw,
            "resolution": a.get("RESOLUTION", ""),
            "codecs": a.get("CODECS", ""),
        })
    out.sort(key=lambda x: x["bandwidth"], reverse=True)
    return out[:cap]


def parse_media(text, base, cap=8000):
    """
    อ่านไฟล์รายการของความละเอียดหนึ่ง ซึ่งชี้ไปยังชิ้นย่อยทั้งหมด

    คืน dict ที่มีรายชื่อชิ้นย่อย ข้อมูลกุญแจ และสถานะการคุ้มครองลิขสิทธิ์
    """
    segs, keys = [], []
    cur = None
    seq = 0
    drm = ""
    total = 0.0
    dur = 0.0

    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("#EXT-X-MEDIA-SEQUENCE"):
            try:
                seq = int(line.split(":", 1)[1])
            except (ValueError, IndexError):
                pass
            continue

        if line.startswith(("#EXT-X-KEY", "#EXT-X-SESSION-KEY")):
            a = _attrs(line)
            method = (a.get("METHOD") or "").upper()
            fmt = a.get("KEYFORMAT", "")
            uri = a.get("URI", "")
            blob = (fmt + " " + uri).lower()
            if method in DRM_METHODS or any(d in blob for d in DRM_MARKS):
                drm = method or "DRM"
                cur = None
                continue
            if method == "NONE":
                cur = None
                continue
            if method in OPEN_METHODS and uri:
                cur = {
                    "method": method,
                    "uri": urljoin(base, uri),
                    "iv": a.get("IV", ""),
                }
                if cur not in keys:
                    keys.append(cur)
            continue

        if line.startswith("#EXTINF"):
            try:
                dur = float(line.split(":", 1)[1].split(",")[0])
            except (ValueError, IndexError):
                dur = 0.0
            continue

        if line.startswith("#EXT-X-MAP"):
            a = _attrs(line)
            if a.get("URI"):
                segs.append({"url": urljoin(base, a["URI"]), "key": cur,
                             "seq": seq, "dur": 0.0, "init": True})
            continue

        if line.startswith("#"):
            continue

        if len(segs) < cap:
            segs.append({"url": urljoin(base, line), "key": cur,
                         "seq": seq + len([s for s in segs if not s.get("init")]),
                         "dur": dur, "init": False})
            total += dur
            dur = 0.0

    return {"segments": segs, "keys": keys, "drm": drm,
            "duration": round(total, 2), "count": len(segs)}


def is_master(text) -> bool:
    return "#EXT-X-STREAM-INF" in (text or "")


# ==================================================================
#  อ่านไฟล์รายการแบบ DASH
# ==================================================================

def parse_mpd(text, base, cap=24):
    """
    อ่านไฟล์รายการแบบ DASH

    โครงสร้างซับซ้อนกว่า HLS มาก และมีหลายวิธีในการระบุชิ้นย่อย
    ที่นี่รองรับสองแบบที่พบบ่อยที่สุด คือระบุที่อยู่ตรง ๆ กับใช้แม่แบบเลขลำดับ
    คืน dict ที่มีรายการความละเอียดและสถานะการคุ้มครองลิขสิทธิ์
    """
    try:
        root = ET.fromstring((text or "").encode("utf-8", "ignore"))
    except ET.ParseError:
        return {"variants": [], "drm": "", "error": "อ่านไฟล์รายการไม่ได้"}

    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    blob = (text or "").lower()
    drm = ""
    if any(d in blob for d in DRM_MARKS) or "contentprotection" in blob:
        # มีการประกาศการคุ้มครองไว้ ต้องดูให้ชัดว่าเป็นชนิดที่ถอดไม่ได้จริง
        if any(d in blob for d in DRM_MARKS):
            drm = "DRM"

    def find(el, name):
        return el.findall(ns + name)

    variants = []
    for period in find(root, "Period") or [root]:
        for aset in find(period, "AdaptationSet"):
            mime = (aset.get("mimeType") or aset.get("contentType") or "").lower()
            if mime and not mime.startswith("video"):
                continue
            for rep in find(aset, "Representation"):
                try:
                    bw = int(rep.get("bandwidth") or 0)
                except ValueError:
                    bw = 0
                w, h = rep.get("width", ""), rep.get("height", "")
                item = {
                    "bandwidth": bw,
                    "resolution": ("%sx%s" % (w, h)) if w and h else "",
                    "codecs": rep.get("codecs", ""),
                    "urls": [],
                }
                for bu in find(rep, "BaseURL"):
                    if bu.text:
                        item["urls"].append(urljoin(base, bu.text.strip()))
                for sl in find(rep, "SegmentList"):
                    for su in find(sl, "SegmentURL"):
                        m = su.get("media")
                        if m:
                            item["urls"].append(urljoin(base, m))
                if item["urls"] or bw:
                    variants.append(item)
    variants.sort(key=lambda x: x["bandwidth"], reverse=True)
    return {"variants": variants[:cap], "drm": drm}


# ==================================================================
#  ถอดรหัส
# ==================================================================

def aes_available():
    """เครื่องนี้ถอดรหัส AES ได้หรือไม่"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher  # noqa: F401
        return True
    except ImportError:
        return False


def iv_of(spec, seq):
    """
    หาค่าเริ่มต้นของการถอดรหัสสำหรับชิ้นหนึ่ง

    ถ้าไฟล์รายการระบุไว้ก็ใช้ค่านั้น ถ้าไม่ระบุให้ใช้เลขลำดับของชิ้น
    แปลงเป็นเลข 16 ไบต์ ตามที่มาตรฐานกำหนด
    """
    raw = (spec or "").strip()
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    if raw:
        try:
            b = bytes.fromhex(raw)
            if len(b) == 16:
                return b
        except ValueError:
            pass
    return int(seq).to_bytes(16, "big")


def decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """
    ถอดรหัสชิ้นย่อยที่เข้ารหัสแบบ AES-128 ตามมาตรฐาน HLS

    ใช้โหมด CBC และตัดส่วนเติมท้ายออกตามมาตรฐาน PKCS7
    ชิ้นสุดท้ายบางเจ้าไม่เติมท้าย จึงตรวจก่อนตัดเสมอ
    """
    if not data or not key:
        return b""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = dec.update(data) + dec.finalize()
    if out:
        pad = out[-1]
        if 1 <= pad <= 16 and out[-pad:] == bytes([pad]) * pad:
            out = out[:-pad]
    return out


# ==================================================================
#  ต่อชิ้นย่อยเป็นไฟล์เดียว
# ==================================================================

def ffmpeg_path():
    """หาที่อยู่ของโปรแกรมต่อไฟล์ คืนค่าว่างถ้าเครื่องนี้ไม่มี"""
    import shutil
    return shutil.which("ffmpeg") or ""


def joinable(kind: str) -> bool:
    """
    ชิ้นย่อยชนิดนี้ต่อกันตรง ๆ ได้โดยไม่ต้องพึ่งโปรแกรมภายนอกหรือไม่

    MPEG-TS ออกแบบมาให้ต่อกันได้ เพราะทุกชิ้นมีข้อมูลกำกับครบในตัวเอง
    ส่วน MP4 แบบแบ่งชิ้นต้องมีส่วนหัวจากชิ้นแรกเสมอ ต่อมั่วไม่ได้
    """
    return kind in ("ts", "m2ts", "")
