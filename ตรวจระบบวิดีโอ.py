# -*- coding: utf-8 -*-
"""
ตรวจระบบวิดีโอทั้งเส้นทาง ด้วยเว็บจำลองที่สร้างขึ้นเอง

รันด้วย  python ตรวจระบบวิดีโอ.py

ไฟล์นี้ไม่แตะเว็บภายนอกและไม่แตะข้อมูลจริง มันจะปั้นเว็บจำลองขึ้นมาเอง
แล้วยิงคำขอเข้าระบบผ่านตัวทดสอบของ Flask ทุกข้อในนี้มาจากอาการที่เคยเกิดขึ้นจริง

ต้องมี ffmpeg ในเครื่องก่อน เพราะใช้ปั้นไฟล์วิดีโอสำหรับทดสอบ
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ok = 0
bad = 0
TMP = tempfile.mkdtemp(prefix="alp-test-")


def check(name, passed, detail=""):
    global ok, bad
    if passed:
        ok += 1
        print("  ผ่าน  %s" % name)
    else:
        bad += 1
        print("  ตก    %s  %s" % (name, detail))


def ffmpeg_ready():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make(path, secs=6, size="320x180", audio=True):
    """ปั้นไฟล์วิดีโอสั้น ๆ ไว้ใช้ทดสอบ"""
    cmd = ["ffmpeg", "-v", "error",
           "-f", "lavfi", "-i", "testsrc=size=%s:rate=15:duration=%d" % (size, secs)]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % secs]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += ["-movflags", "+faststart", "-y", path]
    subprocess.run(cmd, check=True)
    return open(path, "rb").read()


def probe(data):
    """ดูว่าไฟล์นี้เปิดได้ไหม และมีสัญญาณอะไรอยู่ข้างใน"""
    p = os.path.join(TMP, "probe.mp4")
    with open(p, "wb") as f:
        f.write(data)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return set()
    return {x.strip() for x in r.stdout.split() if x.strip()}


# ==================================================================
#  เว็บจำลอง
# ==================================================================

def ump_num(v):
    """เขียนตัวเลขความยาวตามรูปแบบซองเฉพาะของผู้ให้บริการรายหนึ่ง"""
    if v < 0x80:
        return bytes([v])
    if v < 0x4000:
        return bytes([0x80 | (v & 0x3F), (v >> 6) & 0xFF])
    if v < 0x200000:
        return bytes([0xC0 | (v & 0x1F), (v >> 5) & 0xFF, (v >> 13) & 0xFF])
    return bytes([0xE0 | (v & 0x0F), (v >> 4) & 0xFF,
                  (v >> 12) & 0xFF, (v >> 20) & 0xFF])


def ump_part(kind, body):
    return ump_num(kind) + ump_num(len(body)) + body


def build_site():
    """เตรียมไฟล์ทุกแบบที่ต้องใช้ แล้วคืนตารางเส้นทาง"""
    d = os.path.join(TMP, "site")
    os.makedirs(d, exist_ok=True)
    whole = make(os.path.join(d, "whole.mp4"))
    src = os.path.join(d, "whole.mp4")

    # ชิ้นย่อยของสตรีม เล่นเดี่ยวไม่ได้ ระบบต้องซ่อมให้
    subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-c", "copy",
                    "-y", os.path.join(d, "chunk.ts")], check=True)
    chunk = open(os.path.join(d, "chunk.ts"), "rb").read()

    # สตรีมแบบเปิด
    op = os.path.join(d, "open")
    os.makedirs(op, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-c", "copy",
                    "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
                    "-hls_segment_filename", os.path.join(op, "s%d.ts"),
                    "-y", os.path.join(op, "index.m3u8")], check=True)

    # สตรีมเข้ารหัส
    en = os.path.join(d, "enc")
    os.makedirs(en, exist_ok=True)
    with open(os.path.join(en, "k.key"), "wb") as f:
        f.write(os.urandom(16))
    with open(os.path.join(en, "info"), "w") as f:
        f.write("http://KEYHOST/enc/k.key\n%s\n" % os.path.join(en, "k.key"))
    subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-c", "copy",
                    "-f", "hls", "-hls_time", "2", "-hls_list_size", "0",
                    "-hls_key_info_file", os.path.join(en, "info"),
                    "-hls_segment_filename", os.path.join(en, "e%d.ts"),
                    "-y", os.path.join(en, "index.m3u8")], check=True)

    # สตรีมที่มีการคุ้มครองลิขสิทธิ์ ระบบต้องไม่แตะ
    dr = os.path.join(d, "drm")
    os.makedirs(dr, exist_ok=True)
    with open(os.path.join(dr, "index.m3u8"), "w") as f:
        f.write("#EXTM3U\n#EXT-X-VERSION:5\n#EXT-X-TARGETDURATION:2\n"
                '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://a",'
                'KEYFORMAT="com.apple.streamingkeydelivery"\n'
                "#EXTINF:2.0,\nd0.ts\n#EXT-X-ENDLIST\n")
    with open(os.path.join(dr, "d0.ts"), "wb") as f:
        f.write(b"\x47" + os.urandom(3000))

    msg = b"sabr.malformed_config"
    ump_err = ump_part(44, b"\x0a" + bytes([len(msg)]) + msg)
    ump_ok = ump_part(20, b"\x00\x08\x00")
    for i in range(0, len(whole), 60000):
        ump_ok += ump_part(21, b"\x00" + whole[i:i + 60000])
    ump_ok += ump_part(22, b"\x00")

    page = (b'<!doctype html><html><head><title>Test Clip</title></head>'
            b'<body><video controls><source src="/whole.mp4" type="video/mp4">'
            b"</video></body></html>")

    return d, {
        "/": ("text/html", page, 200),
        "/whole.mp4": ("video/mp4", whole, 200),
        "/chunk": ("video/mp4", chunk, 200),
        "/denied": ("text/html", b"<html>no</html>", 403),
        "/ump-ok": ("application/vnd.yt-ump", ump_ok, 200),
        "/ump-err": ("application/vnd.yt-ump", ump_err, 200),
    }


# เครื่องมือจำลอง ใช้วัดเวลาโดยไม่ต้องแตะเว็บจริง
#
# ทางหลักของเว็บวิดีโอสั้นทำท่าล้มเหลวช้า ๆ ส่วนทางสำรองแรกตอบเร็ว
# ถ้าระบบไล่ถามทีละทางจะใช้เวลารวมแปดวินาที ถ้าถามพร้อมกันจะจบในสอง
FAKE_TOOL = '''
import os, sys, time, json
a = sys.argv[1:]
if "--version" in a:
    print("2026.07.04"); raise SystemExit(0)
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "ถูกเรียก.txt"), "a") as f:
    f.write("x\\n")
host = ""
for i, x in enumerate(a):
    if x == "--extractor-args":
        host = a[i + 1]
clip = json.dumps({"title": "คลิปทดสอบ", "duration": 12,
                   "extractor_key": "Mock", "thumbnail": "http://x/t.jpg",
                   "formats": [{"format_id": "h264_540p", "ext": "mp4",
                                "height": 540, "width": 960, "vcodec": "h264",
                                "acodec": "aac", "filesize": 1234567,
                                "url": "http://x/v.mp4"}]})
if "api22" in host:
    time.sleep(2.0); print(clip); raise SystemExit(0)
if "api16" in host:
    time.sleep(5.0); print(clip); raise SystemExit(0)
if any("tiktok" in x for x in a):
    time.sleep(6.0)
    # ถ้ายังมีชีวิตอยู่ถึงตรงนี้ แปลว่าไม่มีใครสั่งหยุด
    open(os.path.join(HERE, "ยังไม่ตาย.txt"), "w").close()
    sys.stderr.write("ERROR: Unable to extract universal data for rehydration\\n")
    raise SystemExit(1)
time.sleep(2.0); print(clip); raise SystemExit(0)
'''


# เครื่องมือจำลอง ใช้วัดเวลาโดยไม่ต้องแตะเว็บจริง
#
# ทางหลักของเว็บวิดีโอสั้นทำท่าล้มเหลวช้า ๆ ส่วนทางสำรองแรกตอบเร็ว
# ถ้าระบบไล่ถามทีละทางจะใช้เวลารวมแปดวินาที ถ้าถามพร้อมกันจะจบในสอง
FAKE_TOOL = '''
import os, sys, time, json
a = sys.argv[1:]
if "--version" in a:
    print("2026.07.04"); raise SystemExit(0)
HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "ถูกเรียก.txt"), "a") as f:
    f.write("x\\n")
host = ""
for i, x in enumerate(a):
    if x == "--extractor-args":
        host = a[i + 1]
clip = json.dumps({"title": "คลิปทดสอบ", "duration": 12,
                   "extractor_key": "Mock", "thumbnail": "http://x/t.jpg",
                   "formats": [{"format_id": "h264_540p", "ext": "mp4",
                                "height": 540, "width": 960, "vcodec": "h264",
                                "acodec": "aac", "filesize": 1234567,
                                "url": "http://x/v.mp4"}]})
if "api22" in host:
    time.sleep(2.0); print(clip); raise SystemExit(0)
if "api16" in host:
    time.sleep(5.0); print(clip); raise SystemExit(0)
if any("tiktok" in x for x in a):
    time.sleep(6.0)
    # ถ้ายังมีชีวิตอยู่ถึงตรงนี้ แปลว่าไม่มีใครสั่งหยุด
    open(os.path.join(HERE, "ยังไม่ตาย.txt"), "w").close()
    sys.stderr.write("ERROR: Unable to extract universal data for rehydration\\n")
    raise SystemExit(1)
time.sleep(2.0); print(clip); raise SystemExit(0)
'''


PORT = [0]


def serve(root, table):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            p = self.path.split("?")[0]
            if p in table:
                ct, body, code = table[p]
            else:
                f = os.path.join(root, p.lstrip("/"))
                if not os.path.isfile(f):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = open(f, "rb").read()
                if f.endswith(".m3u8"):
                    body = body.replace(b"http://KEYHOST",
                                        b"http://127.0.0.1:%d" % PORT[0])
                    ct = "application/vnd.apple.mpegurl"
                elif f.endswith(".key"):
                    ct = "application/octet-stream"
                else:
                    ct = "video/mp2t"
                code = 200
            self.send_response(code)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_GET

    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    PORT[0] = s.server_address[1]
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % PORT[0]


# ==================================================================

def main():
    if not ffmpeg_ready():
        print("  ต้องติดตั้ง ffmpeg ก่อนจึงจะรันชุดทดสอบนี้ได้")
        return 1

    root, table = build_site()
    base = serve(root, table)

    import app as A
    import users
    import billing
    import helper

    A.app.config["TESTING"] = True
    A.app.config["APP_CONFIG"]["allow_private_network"] = True
    c = A.app.test_client()
    who = {"email": "ตรวจระบบ@local", "name": "ตรวจระบบ"}
    try:
        users.create(who["email"], who["name"], "Abcdef12")
    except Exception:
        pass
    with c.session_transaction() as ss:
        ss["user"] = who
        ss["fresh"] = True
    billing.grant(who, 9000000, "ชุดทดสอบ")

    def post(path, **body):
        return c.post(path, json=body)

    print("=== ไฟล์เดียวจบ ===")
    r = post("/api/video-file", url=base + "/whole.mp4")
    check("บันทึกได้", r.status_code == 200, r.status_code)
    check("ไบต์ตรงกับต้นทาง", r.data == table["/whole.mp4"][1])
    check("ไม่ต้องซ่อม จึงส่งต่อตรง", r.headers.get("X-Repaired") is None)
    check("ชื่อไฟล์ไม่ปนนามสกุลรูป",
          ".jpg" not in r.headers.get("Content-Disposition", ""))

    print()
    print("=== ชิ้นย่อยของสตรีม เดิมได้ไฟล์ที่เปิดไม่ขึ้น ===")
    r = post("/api/video-file", url=base + "/chunk")
    check("บันทึกได้", r.status_code == 200, r.status_code)
    check("ระบบซ่อมไฟล์ให้", r.headers.get("X-Repaired") == "1")
    check("ไฟล์ที่ได้เปิดได้จริง", "video" in probe(r.data))

    print()
    print("=== ซองเฉพาะของผู้ให้บริการ ===")
    r = post("/api/video-file", url=base + "/ump-ok")
    check("มีเนื้อไฟล์ในซอง แกะออกมาได้", r.status_code == 200, r.status_code)
    check("ไบต์ตรงกับต้นทาง", r.data == table["/whole.mp4"][1])
    r = post("/api/video-file", url=base + "/ump-err")
    j = r.get_json() or {}
    check("เป็นใบแจ้งเหตุ ต้องไม่ส่งไฟล์เสีย", r.status_code != 200, r.status_code)
    check("บอกรหัสจริงที่ปลายทางส่งมา",
          j.get("code") == "sabr.malformed_config", j.get("code"))
    # ลูกค้าต้องไม่เห็นชื่อเครื่องมือเบื้องหลัง และต้องไม่ถูกยื่นคำสั่งให้ไปพิมพ์เอง
    check("ชี้ทางต่อให้ โดยไม่ยื่นคำสั่งให้ลูกค้า",
          j.get("use_helper") is True and "tool" not in j, sorted(j))
    check("ใบแจ้งเหตุไม่เอ่ยชื่อเครื่องมือเบื้องหลัง",
          "yt-dlp" not in json.dumps(j, ensure_ascii=False))

    print()
    print("=== ปลายทางปฏิเสธ ===")
    r = post("/api/video-file", url=base + "/denied")
    check("ไม่บันทึกขยะ", r.status_code != 200, r.status_code)

    print()
    print("=== สตรีม ===")
    r = post("/api/video-build", url=base + "/open/index.m3u8",
             segments=4, mp4=True)
    check("สตรีมแบบเปิด ประกอบได้", "video" in probe(r.data), r.status_code)
    r = post("/api/video-build", url=base + "/enc/index.m3u8",
             segments=4, mp4=True)
    check("สตรีมเข้ารหัส ถอดแล้วประกอบได้", "video" in probe(r.data), r.status_code)
    r = post("/api/video-build", url=base + "/drm/index.m3u8", segments=2)
    check("มีการคุ้มครองลิขสิทธิ์ ต้องไม่แตะ", r.status_code != 200, r.status_code)

    print()
    print("=== ดูตัวอย่าง ===")
    for path, label in (("/whole.mp4", "ไฟล์ปกติ"), ("/chunk", "ชิ้นย่อย"),
                        ("/ump-ok", "ซองเฉพาะ")):
        r = c.get("/api/video-preview?kind=file&url=" + base + path)
        check("ดูตัวอย่าง %s" % label, "video" in probe(r.data), r.status_code)

    print()
    print("=== ตัวช่วยภายนอก ===")
    st = c.get("/api/helper").get_json() or {}
    if not st.get("ready"):
        print("  ข้าม  ยังไม่ได้ติดตั้ง %s ในเครื่องนี้" % st.get("tool"))
    else:
        r = post("/api/helper-info", url=base + "/")
        j = r.get_json() or {}
        check("อ่านคุณภาพได้", bool(j.get("formats")), j.get("error"))
        check("ทุกรายการมีรหัสสั่งงานแนบมา",
              all("pick" in f for f in j.get("formats", [])))

        t0 = time.time()
        r = c.post("/api/helper-get",
                   json={"url": base + "/", "format": "bv*+ba/b"},
                   buffered=False)
        mid, fid, err, end = [], None, None, 0.0
        buf = ""
        for chunk in r.response:
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                ev, data = "", ""
                for line in raw.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data += line[5:].strip()
                if ev == "progress":
                    mid.append(time.time() - t0)
                elif ev in ("done", "failed"):
                    d = json.loads(data or "{}")
                    fid, err = d.get("file"), d.get("error")
                    end = time.time() - t0
        check("ดาวน์โหลดสำเร็จ", bool(fid), err)
        check("ความคืบหน้าไหลออกมาระหว่างทาง ไม่ใช่ตอนจบ",
              len(mid) >= 2 and end > 0 and max(mid) < end,
              "ข่าวคราว %d ครั้ง" % len(mid))
        if fid:
            got = c.get("/api/helper-file/" + fid)
            check("รับไฟล์ได้", got.status_code == 200, got.status_code)
            check("ได้ทั้งภาพและเสียง", {"video", "audio"} <= probe(got.data),
                  probe(got.data))
            check("รับซ้ำไม่ได้",
                  c.get("/api/helper-file/" + fid).status_code == 404)

    print()
    print("=== ความเร็วตอนกดค้นหา ===")
    #
    # อาการเดิม ระบบอ่านหน้าเว็บให้เสร็จก่อน แล้วค่อยไปถามคุณภาพต่อ
    # ผู้ใช้จึงรอสองรอบต่อกัน ทั้งที่สองขั้นนี้ไม่ได้ใช้ผลของกันและกัน
    fake = os.path.join(TMP, "faketool.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write(FAKE_TOOL)

    keep_find, keep_scan = helper.find, A.scan_video_iter
    helper._SEEN.clear()
    helper.find = lambda: [sys.executable, fake]

    PACE = [3.0]

    def paced_scan(u, **kw):
        """
        แทนขั้นอ่านหน้าเว็บ ให้กินเวลาตามที่ตั้งไว้จะได้วัดได้

        คืนที่อยู่ปลายทางคนละอันกับที่รับมา เลียนแบบลิงก์ย่อที่ถูกส่งต่อ
        เคยพลาดตรงนี้มาแล้ว ระบบไปถามคุณภาพด้วยที่อยู่ปลายทางอีกรอบ
        กลายเป็นถามสองครั้งและช้ากว่าเดิม
        """
        yield "progress", {"stage": "start", "text": "เริ่ม"}
        time.sleep(PACE[0])
        yield "result", {"page_url": u + "?ถูกส่งต่อ", "videos": [],
                         "stats": {}}

    def listen(link):
        """กดค้นหาหนึ่งครั้ง คืนเวลาที่แต่ละเหตุการณ์มาถึงกับเนื้อของมัน"""
        t0 = time.time()
        r = c.get("/api/video-stream?url=%s&level=1" % link, buffered=False)
        at, seen, buf = {}, {}, ""
        for chunk in r.response:
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                ev, data = "", ""
                for line in raw.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data += line[5:].strip()
                if ev:
                    at.setdefault(ev, time.time() - t0)
                    if ev in ("result", "quality") and ev not in seen:
                        try:
                            seen[ev] = json.loads(data or "{}")
                        except ValueError:
                            seen[ev] = {}
        return at, seen

    A.scan_video_iter = paced_scan
    short = base + "/"
    try:
        at, seen = listen(short)

        check("ได้ผลค้นหา", "result" in at, sorted(at))
        check("ได้ตัวเลือกคุณภาพ", "quality" in at, sorted(at))
        if "result" in at and "quality" in at:
            print("  คุณภาพ %.2f วินาที · ผลค้นหา %.2f วินาที"
                  % (at["quality"], at["result"]))
            # อ่านหน้าเว็บสามวินาที ถามคุณภาพสองวินาที
            # ทำพร้อมกันแล้วคุณภาพต้องมาถึงก่อน ไม่ต้องรอให้อ่านหน้าเว็บจบ
            check("ตัวเลือกคุณภาพไม่รอผลค้นหา", at["quality"] < 2.9,
                  "%.2f วินาที" % at["quality"])
            check("อะไรเสร็จก่อนส่งก่อน", at["quality"] < at["result"],
                  "คุณภาพ %.2f ผลค้นหา %.2f" % (at["quality"], at["result"]))
            # แผงถูกวาดไปแล้ว ผลค้นหาต้องพาของเดิมมาด้วย ไม่งั้นแผงจะหายไป
            check("ผลค้นหาไม่ล้างแผงที่วาดไปแล้ว",
                  bool(seen.get("result", {}).get("panel_html")))
            check("หน้าเว็บได้ที่อยู่เดียวกับที่ใช้ถามคุณภาพ",
                  seen.get("result", {}).get("helper_url") == short,
                  seen.get("result", {}).get("helper_url"))

        # ลิงก์ย่อที่ถูกส่งต่อ ต้องถามปลายทางครั้งเดียว ไม่ใช่ถามซ้ำอีกที่อยู่
        hits = 0
        mark = os.path.join(TMP, "ถูกเรียก.txt")
        if os.path.isfile(mark):
            hits = len(open(mark).read().split())
        check("ถามปลายทางครั้งเดียว แม้ที่อยู่จะถูกส่งต่อ", hits == 1,
              "ถามไป %d ครั้ง" % hits)

        # กลับกัน อ่านหน้าเว็บเสร็จก่อน ตัวเลือกคุณภาพตามมาทีหลัง
        #
        # เคยพลาดตรงนี้จนต้องกดค้นสองรอบ รอบแรกได้ผลค้นหาแล้วสายถูกวางทิ้ง
        # ตัวเลือกที่ตามมาจึงไม่มีวันถึงหน้าจอ ค้างที่ "กำลังอ่านคุณภาพ" ตลอด
        PACE[0] = 0.2
        helper._SEEN.clear()
        at2, seen2 = listen(short + "?รอบสอง")
        print("  ผลค้นหา %.2f วินาที · คุณภาพ %.2f วินาที"
              % (at2.get("result", -1), at2.get("quality", -1)))
        check("ผลค้นหามาก่อนก็ยังได้ตัวเลือกคุณภาพครบ",
              "quality" in at2 and bool(seen2.get("quality", {}).get("panel_html")),
              sorted(at2))
        check("บอกหน้าเว็บว่ายังมีของตามมา อย่าเพิ่งวางสาย",
              seen2.get("result", {}).get("quality_wait") is True,
              seen2.get("result", {}).get("quality_wait"))
        check("ผลค้นหาไม่ต้องรอตัวเลือกคุณภาพ",
              at2.get("result", 99) < at2.get("quality", 0),
              "ผลค้นหา %.2f คุณภาพ %.2f"
              % (at2.get("result", -1), at2.get("quality", -1)))
        PACE[0] = 3.0

        # กลับกัน อ่านหน้าเว็บเสร็จก่อน ตัวเลือกคุณภาพตามมาทีหลัง
        #
        # เคยพลาดตรงนี้จนต้องกดค้นสองรอบ รอบแรกได้ผลค้นหาแล้วสายถูกวางทิ้ง
        # ตัวเลือกที่ตามมาจึงไม่มีวันถึงหน้าจอ ค้างที่ "กำลังอ่านคุณภาพ" ตลอด
        PACE[0] = 0.2
        helper._SEEN.clear()
        at2, seen2 = listen(short + "?รอบสอง")
        print("  ผลค้นหา %.2f วินาที · คุณภาพ %.2f วินาที"
              % (at2.get("result", -1), at2.get("quality", -1)))
        check("ผลค้นหามาก่อนก็ยังได้ตัวเลือกคุณภาพครบ",
              "quality" in at2 and bool(seen2.get("quality", {}).get("panel_html")),
              sorted(at2))
        check("บอกหน้าเว็บว่ายังมีของตามมา อย่าเพิ่งวางสาย",
              seen2.get("result", {}).get("quality_wait") is True,
              seen2.get("result", {}).get("quality_wait"))
        check("ผลค้นหาไม่ต้องรอตัวเลือกคุณภาพ",
              at2.get("result", 99) < at2.get("quality", 0),
              "ผลค้นหา %.2f คุณภาพ %.2f"
              % (at2.get("result", -1), at2.get("quality", -1)))
        PACE[0] = 3.0

        # ทางสำรองของเว็บที่มีหลายทาง ต้องถามพร้อมกัน ไม่ใช่ไล่ทีละทาง
        helper._SEEN.clear()
        t0 = time.time()
        got = helper.info("https://www.tiktok.com/@a/video/1")
        took = time.time() - t0
        print("  เว็บที่มีสามทาง ใช้เวลา %.2f วินาที (ไล่ทีละทางต้องใช้ 8.0)"
              % took)
        check("ทางสำรองถามพร้อมกัน", took < 4.5 and not got.get("error"),
              "%.2f วินาที %s" % (took, got.get("error") or ""))

        # ที่อยู่เดิมที่เพิ่งถามไป ต้องตอบได้ทันทีโดยไม่ไปกวนปลายทางซ้ำ
        t0 = time.time()
        helper.info("https://www.tiktok.com/@a/video/1")
        check("ถามที่อยู่เดิมซ้ำได้ทันที", time.time() - t0 < 0.2)

        # ทางที่ยังค้างอยู่ตอนได้คำตอบแล้ว ต้องถูกสั่งหยุด
        # ปล่อยทิ้งไว้จะกลายเป็นงานค้างในเครื่องลูกค้าโดยไม่มีใครรู้
        time.sleep(5.0)
        check("ทางที่ไม่ต้องการแล้ว ถูกสั่งหยุด",
              not os.path.isfile(os.path.join(TMP, "ยังไม่ตาย.txt")))

        # ทางที่ยังค้างอยู่ตอนได้คำตอบแล้ว ต้องถูกสั่งหยุด
        # ปล่อยทิ้งไว้จะกลายเป็นงานค้างในเครื่องลูกค้าโดยไม่มีใครรู้
        time.sleep(5.0)
        check("ทางที่ไม่ต้องการแล้ว ถูกสั่งหยุด",
              not os.path.isfile(os.path.join(TMP, "ยังไม่ตาย.txt")))
    finally:
        helper.find, A.scan_video_iter = keep_find, keep_scan
        helper._SEEN.clear()

    print()
    print("=== ความเร็วตอนกดค้นหา ===")
    #
    # อาการเดิม ระบบอ่านหน้าเว็บให้เสร็จก่อน แล้วค่อยไปถามคุณภาพต่อ
    # ผู้ใช้จึงรอสองรอบต่อกัน ทั้งที่สองขั้นนี้ไม่ได้ใช้ผลของกันและกัน
    fake = os.path.join(TMP, "faketool.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write(FAKE_TOOL)

    keep_find, keep_scan = helper.find, A.scan_video_iter
    helper._SEEN.clear()
    helper.find = lambda: [sys.executable, fake]

    PACE = [3.0]

    def paced_scan(u, **kw):
        """
        แทนขั้นอ่านหน้าเว็บ ให้กินเวลาตามที่ตั้งไว้จะได้วัดได้

        คืนที่อยู่ปลายทางคนละอันกับที่รับมา เลียนแบบลิงก์ย่อที่ถูกส่งต่อ
        เคยพลาดตรงนี้มาแล้ว ระบบไปถามคุณภาพด้วยที่อยู่ปลายทางอีกรอบ
        กลายเป็นถามสองครั้งและช้ากว่าเดิม
        """
        yield "progress", {"stage": "start", "text": "เริ่ม"}
        time.sleep(PACE[0])
        yield "result", {"page_url": u + "?ถูกส่งต่อ", "videos": [],
                         "stats": {}}

    def listen(link):
        """กดค้นหาหนึ่งครั้ง คืนเวลาที่แต่ละเหตุการณ์มาถึงกับเนื้อของมัน"""
        t0 = time.time()
        r = c.get("/api/video-stream?url=%s&level=1" % link, buffered=False)
        at, seen, buf = {}, {}, ""
        for chunk in r.response:
            buf += chunk.decode("utf-8", "replace")
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                ev, data = "", ""
                for line in raw.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data += line[5:].strip()
                if ev:
                    at.setdefault(ev, time.time() - t0)
                    if ev in ("result", "quality") and ev not in seen:
                        try:
                            seen[ev] = json.loads(data or "{}")
                        except ValueError:
                            seen[ev] = {}
        return at, seen

    A.scan_video_iter = paced_scan
    short = base + "/"
    try:
        at, seen = listen(short)

        check("ได้ผลค้นหา", "result" in at, sorted(at))
        check("ได้ตัวเลือกคุณภาพ", "quality" in at, sorted(at))
        if "result" in at and "quality" in at:
            print("  คุณภาพ %.2f วินาที · ผลค้นหา %.2f วินาที"
                  % (at["quality"], at["result"]))
            # อ่านหน้าเว็บสามวินาที ถามคุณภาพสองวินาที
            # ทำพร้อมกันแล้วคุณภาพต้องมาถึงก่อน ไม่ต้องรอให้อ่านหน้าเว็บจบ
            check("ตัวเลือกคุณภาพไม่รอผลค้นหา", at["quality"] < 2.9,
                  "%.2f วินาที" % at["quality"])
            check("อะไรเสร็จก่อนส่งก่อน", at["quality"] < at["result"],
                  "คุณภาพ %.2f ผลค้นหา %.2f" % (at["quality"], at["result"]))
            # แผงถูกวาดไปแล้ว ผลค้นหาต้องพาของเดิมมาด้วย ไม่งั้นแผงจะหายไป
            check("ผลค้นหาไม่ล้างแผงที่วาดไปแล้ว",
                  bool(seen.get("result", {}).get("panel_html")))
            check("หน้าเว็บได้ที่อยู่เดียวกับที่ใช้ถามคุณภาพ",
                  seen.get("result", {}).get("helper_url") == short,
                  seen.get("result", {}).get("helper_url"))

        # ลิงก์ย่อที่ถูกส่งต่อ ต้องถามปลายทางครั้งเดียว ไม่ใช่ถามซ้ำอีกที่อยู่
        hits = 0
        mark = os.path.join(TMP, "ถูกเรียก.txt")
        if os.path.isfile(mark):
            hits = len(open(mark).read().split())
        check("ถามปลายทางครั้งเดียว แม้ที่อยู่จะถูกส่งต่อ", hits == 1,
              "ถามไป %d ครั้ง" % hits)

        # ทางสำรองของเว็บที่มีหลายทาง ต้องถามพร้อมกัน ไม่ใช่ไล่ทีละทาง
        helper._SEEN.clear()
        t0 = time.time()
        got = helper.info("https://www.tiktok.com/@a/video/1")
        took = time.time() - t0
        print("  เว็บที่มีสามทาง ใช้เวลา %.2f วินาที (ไล่ทีละทางต้องใช้ 8.0)"
              % took)
        check("ทางสำรองถามพร้อมกัน", took < 4.5 and not got.get("error"),
              "%.2f วินาที %s" % (took, got.get("error") or ""))

        # ที่อยู่เดิมที่เพิ่งถามไป ต้องตอบได้ทันทีโดยไม่ไปกวนปลายทางซ้ำ
        t0 = time.time()
        helper.info("https://www.tiktok.com/@a/video/1")
        check("ถามที่อยู่เดิมซ้ำได้ทันที", time.time() - t0 < 0.2)
    finally:
        helper.find, A.scan_video_iter = keep_find, keep_scan
        helper._SEEN.clear()

    print()
    print("=== ระบบดูแลตัวช่วยเอง ลูกค้าไม่ต้องกดอะไร ===")
    calls = []
    keep_update = helper.update
    helper.update = lambda *a, **k: (calls.append(1),
                                     (True, "เก่า", "ใหม่", ""))[1]
    try:
        helper._FIXED[0] = 0

        # หน้าธรรมดาที่ไม่มีคลิป เป็นคนละอาการ ปรับรุ่นไปก็ไม่ช่วย
        # เคยรวมสองอาการนี้ไว้ด้วยกัน ค้นเว็บทั่วไปทีก็ไปลงโปรแกรมใหม่ที
        no_fix = helper.catch_up("ERROR: Unsupported URL: https://example.com")
        check("หน้าที่ไม่มีคลิป ไม่ต้องเสียเวลาปรับรุ่น",
              no_fix is False and not calls, "ปรับไป %d รอบ" % len(calls))

        got_fix = helper.catch_up("ERROR: Unable to extract webpage")
        check("ตัวช่วยตามเว็บไม่ทัน ระบบปรับรุ่นให้เอง",
              got_fix is True and len(calls) == 1, "ปรับไป %d รอบ" % len(calls))

        # ปรับถี่ ๆ ไม่ช่วยอะไร มีแต่ทำให้ผู้ใช้รอเปล่า
        got_again = helper.catch_up("ERROR: Unable to extract webpage")
        check("ปรับรุ่นแล้วเว้นระยะ ไม่ปรับซ้ำรัว ๆ",
              got_again is False and len(calls) == 1, "ปรับไป %d รอบ" % len(calls))
    finally:
        helper.update = keep_update
        helper._FIXED[0] = 0

    _k, note, _r = helper.read_error("ERROR: Unable to extract webpage")
    check("ข้อความที่ลูกค้าเห็น ไม่สั่งให้ไปกดอะไรเอง",
          "กดปุ่ม" not in note and "yt-dlp" not in note, note)

    print()
    print("=== ระบบดูแลตัวช่วยเอง ลูกค้าไม่ต้องกดอะไร ===")
    calls = []
    keep_update = helper.update
    helper.update = lambda *a, **k: (calls.append(1),
                                     (True, "เก่า", "ใหม่", ""))[1]
    try:
        helper._FIXED[0] = 0

        # หน้าธรรมดาที่ไม่มีคลิป เป็นคนละอาการ ปรับรุ่นไปก็ไม่ช่วย
        # เคยรวมสองอาการนี้ไว้ด้วยกัน ค้นเว็บทั่วไปทีก็ไปลงโปรแกรมใหม่ที
        no_fix = helper.catch_up("ERROR: Unsupported URL: https://example.com")
        check("หน้าที่ไม่มีคลิป ไม่ต้องเสียเวลาปรับรุ่น",
              no_fix is False and not calls, "ปรับไป %d รอบ" % len(calls))

        got_fix = helper.catch_up("ERROR: Unable to extract webpage")
        check("ตัวช่วยตามเว็บไม่ทัน ระบบปรับรุ่นให้เอง",
              got_fix is True and len(calls) == 1, "ปรับไป %d รอบ" % len(calls))

        # ปรับถี่ ๆ ไม่ช่วยอะไร มีแต่ทำให้ผู้ใช้รอเปล่า
        got_again = helper.catch_up("ERROR: Unable to extract webpage")
        check("ปรับรุ่นแล้วเว้นระยะ ไม่ปรับซ้ำรัว ๆ",
              got_again is False and len(calls) == 1, "ปรับไป %d รอบ" % len(calls))
    finally:
        helper.update = keep_update
        helper._FIXED[0] = 0

    _k, note, _r = helper.read_error("ERROR: Unable to extract webpage")
    check("ข้อความที่ลูกค้าเห็น ไม่สั่งให้ไปกดอะไรเอง",
          "กดปุ่ม" not in note and "yt-dlp" not in note, note)

    print()
    print("=== หน้าเว็บ ===")
    check("หน้าใช้งานเปิดได้", c.get("/app").status_code == 200)
    check("หน้าแนะนำเปิดได้", c.get("/").status_code == 200)

    print()
    print("  ผ่าน %d  ตก %d" % (ok, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
