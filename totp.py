# -*- coding: utf-8 -*-
"""
totp.py — การยืนยันตัวตนสองชั้นแบบรหัสใช้ครั้งเดียวตามเวลา

ทำตามมาตรฐาน RFC 6238 (TOTP) และ RFC 4226 (HOTP)
ใช้ได้กับแอปยืนยันตัวตนทั่วไป เช่น Google Authenticator, Microsoft Authenticator,
Authy, 1Password, Bitwarden

เขียนด้วยไลบรารีมาตรฐานของ Python ล้วน ไม่ต้องติดตั้งอะไรเพิ่ม
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = "Auto Link Photo"
DIGITS = 6
PERIOD = 30          # วินาทีต่อรหัสหนึ่งชุด
WINDOW = 1           # ยอมรับรหัสของช่วงก่อนหน้าและถัดไป (กันนาฬิกาคลาดเคลื่อน)

BACKUP_COUNT = 10
BACKUP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # ตัดตัวที่สับสนออก


# ------------------------------------------------------------------ กุญแจ

def new_secret() -> str:
    """สร้างกุญแจลับใหม่ในรูปแบบ Base32 (160 บิต)"""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _b32decode(secret: str) -> bytes:
    s = (secret or "").strip().replace(" ", "").upper()
    s += "=" * ((8 - len(s) % 8) % 8)
    return base64.b32decode(s, casefold=True)


def pretty(secret: str) -> str:
    """แบ่งกุญแจเป็นกลุ่มละ 4 ตัวให้อ่านและพิมพ์ง่าย"""
    s = (secret or "").upper()
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


# ------------------------------------------------------------------ รหัส

def code_at(secret: str, counter: int) -> str:
    key = _b32decode(secret)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    part = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(part % (10 ** DIGITS)).zfill(DIGITS)


def now_code(secret: str, at: float = None) -> str:
    return code_at(secret, int((at or time.time()) // PERIOD))


def verify(secret: str, code: str, at: float = None) -> bool:
    """ตรวจรหัส 6 หลัก โดยยอมรับช่วงเวลาข้างเคียงตามค่า WINDOW"""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return False
    counter = int((at or time.time()) // PERIOD)
    for drift in range(-WINDOW, WINDOW + 1):
        try:
            if hmac.compare_digest(code, code_at(secret, counter + drift)):
                return True
        except (ValueError, TypeError):
            return False
    return False


def seconds_left(at: float = None) -> int:
    return PERIOD - int((at or time.time()) % PERIOD)


# ------------------------------------------------------------------ QR

def uri(secret: str, account: str) -> str:
    """ที่อยู่มาตรฐานสำหรับให้แอปยืนยันตัวตนอ่าน"""
    label = quote(f"{ISSUER}:{account or 'user'}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(ISSUER)}&algorithm=SHA1"
            f"&digits={DIGITS}&period={PERIOD}")


def qr_svg(data: str, size: int = 208):
    """
    สร้างภาพ QR เป็น SVG คืน None ถ้าเครื่องยังไม่มีไลบรารี qrcode
    (ผู้ใช้ยังกรอกกุญแจด้วยมือได้ตามปกติ)
    """
    try:
        import qrcode
    except ImportError:
        return None
    try:
        qr = qrcode.QRCode(version=None, box_size=1, border=2,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()
    except Exception:
        return None

    n = len(matrix)
    scale = max(1, size // n)
    dim = n * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{dim}" height="{dim}" '
             f'viewBox="0 0 {n} {n}" shape-rendering="crispEdges" role="img" '
             f'aria-label="รหัส QR สำหรับแอปยืนยันตัวตน">'
             f'<rect width="{n}" height="{n}" fill="#ffffff"/>']
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                run = x
                while run < n and row[run]:
                    run += 1
                parts.append(f'<rect x="{x}" y="{y}" width="{run - x}" height="1" fill="#12161c"/>')
                x = run
            else:
                x += 1
    parts.append("</svg>")
    return "".join(parts)


# ------------------------------------------------------------ รหัสสำรอง

def new_backup_codes(count: int = BACKUP_COUNT):
    """สร้างรหัสสำรองแบบใช้ครั้งเดียว คืนรายการรหัสที่ยังอ่านได้"""
    out = []
    for _ in range(count):
        raw = "".join(secrets.choice(BACKUP_ALPHABET) for _ in range(8))
        out.append(raw[:4] + "-" + raw[4:])
    return out


def normalize_backup(code: str) -> str:
    return "".join(ch for ch in (code or "").upper()
                   if ch in BACKUP_ALPHABET)


def hash_backup(code: str) -> str:
    """เก็บรหัสสำรองแบบแปลงค่าแล้ว ไม่เก็บรหัสจริง"""
    return hashlib.sha256(normalize_backup(code).encode("utf-8")).hexdigest()
