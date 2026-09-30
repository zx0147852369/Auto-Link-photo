# -*- coding: utf-8 -*-
"""
scraper.py — เครื่องมือสแกนรูปภาพเชิงลึก

ระดับการสแกน
  1  มาตรฐาน  : แท็ก HTML ทั้งหมด (img / srcset / picture / meta / icon / inline CSS / ลิงก์ตรง)
  2  ละเอียด   : + ไฟล์ CSS ภายนอก, สคริปต์และ JSON-LD, noscript, SVG, แอตทริบิวต์ data-* ทุกตัว
  3  ลึกที่สุด  : + iframe, หน้าย่อยในโดเมนเดียวกัน, สืบค้นไฟล์ต้นฉบับความละเอียดสูง,
                  ตรวจสอบทุกลิงก์แบบขนานและตัดลิงก์เสียทิ้ง
"""

import json
import re
import mimetypes
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse, urlunparse, unquote, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------------ ค่าคงที่

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

IMAGE_EXTS = {
    "jpg", "jpeg", "jfif", "png", "gif", "webp", "avif",
    "bmp", "svg", "ico", "tiff", "tif", "heic", "apng",
}

TIMEOUT = 20
MAX_BYTES = 10 * 1024 * 1024
MAX_ASSETS = 24          # จำนวนไฟล์ CSS/JS ภายนอกสูงสุดต่อหน้า
MAX_PAGES = 12           # จำนวนหน้าสูงสุดในการสแกนระดับ 3
MAX_VERIFY = 400         # จำนวนลิงก์สูงสุดที่ตรวจสอบ
WORKERS = 12

RE_URL_IN_TEXT = re.compile(
    r"""(?:https?:)?\\?/\\?/[^\s"'<>()\\]+?\.(?:%s)(?:\?[^\s"'<>()]*)?"""
    % "|".join(IMAGE_EXTS), re.I)
RE_PATH_IN_TEXT = re.compile(
    r"""["'](\\?/[^"'\s<>]+?\.(?:%s)(?:\?[^"']*)?)["']"""
    % "|".join(IMAGE_EXTS), re.I)
RE_CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.I | re.S)
RE_CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*['"]([^'"]+)['"]""", re.I)

SIZE_PARAMS = {"w", "h", "width", "height", "size", "resize", "fit", "crop",
               "quality", "q", "dpr", "sharp", "s", "maxwidth", "maxheight",
               "thumb", "thumbnail", "scale", "zoom"}


class ScrapeError(Exception):
    """ข้อผิดพลาดที่ต้องการแสดงให้ผู้ใช้เห็นโดยตรง"""


# ------------------------------------------------------------------ ยูทิลิตี้

def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ScrapeError("กรุณาระบุที่อยู่เว็บไซต์")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    p = urlparse(raw)
    if p.scheme not in ("http", "https"):
        raise ScrapeError("รองรับเฉพาะที่อยู่ที่ขึ้นต้นด้วย http:// หรือ https://")
    if not p.netloc:
        raise ScrapeError("รูปแบบที่อยู่เว็บไซต์ไม่ถูกต้อง")
    return raw


def clean_candidate(u: str) -> str:
    """ล้าง escape sequence ที่พบในสคริปต์ เช่น \\/  และ \\u002F"""
    if not u:
        return ""
    u = u.strip().strip('"\'')
    u = u.replace("\\/", "/")
    u = re.sub(r"\\u002[fF]", "/", u)
    u = re.sub(r"&amp;", "&", u)
    if u.startswith("//"):
        u = "https:" + u
    return u


def guess_ext(url: str) -> str:
    if url.startswith("data:"):
        mime = url[5:].split(";", 1)[0].split(",", 1)[0]
        return (mimetypes.guess_extension(mime or "") or "").lstrip(".").lower()
    p = urlparse(url)
    m = re.search(r"\.([A-Za-z0-9]{2,5})$", unquote(p.path))
    if m and m.group(1).lower() in IMAGE_EXTS:
        return m.group(1).lower()
    for k, v in parse_qsl(p.query):
        if k.lower() in ("format", "fm", "ext") and v.lower() in IMAGE_EXTS:
            return v.lower()
    return ""


def looks_like_image(url: str) -> bool:
    return url.startswith("data:image/") or guess_ext(url) != ""


def filename_of(url: str) -> str:
    if url.startswith("data:"):
        return "inline-image"
    name = unquote(urlparse(url).path).rstrip("/").split("/")[-1]
    return name or urlparse(url).netloc


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
    ha, hb = ha.split(":")[0], hb.split(":")[0]
    if ha == hb:
        return True
    pa, pb = ha.split("."), hb.split(".")
    return len(pa) > 1 and len(pb) > 1 and pa[-2:] == pb[-2:]


def parse_srcset(value: str):
    out = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split()
        out.append((bits[0], bits[1] if len(bits) > 1 else ""))
    return out


# ------------------------------------------------------- การเดาไฟล์ต้นฉบับ

def original_candidates(url: str):
    """สร้างรายการ URL ที่น่าจะเป็นไฟล์ต้นฉบับความละเอียดสูงกว่า"""
    if url.startswith("data:"):
        return []
    out, p = [], urlparse(url)
    path, query = p.path, p.query

    def build(new_path, new_query):
        cand = urlunparse((p.scheme, p.netloc, new_path, p.params, new_query, ""))
        if cand != url:
            out.append(cand)

    # 1) ตัดพารามิเตอร์ย่อขนาดออกจาก query string
    if query:
        kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                if k.lower() not in SIZE_PARAMS]
        if len(kept) != len(parse_qsl(query, keep_blank_values=True)):
            build(path, urlencode(kept))

    # 2) รูปแบบ WordPress / ทั่วไป: name-800x600.jpg → name.jpg
    m = re.sub(r"[-_]\d{2,5}x\d{2,5}(?=\.\w{2,5}$)", "", path)
    if m != path:
        build(m, query)

    # 3) คำต่อท้ายบอกขนาด: name_small.jpg / name-thumb.jpg
    m = re.sub(r"[-_](?:thumb|thumbnail|small|medium|mini|tiny|preview|"
               r"low|sm|md|s|m)(?=\.\w{2,5}$)", "", path, flags=re.I)
    if m != path:
        build(m, query)

    # 4) โฟลเดอร์บอกขนาด: /thumb/ /thumbs/ /small/ /preview/
    m = re.sub(r"/(?:thumbs?|thumbnails?|small|preview|resize[d]?|cache)/",
               "/", path, flags=re.I)
    if m != path:
        build(m, query)

    # 5) MediaWiki: /thumb/a/ab/File.jpg/220px-File.jpg → /a/ab/File.jpg
    m = re.match(r"^(.*)/thumb(/.+?)/[^/]+$", path)
    if m:
        build(m.group(1) + m.group(2), query)

    # 6) เส้นทางที่ฝังขนาดไว้: /w_300,h_200/ (Cloudinary) หรือ /300x200/
    m = re.sub(r"/(?:[wh]_\d+[,/]?)+(?=/)", "/", path)
    m = re.sub(r"/\d{2,4}x\d{2,4}(?=/)", "", m)
    if m != path:
        build(m, query)

    # 7) Google/Blogger: =s320-c หรือ /s320/
    m = re.sub(r"=[sw]\d+(?:-c)?$", "=s0", path)
    if m != path:
        build(m, query)
    m = re.sub(r"/s\d{2,4}(?:-c)?/", "/s0/", path)
    if m != path:
        build(m, query)

    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:4]


# ------------------------------------------------------------------ เครือข่าย

def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
    })
    return s


def decode_text(content: bytes, content_type: str = "") -> str:
    enc = ""
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"""charset=["']?([\w\-]+)""", content[:4096], re.I)
        if m:
            enc = m.group(1).decode("ascii", "ignore")
    for c in (enc, "utf-8", "cp874", "latin-1"):
        if not c:
            continue
        try:
            return content.decode(c)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def fetch_text(sess, url, referer=None, raise_on_error=False):
    """คืน (ข้อความ, url สุดท้าย, content-type) — คืน None ถ้าไม่ใช่ข้อความ"""
    headers = {"Referer": referer} if referer else {}
    try:
        r = sess.get(url, timeout=TIMEOUT, allow_redirects=True,
                     stream=True, headers=headers)
    except requests.exceptions.SSLError:
        if raise_on_error:
            raise ScrapeError("เชื่อมต่อไม่สำเร็จ: ใบรับรองความปลอดภัยของปลายทางไม่ถูกต้อง")
        return None, url, ""
    except requests.exceptions.Timeout:
        if raise_on_error:
            raise ScrapeError("เชื่อมต่อไม่สำเร็จ: ปลายทางตอบกลับช้าเกินกำหนด")
        return None, url, ""
    except requests.exceptions.RequestException:
        if raise_on_error:
            raise ScrapeError("เชื่อมต่อไม่สำเร็จ: ไม่พบเซิร์ฟเวอร์ปลายทาง หรือถูกปฏิเสธการเชื่อมต่อ")
        return None, url, ""

    ctype = r.headers.get("Content-Type", "")
    if r.status_code >= 400:
        r.close()
        if raise_on_error:
            raise ScrapeError(f"ปลายทางตอบกลับสถานะ {r.status_code} — "
                              f"อาจต้องเข้าสู่ระบบ หรือหน้าดังกล่าวไม่มีอยู่")
        return None, r.url, ctype
    if "image/" in ctype:
        r.close()
        return None, r.url, ctype

    data = r.raw.read(MAX_BYTES, decode_content=True)
    final = r.url
    r.close()
    return decode_text(data, ctype), final, ctype


def head_info(url, sess=None):
    s = sess or _session()
    try:
        r = s.head(url, timeout=12, allow_redirects=True,
                   headers={"Referer": url})
        if r.status_code >= 400 or "Content-Length" not in r.headers:
            r = s.get(url, timeout=12, allow_redirects=True, stream=True,
                      headers={"Referer": url, "Range": "bytes=0-0"})
            r.close()
    except requests.exceptions.RequestException:
        return {"ok": False, "status": 0, "bytes": None, "content_type": ""}

    size = r.headers.get("Content-Length")
    rng = r.headers.get("Content-Range", "")
    if rng and "/" in rng:
        tail = rng.split("/")[-1]
        size = tail if tail.isdigit() else size
    ctype = r.headers.get("Content-Type", "")
    return {
        "ok": r.status_code < 400 and (not ctype or "image" in ctype
                                       or "octet-stream" in ctype),
        "status": r.status_code,
        "bytes": int(size) if size and str(size).isdigit() else None,
        "content_type": ctype,
        "final_url": r.url,
    }


# ------------------------------------------------------- ตัวดึงจากเนื้อหา

def urls_from_css(text, base):
    out = []
    for m in RE_CSS_URL.finditer(text or ""):
        u = clean_candidate(m.group(2))
        if u and not u.startswith("#") and (looks_like_image(u) or u.startswith("data:image/")):
            out.append(urljoin(base, u))
    return out


def imports_from_css(text, base):
    return [urljoin(base, m.group(1)) for m in RE_CSS_IMPORT.finditer(text or "")]


def urls_from_script(text, base):
    out = []
    for m in RE_URL_IN_TEXT.finditer(text or ""):
        u = clean_candidate(m.group(0))
        if u.startswith("//"):
            u = "https:" + u
        out.append(urljoin(base, u))
    for m in RE_PATH_IN_TEXT.finditer(text or ""):
        out.append(urljoin(base, clean_candidate(m.group(1))))
    return out


def urls_from_jsonld(text, base):
    out = []
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return out

    keys = {"image", "thumbnailurl", "contenturl", "logo", "photo",
            "primaryimageofpage", "screenshot", "images"}

    def walk(node, in_image_key=False):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k.lower() in keys)
        elif isinstance(node, list):
            for v in node:
                walk(v, in_image_key)
        elif isinstance(node, str):
            u = clean_candidate(node)
            if u.startswith(("http://", "https://", "/")) and (in_image_key or looks_like_image(u)):
                out.append(urljoin(base, u))

    walk(data)
    return out


# ------------------------------------------------------------------ ตัวหลัก

class Scanner:
    def __init__(self, level=2, include_data_uri=False, follow_pages=False,
                 find_originals=True, verify=True):
        self.level = int(level)
        self.include_data_uri = include_data_uri
        self.follow_pages = follow_pages and self.level >= 3
        self.find_originals = find_originals and self.level >= 3
        self.verify = verify
        self.sess = _session()
        self.records = OrderedDict()
        self.stats = {"pages": 0, "css": 0, "scripts": 0, "iframes": 0,
                      "checked": 0, "removed": 0, "originals": 0}

    # ---- เก็บผลลัพธ์
    def add(self, raw, source, base, alt="", w="", h="", srcset="", page=""):
        u = clean_candidate(raw)
        if not u or u.startswith(("javascript:", "about:", "mailto:", "#")):
            return
        if u.startswith("data:"):
            if not (self.include_data_uri and u.startswith("data:image/")):
                return
            full = u[:200000]
        else:
            try:
                full = urljoin(base, u)
            except ValueError:
                return
            if urlparse(full).scheme not in ("http", "https"):
                return
            full = full.split("#")[0]

        if full in self.records:
            rec = self.records[full]
            if alt and not rec["alt"]:
                rec["alt"] = alt.strip()[:300]
            if w and not rec["width"]:
                rec["width"], rec["height"] = str(w), str(h)
            return

        self.records[full] = {
            "url": full,
            "source": source,
            "alt": (alt or "").strip()[:300],
            "filename": filename_of(full),
            "ext": guess_ext(full) or "-",
            "width": str(w or ""),
            "height": str(h or ""),
            "srcset": srcset or "",
            "host": urlparse(full).netloc,
            "page": page,
        }

    # ---- สแกน HTML หนึ่งหน้า
    def scan_html(self, html, base, page_url, progress=None):
        soup = BeautifulSoup(html, "html.parser")
        bt = soup.find("base", href=True)
        if bt:
            base = urljoin(base, bt["href"].strip())

        # --- ระดับ 1 : แท็กรูปโดยตรง
        for img in soup.find_all("img"):
            alt = img.get("alt", "")
            w, h = img.get("width", ""), img.get("height", "")
            ss = img.get("srcset") or img.get("data-srcset") or ""
            self.add(img.get("src"), "img", base, alt, w, h, ss, page_url)
            for u, _ in parse_srcset(ss):
                self.add(u, "srcset", base, alt, "", "", ss, page_url)
            for k, v in img.attrs.items():
                if k.startswith("data-") and isinstance(v, str) and v.strip():
                    if looks_like_image(v) or v.startswith(("http", "/")):
                        self.add(v, "lazy", base, alt, w, h, "", page_url)

        for s in soup.find_all("source"):
            ss = s.get("srcset") or s.get("data-srcset") or ""
            for u, _ in parse_srcset(ss):
                self.add(u, "picture", base, "", "", "", ss, page_url)
            self.add(s.get("src"), "picture", base, page=page_url)

        for meta in soup.find_all("meta"):
            key = (meta.get("property") or meta.get("name") or "").lower()
            if key in ("og:image", "og:image:url", "og:image:secure_url", "image",
                       "twitter:image", "twitter:image:src", "thumbnail",
                       "msapplication-tileimage", "itemprop"):
                self.add(meta.get("content"), "meta", base, page=page_url)

        for link in soup.find_all("link", href=True):
            rel = " ".join(link.get("rel") or []).lower()
            if "icon" in rel or "image_src" in rel or "preload" in rel:
                if "icon" in rel or looks_like_image(link["href"]):
                    self.add(link["href"], "icon", base, page=page_url)

        for el in soup.find_all(style=True):
            for u in urls_from_css(el["style"], base):
                self.add(u, "css", base, page=page_url)

        for a in soup.find_all("a", href=True):
            if looks_like_image(a["href"]):
                self.add(a["href"], "link", base,
                         a.get_text(strip=True)[:120], page=page_url)

        if self.level < 2:
            return soup, base

        # --- ระดับ 2 : เนื้อหาที่ซ่อนอยู่
        for tag in soup.find_all(["object", "embed", "video", "audio",
                                  "input", "track", "iframe"]):
            for attr in ("src", "data", "poster", "href"):
                v = tag.get(attr)
                if v and looks_like_image(v):
                    self.add(v, tag.name, base, page=page_url)

        for im in soup.find_all(["image", "use"]):
            v = im.get("href") or im.get("xlink:href")
            if v:
                self.add(v, "svg", base, page=page_url)

        for ns in soup.find_all("noscript"):
            inner = BeautifulSoup(ns.decode_contents(), "html.parser")
            for img in inner.find_all("img"):
                self.add(img.get("src"), "noscript", base,
                         img.get("alt", ""), page=page_url)
                for u, _ in parse_srcset(img.get("srcset") or ""):
                    self.add(u, "noscript", base, page=page_url)

        # แอตทริบิวต์ data-* บนทุกแท็ก
        for el in soup.find_all(True):
            for k, v in el.attrs.items():
                if not k.startswith("data-") or not isinstance(v, str):
                    continue
                v = v.strip()
                if len(v) > 4 and looks_like_image(v) and not v.startswith("data:"):
                    self.add(v, "data-attr", base, page=page_url)
                elif v.startswith("[") or v.startswith("{"):
                    for u in urls_from_jsonld(v, base):
                        self.add(u, "data-attr", base, page=page_url)

        # <style> ภายในหน้า
        for st in soup.find_all("style"):
            for u in urls_from_css(st.get_text(), base):
                self.add(u, "css", base, page=page_url)

        # <script> ภายในหน้า + JSON-LD
        for sc in soup.find_all("script"):
            stype = (sc.get("type") or "").lower()
            body = sc.string or sc.get_text() or ""
            if not body.strip():
                continue
            if "json" in stype:
                for u in urls_from_jsonld(body, base):
                    self.add(u, "json-ld", base, page=page_url)
            for u in urls_from_script(body, base):
                self.add(u, "script", base, page=page_url)

        # ไฟล์ CSS / JS ภายนอก
        assets = []
        for lk in soup.find_all("link", href=True):
            rel = " ".join(lk.get("rel") or []).lower()
            if "stylesheet" in rel:
                assets.append(("css", urljoin(base, lk["href"])))
        for sc in soup.find_all("script", src=True):
            assets.append(("js", urljoin(base, sc["src"])))

        for kind, aurl in assets[:MAX_ASSETS]:
            if not same_site(aurl, page_url) and kind == "js":
                continue      # ข้ามสคริปต์ของบุคคลที่สาม (โฆษณา/สถิติ)
            if progress:
                progress("asset", f"อ่านไฟล์ {kind.upper()}: {filename_of(aurl)}")
            text, furl, _ = fetch_text(self.sess, aurl, referer=page_url)
            if not text:
                continue
            if kind == "css":
                self.stats["css"] += 1
                for u in urls_from_css(text, furl):
                    self.add(u, "css-file", furl, page=page_url)
                for imp in imports_from_css(text, furl)[:6]:
                    itext, iurl, _ = fetch_text(self.sess, imp, referer=page_url)
                    if itext:
                        self.stats["css"] += 1
                        for u in urls_from_css(itext, iurl):
                            self.add(u, "css-file", iurl, page=page_url)
            else:
                self.stats["scripts"] += 1
                for u in urls_from_script(text, furl):
                    self.add(u, "js-file", furl, page=page_url)

        return soup, base

    # ---- ตรวจสอบลิงก์แบบขนาน
    def verify_all(self, progress=None):
        targets = [u for u in self.records if not u.startswith("data:")][:MAX_VERIFY]
        if not targets:
            return {}
        done = [0]
        info = {}

        def work(u):
            r = head_info(u, self.sess)
            done[0] += 1
            if progress and done[0] % 5 == 0:
                progress("verify", f"ตรวจสอบลิงก์ {done[0]}/{len(targets)}")
            return u, r

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for u, r in ex.map(work, targets):
                info[u] = r
        self.stats["checked"] = len(targets)

        if self.level >= 3:
            for u, r in info.items():
                if not r.get("ok"):
                    self.records.pop(u, None)
                    self.stats["removed"] += 1
        return info

    # ---- สืบค้นไฟล์ต้นฉบับความละเอียดสูง
    def upgrade_originals(self, info, progress=None):
        pairs = []
        for u, rec in list(self.records.items()):
            if u.startswith("data:"):
                continue
            for cand in original_candidates(u):
                if cand not in self.records:
                    pairs.append((u, cand))
        pairs = pairs[:180]
        if not pairs:
            return info
        if progress:
            progress("original", f"สืบค้นไฟล์ต้นฉบับ {len(pairs)} รายการ")

        def work(pair):
            src, cand = pair
            return src, cand, head_info(cand, self.sess)

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for src, cand, r in ex.map(work, pairs):
                if not r.get("ok"):
                    continue
                base_bytes = (info.get(src) or {}).get("bytes")
                cand_bytes = r.get("bytes")
                better = (base_bytes is None or cand_bytes is None
                          or cand_bytes > base_bytes * 1.05)
                if not better:
                    continue
                old = self.records.get(src)
                if not old or cand in self.records:
                    continue
                self.records[cand] = {
                    **old, "url": cand, "source": "original",
                    "filename": filename_of(cand), "ext": guess_ext(cand) or "-",
                    "width": "", "height": "", "host": urlparse(cand).netloc,
                }
                info[cand] = r
                self.stats["originals"] += 1
        return info


# ------------------------------------------------------- จุดเข้าใช้งานหลัก

def scan_iter(url, level=2, include_data_uri=False, follow_pages=False,
              find_originals=True, verify=True):
    """
    ตัวสร้าง (generator) คืนค่าเป็น tuple:
      ("progress", {stage, text})   ระหว่างทำงาน
      ("result",   {...})           เมื่อเสร็จสิ้น
    """
    url = normalize_url(url)
    sc = Scanner(level, include_data_uri, follow_pages, find_originals, verify)
    events = []

    def progress(stage, text):
        events.append({"stage": stage, "text": text})

    yield "progress", {"stage": "connect", "text": "กำลังเชื่อมต่อปลายทาง"}

    html, final_url, ctype = fetch_text(sc.sess, url, raise_on_error=True)

    # กรณีผู้ใช้ใส่ที่อยู่ไฟล์รูปโดยตรง
    if html is None:
        rec = {
            "url": final_url, "source": "direct", "alt": "",
            "filename": filename_of(final_url), "ext": guess_ext(final_url) or "-",
            "width": "", "height": "", "srcset": "",
            "host": urlparse(final_url).netloc, "page": final_url,
        }
        info = {final_url: head_info(final_url, sc.sess)}
        yield "result", {
            "page_url": final_url, "page_title": filename_of(final_url),
            "images": [rec], "info": info, "stats": sc.stats, "level": level,
        }
        return

    title = ""
    pages_done, queue = set(), [final_url]
    page_html = {final_url: (html, final_url)}
    page_limit = MAX_PAGES if sc.level >= 3 else 1

    while queue:
        purl = queue.pop(0)
        if purl in pages_done or len(pages_done) >= page_limit:
            continue
        pages_done.add(purl)

        if purl in page_html:
            phtml, pbase = page_html[purl]
        else:
            yield "progress", {"stage": "page", "text": f"อ่านหน้า: {purl[:90]}"}
            phtml, pbase, _ = fetch_text(sc.sess, purl, referer=final_url)
            if not phtml:
                continue

        yield "progress", {"stage": "parse",
                           "text": f"วิเคราะห์โครงสร้างหน้า ({len(pages_done)})"}
        soup, pbase = sc.scan_html(phtml, pbase, purl, progress=progress)
        sc.stats["pages"] += 1
        while events:
            yield "progress", events.pop(0)
        yield "progress", {"stage": "found",
                           "text": f"พบลิงก์รูปภาพแล้ว {len(sc.records)} รายการ"}

        if sc.level >= 3:
            # iframe ในโดเมนเดียวกัน
            for fr in soup.find_all("iframe", src=True):
                fsrc = urljoin(pbase, fr["src"])
                if same_site(fsrc, final_url) and fsrc not in pages_done:
                    sc.stats["iframes"] += 1
                    queue.append(fsrc)
            # หน้าย่อยในโดเมนเดียวกัน
            if sc.follow_pages:
                for a in soup.find_all("a", href=True):
                    nxt = urljoin(pbase, a["href"]).split("#")[0]
                    if (same_site(nxt, final_url) and nxt not in pages_done
                            and not looks_like_image(nxt) and nxt not in queue):
                        queue.append(nxt)

        if not title:
            t = soup.title.get_text(strip=True) if soup.title else ""
            title = t or urlparse(final_url).netloc

    info = {}
    if verify or sc.level >= 3:
        yield "progress", {"stage": "verify",
                           "text": f"ตรวจสอบลิงก์ {min(len(sc.records), MAX_VERIFY)} รายการ"}
        info = sc.verify_all(progress=progress)
        while events:
            yield "progress", events.pop(0)

    if sc.find_originals:
        yield "progress", {"stage": "original", "text": "สืบค้นไฟล์ต้นฉบับความละเอียดสูง"}
        info = sc.upgrade_originals(info, progress=progress)
        while events:
            yield "progress", events.pop(0)

    yield "result", {
        "page_url": final_url,
        "page_title": title or urlparse(final_url).netloc,
        "images": list(sc.records.values()),
        "info": info,
        "stats": sc.stats,
        "level": level,
    }


def scan(url, **kw):
    """เวอร์ชันเรียกใช้แบบปกติ (ไม่สตรีม)"""
    out = None
    for kind, payload in scan_iter(url, **kw):
        if kind == "result":
            out = payload
    return out
