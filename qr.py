# -*- coding: utf-8 -*-
"""
qr.py — ตัวสร้างรหัส QR ในตัวระบบ

เขียนขึ้นเองด้วยไลบรารีมาตรฐานของ Python เท่านั้น
จึงใช้งานได้ทันทีทุกเครื่องโดยไม่ต้องติดตั้งอะไรเพิ่ม

รองรับการเข้ารหัสแบบไบต์ (ครอบคลุมข้อความทุกแบบรวมทั้งภาษาไทย)
เวอร์ชัน 1 ถึง 14 และระดับการกู้คืนข้อมูล L / M / Q / H
ซึ่งเพียงพอสำหรับที่อยู่ตั้งค่าแอปยืนยันตัวตนอย่างมาก

ใช้งาน
    import qr
    svg = qr.svg("otpauth://totp/...")        # ได้ภาพ SVG เป็นข้อความ
    grid = qr.matrix("ข้อความ")               # ได้ตารางจุด True/False
"""

import re

# ==================================================================
#  ตารางตามมาตรฐาน ISO/IEC 18004
# ==================================================================

# จำนวนบล็อกและจำนวนไบต์ข้อมูลในแต่ละบล็อก แยกตามเวอร์ชันและระดับการกู้คืน
# รูปแบบ (จำนวนบล็อก, ไบต์รวมต่อบล็อก, ไบต์ข้อมูลต่อบล็อก)
BLOCKS = {
     1: {"L": [(1, 26, 19)], "M": [(1, 26, 16)], "Q": [(1, 26, 13)], "H": [(1, 26, 9)]},
     2: {"L": [(1, 44, 34)], "M": [(1, 44, 28)], "Q": [(1, 44, 22)], "H": [(1, 44, 16)]},
     3: {"L": [(1, 70, 55)], "M": [(1, 70, 44)], "Q": [(2, 35, 17)], "H": [(2, 35, 13)]},
     4: {"L": [(1, 100, 80)], "M": [(2, 50, 32)], "Q": [(2, 50, 24)], "H": [(4, 25, 9)]},
     5: {"L": [(1, 134, 108)], "M": [(2, 67, 43)],
         "Q": [(2, 33, 15), (2, 34, 16)], "H": [(2, 33, 11), (2, 34, 12)]},
     6: {"L": [(2, 86, 68)], "M": [(4, 43, 27)], "Q": [(4, 43, 19)], "H": [(4, 43, 15)]},
     7: {"L": [(2, 98, 78)], "M": [(4, 49, 31)],
         "Q": [(2, 32, 14), (4, 33, 15)], "H": [(4, 39, 13), (1, 40, 14)]},
     8: {"L": [(2, 121, 97)], "M": [(2, 60, 38), (2, 61, 39)],
         "Q": [(4, 40, 18), (2, 41, 19)], "H": [(4, 40, 14), (2, 41, 15)]},
     9: {"L": [(2, 146, 116)], "M": [(3, 58, 36), (2, 59, 37)],
         "Q": [(4, 36, 16), (4, 37, 17)], "H": [(4, 36, 12), (4, 37, 13)]},
    10: {"L": [(2, 86, 68), (2, 87, 69)], "M": [(4, 69, 43), (1, 70, 44)],
         "Q": [(6, 43, 19), (2, 44, 20)], "H": [(6, 43, 15), (2, 44, 16)]},
    11: {"L": [(4, 101, 81)], "M": [(1, 80, 50), (4, 81, 51)],
         "Q": [(4, 50, 22), (4, 51, 23)], "H": [(3, 36, 12), (8, 37, 13)]},
    12: {"L": [(2, 116, 92), (2, 117, 93)], "M": [(6, 58, 36), (2, 59, 37)],
         "Q": [(4, 46, 20), (6, 47, 21)], "H": [(7, 42, 14), (4, 43, 15)]},
    13: {"L": [(4, 133, 107)], "M": [(8, 59, 37), (1, 60, 38)],
         "Q": [(8, 44, 20), (4, 45, 21)], "H": [(12, 33, 11), (4, 34, 12)]},
    14: {"L": [(3, 145, 115), (1, 146, 116)], "M": [(4, 64, 40), (5, 65, 41)],
         "Q": [(11, 36, 16), (5, 37, 17)], "H": [(11, 36, 12), (5, 37, 13)]},
}

# ตำแหน่งกลางของลายจัดแนว ในแต่ละเวอร์ชัน
ALIGN = {
     1: [],            2: [6, 18],        3: [6, 22],        4: [6, 26],
     5: [6, 30],        6: [6, 34],        7: [6, 22, 38],    8: [6, 24, 42],
     9: [6, 26, 46],   10: [6, 28, 50],   11: [6, 30, 54],   12: [6, 32, 58],
    13: [6, 34, 62],   14: [6, 26, 46, 66],
}

MAX_VERSION = 14

# ค่าประจำระดับการกู้คืนข้อมูล ใช้ประกอบข้อมูลกำกับรูปแบบ
EC_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

BYTE_MODE = 4          # ตัวบ่งชี้โหมดไบต์
PAD = (0xEC, 0x11)     # ไบต์เติมช่องว่างตามมาตรฐาน


class QRError(ValueError):
    """ข้อความยาวเกินกว่าที่รหัส QR รองรับ"""


# ==================================================================
#  เลขคณิตในฟีลด์จำกัด GF(256) สำหรับคำนวณข้อมูลกู้คืน
# ==================================================================

_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:          # เกินขอบเขต ต้องหารด้วยพหุนามประจำฟีลด์
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_poly(n):
    """พหุนามตัวสร้างสำหรับข้อมูลกู้คืน n ไบต์"""
    poly = [1]
    for i in range(n):
        nxt = [0] * (len(poly) + 1)
        for j, c in enumerate(poly):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        poly = nxt
    return poly


def _ec_bytes(data, count):
    """คำนวณไบต์กู้คืนข้อมูลของบล็อกหนึ่ง"""
    gen = _rs_poly(count)
    rest = list(data) + [0] * count
    for i in range(len(data)):
        factor = rest[i]
        if factor == 0:
            continue
        for j, g in enumerate(gen):
            rest[i + j] ^= _mul(g, factor)
    return rest[len(data):]


# ==================================================================
#  จัดเรียงข้อมูลลงในสายบิต
# ==================================================================

class _Bits:
    def __init__(self):
        self.bits = []

    def put(self, value, length):
        for i in range(length - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def __len__(self):
        return len(self.bits)


def _capacity(version, level):
    return sum(n * d for n, _, d in BLOCKS[version][level])


def _pick_version(nbytes, level, min_version=1):
    for v in range(max(1, min_version), MAX_VERSION + 1):
        count_bits = 8 if v <= 9 else 16
        need = (4 + count_bits + nbytes * 8 + 7) // 8
        if need <= _capacity(v, level):
            return v
    raise QRError("ข้อความยาวเกินกว่าที่รหัส QR รองรับ")


def _make_codewords(data, version, level):
    """สร้างไบต์ข้อมูลพร้อมไบต์กู้คืน แล้วสลับลำดับตามที่มาตรฐานกำหนด"""
    bits = _Bits()
    bits.put(BYTE_MODE, 4)
    bits.put(len(data), 8 if version <= 9 else 16)
    for byte in data:
        bits.put(byte, 8)

    total = _capacity(version, level) * 8
    if len(bits) > total:
        raise QRError("ข้อความยาวเกินกว่าที่รหัส QR รองรับ")

    # ตัวปิดท้าย ไม่เกิน 4 บิต และไม่เกินที่ว่างเหลือ
    bits.put(0, min(4, total - len(bits)))
    while len(bits) % 8:
        bits.bits.append(0)

    words = [int("".join(str(b) for b in bits.bits[i:i + 8]), 2)
             for i in range(0, len(bits), 8)]
    i = 0
    while len(words) < _capacity(version, level):
        words.append(PAD[i % 2])
        i += 1

    # แบ่งเป็นบล็อกตามตาราง แล้วคำนวณไบต์กู้คืนของแต่ละบล็อก
    dblocks, eblocks = [], []
    pos = 0
    for n, total_len, dlen in BLOCKS[version][level]:
        for _ in range(n):
            chunk = words[pos:pos + dlen]
            pos += dlen
            dblocks.append(chunk)
            eblocks.append(_ec_bytes(chunk, total_len - dlen))

    # สลับลำดับ ไบต์ลำดับเดียวกันของทุกบล็อกเรียงติดกัน
    out = []
    for i in range(max(len(b) for b in dblocks)):
        for b in dblocks:
            if i < len(b):
                out.append(b[i])
    for i in range(max(len(b) for b in eblocks)):
        for b in eblocks:
            if i < len(b):
                out.append(b[i])
    return out


# ==================================================================
#  วางลายบนตาราง
# ==================================================================

def _blank(size):
    return [[None] * size for _ in range(size)]


def _put_finders(g, size):
    """ลายกำหนดตำแหน่งสามมุม พร้อมเส้นคั่นรอบลาย"""
    for oy, ox in ((0, 0), (0, size - 7), (size - 7, 0)):
        for y in range(-1, 8):
            for x in range(-1, 8):
                py, px = oy + y, ox + x
                if not (0 <= py < size and 0 <= px < size):
                    continue
                inside = 0 <= y < 7 and 0 <= x < 7
                if inside:
                    edge = y in (0, 6) or x in (0, 6)
                    core = 2 <= y <= 4 and 2 <= x <= 4
                    g[py][px] = edge or core
                else:
                    g[py][px] = False          # เส้นคั่น


def _put_align(g, version, size):
    pos = ALIGN[version]
    for cy in pos:
        for cx in pos:
            # ไม่วางทับลายกำหนดตำแหน่ง
            if (cy, cx) in ((6, 6), (6, size - 7), (size - 7, 6)):
                continue
            if (cy <= 8 and cx <= 8) or (cy <= 8 and cx >= size - 9) \
               or (cy >= size - 9 and cx <= 8):
                continue
            for y in range(-2, 3):
                for x in range(-2, 3):
                    ring = max(abs(y), abs(x))
                    g[cy + y][cx + x] = ring != 1


def _put_timing(g, size):
    for i in range(size):
        if g[6][i] is None:
            g[6][i] = i % 2 == 0
        if g[i][6] is None:
            g[i][6] = i % 2 == 0


def _format_cells(size):
    """ตำแหน่งของข้อมูลกำกับรูปแบบ 15 บิต ทั้งสองชุด"""
    a, b = [], []
    for i in range(6):
        a.append((8, i))
    a.append((8, 7))
    a.append((8, 8))
    a.append((7, 8))
    for i in range(5, -1, -1):
        a.append((i, 8))
    for i in range(7):
        b.append((size - 1 - i, 8))
    for i in range(8):
        b.append((8, size - 8 + i))
    return a, b


def _reserve(g, size, version):
    for y, x in _format_cells(size)[0] + _format_cells(size)[1]:
        g[y][x] = False
    g[size - 8][8] = True                      # จุดทึบประจำตำแหน่ง
    if version >= 7:
        for i in range(18):
            g[size - 11 + i % 3][i // 3] = False
            g[i // 3][size - 11 + i % 3] = False


def _put_data(g, size, words):
    """ไล่วางบิตข้อมูลแบบซิกแซกจากมุมขวาล่าง"""
    bits = []
    for w in words:
        for i in range(7, -1, -1):
            bits.append((w >> i) & 1)
    idx = 0
    up = True
    col = size - 1
    while col > 0:
        if col == 6:                           # ข้ามคอลัมน์เส้นจับเวลา
            col -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for row in rows:
            for c in (col, col - 1):
                if g[row][c] is not None:
                    continue
                g[row][c] = bool(bits[idx]) if idx < len(bits) else False
                idx += 1
        up = not up
        col -= 2


# ==================================================================
#  หน้ากากและการให้คะแนน
# ==================================================================

def _mask_rule(n, y, x):
    if n == 0: return (y + x) % 2 == 0
    if n == 1: return y % 2 == 0
    if n == 2: return x % 3 == 0
    if n == 3: return (y + x) % 3 == 0
    if n == 4: return (y // 2 + x // 3) % 2 == 0
    if n == 5: return (y * x) % 2 + (y * x) % 3 == 0
    if n == 6: return ((y * x) % 2 + (y * x) % 3) % 2 == 0
    return ((y + x) % 2 + (y * x) % 3) % 2 == 0


def _reserved_map(g, size):
    """
    ช่องที่เป็นลายประจำรหัส ดูจากผลการวางจริง ไม่ใช่จากการคาดเดาตำแหน่ง

    การคาดเดาด้วยสูตรทำให้พลาดได้ เพราะลายจัดแนวบางตำแหน่งในตารางถูกข้ามไป
    เมื่อทับกับลายกำหนดตำแหน่ง ช่องรอบ ๆ จึงยังเป็นช่องข้อมูลที่ต้องใส่หน้ากาก
    """
    return [[g[y][x] is not None for x in range(size)] for y in range(size)]


def _apply_mask(g, size, reserved, n):
    out = [row[:] for row in g]
    for y in range(size):
        for x in range(size):
            if not reserved[y][x] and _mask_rule(n, y, x):
                out[y][x] = not out[y][x]
    return out


def _penalty(g, size):
    score = 0

    # กฎ 1 จุดสีเดียวกันเรียงติดกันเกินสี่ช่อง
    for line in list(g) + [list(col) for col in zip(*g)]:
        run, prev = 0, None
        for v in line:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run, prev = 1, v
        if run >= 5:
            score += run - 2

    # กฎ 2 บล็อกสีเดียวกันขนาดสองคูณสอง
    for y in range(size - 1):
        for x in range(size - 1):
            v = g[y][x]
            if v == g[y][x + 1] == g[y + 1][x] == g[y + 1][x + 1]:
                score += 3

    # กฎ 3 ลายที่คล้ายลายกำหนดตำแหน่ง
    # นับเมื่อพบลาย ทึบ-สว่าง-ทึบสามช่อง-สว่าง-ทึบ แล้วมีพื้นสว่างกว้างสี่ช่อง
    # อยู่ด้านหน้าหรือด้านหลังก็ได้ และนับด้วยเมื่อลายอยู่ชิดขอบภาพ
    # เพราะขอบขาวรอบนอกทำหน้าที่เป็นพื้นสว่างนั้นเอง
    core = [True, False, True, True, True, False, True]
    for line in list(g) + [list(col) for col in zip(*g)]:
        i = 0
        while i <= size - 7:
            if line[i:i + 7] == core:
                after = i + 7
                if (i == 0 or i == size - 7
                        or not any(line[max(i - 4, 0):i])
                        or not any(line[after:after + 4])):
                    score += 40
                    i = after
                else:
                    i += 4          # ข้ามไปยังจุดที่อาจซ้อนกันได้ถัดไป
            else:
                i += 1

    # กฎ 4 สัดส่วนจุดทึบต่างจากครึ่งหนึ่งมากเกินไป
    # คิดด้วยจำนวนเต็มตรง ๆ ไม่ปัดเศษเปอร์เซ็นต์ก่อน เพราะการปัดก่อน
    # ทำให้คะแนนคลาดไปหนึ่งขั้นในกรณีที่สัดส่วนอยู่ตรงรอยต่อพอดี
    dark = sum(1 for row in g for v in row if v)
    total = size * size
    score += 10 * (abs(dark * 100 - 50 * total) // (5 * total))
    return score


# ==================================================================
#  ข้อมูลกำกับรูปแบบและเวอร์ชัน
# ==================================================================

def _bch15(data):
    v = data << 10
    while v.bit_length() - 1 >= 10:
        v ^= 0x537 << (v.bit_length() - 11)
    return ((data << 10) | v) ^ 0x5412


def _bch18(version):
    v = version << 12
    while v.bit_length() - 1 >= 12:
        v ^= 0x1F25 << (v.bit_length() - 13)
    return (version << 12) | v


def _put_format(g, size, level, mask):
    """
    วางข้อมูลกำกับรูปแบบ 15 บิต สองชุด
    มาตรฐานกำหนดให้เรียงบิตที่มีนัยสำคัญสูงสุดไว้ตำแหน่งแรก
    """
    value = _bch15((EC_BITS[level] << 3) | mask)
    a, b = _format_cells(size)
    for cells in (a, b):
        for i, (y, x) in enumerate(cells):
            g[y][x] = bool((value >> (14 - i)) & 1)
    g[size - 8][8] = True


def _put_version(g, size, version):
    if version < 7:
        return
    value = _bch18(version)
    for i in range(18):
        bit = bool((value >> i) & 1)
        g[size - 11 + i % 3][i // 3] = bit
        g[i // 3][size - 11 + i % 3] = bit


# ==================================================================
#  หน้าที่เรียกใช้จากภายนอก
# ==================================================================

def matrix(text, level="M", min_version=1):
    """
    สร้างตารางจุดของรหัส QR คืนรายการของรายการค่า True/False
    True หมายถึงจุดทึบ ไม่รวมขอบขาวรอบนอก
    """
    if level not in EC_BITS:
        level = "M"
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    version = _pick_version(len(data), level, min_version)
    words = _make_codewords(data, version, level)

    size = version * 4 + 17
    g = _blank(size)
    _put_finders(g, size)
    _put_align(g, version, size)
    _put_timing(g, size)
    _reserve(g, size, version)
    reserved = _reserved_map(g, size)      # จดไว้ก่อนเติมข้อมูล
    _put_data(g, size, words)

    best, best_score = None, None
    for m in range(8):
        cand = _apply_mask(g, size, reserved, m)
        _put_format(cand, size, level, m)
        _put_version(cand, size, version)
        s = _penalty(cand, size)
        if best_score is None or s < best_score:
            best, best_score = cand, s
    return best


def svg(text, size=208, level="M", border=4,
        dark="#12161c", light="#ffffff", label="รหัส QR"):
    """
    สร้างภาพรหัส QR เป็นข้อความ SVG พร้อมใช้กับหน้าเว็บได้ทันที
    รวมจุดที่ต่อกันในแถวเดียวกันเป็นแถบเดียว เพื่อให้ไฟล์เล็กและวาดเร็ว
    """
    g = matrix(text, level=level)
    n = len(g) + border * 2
    dim = max(size, n)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d" shape-rendering="crispEdges" role="img" '
           'aria-label="%s"><rect width="%d" height="%d" fill="%s"/>'
           % (dim, dim, n, n, _esc(label), n, n, light)]
    for y, row in enumerate(g):
        x = 0
        while x < len(row):
            if row[x]:
                run = x
                while run < len(row) and row[run]:
                    run += 1
                out.append('<rect x="%d" y="%d" width="%d" height="1" fill="%s"/>'
                           % (x + border, y + border, run - x, dark))
                x = run
            else:
                x += 1
    out.append("</svg>")
    return "".join(out)


def text_art(text, level="M", on="██", off="  "):
    """แสดงรหัส QR เป็นตัวอักษร ใช้ตรวจสอบผลด้วยตาในหน้าต่างคำสั่ง"""
    g = matrix(text, level=level)
    pad = off * (len(g) + 4)
    lines = [pad, pad]
    for row in g:
        lines.append(off * 2 + "".join(on if v else off for v in row) + off * 2)
    lines += [pad, pad]
    return "\n".join(lines)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
