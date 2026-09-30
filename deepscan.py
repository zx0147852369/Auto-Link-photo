# -*- coding: utf-8 -*-
"""
deepscan.py — ส่วนขยายสำหรับการค้นหาระดับที่ 4 “ลึกที่สุด”

ระดับ 1 ถึง 3 อ่านหน้าที่ระบุและหน้าย่อยจำนวนหนึ่ง
ระดับ 4 เพิ่มการไล่หาแหล่งที่ระดับอื่นไม่ได้แตะ ได้แก่

  • แผนผังเว็บไซต์ (sitemap.xml) ทั้งแบบไฟล์เดียวและแบบมีดัชนีซ้อน
  • ไฟล์ robots.txt เพื่อหาที่อยู่ของแผนผังเว็บไซต์
  • ฟีดข่าว RSS และ Atom
  • ไฟล์ประกาศแอปบนเว็บ (manifest) ซึ่งเก็บชุดไอคอนความละเอียดสูง
  • ไฟล์สไตล์ที่ถูกเรียกซ้อนกันหลายชั้นด้วยคำสั่งนำเข้า
  • เฟรมที่ซ้อนอยู่ในเฟรมอีกที
  • ที่อยู่รูปที่เขียนเป็นข้อความอยู่ในไฟล์ข้อมูล JSON

เรื่องการใช้ทรัพยากรเครื่อง
  งานนี้เป็นงานรอเครือข่ายกับอ่านข้อความเป็นหลัก ไม่ใช่งานคำนวณตัวเลขจำนวนมาก
  การ์ดจอจึงช่วยอะไรไม่ได้ ตัวที่ทำให้เร็วขึ้นจริงคือจำนวนการเชื่อมต่อพร้อมกัน
  ซึ่งปรับได้ด้วยค่า workers ด้านล่าง ส่วนหน่วยความจำใช้เก็บผลที่พบไว้ทั้งหมด
  ระหว่างทำงาน เพื่อไม่ต้องอ่านซ้ำ
"""

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

# ค่าตั้งของระดับ 4 — ตัวเลขเหล่านี้ผู้ดูแลปรับได้จากไฟล์ตั้งค่า
ULTRA = {
    "pages": 60,             # จำนวนหน้าสูงสุดที่จะไล่อ่าน
    "assets": 120,           # จำนวนไฟล์สไตล์และสคริปต์สูงสุดต่อหนึ่งหน้า
    "verify": 3000,          # จำนวนลิงก์สูงสุดที่จะตรวจสอบว่ามีอยู่จริง
    "workers": 32,           # จำนวนการเชื่อมต่อพร้อมกัน
    "sitemap_urls": 500,     # จำนวนที่อยู่สูงสุดที่ดึงจากแผนผังเว็บไซต์
    "css_depth": 3,          # ความลึกของการไล่ตามคำสั่งนำเข้าในไฟล์สไตล์
    "frame_depth": 3,        # ความลึกของเฟรมที่ซ้อนกัน
    "render": True,          # เปิดหน้าเว็บจริงด้วยเบราว์เซอร์เบื้องหลังถ้ามี
}

SITEMAP_GUESSES = [
    "/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
    "/sitemap/sitemap.xml", "/wp-sitemap.xml", "/sitemap1.xml",
]

FEED_GUESSES = ["/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml",
                "/index.xml"]

RE_XML_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
RE_XML_IMAGE = re.compile(r"<image:loc>\s*([^<\s]+)\s*</image:loc>", re.I)
RE_ROBOTS_SITEMAP = re.compile(r"^\s*sitemap\s*:\s*(\S+)", re.I | re.M)


def limits(cfg=None):
    """ค่าตั้งของระดับ 4 รวมค่าที่ผู้ดูแลแก้ไว้"""
    out = dict(ULTRA)
    for k, v in (cfg or {}).items():
        if k in out and isinstance(v, type(out[k])):
            out[k] = v
    # กันค่าที่ทำให้ระบบทำงานหนักเกินจนใช้ไม่ได้
    out["pages"] = max(1, min(500, int(out["pages"])))
    out["assets"] = max(1, min(600, int(out["assets"])))
    out["verify"] = max(1, min(20000, int(out["verify"])))
    out["workers"] = max(1, min(64, int(out["workers"])))
    out["sitemap_urls"] = max(0, min(5000, int(out["sitemap_urls"])))
    out["css_depth"] = max(0, min(6, int(out["css_depth"])))
    out["frame_depth"] = max(0, min(6, int(out["frame_depth"])))
    return out


# ==================================================================
#  แผนผังเว็บไซต์และฟีด
# ==================================================================

def sitemap_candidates(fetch, root, cap=6):
    """
    หาที่อยู่ของแผนผังเว็บไซต์

    ดูจากไฟล์ robots.txt ก่อน เพราะเป็นที่ที่เว็บไซต์ประกาศไว้อย่างเป็นทางการ
    ถ้าไม่พบจึงลองที่อยู่ที่นิยมใช้กัน
    """
    found = []
    txt, _, _ = fetch(urljoin(root, "/robots.txt"))
    if txt:
        for m in RE_ROBOTS_SITEMAP.finditer(txt[:200000]):
            u = m.group(1).strip()
            if u.startswith("http") and u not in found:
                found.append(u)
    for path in SITEMAP_GUESSES:
        u = urljoin(root, path)
        if u not in found:
            found.append(u)
    return found[:cap]


def read_sitemap(fetch, url, cap, depth=0, seen=None):
    """
    อ่านแผนผังเว็บไซต์ คืน (รายชื่อหน้า, รายชื่อรูปที่ประกาศไว้)

    แผนผังบางแห่งเป็นดัชนีที่ชี้ไปยังแผนผังย่อยอีกที จึงต้องไล่ตามลงไป
    และบางแห่งประกาศที่อยู่รูปไว้ตรง ๆ ซึ่งเป็นรูปต้นฉบับความละเอียดเต็ม
    """
    seen = seen if seen is not None else set()
    if depth > 2 or url in seen or len(seen) > 40:
        return [], []
    seen.add(url)

    txt, _, ctype = fetch(url)
    if not txt or ("xml" not in (ctype or "").lower() and "<loc" not in txt[:4000]):
        return [], []

    pages, images = [], []
    is_index = "<sitemapindex" in txt[:4000].lower()

    for m in RE_XML_IMAGE.finditer(txt):
        images.append(m.group(1).strip())
        if len(images) >= cap:
            break

    locs = [m.group(1).strip() for m in RE_XML_LOC.finditer(txt)]
    if is_index:
        for child in locs[:20]:
            p, i = read_sitemap(fetch, child, cap, depth + 1, seen)
            pages += p
            images += i
            if len(pages) >= cap:
                break
    else:
        pages = locs

    return pages[:cap], images[:cap]


def read_feed(fetch, url, cap=200):
    """อ่านฟีดข่าว คืน (รายชื่อหน้า, รายชื่อรูป)"""
    txt, _, ctype = fetch(url)
    if not txt:
        return [], []
    low = (ctype or "").lower()
    if "xml" not in low and "rss" not in low and "<rss" not in txt[:2000].lower() \
            and "<feed" not in txt[:2000].lower():
        return [], []

    pages, images = [], []
    try:
        root = ET.fromstring(txt.encode("utf-8", "replace"))
    except ET.ParseError:
        return [], []

    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        if tag == "link":
            href = el.get("href") or (el.text or "").strip()
            if href and href.startswith("http"):
                pages.append(href)
        elif tag in ("guid", "id") and (el.text or "").startswith("http"):
            pages.append(el.text.strip())
        elif tag in ("enclosure", "thumbnail", "content"):
            u = el.get("url") or el.get("src") or ""
            if u.startswith("http"):
                images.append(u)
        if len(pages) >= cap and len(images) >= cap:
            break
    return pages[:cap], images[:cap]


# ==================================================================
#  ไฟล์ประกาศแอปบนเว็บ
# ==================================================================

def read_manifest(fetch, url, base):
    """ดึงชุดไอคอนจากไฟล์ประกาศแอป ซึ่งมักเป็นภาพความละเอียดสูงหลายขนาด"""
    txt, final, _ = fetch(url)
    if not txt:
        return []
    try:
        d = json.loads(txt)
    except (ValueError, TypeError):
        return []
    out = []
    for key in ("icons", "screenshots", "shortcuts"):
        items = d.get(key)
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            src = it.get("src") or ""
            if src:
                out.append(urljoin(final or base, src))
            for sub in (it.get("icons") or []):
                if isinstance(sub, dict) and sub.get("src"):
                    out.append(urljoin(final or base, sub["src"]))
    return out


# ==================================================================
#  ไฟล์ข้อมูล JSON ที่ฝังอยู่ในหน้า
# ==================================================================

def urls_from_json_blob(text, base, exts, cap=400):
    """
    ไล่หาที่อยู่รูปในโครงสร้างข้อมูล JSON ทุกชั้น

    เว็บสมัยใหม่มักฝังข้อมูลทั้งหน้าไว้เป็น JSON ก้อนเดียวในแท็กสคริปต์
    แล้วให้สคริปต์ไปวาดเป็นรูปทีหลัง การอ่านตรงนี้จึงได้รูปที่ยังไม่ถูกวาด
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []

    out = []
    seen = set()

    def walk(node, depth=0):
        if len(out) >= cap or depth > 12:
            return
        if isinstance(node, str):
            s = node.strip()
            if len(s) > 8 and len(s) < 2000:
                low = s.split("?")[0].rsplit(".", 1)[-1].lower()
                if low in exts and s not in seen:
                    seen.add(s)
                    try:
                        out.append(urljoin(base, s))
                    except ValueError:
                        pass
        elif isinstance(node, dict):
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    return out


# ==================================================================
#  เปิดหน้าเว็บจริงด้วยเบราว์เซอร์เบื้องหลัง
# ==================================================================

_render_checked = False
_render_ready = False


def render_available():
    """
    เครื่องนี้มีเบราว์เซอร์เบื้องหลังให้ใช้หรือไม่

    ตรวจครั้งเดียวแล้วจำไว้ เพราะการตรวจแต่ละครั้งใช้เวลาพอสมควร
    ถ้าไม่มี ระบบจะข้ามขั้นตอนนี้ไปโดยไม่แจ้งข้อผิดพลาด
    """
    global _render_checked, _render_ready
    if _render_checked:
        return _render_ready
    _render_checked = True
    try:
        from playwright.sync_api import sync_playwright   # noqa: F401
        _render_ready = True
    except Exception:
        _render_ready = False
    return _render_ready


def render_page(url, wait_ms=2500, scrolls=6, timeout_ms=45000):
    """
    เปิดหน้าเว็บจริง รอให้สคริปต์ทำงาน เลื่อนหน้าลงเพื่อให้รูปที่โหลดภายหลังปรากฏ
    แล้วคืนเนื้อหาหน้าที่ได้ พร้อมที่อยู่รูปทุกใบที่เบราว์เซอร์ดาวน์โหลดจริง

    ขั้นตอนนี้กินหน่วยความจำและซีพียูมากที่สุดในระบบ เพราะเปิดเบราว์เซอร์เต็มตัว
    แต่เป็นวิธีเดียวที่ได้รูปของหน้าที่สร้างเนื้อหาด้วยสคริปต์ทั้งหมด

    คืน (html, รายชื่อรูปที่เบราว์เซอร์โหลด) หรือ (None, []) ถ้าทำไม่ได้
    """
    if not render_available():
        return None, []
    seen = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = ctx.new_page()

            def on_response(res):
                try:
                    if "image" in (res.headers.get("content-type") or ""):
                        seen.append(res.url)
                except Exception:
                    pass
            page.on("response", on_response)

            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)

            # เลื่อนหน้าลงทีละช่วง เพื่อให้รูปแบบโหลดเมื่อเลื่อนถึงปรากฏครบ
            for _ in range(max(0, scrolls)):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(450)
            page.wait_for_timeout(600)

            html = page.content()
            browser.close()
        return html, list(dict.fromkeys(seen))
    except Exception:
        return None, list(dict.fromkeys(seen))
