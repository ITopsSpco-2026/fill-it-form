"""Check the two-page form (data with "signers"). Run: python test_two_page.py"""
import io
import fitz
from reportlab.pdfgen import canvas
import Main

# stand-in template: one page with signature text inside the signature section
buf = io.BytesIO()
c = canvas.Canvas(buf, pagesize=(Main.PAGE_W, Main.PAGE_H))
c.setFont("Thai", 14)
c.drawString(80, Main.PAGE_H - 620, "ลงชื่อ .................... ผู้ขอ")
c.drawString(80, Main.PAGE_H - 300, "ประเภทคำขอ")
c.save()
TPL = buf.getvalue()

SIGNERS = [["ผู้ร้องขอ/ตรวจสอบ", "ปวรวรรณ สิทธิวุฒิ"], ["ผู้ขอใช้สิทธิ์ / ผู้ดำเนินการ", "ภรภัทร ดวงแก้ว"],
           ["หัวหน้างาน", "กนกกาญจน์ คณารัตนดิลก"], ["อนุมัติ", "ภาณุ ธีรภานุ"], ["ผู้บันทึก/ควบคุมสิทธิ์", "สิทธินันท์ เอื้อกิจ"]]
BASE = {"doc_no": "SPCO-ITR1-2026/170", "sign_requester": "ไม่ควรอยู่หน้า 1"}


def fill(**kw):
    return fitz.open(stream=Main.fill_pdf(dict(BASE, **kw), TPL), filetype="pdf")


d = fill(signers=SIGNERS, acceptors=["สุภาวดี วงษ์ลา", "ทองพิทักษ์ เหล่าอยู่คง"])
area = d[0].get_text(clip=fitz.Rect(*Main.SIGN_AREA))
assert len(d) == 2
assert "ลงชื่อ" not in area and "ไม่ควรอยู่หน้า 1" not in d[0].get_text(), "page 1 signature section not removed"
assert "ประเภทคำขอ" in d[0].get_text(), "rest of page 1 kept"
assert "อยู่ที่หน้า 2" in area and "ผู้ตรวจรับ" in area
assert "( ทองพิทักษ์ เหล่าอยู่คง )" in d[1].get_text() and "( ภาณุ ธีรภานุ )" in d[1].get_text()

d = fill(signers=SIGNERS, acceptors=[], no_accept_reason="ใบนี้ปิดอัตโนมัติ (เกิน SLA)")
assert "ไม่มี เนื่องจากใบนี้ปิดอัตโนมัติ" in d[1].get_text()
assert "ผู้ตรวจรับ" not in d[0].get_text(clip=fitz.Rect(*Main.SIGN_AREA))

d = fill(signers=SIGNERS, acceptors=["คนที่ %d" % i for i in range(1, 10)], detail="ยาว " * 400)
assert len(d) == 4, len(d)   # page 1, signatures x2, continuation
assert "(มีต่อหน้า 4)" in d[0].get_text() and "ส่วนลงนาม (ต่อ)" in d[2].get_text() and "ต่อจากหน้า 1" in d[3].get_text()

d = fill(sign_requester="ผู้ขอเดิม", detail="ยาว " * 400)
assert len(d) == 2 and "ผู้ขอเดิม" in d[0].get_text() and "(มีต่อหน้า 2)" in d[0].get_text(), "no signers → one-page form as before"
print("two-page checks passed")
