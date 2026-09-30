# -*- coding: utf-8 -*-
"""
กู้ไฟล์โครงการคืนจากประวัติการสนทนาที่เก็บไว้ในเครื่อง

วิธีทำงาน
  ประวัติการสนทนาทุกครั้งถูกบันทึกเป็นไฟล์ .jsonl ไว้ในเครื่องนี้
  ในนั้นมีคำสั่งสร้างไฟล์และคำสั่งแก้ไฟล์ทุกครั้งที่เคยทำ พร้อมเนื้อหาเต็ม
  สคริปต์นี้อ่านทั้งหมด เรียงตามเวลา แล้วเล่นซ้ำทีละขั้นเหมือนย้อนเทป
  ผลที่ได้คือไฟล์เวอร์ชันล่าสุดเท่าที่ประวัติบันทึกไว้

ผลลัพธ์จะไปอยู่ในโฟลเดอร์ _กู้คืนจากประวัติ ไม่เขียนทับของเดิม
"""

import glob
import json
import os
import sys

HISTORY = os.path.join(os.environ.get("APPDATA", ""), "Claude",
                       "local-agent-mode-sessions")
PROJECT = r"C:\Users\Windows\Desktop\Auto Link photo"
OUT = os.path.join(PROJECT, "_กู้คืนจากประวัติ")


def same_place(path):
    """ไฟล์นี้อยู่ในโฟลเดอร์โครงการหรือไม่ คืนที่อยู่แบบย่อถ้าใช่"""
    try:
        p = os.path.normcase(os.path.normpath(path))
        base = os.path.normcase(os.path.normpath(PROJECT))
    except Exception:
        return ""
    if p == base or not p.startswith(base + os.sep):
        return ""
    return os.path.relpath(path, PROJECT)


def collect():
    """ไล่อ่านประวัติทุกไฟล์ คืนรายการงานเรียงตามเวลา"""
    jobs = []
    files = glob.glob(os.path.join(HISTORY, "**", "*.jsonl"), recursive=True)
    print("  พบไฟล์ประวัติ %d ไฟล์" % len(files))
    seq = 0
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
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    tool = b.get("name") or ""
                    arg = b.get("input")
                    if not isinstance(arg, dict):
                        continue
                    rel = same_place(str(arg.get("file_path") or ""))
                    if not rel:
                        continue
                    if tool == "Write" and isinstance(arg.get("content"), str):
                        jobs.append((when, seq, "write", rel,
                                     arg["content"], "", False))
                    elif tool == "Edit" and isinstance(arg.get("old_string"), str):
                        jobs.append((when, seq, "edit", rel,
                                     arg["old_string"],
                                     str(arg.get("new_string") or ""),
                                     bool(arg.get("replace_all"))))
    jobs.sort(key=lambda j: (j[0], j[1]))
    return jobs


def replay(jobs):
    """เล่นซ้ำทุกขั้นตามลำดับเวลา คืนเนื้อไฟล์สุดท้ายของแต่ละไฟล์"""
    now = {}
    miss = 0
    for when, seq, kind, rel, a, b, allof in jobs:
        if kind == "write":
            now[rel] = a
            continue
        cur = now.get(rel)
        if cur is None or a not in cur:
            miss += 1
            continue
        now[rel] = cur.replace(a, b) if allof else cur.replace(a, b, 1)
    return now, miss


def main():
    print()
    print("=" * 62)
    print("  กู้ไฟล์คืนจากประวัติการสนทนา")
    print("=" * 62)
    print()

    if not os.path.isdir(HISTORY):
        print("  ไม่พบโฟลเดอร์ประวัติที่ %s" % HISTORY)
        return 1
    print("  อ่านประวัติจาก %s" % HISTORY)

    jobs = collect()
    print("  พบขั้นตอนที่เกี่ยวกับโครงการนี้ %d ขั้น" % len(jobs))
    if not jobs:
        print()
        print("  ไม่พบร่องรอยของไฟล์ในโครงการนี้เลย")
        return 1

    files, miss = replay(jobs)
    print("  ประกอบกลับได้ %d ไฟล์  (ขั้นที่ต่อไม่ติด %d ขั้น)" % (len(files), miss))
    print()

    os.makedirs(OUT, exist_ok=True)
    done = 0
    for rel, text in sorted(files.items()):
        dst = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            with open(dst, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except OSError as e:
            print("  เขียนไม่ได้ %s (%s)" % (rel, e))
            continue
        done += 1
        print("  %-40s %8d ตัวอักษร" % (rel, len(text)))

    print()
    print("=" * 62)
    print("  เขียนไฟล์คืนแล้ว %d ไฟล์" % done)
    print("  อยู่ในโฟลเดอร์  %s" % OUT)
    print("=" * 62)
    print()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        code = 1
    sys.exit(code)
