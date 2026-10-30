"""
fill_it_form v9.6
"""

import io
import unicodedata
import base64
from flask import Flask, request, jsonify
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_FILE = "THSarabun.ttf"
pdfmetrics.registerFont(TTFont("Thai", FONT_FILE))
pdfmetrics.registerFont(TTFont("CordiaNew", "cordia.ttc", subfontIndex=0))

PAGE_W = 612.0
PAGE_H = 792.0
BLUE  = (0.0, 0.0, 1.0)
BLACK = (0.0, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)

FIELDS = {
    "doc_no":          (441.7, 118.0, 536.3, 133.0, 13, BLUE),
    "fullname_th":     (160.0, 135.0, 368.0, 152.0, 13, BLUE),   # top 133→135: keeps rect below row-sep at pdfY=133.8
    "date":            (450.0, 137.0, 536.3, 152.0, 13, BLUE),
    "fullname_en":     (202.4, 171.0, 350.0, 186.0, 13, BLUE),
    "emp_id":          (450.0, 171.0, 536.3, 186.0, 13, BLUE),
    "workplace":       (183.4, 199.0, 536.3, 214.0, 13, BLUE),
    "department":      (197.5, 226.0, 536.3, 241.0, 13, BLUE),
    "position":        (183.4, 254.0, 536.3, 269.0, 13, BLUE),
    "req_type":        (183.4, 281.0, 536.3, 296.0, 13, BLUE),
    "program":         (197.5, 309.0, 536.3, 324.0, 13, BLUE),
    "asset_tag":       (183.0, 330.0, 536.3, 345.0, 13, BLUE),  # อีเมลที่ร้องขอ (email template only)
    "detail":          (183.2, 364.0, 536.3, 432.0, 13, BLUE),   # covers 3 dotted lines; overflow → page 2
    "note":            (114.1, 505.0, 536.3, 572.0, 13, BLACK),  # bot expanded to 572 for multi-line wrap
    "sign_requester":  (134.0, 607.0, 223.0, 626.0, 13, BLACK),  # top 609→607: old text at pdfY=607.7
    "sign_date":       (134.0, 623.0, 223.0, 640.0, 12, BLACK),  # top 626→623: old date at pdfY=624.7
    "sign_approver":   (395.0, 607.0, 473.0, 626.0, 13, BLACK),  # top 609→607: old text at pdfY=607.0
    "sign_supervisor": (132.0, 687.0, 217.0, 706.0, 13, BLACK),  # top 689→687: old text at pdfY=687.5
    "sign_recorder":   (396.0, 687.0, 475.0, 704.0, 13, BLACK),
}


WRAP_FIELDS = {"note", "detail"}
# overflow → full text on continuation page (audit: no silent truncation)
CONT_LABELS = {"detail": "รายละเอียดร้องขอ", "note": "หมายเหตุ"}
CONT_MARK   = "...(มีต่อหน้า 2)"

# Label overrides — draw white rect + new text to replace printed template labels
# key: data key   value: (x0, top, x1, bot, fsize, color)
# LABEL_OVERRIDES: (rect_x0, rect_top, rect_x1, rect_bot, txt_top, txt_bot, fsize, color)
# rect_* = white rect ขยายขึ้นคลุม tone marks/vowels ของ label เดิม
# txt_*  = ตำแหน่งจริงของ label เดิม (ใช้ calc_text_y → align ตรงแถว)
LABEL_OVERRIDES = {
    "label_requester": (232.0, 575.0, 328.0, 614.0, 595.5, 608.4, 13, BLACK),
    "label_recorder":  (481.0, 655.0, 542.0, 693.0, 675.0, 687.9, 13, BLACK),
}
LABEL_FONT = "CordiaNew"

# white rect ทับ label "อีเมลที่ร้องขอ" (งานโปรแกรม — ใช้ email template แต่ไม่ใช่คำขออีเมล)
# (x0, top, x1, bot) — ปรับให้คลุม label จริง (แถวเดียวกับ asset_tag pdfY=330-345)
HIDE_EMAIL_LABEL_RECT = (50.0, 328.0, 183.0, 348.0)


def _split_long(c, word, max_w, fsize):
    """Break a word wider than max_w (Thai has no spaces) without orphaning combining marks."""
    parts, cur = [], ""
    for ch in word:
        if cur and not unicodedata.combining(ch) and c.stringWidth(cur + ch, "Thai", fsize) > max_w:
            parts.append(cur)
            cur = ""
        cur += ch
    return parts + [cur] if cur else parts


def _wrap_lines(c, text, max_w, fsize):
    """Split text into wrapped lines (continuous flow; newlines treated as spaces)."""
    words = []
    for w in str(text).split():   # split on all whitespace incl. newlines → flow ต่อกัน
        words += _split_long(c, w, max_w, fsize)   # returns [w] when it already fits
    lines = []
    cur   = ""
    for w in words:
        test = (cur + " " + w).strip() if cur else w
        if c.stringWidth(test, "Thai", fsize) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def wrap_text(c, text, x0, x1, top, bot, fsize):
    """Word-wrap within field at fixed font. Returns True if text overflowed (marked, continued on page 2)."""
    max_w     = x1 - x0 - 4
    box_h     = bot - top
    line_h    = fsize * 1.4
    max_lines = max(1, int(box_h / line_h))

    lines = _wrap_lines(c, text, max_w, fsize)
    overflow = len(lines) > max_lines
    if overflow:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and c.stringWidth(last + CONT_MARK, "Thai", fsize) > max_w:
            last = last[:-1]
        lines[-1] = last + CONT_MARK

    c.setFont("Thai", fsize)
    descent = fsize * (2.75 / 11)
    rl_top  = PAGE_H - top
    for i, line in enumerate(lines):
        y = rl_top - fsize + descent - i * line_h
        c.drawString(x0 + 2, y, line)
    return overflow


def draw_continuation(c, data, fields):
    """Extra page(s) with the full text of overflowed fields."""
    left, fsize, line_h = 60, 14, 14 * 1.4
    c.showPage()
    c.setFillColorRGB(*BLACK)
    y = PAGE_H - 60
    c.setFont("Thai", 16)
    c.drawString(left, y, "รายละเอียดเพิ่มเติม (ต่อจากหน้า 1)   เลขที่คำขอ: " + str(data.get("doc_no", "")))
    y -= 32
    for f in fields:
        c.setFont("Thai", 15)
        c.drawString(left, y, CONT_LABELS[f] + " :")
        y -= 22
        # page 2 keeps the requester's line breaks (page 1 flows continuously)
        lines = []
        for para in str(data[f]).splitlines():
            lines += _wrap_lines(c, para, PAGE_W - 2 * left - 10, fsize) or [""]
        for line in lines:
            if y < 60:
                c.showPage()
                c.setFillColorRGB(*BLACK)
                y = PAGE_H - 60
            c.setFont("Thai", fsize)
            c.drawString(left + 10, y, line)
            y -= line_h
        y -= 12


def calc_text_y(top, bot, fsize):
    """Center text vertically in field, guaranteeing descenders never touch the underline.

    For narrow fields (field_h < fsize) the minimum-clearance floor kicks in,
    so text floats slightly above the underline regardless of field height.
    """
    field_h   = bot - top
    rl_bot    = PAGE_H - bot
    descent   = fsize * (2.75 / 11)  # THSarabun actual descent (measured)
    centered  = rl_bot + (field_h - fsize) / 2 + descent   # visually centered
    min_y     = rl_bot + descent + 2                         # ≥ 2pt clearance from bottom
    return max(centered, min_y)


def fill_pdf(data: dict, template_bytes: bytes) -> bytes:
    data = dict(data)
    data["sign_approver"] = data.get("sign_approver") or "ภาณุ ธีรภานุ"

    buf = io.BytesIO()
    c   = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    overflowed = []
    for field, (x0, top, x1, bot, fsize, color) in FIELDS.items():
        value = str(data.get(field, "") or "")
        if not value:
            continue

        c.setFillColorRGB(*color)
        if field in WRAP_FIELDS:
            if wrap_text(c, value, x0, x1, top, bot, fsize):
                overflowed.append(field)
        else:
            c.setFont("Thai", fsize)
            c.drawString(x0 + 1, calc_text_y(top, bot, fsize), value)

    # Label overrides — white rect + new label text (repair template only)
    for field, (rx0, rtop, rx1, rbot, ttop, tbot, fsize, color) in LABEL_OVERRIDES.items():
        value = str(data.get(field, "") or "")
        if not value:
            continue
        # white rect (ขยายขึ้นบนเพื่อคลุม tone marks ของ label เดิม)
        rl_rbot = PAGE_H - rbot
        c.setFillColorRGB(*WHITE)
        c.setStrokeColorRGB(*WHITE)
        c.rect(rx0, rl_rbot + 1, rx1 - rx0, rbot - rtop, fill=1, stroke=0)
        # text ที่ตำแหน่ง label เดิม → align ตรงแถวกับ label อื่น
        c.setFillColorRGB(*color)
        c.setFont(LABEL_FONT, fsize)
        c.drawString(rx0 + 1, calc_text_y(ttop, tbot, fsize), value)

    # ซ่อน label "อีเมลที่ร้องขอ" (งานโปรแกรม)
    if data.get("hide_email_label"):
        hx0, htop, hx1, hbot = HIDE_EMAIL_LABEL_RECT
        c.setFillColorRGB(*WHITE)
        c.setStrokeColorRGB(*WHITE)
        c.rect(hx0, PAGE_H - hbot, hx1 - hx0, hbot - htop, fill=1, stroke=0)

    if overflowed:
        draw_continuation(c, data, overflowed)

    c.save()
    buf.seek(0)

    template = PdfReader(io.BytesIO(template_bytes))
    overlay  = PdfReader(buf)
    writer   = PdfWriter()
    page     = template.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)
    for extra in overlay.pages[1:]:   # continuation page(s)
        writer.add_page(extra)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


app = Flask(__name__)

@app.route("/fill_it_form", methods=["POST"])
def handle_fill_it_form():
    try:
        body           = request.get_json(force=True)
        data           = body["data"]
        template_bytes = base64.b64decode(body["template_b64"])
        pdf_bytes      = fill_pdf(data, template_bytes)
        return jsonify({"ok": True, "pdf_b64": base64.b64encode(pdf_bytes).decode()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/", methods=["GET"])
def health():
    return "ok v9.6", 200
