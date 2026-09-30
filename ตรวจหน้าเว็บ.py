# -*- coding: utf-8 -*-
"""
ตรวจข้อผิดพลาดของหน้าเว็บที่เคยเกิดขึ้นมาแล้ว

รันด้วย  python ตรวจหน้าเว็บ.py

ไฟล์นี้ไม่ได้ตรวจว่าหน้าเว็บสวยหรือไม่ แต่ตรวจเฉพาะข้อผิดพลาดชนิดที่
เคยหลุดออกไปถึงหน้าจอผู้ใช้มาแล้ว แต่ละข้อจึงมีที่มาจากของจริง

  1  ใช้ตัวแปรสีที่ไม่ได้ประกาศไว้ ทำให้ปุ่มกลายเป็นขาวบนขาวจนมองไม่เห็น
  2  สั่งตัดข้อความด้วยจุดไข่ปลาบนสิ่งที่ไม่ใช่บล็อก ทำให้แถวล้นทับกัน
  3  รหัสประจำตัวซ้ำกัน ทำให้สคริปต์ไปหยิบผิดตัว
  4  สคริปต์เรียกรหัสประจำตัวที่ไม่มีอยู่จริงในหน้า
  5  ค่าความต่างของสีต่ำกว่าเกณฑ์การเข้าถึง จนอ่านไม่ออก
"""

import ast
import ast
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = [os.path.join(HERE, "templates", f)
         for f in ("index.html", "landing.html")]
SHEETS = sorted(glob.glob(os.path.join(HERE, "static", "*.css")))
FILES = [p for p in PAGES + SHEETS if os.path.isfile(p)]

ok = 0
bad = 0


def check(name, passed, detail=""):
    global ok, bad
    if passed:
        ok += 1
        print("  ผ่าน  %s" % name)
    else:
        bad += 1
        print("  ตก    %s  %s" % (name, detail))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def short(path):
    return os.path.relpath(path, HERE)


# ------------------------------------------------------------------
print("=== ตัวแปรสีที่ใช้ ต้องประกาศไว้จริง ===")

declared = set()
for p in FILES:
    declared |= set(re.findall(r"(--[\w-]+)\s*:", read(p)))

for p in FILES:
    missing = set()
    for m in re.finditer(r"var\((--[\w-]+)\s*(,)?", read(p)):
        # มีค่าสำรองต่อท้ายถือว่าตั้งใจ ไม่นับเป็นข้อผิดพลาด
        if m.group(1) not in declared and not m.group(2):
            missing.add(m.group(1))
    check("%s ใช้ตัวแปรที่ประกาศครบ" % short(p), not missing, sorted(missing))


# ------------------------------------------------------------------
print()
print("=== การตัดข้อความด้วยจุดไข่ปลา ===")

BLOCKY = re.compile(r"display\s*:\s*(block|flex|grid|inline-block|table-cell)")

for p in FILES:
    text = read(p)
    risky = []
    for sel, body in re.findall(r"([.#][\w.\-]+)\s*\{([^}]*)\}", text):
        if "text-overflow" in body and "ellipsis" in body:
            if BLOCKY.search(body):
                continue
            # ถ้าคลาสนี้ถูกใช้กับแท็กที่เป็นบล็อกอยู่แล้ว ก็ไม่เป็นไร
            cls = sel[1:].split(".")[0].split(":")[0]
            used_on = re.findall(
                r"<(\w+)[^>]*class=[\"'][^\"']*\b%s\b" % re.escape(cls), text)
            if used_on and all(t in ("div", "td", "p", "li", "section")
                               for t in used_on):
                continue
            risky.append(sel)
    check("%s ไม่มีการตัดข้อความบนสิ่งที่ไม่ใช่บล็อก" % short(p),
          not risky, risky)


# ------------------------------------------------------------------
print()
print("=== รหัสประจำตัวในหน้า ===")

for p in PAGES:
    if not os.path.isfile(p):
        continue
    text = read(p)
    ids = re.findall(r"id=[\"']([\w-]+)[\"']", text)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    check("%s ไม่มีรหัสซ้ำ" % short(p), not dup, dup)

    # สคริปต์เรียกรหัสไหนบ้าง ต้องมีอยู่จริงหรือถูกสร้างขึ้นระหว่างทำงาน
    called = set(re.findall(r"\$\(\"#([\w-]+)\"\)", text))
    made = set(ids) | set(re.findall(r"id=\\?[\"']([\w-]+)\\?[\"']", text))
    ghost = sorted(called - made)
    check("%s สคริปต์ไม่ได้เรียกรหัสที่ไม่มีอยู่" % short(p), not ghost, ghost)


# ------------------------------------------------------------------
print()
print("=== เหตุการณ์ที่มาไม่เรียงลำดับ ===")

# ตัวเลือกคุณภาพกับผลค้นหาแยกสายกัน อันไหนเสร็จก่อนมาก่อน
# ถ้าหน้าเว็บเผลอไปพึ่งของอีกอันหรือค่าที่ค้างจากรอบก่อน จะโหลดผิดคลิป
_page = read(PAGES[0])

_q = re.search(r'addEventListener\("quality".{0,400}?\}\);', _page, re.S)
check("แผงคุณภาพใช้ที่อยู่ที่ติดมากับตัวมันเอง",
      bool(_q) and "hpInit(q.url" in _q.group(0),
      "ไม่พบ hpInit(q.url ในตัวรับเหตุการณ์")

_s = re.search(r'function startVideo\(\).{0,1400}?EventSource', _page, re.S)
check("เริ่มค้นรอบใหม่ ต้องล้างที่อยู่ของรอบก่อน",
      bool(_s) and re.search(r'HP\.url\s*=\s*""', _s.group(0)) is not None,
      "ไม่พบการล้าง HP.url ตอนเริ่มค้น")

# เคยพลาดจนต้องกดค้นสองรอบ ผลค้นหามาถึงแล้ววางสายทิ้งทันที
# ตัวเลือกคุณภาพที่ตามมาทีหลังจึงไม่มีวันถึงหน้าจอ
_f = re.search(r'function finish\(\)\s*\{(.{0,400}?)\}', _page, re.S)
check("ปิดสายเฉพาะตอนไม่มีของตามมาแล้ว",
      bool(_f) and re.search(r'if\s*\(\s*ES\s*&&\s*!QWAIT', _f.group(0)),
      "finish() ปิดสายโดยไม่ดูว่ายังรออะไรอยู่")

_r = re.search(r'addEventListener\("result".{0,400}?\}\);', _page, re.S)
check("จำไว้ว่ายังรอตัวเลือกคุณภาพอยู่ ก่อนจะปิดสาย",
      bool(_r) and re.search(r'QWAIT\s*=\s*!!\s*r\.quality_wait', _r.group(0))
      and _r.group(0).index("QWAIT") < _r.group(0).index("finish()"),
      "ไม่ได้ตั้ง QWAIT จาก quality_wait ก่อนเรียก finish()")


# ------------------------------------------------------------------
print()
print("=== เหตุการณ์ที่มาไม่เรียงลำดับ ===")

# ตัวเลือกคุณภาพกับผลค้นหาแยกสายกัน อันไหนเสร็จก่อนมาก่อน
# ถ้าหน้าเว็บเผลอไปพึ่งของอีกอันหรือค่าที่ค้างจากรอบก่อน จะโหลดผิดคลิป
_page = read(PAGES[0])

_q = re.search(r'addEventListener\("quality".{0,400}?\}\);', _page, re.S)
check("แผงคุณภาพใช้ที่อยู่ที่ติดมากับตัวมันเอง",
      bool(_q) and "hpInit(q.url" in _q.group(0),
      "ไม่พบ hpInit(q.url ในตัวรับเหตุการณ์")

_s = re.search(r'function startVideo\(\).{0,1400}?EventSource', _page, re.S)
check("เริ่มค้นรอบใหม่ ต้องล้างที่อยู่ของรอบก่อน",
      bool(_s) and re.search(r'HP\.url\s*=\s*""', _s.group(0)) is not None,
      "ไม่พบการล้าง HP.url ตอนเริ่มค้น")

# เคยพลาดจนต้องกดค้นสองรอบ ผลค้นหามาถึงแล้ววางสายทิ้งทันที
# ตัวเลือกคุณภาพที่ตามมาทีหลังจึงไม่มีวันถึงหน้าจอ
_f = re.search(r'function finish\(\)\s*\{(.{0,400}?)\}', _page, re.S)
check("ปิดสายเฉพาะตอนไม่มีของตามมาแล้ว",
      bool(_f) and re.search(r'if\s*\(\s*ES\s*&&\s*!QWAIT', _f.group(0)),
      "finish() ปิดสายโดยไม่ดูว่ายังรออะไรอยู่")

_r = re.search(r'addEventListener\("result".{0,400}?\}\);', _page, re.S)
check("จำไว้ว่ายังรอตัวเลือกคุณภาพอยู่ ก่อนจะปิดสาย",
      bool(_r) and re.search(r'QWAIT\s*=\s*!!\s*r\.quality_wait', _r.group(0))
      and _r.group(0).index("QWAIT") < _r.group(0).index("finish()"),
      "ไม่ได้ตั้ง QWAIT จาก quality_wait ก่อนเรียก finish()")


# ------------------------------------------------------------------
print()
print("=== ชื่อเครื่องมือเบื้องหลัง ต้องไม่โผล่หน้าลูกค้า ===")

# กติกาข้อที่หนึ่งของโครงการ ลูกค้าไม่ต้องรู้จักและไม่ต้องยุ่งกับเครื่องมือเบื้องหลัง
# ข้อความที่ลูกค้าอ่านเป็นภาษาไทย ส่วนชื่อแพ็กเกจกับคำสั่งเป็นภาษาอังกฤษล้วน
# จึงถือว่าข้อความไทยที่มีชื่อเครื่องมือปนอยู่ คือข้อความที่หลุดไปถึงหน้าจอ
THAI = re.compile(r"[฀-๿]")
HIDDEN = ("yt-dlp", "yt_dlp")


def talk_strings(path):
    """ข้อความที่ระบบเอาไปแสดง ไม่นับคำอธิบายประจำฟังก์ชัน"""
    tree = ast.parse(read(path))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False) is not None:
                skip.add(id(node.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


for name in ("app.py", "helper.py", "render.py", "videoscan.py",
             "scraper.py", "panel.py"):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        continue
    leak = [s[:60] for s in talk_strings(p)
            if THAI.search(s) and any(k in s for k in HIDDEN)]
    check("%s ไม่เอ่ยชื่อเครื่องมือในข้อความที่ลูกค้าอ่าน" % name, not leak, leak)

for p in PAGES:
    if not os.path.isfile(p):
        continue
    leak = [l.strip()[:60] for l in read(p).splitlines()
            if THAI.search(l) and any(k in l for k in HIDDEN)]
    check("%s ไม่เอ่ยชื่อเครื่องมือ" % short(p), not leak, leak)


# ------------------------------------------------------------------
print()
print("=== ชื่อเครื่องมือเบื้องหลัง ต้องไม่โผล่หน้าลูกค้า ===")

# กติกาข้อที่หนึ่งของโครงการ ลูกค้าไม่ต้องรู้จักและไม่ต้องยุ่งกับเครื่องมือเบื้องหลัง
# ข้อความที่ลูกค้าอ่านเป็นภาษาไทย ส่วนชื่อแพ็กเกจกับคำสั่งเป็นภาษาอังกฤษล้วน
# จึงถือว่าข้อความไทยที่มีชื่อเครื่องมือปนอยู่ คือข้อความที่หลุดไปถึงหน้าจอ
THAI = re.compile(r"[฀-๿]")
HIDDEN = ("yt-dlp", "yt_dlp")


def talk_strings(path):
    """ข้อความที่ระบบเอาไปแสดง ไม่นับคำอธิบายประจำฟังก์ชัน"""
    tree = ast.parse(read(path))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node, clean=False) is not None:
                skip.add(id(node.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


for name in ("app.py", "helper.py", "render.py", "videoscan.py",
             "scraper.py", "panel.py"):
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        continue
    leak = [s[:60] for s in talk_strings(p)
            if THAI.search(s) and any(k in s for k in HIDDEN)]
    check("%s ไม่เอ่ยชื่อเครื่องมือในข้อความที่ลูกค้าอ่าน" % name, not leak, leak)

for p in PAGES:
    if not os.path.isfile(p):
        continue
    leak = [l.strip()[:60] for l in read(p).splitlines()
            if THAI.search(l) and any(k in l for k in HIDDEN)]
    check("%s ไม่เอ่ยชื่อเครื่องมือ" % short(p), not leak, leak)


# ------------------------------------------------------------------
print()
print("=== ค่าความต่างของสี ===")


def lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def lum(t):
    return .2126 * lin(t[0]) + .7152 * lin(t[1]) + .0722 * lin(t[2])


def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + .05) / (lo + .05)


def rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def palette(text, block):
    m = re.search(block + r"\s*\{(.*?)\}", text, re.S)
    if not m:
        return {}
    return {k: v.strip() for k, v in
            re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1))}


light = palette(read(PAGES[0]), r":root")
dark = palette(read(os.path.join(HERE, "static", "theme.css")),
               r'html\[data-theme="dark"\]')

# คู่สีที่ต้องอ่านออกทั้งสองโหมด
PAIRS = [
    ("อักษรบนพื้นสีเน้น", "--on-dark", "--dark"),
]
for label, fg, bg in PAIRS:
    for mode, pal in (("สว่าง", light), ("มืด", dark)):
        f, b = pal.get(fg, ""), pal.get(bg, "")
        if not (f.startswith("#") and b.startswith("#")):
            check("%s โหมด%s อ่านค่าสีได้" % (label, mode), False,
                  "%s=%r %s=%r" % (fg, f, bg, b))
            continue
        r = ratio(rgb(f), rgb(b))
        check("%s โหมด%s (%.2f:1)" % (label, mode, r), r >= 4.5,
              "ต่ำกว่าเกณฑ์ 4.5:1")


# ------------------------------------------------------------------
print()
print("  ผ่าน %d  ตก %d" % (ok, bad))
sys.exit(1 if bad else 0)
