# -*- coding: utf-8 -*-
"""
mailer.py — ส่งอีเมลรหัสยืนยันผ่าน SMTP (ค่าเริ่มต้นคือ Gmail)

ตั้งค่าในไฟล์ config.json ที่คีย์ "smtp"
ถ้ายังไม่ได้ตั้งค่า ระบบจะไม่ส่งอีเมลจริง แต่จะแสดงรหัสบนหน้าจอแทน
"""

import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

DEFAULT_SMTP = {
    "host": "smtp.gmail.com",
    "port": 465,
    "user": "",
    "password": "",
    "sender_name": "Auto Link Photo",
}


def smtp_config(cfg):
    s = dict(DEFAULT_SMTP)
    s.update(cfg.get("smtp") or {})
    s["user"] = str(s.get("user") or "").strip()
    # รหัสผ่านแอปของ Google แสดงเป็น 4 กลุ่มมีเว้นวรรค — ตัดช่องว่างออกให้อัตโนมัติ
    s["password"] = str(s.get("password") or "").replace(" ", "").strip()
    return s


def is_ready(cfg) -> bool:
    s = smtp_config(cfg)
    return bool(s.get("host") and s.get("user") and s.get("password"))


# ------------------------------------------------------------------ เนื้อหา

def _html(code: str, name: str, minutes: int) -> str:
    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#eef2f8;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#eef2f8;padding:32px 14px;">
 <tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="max-width:460px;background:#ffffff;border-radius:14px;
                border:1px solid #e2e7ee;overflow:hidden;
                font-family:'Segoe UI',Tahoma,Arial,sans-serif;">
   <tr><td style="padding:24px 30px 0;">
     <div style="font-size:17px;font-weight:800;letter-spacing:-.02em;color:#14379e;">
       AUTO LINK <span style="font-weight:600;color:#0fbcf0;">PHOTO</span></div>
   </td></tr>
   <tr><td style="padding:20px 30px 0;">
     <div style="font-size:16px;font-weight:700;color:#141a24;">ยืนยันอีเมลของคุณ</div>
     <div style="font-size:13.5px;color:#78838f;line-height:1.65;padding-top:6px;">
       สวัสดีคุณ {name} — กรอกรหัสด้านล่างในหน้าสมัครสมาชิกเพื่อยืนยันอีเมลนี้
     </div>
   </td></tr>
   <tr><td style="padding:22px 30px 0;">
     <div style="background:#f3f7fd;border:1px solid #d9e4f4;border-radius:11px;
                 padding:18px;text-align:center;">
       <div style="font-size:34px;font-weight:800;letter-spacing:.34em;
                   color:#123a86;font-family:Consolas,monospace;">{code}</div>
       <div style="font-size:11.5px;color:#8a94a0;padding-top:8px;">
         รหัสมีอายุ {minutes} นาที</div>
     </div>
   </td></tr>
   <tr><td style="padding:20px 30px 26px;">
     <div style="font-size:11.5px;color:#a3acb7;line-height:1.65;
                 border-top:1px solid #eef1f5;padding-top:16px;">
       ถ้าคุณไม่ได้เป็นผู้ขอรหัสนี้ ให้ลบอีเมลฉบับนี้ทิ้งได้เลย
       และอย่าบอกรหัสนี้กับผู้อื่นไม่ว่ากรณีใด
     </div>
   </td></tr>
  </table>
 </td></tr>
</table>
</body></html>"""


def _text(code: str, name: str, minutes: int) -> str:
    return (f"AUTO LINK PHOTO\n\n"
            f"สวัสดีคุณ {name}\n\n"
            f"รหัสยืนยันอีเมลของคุณคือ  {code}\n"
            f"รหัสมีอายุ {minutes} นาที\n\n"
            f"ถ้าคุณไม่ได้เป็นผู้ขอรหัสนี้ ให้ลบอีเมลฉบับนี้ทิ้งได้เลย\n")


# ------------------------------------------------------------------ ส่งจริง

def send_code(cfg, to_email: str, code: str, name: str = "", minutes: int = 10):
    """คืน (สำเร็จ, ข้อความแจ้งเตือน)"""
    s = smtp_config(cfg)
    if not is_ready(cfg):
        return False, "ยังไม่ได้ตั้งค่าการส่งอีเมล"

    name = name or to_email.split("@")[0]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(f"รหัสยืนยัน {code} — Auto Link Photo", "utf-8")
    msg["From"] = formataddr((str(Header(s.get("sender_name") or "Auto Link Photo",
                                         "utf-8")), s["user"]))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(_text(code, name, minutes), "plain", "utf-8"))
    msg.attach(MIMEText(_html(code, name, minutes), "html", "utf-8"))

    host, port = s["host"], int(s.get("port") or 465)
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=25, context=ctx) as srv:
                srv.login(s["user"], s["password"])
                srv.sendmail(s["user"], [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=25) as srv:
                srv.ehlo()
                srv.starttls(context=ctx)
                srv.login(s["user"], s["password"])
                srv.sendmail(s["user"], [to_email], msg.as_string())
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, ("เข้าสู่ระบบอีเมลผู้ส่งไม่สำเร็จ — ตรวจสอบอีเมลและรหัสผ่านแอป "
                       "ในไฟล์ config.json")
    except smtplib.SMTPRecipientsRefused:
        return False, "ปลายทางปฏิเสธอีเมลนี้ — ตรวจสอบว่าพิมพ์อีเมลถูกต้อง"
    except (smtplib.SMTPException, OSError, ssl.SSLError):
        return False, "ส่งอีเมลไม่สำเร็จ — ตรวจสอบการเชื่อมต่ออินเทอร์เน็ตแล้วลองใหม่"
