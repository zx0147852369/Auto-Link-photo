# -*- coding: utf-8 -*-
"""
gateway.py — ช่องต่อระบบรับชำระเงิน

ไฟล์นี้เป็น "ช่องเสียบ" สำหรับต่อกับผู้ให้บริการรับชำระเงินที่คุณเปิดบัญชีร้านค้าไว้
ระบบจะทำงานได้ทันทีเมื่อกรอกคีย์ในไฟล์ตั้งค่า และหากยังไม่ได้ต่อ
ผู้ใช้ยังเติม Token ได้ด้วยรหัสเติมที่ผู้ดูแลสร้างให้

สิ่งที่ต้องเตรียมเมื่อจะเปิดใช้จริง
  1. บัญชีร้านค้ากับผู้ให้บริการ (เช่น Omise, Stripe, 2C2P, GB Prime Pay)
  2. คีย์สาธารณะและคีย์ลับจากหน้าจัดการของผู้ให้บริการ
  3. ตั้งที่อยู่รับผลการชำระ (webhook) ไปที่  <ที่อยู่เว็บของคุณ>/api/pay/webhook

ดูรายละเอียดการกรอกค่าได้ในไฟล์  คู่มือระบบแพ็กเกจ.md
"""

import hashlib
import hmac
import json


DEFAULT = {
    "provider": "",          # ว่าง = ยังไม่ได้ต่อเกตเวย์
    "public_key": "",
    "secret_key": "",
    "webhook_secret": "",
    "currency": "THB",
    "return_url": "",
}

# ผู้ให้บริการที่เตรียมช่องต่อไว้แล้ว
KNOWN = {
    "omise": "Omise",
    "stripe": "Stripe",
    "2c2p": "2C2P",
    "gbprimepay": "GB Prime Pay",
    "custom": "กำหนดเอง",
}


def conf(cfg):
    c = dict(DEFAULT)
    c.update((cfg or {}).get("payment") or {})
    for k in ("provider", "public_key", "secret_key", "webhook_secret"):
        c[k] = str(c.get(k) or "").strip()
    return c


def is_ready(cfg) -> bool:
    """ต่อเกตเวย์เรียบร้อยหรือยัง"""
    c = conf(cfg)
    return bool(c["provider"] and c["public_key"] and c["secret_key"])


def provider_name(cfg) -> str:
    c = conf(cfg)
    return KNOWN.get(c["provider"], c["provider"] or "")


# ==================================================================
#  สร้างรายการชำระเงิน
# ==================================================================

def create_checkout(cfg, order):
    """
    ส่งคำสั่งซื้อไปยังเกตเวย์ แล้วคืน dict สำหรับพาผู้ใช้ไปหน้าชำระเงิน

      { "ok": True, "redirect": "https://...", "ref": "..." }
      { "ok": False, "error": "ข้อความ" }

    ยังไม่ผูกกับผู้ให้บริการรายใดโดยเจาะจง เพราะแต่ละรายมีรูปแบบต่างกัน
    เมื่อคุณมีคีย์แล้ว ให้เติมโค้ดเรียก API ของรายนั้นในส่วนที่ทำเครื่องหมายไว้
    """
    c = conf(cfg)
    if not is_ready(cfg):
        return {"ok": False, "error": "ยังไม่ได้ตั้งค่าระบบรับชำระเงิน"}

    # ------------------------------------------------------------------
    #  จุดที่ต้องเติมโค้ดเรียก API ของผู้ให้บริการ
    #
    #  ตัวอย่างโครงสำหรับ Omise (ต้องติดตั้งไลบรารีของผู้ให้บริการก่อน)
    #
    #      import omise
    #      omise.api_secret = c["secret_key"]
    #      source = omise.Source.create(
    #          type="promptpay",
    #          amount=order["amount"] * 100,      # หน่วยสตางค์
    #          currency=c["currency"],
    #      )
    #      charge = omise.Charge.create(
    #          amount=order["amount"] * 100,
    #          currency=c["currency"],
    #          source=source.id,
    #          return_uri=c["return_url"],
    #          metadata={"order_id": order["id"]},
    #      )
    #      return {"ok": True, "redirect": charge.authorize_uri, "ref": charge.id}
    #
    #  สิ่งสำคัญคือต้องส่ง order["id"] ไปกับรายการชำระเงินด้วย
    #  เพื่อให้ตอนรับผลกลับมารู้ว่าเป็นคำสั่งซื้อใบไหน
    # ------------------------------------------------------------------

    return {"ok": False,
            "error": f"ต่อกับ{provider_name(cfg)}ไว้แล้ว "
                     f"แต่ยังไม่ได้เติมโค้ดเรียกใช้บริการในไฟล์ gateway.py"}


# ==================================================================
#  รับผลการชำระเงิน
# ==================================================================

def verify_webhook(cfg, raw_body: bytes, signature: str) -> bool:
    """
    ตรวจลายเซ็นของข้อมูลที่เกตเวย์ส่งกลับมา

    ขั้นตอนนี้สำคัญมาก เพราะถ้าไม่ตรวจ ใครก็ส่งข้อมูลปลอมมาบอกว่า
    ชำระเงินแล้วได้ ระบบจึงปฏิเสธทุกคำขอที่ลายเซ็นไม่ถูกต้อง
    """
    c = conf(cfg)
    secret = c["webhook_secret"]
    if not secret:
        return False
    sig = (signature or "").strip()
    if not sig:
        return False
    # รูปแบบที่ผู้ให้บริการส่วนใหญ่ใช้ คือ HMAC-SHA256 ของเนื้อหาคำขอ
    expect = hmac.new(secret.encode("utf-8"), raw_body or b"",
                      hashlib.sha256).hexdigest()
    sig = sig.split("=")[-1].strip().lower()
    return hmac.compare_digest(sig, expect)


def read_webhook(raw_body: bytes):
    """
    อ่านข้อมูลที่เกตเวย์ส่งมา แล้วดึงเลขคำสั่งซื้อกับสถานะออกมา
    คืน (order_id, สำเร็จหรือไม่, เลขอ้างอิงของเกตเวย์)
    """
    try:
        d = json.loads((raw_body or b"{}").decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return "", False, ""

    def dig(obj, *names):
        if isinstance(obj, dict):
            for n in names:
                if n in obj and obj[n]:
                    return obj[n]
            for v in obj.values():
                got = dig(v, *names)
                if got:
                    return got
        elif isinstance(obj, list):
            for v in obj:
                got = dig(v, *names)
                if got:
                    return got
        return None

    oid = dig(d, "order_id", "orderId", "reference", "referenceNo") or ""
    ref = dig(d, "id", "charge_id", "transaction_id", "paymentId") or ""
    status = str(dig(d, "status", "state", "payment_status") or "").lower()
    paid = status in ("paid", "successful", "success", "succeeded",
                      "completed", "capture", "captured")
    return str(oid), paid, str(ref)
