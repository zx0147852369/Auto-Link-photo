# -*- coding: utf-8 -*-
"""
ตัวเชื่อมกับเครื่องมือดาวน์โหลดภายนอก

ระบบหลักของ Auto Link Photo อ่านหน้าเว็บแล้วดึงที่อยู่ไฟล์ออกมาตรง ๆ
วิธีนี้ใช้ได้กับเว็บส่วนใหญ่ แต่ผู้ให้บริการรายใหญ่บางรายไม่ได้ส่งไฟล์
ให้คนที่เปิดที่อยู่ตรง ๆ อีกแล้ว เขาเปลี่ยนไปรับคำขอตามรูปแบบของตัวเอง

ไฟล์นี้ไม่ได้เลียนแบบรูปแบบคำขอของใคร แต่ส่งงานต่อให้เครื่องมือ
ที่ผู้ใช้ติดตั้งไว้ในเครื่องเอง ทำหน้าที่เหมือนที่ระบบใช้ ffmpeg อยู่แล้ว
คือเรียกโปรแกรมภายนอกที่มีอยู่ ไม่ได้เขียนความสามารถนั้นขึ้นมาเอง

ข้อควรระวังด้านความปลอดภัยที่ยึดในไฟล์นี้
- เรียกโปรแกรมด้วยรายการอาร์กิวเมนต์เสมอ ไม่ผ่านตัวแปลคำสั่งของระบบ
  ที่อยู่เว็บจึงกลายเป็นคำสั่งไม่ได้
- ใส่เครื่องหมายปิดรายการตัวเลือกก่อนที่อยู่เสมอ
  ที่อยู่ที่ขึ้นต้นด้วยขีดจึงถูกอ่านเป็นตัวเลือกไม่ได้
- สั่งให้ข้ามไฟล์ตั้งค่าของผู้ใช้ กันไม่ให้ไฟล์ตั้งค่าที่มีคำสั่งแนบมา
  ถูกหยิบไปทำงานโดยไม่ตั้งใจ
- เขียนไฟล์ลงโฟลเดอร์ชั่วคราวที่กำหนดเองเท่านั้น และตั้งชื่อไฟล์เอง
  ชื่อไฟล์จากปลายทางจึงพาออกนอกโฟลเดอร์ไม่ได้
- จำกัดเวลาทำงาน ไม่ให้ค้างไปเรื่อย ๆ
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

TOOL = "yt-dlp"

# เวลารอสูงสุดของแต่ละงาน หน่วยเป็นวินาที
INFO_TIMEOUT = 90
GET_TIMEOUT = 3600

# ตัวเลือกที่ใส่ทุกครั้ง เพื่อความปลอดภัยและความคาดเดาได้
BASE_FLAGS = [
    "--ignore-config",      # ไม่อ่านไฟล์ตั้งค่าของผู้ใช้
    "--no-playlist",        # ที่อยู่เดียวคือไฟล์เดียว ไม่ลากทั้งชุดมา
    "--no-warnings",
    "--no-colors",
    "--restrict-filenames",
]


def _run(cmd, timeout, cwd=None):
    """เรียกโปรแกรมภายนอกแบบไม่ผ่านตัวแปลคำสั่ง"""
    return subprocess.run(
        cmd, capture_output=True, timeout=timeout, cwd=cwd,
        stdin=subprocess.DEVNULL,
    )


# ที่อยู่ของเครื่องมือที่หาเจอครั้งล่าสุด กับเวลาที่หา
#
# หนึ่งคำขอเรียก find() หลายรอบ ถ้าเครื่องมือไม่ได้อยู่ในตัวแปรระบบ
# แต่ละรอบต้องไล่เปิดดูสิบกว่าที่ ซึ่งช้าเป็นพิเศษบนเครื่องที่สแกนไวรัสอยู่
# ที่อยู่ของโปรแกรมไม่ได้ย้ายไปไหนระหว่างนั้น จึงจำไว้สั้น ๆ ได้
# จำเฉพาะตอนหาเจอ ถ้ายังไม่เจอต้องหาใหม่ทุกครั้ง ระบบจะได้เห็นทันทีที่ติดตั้งเสร็จ
_FOUND = [0.0, []]
_FOUND_TTL = 60


def find():
    """
    หาตัวเครื่องมือในเครื่อง

    คืนรายการคำสั่งที่พร้อมใช้ หรือรายการว่างถ้าไม่พบ
    หาได้สองแบบ คือเป็นโปรแกรมเดี่ยว หรือเป็นส่วนเสริมของ Python
    """
    if _FOUND[1] and time.time() - _FOUND[0] < _FOUND_TTL:
        return list(_FOUND[1])
    got = _look()
    if got:
        _FOUND[0] = time.time()
        _FOUND[1] = list(got)
    return got


def forget():
    """ลืมที่อยู่ที่จำไว้ เรียกหลังติดตั้งหรืออัปเดตเสร็จ"""
    _FOUND[0] = 0.0
    _FOUND[1] = []


def _look():
    exe = shutil.which(TOOL)
    if exe:
        return [exe]

    # บางเครื่องติดตั้งไว้แต่ยังไม่ได้เพิ่มที่อยู่ลงในตัวแปรระบบ
    for guess in _extra_paths():
        if os.path.isfile(guess) and os.access(guess, os.X_OK):
            return [guess]

    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return []


def _extra_paths():
    """ที่ที่เครื่องมือมักถูกติดตั้งไว้แต่ยังไม่อยู่ในตัวแปรระบบ"""
    out = []
    home = os.path.expanduser("~")
    names = ([TOOL + ".exe"] if os.name == "nt" else [TOOL])
    spots = [
        os.path.join(home, ".local", "bin"),
        os.path.join(home, "AppData", "Roaming", "Python", "Scripts"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Scripts"),
        os.path.join(os.path.dirname(sys.executable), "Scripts"),
        os.path.dirname(sys.executable),
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]
    for d in spots:
        for n in names:
            out.append(os.path.join(d, n))
    return out


def version():
    """อ่านรุ่นของเครื่องมือ คืนข้อความว่างถ้าเรียกไม่ได้"""
    cmd = find()
    if not cmd:
        return ""
    try:
        r = _run(cmd + ["--version"], 30)
    except (subprocess.SubprocessError, OSError):
        return ""
    if r.returncode != 0:
        return ""
    return (r.stdout or b"").decode("utf-8", "replace").strip()[:40]


def status():
    """สรุปสถานะให้หน้าเว็บแสดง"""
    cmd = find()
    if not cmd:
        return {"ready": False, "tool": TOOL, "version": "",
                "how": "ยังไม่พบเครื่องมือนี้ในเครื่อง"}
    v = version()
    return {"ready": bool(v), "tool": TOOL, "version": v,
            "how": "" if v else "พบเครื่องมือแต่เรียกใช้ไม่ได้"}


# ------------------------------------------------------------------
#  อ่านรายการคุณภาพที่มี
# ------------------------------------------------------------------

def _size_of(f):
    for k in ("filesize", "filesize_approx"):
        v = f.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return 0


VIDEO_EXT = ("mp4", "webm", "mkv", "mov", "flv", "avi", "m4v", "ts", "3gp")


def _tidy(f, guess=False):
    """ย่อข้อมูลคุณภาพหนึ่งรายการให้เหลือเท่าที่หน้าเว็บใช้

    guess ใช้ตอนที่ข้อมูลไม่ได้ระบุชนิดสัญญาณมา ให้เดาจากนามสกุลแทน
    ไม่งั้นไฟล์ที่มีทั้งภาพและเสียงจะถูกป้ายว่าเป็นเสียงอย่างเดียว
    """
    vc = f.get("vcodec") or ""
    ac = f.get("acodec") or ""
    if guess and not vc and not ac:
        vid = str(f.get("ext") or "").lower() in VIDEO_EXT
        return {
            "id": str(f.get("format_id") or ""),
            "ext": str(f.get("ext") or ""),
            "note": str(f.get("format_note") or "")[:40],
            "width": f.get("width") or 0,
            "height": f.get("height") or 0,
            "fps": f.get("fps") or 0,
            "size": _size_of(f),
            "vbr": f.get("vbr") or f.get("tbr") or 0,
            "has_video": vid,
            "has_audio": True,
        }
    vc = vc or "none"
    ac = ac or "none"
    return {
        "id": str(f.get("format_id") or ""),
        "ext": str(f.get("ext") or ""),
        "note": str(f.get("format_note") or "")[:40],
        "width": f.get("width") or 0,
        "height": f.get("height") or 0,
        "fps": f.get("fps") or 0,
        "size": _size_of(f),
        "vbr": f.get("vbr") or f.get("tbr") or 0,
        "has_video": vc != "none",
        "has_audio": ac != "none",
    }


def info(url, timeout=INFO_TIMEOUT):
    """
    ถามเครื่องมือว่าที่อยู่นี้มีอะไรให้บ้าง

    คืน dict มีชื่อเรื่อง ความยาว และรายการคุณภาพ
    ถ้าทำไม่ได้จะคืน dict ที่มีคีย์ error พร้อมเหตุผลจากเครื่องมือ
    """
    cmd = find()
    if not cmd:
        return {"error": "ยังไม่ได้ติดตั้งเครื่องมือนี้ในเครื่อง"}

    args = cmd + BASE_FLAGS + ["--dump-single-json", "--", url]
    try:
        r = _run(args, timeout)
    except subprocess.TimeoutExpired:
        return {"error": "อ่านข้อมูลนานเกินไป ยกเลิกแล้ว"}
    except (subprocess.SubprocessError, OSError) as e:
        return {"error": "เรียกเครื่องมือไม่สำเร็จ (%s)" % type(e).__name__}

    if r.returncode != 0:
        return {"error": _why(r.stderr)}

    try:
        raw = json.loads((r.stdout or b"").decode("utf-8", "replace"))
    except (ValueError, UnicodeError):
        return {"error": "อ่านผลลัพธ์จากเครื่องมือไม่ออก"}

    fmts = []
    for f in (raw.get("formats") or []):
        t = _tidy(f)
        if t["id"] and (t["has_video"] or t["has_audio"]):
            fmts.append(t)
    # บางหน้ามีไฟล์เดียวจบ เครื่องมือจึงไม่แจกเป็นรายการคุณภาพ
    # ต้องประกอบรายการเดียวขึ้นมาเอง ไม่งั้นหน้าเว็บจะว่างเปล่า
    if not fmts and raw.get("url"):
        one = _tidy(raw, guess=True)
        one["id"] = one["id"] or "best"
        one["note"] = one["note"] or "ไฟล์เดียวจบ"
        fmts = [one]
    fmts.sort(key=lambda x: (x["has_video"], x["height"], x["vbr"]), reverse=True)

    return {
        "title": str(raw.get("title") or "")[:200],
        "duration": int(raw.get("duration") or 0),
        "site": str(raw.get("extractor_key") or raw.get("extractor") or "")[:40],
        "thumb": str(raw.get("thumbnail") or "")[:600],
        "formats": fmts[:60],
    }


def _why(stderr):
    """ดึงเหตุผลจากข้อความที่เครื่องมือพิมพ์ออกมา"""
    text = (stderr or b"").decode("utf-8", "replace")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for l in reversed(lines):
        if l.upper().startswith("ERROR"):
            return l[:300]
    return (lines[-1][:300] if lines else "เครื่องมือทำงานไม่สำเร็จ")


# ------------------------------------------------------------------
#  ดาวน์โหลด
# ------------------------------------------------------------------

# รูปแบบบรรทัดความคืบหน้าที่สั่งให้เครื่องมือพิมพ์ออกมา
PROG_TPL = ("ALP|%(progress.downloaded_bytes)s|%(progress.total_bytes)s"
            "|%(progress.total_bytes_estimate)s|%(progress.speed)s"
            "|%(progress.eta)s")

SAFE_FMT = re.compile(r"^[A-Za-z0-9_.+-]{1,60}$")


def _num(s):
    try:
        v = float(s)
        return v if v == v and v not in (float("inf"), float("-inf")) else 0
    except (TypeError, ValueError):
        return 0


def fetch(url, outdir, fmt="", on_step=None, timeout=GET_TIMEOUT,
          merge=True):
    """
    สั่งดาวน์โหลดลงโฟลเดอร์ที่กำหนด

    outdir  โฟลเดอร์ปลายทาง ต้องเป็นโฟลเดอร์ที่ผู้เรียกสร้างเองแล้ว
    fmt     รหัสคุณภาพที่ผู้ใช้เลือก ปล่อยว่างให้เครื่องมือเลือกเอง
    on_step ฟังก์ชันรับความคืบหน้า รับ dict หนึ่งตัว

    คืน (ที่อยู่ไฟล์, ข้อความเหตุขัดข้อง)

    ถ้าพลาดเพราะเว็บเปลี่ยนหน้า จะปรับตัวช่วยให้เองแล้วลองใหม่หนึ่งรอบ
    ลูกค้าไม่ต้องกดอะไรทั้งสิ้น ตามกติกาข้อที่หนึ่งของโครงการ
    """
    path, why = _fetch_once(url, outdir, fmt, on_step, timeout, merge)
    if not path and catch_up(why):
        if on_step:
            on_step({"note": "ปรับตัวช่วยให้ตามเว็บทันแล้ว กำลังลองใหม่"})
        path, why = _fetch_once(url, outdir, fmt, on_step, timeout, merge)
    return path, why


def _fetch_once(url, outdir, fmt="", on_step=None, timeout=GET_TIMEOUT,
                merge=True):
    """ดาวน์โหลดหนึ่งรอบ ไม่ยุ่งกับการปรับรุ่น"""
    cmd = find()
    if not cmd:
        return "", "ยังไม่ได้ติดตั้งเครื่องมือนี้ในเครื่อง"

    if fmt and not SAFE_FMT.match(fmt):
        return "", "รหัสคุณภาพไม่ถูกต้อง"

    # ตั้งชื่อไฟล์เอง ไม่ใช้ชื่อจากปลายทาง
    # ชื่อจากปลายทางพาเขียนไฟล์ออกนอกโฟลเดอร์ได้
    stem = "alp-%d" % int(time.time() * 1000)
    args = cmd + BASE_FLAGS + [
        "--newline",
        "--progress",
        "--progress-template", PROG_TPL,
        "--paths", outdir,
        "-o", stem + ".%(ext)s",
        "--no-part",
    ]
    if merge:
        args += ["--merge-output-format", "mp4"]
    if fmt:
        args += ["-f", fmt]
    args += ["--", url]

    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, cwd=outdir)
    except (subprocess.SubprocessError, OSError) as e:
        return "", "เรียกเครื่องมือไม่สำเร็จ (%s)" % type(e).__name__

    started = time.time()
    try:
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("ALP|") and on_step:
                bits = line.split("|")
                total = _num(bits[2]) or _num(bits[3])
                on_step({
                    "done": _num(bits[1]),
                    "total": total,
                    "speed": _num(bits[4]),
                    "eta": _num(bits[5]),
                })
            elif on_step and line.startswith("[") and "]" in line:
                on_step({"note": line[:160]})
            if time.time() - started > timeout:
                p.kill()
                return "", "ดาวน์โหลดนานเกินกำหนด ยกเลิกแล้ว"
    finally:
        try:
            p.stdout.close()
        except Exception:
            pass
        err = b""
        try:
            err = p.stderr.read() or b""
            p.stderr.close()
        except Exception:
            pass
        p.wait()

    if p.returncode != 0:
        return "", _why(err)

    got = [n for n in os.listdir(outdir) if n.startswith(stem)]
    if not got:
        return "", "เครื่องมือทำงานจบแต่ไม่พบไฟล์ที่ได้"
    got.sort(key=lambda n: os.path.getsize(os.path.join(outdir, n)),
             reverse=True)
    return os.path.join(outdir, got[0]), ""


def pick_label(f):
    """ข้อความสั้น ๆ อธิบายคุณภาพหนึ่งรายการ"""
    if not f.get("has_video"):
        return "เสียงอย่างเดียว · %s" % (f.get("ext") or "")
    size = f.get("height") or 0
    base = ("%dp" % size) if size else (f.get("note") or f.get("id") or "")
    if f.get("fps") and f["fps"] >= 50:
        base += " %dfps" % int(f["fps"])
    if not f.get("has_audio"):
        base += " · ไม่มีเสียงในตัว"
    return base
