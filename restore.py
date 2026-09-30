# -*- coding: utf-8 -*-
"""
กู้ไฟล์โครงการคืนจากประวัติการสนทนาที่เก็บไว้ในเครื่อง

ประวัติการสนทนาทุกครั้งถูกบันทึกเป็นไฟล์ .jsonl ไว้ในเครื่องนี้
ในนั้นมีคำสั่งสร้างไฟล์และคำสั่งแก้ไฟล์ทุกครั้ง พร้อมเนื้อหาเต็ม
สคริปต์นี้อ่านทั้งหมด เรียงตามเวลา แล้วเล่นซ้ำทีละขั้นเหมือนย้อนเทป

ผลลัพธ์ไปอยู่ในโฟลเดอร์ _restored ไม่เขียนทับของเดิม
และเขียนรายงานไว้ที่ _restore_report.txt
"""

import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_restored")
REPORT = os.path.join(HERE, "_restore_report.txt")
NAME = os.path.basename(HERE).lower()          # "auto link photo"

LINES = []


def say(text=""):
    print(text)
    LINES.append(text)


APPDATA = os.environ.get("APPDATA", "")
LOCAL = os.environ.get("LOCALAPPDATA", "")
HOME = os.environ.get("USERPROFILE", "")

# ที่ที่ประวัติการสนทนามักถูกเก็บไว้ ดูให้ครบทุกที่ ไม่หยุดที่ที่แรกที่เจอ
CANDIDATES = [
    os.path.join(APPDATA, "Claude"),
    os.path.join(LOCAL, "Claude"),
    os.path.join(APPDATA, "AnthropicClaude"),
    os.path.join(LOCAL, "AnthropicClaude"),
    os.path.join(HOME, ".claude"),
    os.path.join(HOME, ".config", "claude"),
]

# โฟลเดอร์ที่ไม่ต้องเข้าไปคุ้ย เสียเวลาเปล่า
SKIP = {"node_modules", "Cache", "cache", "GPUCache", "Code Cache",
        "blob_storage", "Crashpad", "Partitions", "Service Worker",
        "IndexedDB", "Local Storage", "Session Storage", "__pycache__",
        "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache"}


def walk_jsonl(root, max_depth=12):
    out = []
    if not root or not os.path.isdir(root):
        return out
    base_depth = root.count(os.sep)
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        if base.count(os.sep) - base_depth > max_depth:
            dirs[:] = []
            continue
        for n in names:
            if n.lower().endswith(".jsonl"):
                out.append(os.path.join(base, n))
    return out


def under_project(path):
    """ที่อยู่นี้ชี้เข้าโฟลเดอร์โครงการหรือไม่ คืนที่อยู่แบบย่อถ้าใช่

    เทียบสองแบบ แบบตรงตัวกับแบบดูจากชื่อโฟลเดอร์โครงการ
    เผื่อเคยย้ายที่เก็บโครงการมาก่อน ที่อยู่ในประวัติจะไม่ตรงกับตอนนี้
    """
    p = str(path or "").replace("/", "\\")
    if not p:
        return ""
    low = p.lower()
    key = "\\" + NAME + "\\"
    at = low.find(key)
    if at >= 0:
        rel = p[at + len(key):]
        return rel if rel and ".." not in rel else ""
    try:
        base = os.path.normcase(os.path.normpath(HERE))
        q = os.path.normcase(os.path.normpath(p))
        if q.startswith(base + os.sep):
            return os.path.relpath(p, HERE)
    except Exception:
        pass
    return ""


LINE_NO = None


def unnumber(text):
    """ถอดเลขบรรทัดหน้าข้อความที่ได้จากการเปิดอ่านไฟล์ คืนเนื้อไฟล์จริง

    ผลของการเปิดอ่านไฟล์ถูกบันทึกไว้พร้อมเลขบรรทัดนำหน้าทุกบรรทัด
    ถ้าถอดออกมาได้ครบตั้งแต่บรรทัดที่หนึ่ง ถือว่าได้ไฟล์ทั้งใบ
    ใช้เป็นจุดตั้งต้นได้ดีกว่าการไล่ประกอบจากคำสั่งแก้ทีละครั้ง
    """
    global LINE_NO
    import re
    if LINE_NO is None:
        LINE_NO = re.compile(r"^\s*(\d+)\t(.*)$")
    if not isinstance(text, str) or "\t" not in text:
        return ""
    if "lines truncated" in text or "system-reminder" in text:
        return ""
    # เคยเปิดอ่านไฟล์ตอนที่มันเสียไปแล้ว ภาพถ่ายใบนั้นใช้ไม่ได้
    # ถ้าเผลอเอามาเป็นตัวตั้งต้น จะกลายเป็นเอาไฟล์เสียไปทับไฟล์ดี
    if "\x00" in text:
        return ""
    out = []
    want = 1
    for line in text.split("\n"):
        m = LINE_NO.match(line)
        if not m:
            if line.strip() == "":
                continue
            return ""
        if int(m.group(1)) != want:
            return ""
        out.append(m.group(2))
        want += 1
    return "\n".join(out) if len(out) > 3 else ""


def result_text(block):
    """ดึงข้อความออกจากผลของเครื่องมือ รองรับทั้งแบบข้อความและแบบรายการ"""
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        bits = []
        for x in c:
            if isinstance(x, dict) and isinstance(x.get("text"), str):
                bits.append(x["text"])
        return "\n".join(bits)
    return ""


def collect(files):
    """ไล่อ่านประวัติทุกไฟล์ คืน (รายการงานเรียงตามเวลา, โฟลเดอร์ที่เคยเห็น)"""
    jobs = []
    seen = {}
    seq = 0
    reads = {}          # รหัสคำสั่งเปิดอ่าน -> ที่อยู่ไฟล์
    for jf in files:
        try:
            fh = open(jf, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line or line[0] != "{":
                    continue
                seq += 1
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                when = str(obj.get("timestamp") or "")
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                blocks = msg.get("content")
                if not isinstance(blocks, list):
                    continue
                for b in blocks:
                    if not isinstance(b, dict):
                        continue

                    # ผลของการเปิดอ่านไฟล์ ใช้เป็นภาพถ่ายไฟล์ทั้งใบได้
                    if b.get("type") == "tool_result":
                        rel = reads.get(b.get("tool_use_id"))
                        if not rel:
                            continue
                        body = unnumber(result_text(b))
                        if body:
                            jobs.append((when, seq, "snap", rel, body, "",
                                         False))
                        continue

                    if b.get("type") != "tool_use":
                        continue
                    tool = b.get("name") or ""
                    arg = b.get("input")
                    if not isinstance(arg, dict):
                        continue
                    raw = str(arg.get("file_path") or "")
                    if tool == "Read" and not arg.get("offset"):
                        r = under_project(raw)
                        if r:
                            reads[b.get("id")] = r
                    if raw:
                        folder = os.path.dirname(raw)
                        seen[folder] = seen.get(folder, 0) + 1
                    rel = under_project(raw)
                    if not rel:
                        continue
                    if tool == "Write" and isinstance(arg.get("content"), str):
                        if "\x00" in arg["content"]:
                            continue
                        jobs.append((when, seq, "write", rel,
                                     arg["content"], "", False))
                    elif tool == "Edit" and isinstance(arg.get("old_string"),
                                                       str):
                        jobs.append((when, seq, "edit", rel,
                                     arg["old_string"],
                                     str(arg.get("new_string") or ""),
                                     bool(arg.get("replace_all"))))
    jobs.sort(key=lambda j: (j[0], j[1]))
    return jobs, seen


def replay(jobs):
    """เล่นซ้ำทุกขั้นตามลำดับเวลา คืนเนื้อไฟล์สุดท้ายของแต่ละไฟล์"""
    now = {}
    bad = {}
    miss = 0
    for when, seq, kind, rel, a, b, allof in jobs:
        if kind in ("write", "snap"):
            now[rel] = a
            continue
        cur = now.get(rel)
        if cur is None or a not in cur:
            miss += 1
            bad[rel] = bad.get(rel, 0) + 1
            continue
        now[rel] = cur.replace(a, b) if allof else cur.replace(a, b, 1)
    return now, miss, bad


def sweep_cache():
    """ทิ้งไฟล์ที่ Python แปลไว้ล่วงหน้า เพราะชุดที่กู้กลับมาเสียหาย

    Python จะหยิบไฟล์แปลแล้วมาใช้ก่อนไฟล์ต้นฉบับเสมอถ้ามันมีอยู่
    ชุดที่เสียทำให้ขึ้น bad marshal data ทั้งที่ต้นฉบับไม่มีปัญหา
    ลบทิ้งแล้ว Python จะแปลใหม่จากต้นฉบับให้เอง
    """
    import shutil
    gone = 0
    for base, dirs, names in os.walk(HERE):
        for n in list(names):
            if n.lower().endswith(".pyc"):
                try:
                    os.remove(os.path.join(base, n))
                    gone += 1
                except OSError:
                    pass
        for d in list(dirs):
            if d == "__pycache__":
                try:
                    shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                except OSError:
                    pass
                dirs.remove(d)
    say("  cleared %d stale compiled files" % gone)


def main():
    say()
    say("=" * 62)
    say("  REBUILD PROJECT FILES FROM CHAT HISTORY")
    say("=" * 62)
    say()
    sweep_cache()
    say("  project folder : %s" % HERE)
    say("  searching for chat history ...")

    files = []
    for root in CANDIDATES:
        got = walk_jsonl(root)
        if got:
            say("  %-52s %5d files" % (root, len(got)))
        files.extend(got)

    # กวาดทั้งโฟลเดอร์ผู้ใช้ด้วยเสมอ เพราะบางเครื่องเก็บประวัติไว้คนละที่
    # เช่นแอปที่ติดตั้งแบบแพ็กเกจ ข้อมูลจะไปอยู่ใต้ Packages อีกชั้นหนึ่ง
    say("  scanning the whole user folder, this can take a minute ...")
    files.extend(walk_jsonl(HOME, max_depth=14))

    files = sorted(set(files))
    say("  history files total: %d" % len(files))
    if not files:
        say()
        say("  NO HISTORY FILES FOUND ON THIS PC.")
        return 1

    # เอาเฉพาะไฟล์ที่เอ่ยถึงโครงการนี้จริง ๆ จะได้ไม่ต้องแกะทั้งหมด
    want = []
    tag = NAME.lower()
    for jf in files:
        try:
            with open(jf, encoding="utf-8", errors="replace") as f:
                for chunk in iter(lambda: f.read(1 << 20), ""):
                    if tag in chunk.lower():
                        want.append(jf)
                        break
        except OSError:
            continue
    say("  history files that mention this project: %d" % len(want))
    if want:
        files = want

    jobs, seen = collect(files)
    say("  steps that touch this project: %d" % len(jobs))

    if not jobs:
        say()
        say("  Could not match this project. Folders seen in the history:")
        top = sorted(seen.items(), key=lambda kv: -kv[1])[:25]
        for folder, n in top:
            say("    %5d  %s" % (n, folder))
        return 1

    got, miss, bad = replay(jobs)
    say("  rebuilt %d files   (steps that did not apply: %d)" % (len(got), miss))
    say()

    os.makedirs(OUT, exist_ok=True)
    done = 0
    for rel, text in sorted(got.items()):
        if "\x00" in text:          # กันไฟล์เสียหลุดออกไปอีกรอบ
            say("  SKIP (still damaged)  %s" % rel)
            continue
        dst = os.path.join(OUT, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError as e:
            say("  FAILED  %s  (%s)" % (rel, e))
            continue
        done += 1
        note = ("  <-- %d steps lost" % bad[rel]) if bad.get(rel) else ""
        say("  %-46s %9d chars%s" % (rel, len(text), note))

    say()
    say("  wrote %d files into  %s" % (done, OUT))
    say()
    install(got)
    return 0


def broken(path):
    """ไฟล์นี้ใช้ไม่ได้แล้วหรือยัง ไม่มีจริงหรือมีไบต์ศูนย์ปนอยู่ข้างใน"""
    if not os.path.isfile(path):
        return True
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    return False
                if b"\x00" in chunk:
                    return True
    except OSError:
        return True


def install(got):
    """เอาไฟล์ที่ประกอบได้ไปแทนที่ไฟล์ที่เสีย ของที่ยังดีอยู่ไม่แตะ"""
    say("=" * 62)
    say("  PUTTING GOOD FILES BACK IN PLACE")
    say("=" * 62)
    say()
    keep = os.path.join(HERE, "_broken_backup")
    fixed = skipped = 0
    for rel in sorted(got):
        live = os.path.join(HERE, rel)
        fresh = os.path.join(OUT, rel)
        if not os.path.isfile(fresh):
            continue
        if not broken(live):
            skipped += 1
            continue
        try:
            if os.path.isfile(live):
                bak = os.path.join(keep, rel)
                os.makedirs(os.path.dirname(bak), exist_ok=True)
                if os.path.isfile(bak):
                    os.remove(bak)
                os.replace(live, bak)
            os.makedirs(os.path.dirname(live), exist_ok=True)
            with open(fresh, encoding="utf-8") as a:
                text = a.read()
            with open(live, "w", encoding="utf-8", newline="") as b:
                b.write(text)
            fixed += 1
            say("  REPLACED  %s" % rel)
        except OSError as e:
            say("  FAILED    %s  (%s)" % (rel, e))

    say()
    say("  replaced %d broken files, left %d good ones alone" % (fixed,
                                                                 skipped))
    say("  the damaged originals were moved to  _broken_backup")
    say()
    salvage()
    verify()
    return 0


def salvage():
    """ขุดเนื้อที่ยังดีออกจากไฟล์ที่เสีย

    ไฟล์ที่กู้กลับมาแบบเสียมักไม่ได้พังทั้งใบ พังเฉพาะบางช่วงที่ถูกเขียนทับ
    ส่วนที่เหลือยังเป็นโค้ดจริงของเวอร์ชันล่าสุด ซึ่งใหม่กว่าที่ประกอบจากประวัติ
    ตรงนี้จึงดึงส่วนที่ยังอ่านได้ออกมาเก็บไว้ให้ครบทุกไฟล์
    """
    say("=" * 62)
    say("  DIGGING REAL CODE OUT OF THE DAMAGED FILES")
    say("=" * 62)
    say()
    out = os.path.join(HERE, "_salvage")
    os.makedirs(out, exist_ok=True)

    roots = [os.path.join(HERE, "_broken_backup"), HERE]
    seen = set()
    total = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for base, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs
                       if d not in ("_salvage", "_restored", "__pycache__")]
            for n in names:
                src = os.path.join(base, n)
                rel = os.path.relpath(src, root)
                if rel in seen or os.path.splitext(n)[1].lower() not in (
                        ".py", ".html", ".css", ".js", ".md", ".json", ".txt"):
                    continue
                try:
                    with open(src, "rb") as f:
                        raw = f.read()
                except OSError:
                    continue
                if b"\x00" not in raw:
                    continue
                seen.add(rel)
                kept = b"".join(p for p in raw.split(b"\x00") if p)
                text = kept.decode("utf-8", "replace")
                dst = os.path.join(out, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    with open(dst, "w", encoding="utf-8", newline="") as f:
                        f.write(text)
                except OSError:
                    continue
                total += 1
                pct = (len(kept) * 100 // len(raw)) if raw else 0
                head = text.lstrip()[:46].replace("\n", " ")
                say("  %-26s %7d/%7d bytes (%3d%%)  starts: %s"
                    % (rel, len(kept), len(raw), pct, head))

    say()
    say("  salvaged %d files into  _salvage" % total)
    say()


def verify():
    """ตรวจว่าไฟล์โปรแกรมแต่ละตัวยังอ่านเป็นภาษา Python ได้ครบหรือไม่

    ไฟล์ที่ประกอบกลับมาไม่ครบจะพังตรงกลาง ตัวนี้ชี้ให้เห็นว่าพังที่ไฟล์ไหน
    """
    say("=" * 62)
    say("  CHECKING EVERY PYTHON FILE")
    say("=" * 62)
    say()
    good = bad = 0
    for name in sorted(os.listdir(HERE)):
        if not name.lower().endswith(".py"):
            continue
        path = os.path.join(HERE, name)
        try:
            with open(path, encoding="utf-8", errors="strict") as f:
                src = f.read()
            compile(src, name, "exec")
            good += 1
            say("  OK      %-24s %8d chars" % (name, len(src)))
        except SyntaxError as e:
            bad += 1
            say("  BROKEN  %-24s line %s: %s" % (name, e.lineno, e.msg))
        except Exception as e:
            bad += 1
            say("  BROKEN  %-24s %s" % (name, e))
    say()
    say("=" * 62)
    say("  %d files fine, %d files still broken" % (good, bad))
    say("=" * 62)


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        import traceback
        LINES.append(traceback.format_exc())
        traceback.print_exc()
        code = 1
    try:
        with open(REPORT, "w", encoding="utf-8") as f:
            f.write("\n".join(LINES))
    except OSError:
        pass
    sys.exit(code)
