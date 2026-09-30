# -*- coding: utf-8 -*-
"""
จัดรูปข้อมูลให้พร้อมแสดง ทำที่เซิร์ฟเวอร์

เดิมหน้าเว็บรับข้อมูลดิบไปแล้วประกอบข้อความเอง ทั้งการระบายสีโค้ด
การจัดรูปขนาดไฟล์และเวลา การประกอบป้ายกำกับ และการกรองเรียงรายการ
งานพวกนี้ทำซ้ำทุกครั้งที่มีเหตุการณ์เข้ามา เครื่องของผู้ใช้จึงต้องทำงานตลอด
โดยเฉพาะตอนสแกนระดับลึกที่ส่งเหตุการณ์เข้ามาหลายร้อยครั้ง

ไฟล์นี้ย้ายงานทั้งหมดมาไว้ที่เซิร์ฟเวอร์ หน้าเว็บเหลือหน้าที่แค่เอา
ข้อความที่ได้ไปวางเท่านั้น

ข้อควรระวัง โค้ดและชื่อไฟล์ที่นำมาแสดงเป็นของเว็บปลายทางซึ่งควบคุมไม่ได้
จึงต้องแปลงอักขระพิเศษให้เรียบร้อยก่อนเสมอ แล้วค่อยใส่แท็กของเราเอง
ถ้าทำสลับกันจะกลายเป็นช่องให้สคริปต์แปลกปลอมทำงานในหน้าเว็บ
"""

import html
import re

# ==================================================================
#  จัดรูปตัวเลข
# ==================================================================

def size_text(n):
    """ขนาดไฟล์เป็นข้อความที่คนอ่านเข้าใจ"""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n < 1024:
        return "%d B" % int(n)
    if n < 1048576:
        return "%.0f KB" % (n / 1024)
    if n < 1073741824:
        return "%.2f MB" % (n / 1048576)
    return "%.2f GB" % (n / 1073741824)


def time_text(sec):
    """ความยาวเป็นข้อความ ชั่วโมงแสดงเฉพาะเมื่อมีจริง"""
    try:
        sec = int(float(sec or 0))
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def count_text(n):
    """ตัวเลขจำนวนนับ คั่นหลักพันให้อ่านง่าย"""
    try:
        return "{:,}".format(int(n or 0))
    except (TypeError, ValueError):
        return "0"


# ==================================================================
#  ระบายสีโค้ด
# ==================================================================

KEYWORDS = frozenset((
    "var let const function return if else for while new class extends "
    "import export default from as async await try catch finally throw "
    "typeof instanceof of in do switch case break continue this null "
    "true false undefined void delete yield static get set super"
).split())

# ลำดับกลุ่มสำคัญ ต้องจับคำอธิบายและข้อความก่อนอย่างอื่นเสมอ
TOKEN = re.compile(
    r"(/\*.*?\*/|//[^\n]*)"                       # คำอธิบายในโค้ด
    r"|(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)"   # ข้อความ
    r"|(\b\d[\w.]*\b)"                            # ตัวเลข
    r"|([A-Za-z_$][\w$]*)"                        # ชื่อ
    r"|([{}()\[\];:,.=+\-*/<>!?&|%~^]+)",         # เครื่องหมาย
    re.S,
)

CLASS_OF = {1: "tk-c", 2: "tk-s", 3: "tk-n", 5: "tk-p"}


def esc(text):
    """แปลงอักขระพิเศษให้ปลอดภัยก่อนนำไปแสดง"""
    return html.escape("" if text is None else str(text), quote=True)


def paint(text):
    """ใส่สีให้โค้ดหนึ่งช่วง คืน HTML ที่ปลอดภัยแล้ว"""
    if not text:
        return ""
    out = []
    last = 0
    for m in TOKEN.finditer(text):
        if m.start() > last:
            out.append(esc(text[last:m.start()]))
        word = m.group(0)
        if m.group(4):
            if word in KEYWORDS:
                out.append('<span class="tk-k">%s</span>' % esc(word))
            else:
                out.append(esc(word))
        else:
            for idx, cls in CLASS_OF.items():
                if m.group(idx):
                    out.append('<span class="%s">%s</span>' % (cls, esc(word)))
                    break
            else:
                out.append(esc(word))
        last = m.end()
    if last < len(text):
        out.append(esc(text[last:]))
    return "".join(out)


def _spans(row, length):
    """รวมช่วงที่ต้องเน้น แล้วเรียงและตัดส่วนที่ทับกันทิ้ง"""
    raw = []
    hits = row.get("hits")
    if isinstance(hits, (list, tuple)):
        raw.extend(hits)
    one = row.get("hit")
    if isinstance(one, (list, tuple)) and len(one) == 2:
        raw.append(one)

    out = []
    for span in raw:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        try:
            a, b = int(span[0]), int(span[1])
        except (TypeError, ValueError):
            continue
        a = max(0, min(length, a))
        b = max(0, min(length, b))
        if b > a:
            out.append((a, b))
    out.sort()
    return out


def code_html(rows):
    """
    ประกอบหน้าต่างโค้ดทั้งก้อน คืน HTML ที่พร้อมวางลงหน้าเว็บ

    บรรทัดเดียวมักดึงรูปหลายใบ จึงเน้นได้หลายช่วงในบรรทัดเดียวกัน
    แถวที่ต่อเนื่องคือส่วนที่หั่นมาจากบรรทัดเดียวกัน จะไม่แสดงเลขบรรทัดซ้ำ
    """
    if not isinstance(rows, (list, tuple)) or not rows:
        return ""

    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = "" if row.get("t") is None else str(row["t"])
        body = []
        at = 0
        for a, b in _spans(row, len(text)):
            if a < at:
                continue
            body.append(paint(text[at:a]))
            body.append("<b>%s</b>" % paint(text[a:b]))
            at = b
        body.append(paint(text[at:]))
        line = "".join(body)

        if row.get("ca"):
            line = '<span class="rdcut">…</span>' + line
        if row.get("cb"):
            line += '<span class="rdcut">…</span>'

        if row.get("cont"):
            gut = ('<span class="rdgut cont" title="บรรทัด %s คอลัมน์ %s">⤷</span>'
                   % (esc(row.get("n")), esc(row.get("col") or 1)))
        else:
            gut = '<span class="rdgut">%s</span>' % esc(row.get("n"))

        parts.append('<div class="rdrow%s">%s<span class="rdsrc">%s</span></div>'
                     % (" on" if row.get("on") else "", gut, line))
    return "".join(parts)


def peek_html(peek):
    """เติม HTML สำเร็จรูปลงในผลของ peek_lines แล้วเอาข้อมูลดิบออก

    ข้อมูลดิบไม่ต้องส่งไปให้หน้าเว็บอีก เพราะหน้าเว็บไม่ต้องประกอบเองแล้ว
    ส่งไปด้วยก็เปลืองสายและเปลืองหน่วยความจำของเบราว์เซอร์เปล่า ๆ
    """
    if not isinstance(peek, dict):
        return peek
    out = dict(peek)
    out["html"] = code_html(peek.get("rows"))
    out.pop("rows", None)
    return out


# ==================================================================
#  ป้ายกำกับของรายการวิดีโอ
# ==================================================================

def video_view(v):
    """เติมข้อความที่พร้อมแสดงลงในวิดีโอหนึ่งรายการ"""
    if not isinstance(v, dict):
        return v
    out = dict(v)
    out["size_text"] = size_text(v.get("size"))
    out["time_text"] = time_text(v.get("duration"))
    out["seg_text"] = ("%s ชิ้น" % count_text(v.get("segments"))
                       if v.get("segments") else "")

    head = v.get("resolution") or v.get("ext") or "วิดีโอ"
    out["head_text"] = str(head)

    bits = []
    if out["time_text"]:
        bits.append(out["time_text"])
    if out["size_text"]:
        bits.append(out["size_text"])
    if out["seg_text"]:
        bits.append(out["seg_text"])
    if v.get("from_net"):
        bits.append("ดักได้จากชั้นเครือข่าย")
    out["meta_text"] = " · ".join(bits)

    tags = []
    if v.get("drm"):
        tags.append({"text": "ถอดรหัสไม่ได้", "kind": "no"})
    elif v.get("encrypted"):
        tags.append({"text": "เข้ารหัสแบบถอดได้", "kind": "lock"})
    hl = v.get("health") or {}
    if hl.get("expired"):
        tags.append({"text": "ลิงก์หมดอายุ", "kind": "no"})
    elif hl.get("proto"):
        tags.append({"text": "ต้องใช้เครื่องมือเฉพาะทาง", "kind": "warn"})
    elif hl.get("mine"):
        tags.append({"text": "ใช้ได้จากเครื่องนี้", "kind": ""})
    elif not hl.get("usable", True):
        tags.append({"text": "ใช้จากที่นี่ไม่ได้", "kind": "no"})
    out["tags"] = tags
    return out


# ==================================================================
#  ป้ายกำกับของตัวเลือกคุณภาพ
# ==================================================================

def quality_view(f):
    """เติมข้อความที่พร้อมแสดงลงในคุณภาพหนึ่งรายการ"""
    if not isinstance(f, dict):
        return f
    out = dict(f)
    chips = []
    fps = f.get("fps") or 0
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        fps = 0
    if fps >= 50:
        chips.append("%dfps" % round(fps))
    if f.get("codec"):
        chips.append(str(f["codec"]))
    if f.get("ext"):
        chips.append(str(f["ext"]).upper())
    if f.get("has_video") and not f.get("has_audio"):
        chips.append("รวมเสียงให้")

    if f.get("has_video"):
        h = f.get("height") or 0
        res = ("%dp" % h) if h else (f.get("note") or f.get("id") or "")
    else:
        res = "เสียง"

    out["chips"] = chips
    out["res_text"] = str(res)
    out["size_text"] = size_text(f.get("size"))
    return out


# ==================================================================
#  รายการรูปภาพ
# ==================================================================

SORTS = ("found", "name", "size", "ext")


def image_view(d):
    """เติมข้อความที่พร้อมแสดงลงในรูปหนึ่งใบ"""
    if not isinstance(d, dict):
        return d
    out = dict(d)
    out["size_text"] = size_text(d.get("size"))
    wh = ""
    if d.get("width") and d.get("height"):
        wh = "%s × %s" % (count_text(d["width"]), count_text(d["height"]))
    out["dim_text"] = wh
    bits = [x for x in (str(d.get("ext") or "").upper(), wh, out["size_text"]) if x]
    out["meta_text"] = " · ".join(bits)
    return out


def pick_images(items, q="", ext="", sort="found", desc=False):
    """
    กรอง เรียง แล้วจัดรูปรายการรูปภาพ

    เดิมงานนี้ทำในเบราว์เซอร์ทุกครั้งที่ผู้ใช้พิมพ์ค้นหาหรือเปลี่ยนตัวกรอง
    รายการหลักพันใบจึงทำให้หน้าเว็บหน่วง ย้ายมาทำที่นี่แทน
    """
    q = str(q or "").strip().lower()
    ext = str(ext or "").strip().lower()
    sort = sort if sort in SORTS else "found"

    got = []
    for i, d in enumerate(items or []):
        if not isinstance(d, dict):
            continue
        if ext and str(d.get("ext") or "").lower() != ext:
            continue
        if q:
            hay = "%s %s" % (d.get("filename") or "", d.get("url") or "")
            if q not in hay.lower():
                continue
        got.append((i, d))

    if sort == "name":
        got.sort(key=lambda p: str(p[1].get("filename") or "").lower())
    elif sort == "size":
        got.sort(key=lambda p: int(p[1].get("size") or 0))
    elif sort == "ext":
        got.sort(key=lambda p: (str(p[1].get("ext") or "").lower(),
                                str(p[1].get("filename") or "").lower()))
    if desc:
        got.reverse()

    out = []
    for i, d in got:
        view = image_view(d)
        view["at"] = i          # ตำแหน่งเดิมในรายการ ใช้อ้างตอนกดเปิดดู
        out.append(view)
    return out


def ext_counts(items):
    """นับจำนวนไฟล์แต่ละชนิด ใช้ทำตัวกรอง"""
    tally = {}
    for d in items or []:
        if isinstance(d, dict):
            e = str(d.get("ext") or "").lower()
            if e:
                tally[e] = tally.get(e, 0) + 1
    return [{"ext": e, "n": n, "text": "%s (%s)" % (e.upper(), count_text(n))}
            for e, n in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))]
