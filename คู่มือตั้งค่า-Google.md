# คู่มือเปิดใช้งานการเข้าสู่ระบบด้วย Google

ใช้เวลาประมาณ 5–10 นาที ทำครั้งเดียวจบ ไม่มีค่าใช้จ่าย

---

## ก่อนเริ่ม

รัน `run.bat` หนึ่งครั้งเพื่อให้ระบบสร้างไฟล์ `config.json` ขึ้นมาก่อน
ตอนนี้จะเข้าใช้งานได้ด้วย **รหัสผ่าน `1234`** ไปพลาง ๆ

> เปลี่ยนรหัสผ่านได้ทันทีโดยแก้ค่า `access_password` ในไฟล์ `config.json`

---

## ขั้นตอนที่ 1 — สร้างโปรเจกต์

1. เปิด https://console.cloud.google.com/
2. เข้าสู่ระบบด้วยบัญชี Google ของคุณ
3. กดที่ชื่อโปรเจกต์มุมบนซ้าย แล้วเลือก **New project** / **โปรเจกต์ใหม่**
4. ตั้งชื่อว่า `Auto Link Photo` แล้วกด **Create**
5. รอสักครู่ แล้วเลือกโปรเจกต์ที่เพิ่งสร้างจากมุมบนซ้าย

---

## ขั้นตอนที่ 2 — ตั้งค่าหน้าจอขออนุญาต

1. เมนูซ้าย เลือก **APIs & Services → OAuth consent screen**
2. เลือก **External** แล้วกด **Create**
3. กรอกเฉพาะช่องที่มีเครื่องหมายดอกจัน

   | ช่อง | ใส่ว่า |
   |---|---|
   | App name | `Auto Link Photo` |
   | User support email | อีเมลของคุณ |
   | Developer contact information | อีเมลของคุณ |

4. กด **Save and Continue** ผ่านหน้า Scopes และ Test users ไปจนจบ
5. กลับมาที่หน้า OAuth consent screen แล้วกด **Publish app → Confirm**

   > ขั้นตอนนี้สำคัญ ถ้าไม่กด Publish จะมีแค่บัญชีที่เพิ่มเป็น Test users
   > เท่านั้นที่เข้าได้ (สูงสุด 100 บัญชี)

---

## ขั้นตอนที่ 3 — สร้าง Client ID

1. เมนูซ้าย เลือก **APIs & Services → Credentials**
2. กด **+ Create Credentials → OAuth client ID**
3. ตั้งค่าดังนี้

   | ช่อง | ใส่ว่า |
   |---|---|
   | Application type | **Web application** |
   | Name | `Auto Link Photo` |

4. ที่หัวข้อ **Authorized redirect URIs** กด **+ Add URI** แล้วใส่ที่อยู่นี้
   ให้ตรงทุกตัวอักษร

   ```
   http://127.0.0.1:5000/auth/google/callback
   ```

   ถ้าต้องการเปิดผ่าน `localhost` ด้วย ให้กด Add URI เพิ่มอีกบรรทัด

   ```
   http://localhost:5000/auth/google/callback
   ```

5. กด **Create**
6. จะมีหน้าต่างแสดง **Client ID** และ **Client secret** — คัดลอกเก็บไว้ทั้งสองค่า

---

## ขั้นตอนที่ 4 — ใส่ค่าลงในโปรแกรม

เปิดไฟล์ `config.json` ด้วย Notepad แล้ววางค่าที่ได้ลงไป

```json
{
  "secret_key": "อย่าแก้ค่านี้",
  "access_password": "ตั้งรหัสผ่านที่ต้องการ",
  "google_client_id": "วาง Client ID ที่นี่",
  "google_client_secret": "วาง Client secret ที่นี่",
  "allowed_emails": [],
  "session_days": 14
}
```

บันทึกไฟล์ แล้วปิดหน้าต่างโปรแกรมเดิม รัน `run.bat` ใหม่อีกครั้ง

ปุ่ม **เข้าสู่ระบบด้วย Google** จะใช้งานได้ทันที

---

## จำกัดสิทธิ์ว่าใครเข้าได้บ้าง

ค่าเริ่มต้น `"allowed_emails": []` คือ **ใครก็ตามที่มีบัญชี Google เข้าได้**

ถ้าต้องการจำกัด ให้ใส่รายชื่อลงไป รองรับทั้งอีเมลรายตัวและทั้งโดเมน

```json
"allowed_emails": [
  "bokxz1232@gmail.com",
  "@company.com"
]
```

---

## แก้ปัญหาที่พบบ่อย

| อาการ | สาเหตุและวิธีแก้ |
|---|---|
| `Error 400: redirect_uri_mismatch` | ที่อยู่ใน Authorized redirect URIs ไม่ตรง ต้องเป็น `http://127.0.0.1:5000/auth/google/callback` เป๊ะ ๆ ทั้งตัวพิมพ์เล็กใหญ่และเครื่องหมาย และต้องเปิดเว็บด้วยที่อยู่เดียวกับที่ลงทะเบียนไว้ |
| ขึ้นหน้า "Google hasn't verified this app" | กด **Advanced → Go to Auto Link Photo (unsafe)** ได้เลย เป็นเรื่องปกติของแอปที่ยังไม่ส่งตรวจ ซึ่งไม่จำเป็นสำหรับการใช้งานส่วนตัว |
| `Access blocked: has not completed the Google verification process` | ยังไม่ได้กด **Publish app** ในขั้นตอนที่ 2 ข้อ 5 |
| ปุ่ม Google เป็นสีจาง กดไม่ได้ | ยังไม่ได้ใส่ค่าใน `config.json` หรือใส่แล้วแต่ยังไม่ได้ปิดโปรแกรมแล้วรันใหม่ |
| ลืมรหัสผ่าน | เปิด `config.json` ดูค่า `access_password` ได้โดยตรง |

---

## ข้อควรรู้เรื่องความปลอดภัย

- ไฟล์ `config.json` เก็บ Client secret และรหัสผ่านแบบข้อความธรรมดา
  **อย่าส่งไฟล์นี้ให้ผู้อื่น** และอย่าอัปโหลดขึ้นที่สาธารณะ
- โปรแกรมเปิดรับเฉพาะเครื่องตัวเอง (`127.0.0.1`) คนอื่นในเครือข่ายเข้าไม่ได้
- ถ้า Client secret หลุด ให้เข้า Credentials แล้วกดลบ Client ID เดิมทิ้ง
  แล้วสร้างใหม่ตามขั้นตอนที่ 3
