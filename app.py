# -*- coding: utf-8 -*-
"""
app.py — เว็บเซิร์ฟเวอร์
รัน:  python app.py   แล้วเปิด http://127.0.0.1:5000
"""

import io
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Flask, jsonify, render_template, request, Response, send_file

import auth
from scraper import (
    ScrapeError, scan, scan_iter, head_info, filename_of, USER_AGENT,
)

app = Flask(__name__)
try:
    app.json.ensure_ascii = False
except AttributeError:
    app.config["JSON_AS_ASCII"] = False

auth.install(app)          # ระบบเข้าสู่ระบบ (Google + รหัสผ่าน)


def _bool(v, default=False):
    if v is None:
        return default
    return str(v).lower() in ("1", "true", "yes", "on")


@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------ สแกนแบบสตรีม

@app.get("/api/scan-stream")
def api_scan_stream():
    """ส่งความคืบหน้าแบบเรียลไทม์ด้วย Server-Sent Events"""
    url = request.args.get("url", "")
    level = int(request.args.get("level", 2) or 2)
    opts = dict(
        level=max(1, min(3, level)),
        include_data_uri=_bool(request.args.get("data_uri")),
        follow_pages=_bool(request.args.get("follow")),
        find_originals=_bool(request.args.get("originals"), True),
        verify=_bool(request.args.get("verify"), True),
    )

    def gen():
        def sse(event, data):
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        try:
            for kind, payload in scan_iter(url, **opts):
                if kind == "progress":
                    yield sse("progress", payload)
                else:
                    payload["ok"] = True
                    payload["count"] = len(payload["images"])
                    yield sse("result", payload)
        except ScrapeError as e:
            yield sse("failed", {"error": str(e)})
        except Exception:
            yield sse("failed", {"error": "เกิดข้อผิดพลาดระหว่างประมวลผลหน้าเว็บนี้"})

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@app.post("/api/scan")
def api_scan():
    """สแกนแบบคำขอเดียว (สำรองกรณีเบราว์เซอร์ไม่รองรับ SSE)"""
    d = request.get_json(silent=True) or {}
    try:
        res = scan(
            d.get("url", ""),
            level=max(1, min(3, int(d.get("level", 2) or 2))),
            include_data_uri=bool(d.get("include_data_uri")),
            follow_pages=bool(d.get("follow_pages")),
            find_originals=bool(d.get("find_originals", True)),
            verify=bool(d.get("verify", True)),
        )
    except ScrapeError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception:
        return jsonify({"ok": False,
                        "error": "เกิดข้อผิดพลาดระหว่างประมวลผลหน้าเว็บนี้"}), 500
    res["ok"] = True
    res["count"] = len(res["images"])
    return jsonify(res)


@app.post("/api/inspect")
def api_inspect():
    d = request.get_json(silent=True) or {}
    urls = [u for u in (d.get("urls") or [])
            if isinstance(u, str) and u.startswith(("http://", "https://"))][:80]
    if not urls:
        return jsonify({"ok": True, "results": {}})
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = dict(zip(urls, ex.map(head_info, urls)))
    return jsonify({"ok": True, "results": results})


@app.get("/api/proxy")
def api_proxy():
    """ส่งต่อรูปภาพเพื่อใช้แสดงตัวอย่าง (เลี่ยงการบล็อกลิงก์ข้ามเว็บ)"""
    url = request.args.get("url", "")
    if not url.startswith(("http://", "https://")):
        return "", 400
    try:
        r = requests.get(url, timeout=15, stream=True,
                         headers={"User-Agent": USER_AGENT, "Referer": url})
    except requests.exceptions.RequestException:
        return "", 502
    return Response(r.iter_content(65536),
                    content_type=r.headers.get("Content-Type", "application/octet-stream"),
                    headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/download")
def api_download():
    url = request.args.get("url", "")
    if not url.startswith(("http://", "https://")):
        return "", 400
    try:
        r = requests.get(url, timeout=30,
                         headers={"User-Agent": USER_AGENT, "Referer": url})
        r.raise_for_status()
    except requests.exceptions.RequestException:
        return "", 502
    return send_file(io.BytesIO(r.content),
                     mimetype=r.headers.get("Content-Type", "application/octet-stream"),
                     as_attachment=True, download_name=filename_of(url) or "image")


@app.post("/api/download-zip")
def api_download_zip():
    d = request.get_json(silent=True) or {}
    urls = [u for u in (d.get("urls") or [])
            if isinstance(u, str) and u.startswith(("http://", "https://"))][:150]
    if not urls:
        return jsonify({"ok": False, "error": "ยังไม่ได้เลือกรายการ"}), 400

    def grab(u):
        try:
            r = requests.get(u, timeout=25,
                             headers={"User-Agent": USER_AGENT, "Referer": u})
            r.raise_for_status()
            return u, r.content
        except requests.exceptions.RequestException:
            return u, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = list(ex.map(grab, urls))

    buf, used = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (u, content) in enumerate(fetched, 1):
            if content is None:
                continue
            name = filename_of(u) or f"image_{i}"
            if "." not in name:
                name += ".jpg"
            base, ext = os.path.splitext(name)
            n, final = 1, name
            while final in used:
                final = f"{base}_{n}{ext}"
                n += 1
            used.add(final)
            zf.writestr(final, content)
        zf.writestr("_links.txt", "\n".join(urls))
    buf.seek(0)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name="images.zip")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  เปิดใช้งานที่  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
