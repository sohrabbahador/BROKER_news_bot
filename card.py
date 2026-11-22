"""ساخت تصویر خبری برندشده؛ متن فارسی توسط خود برنامه روی تصویر می‌نشیند (بدون ذخیره‌ی فایل)."""
import io, os
from PIL import Image, ImageDraw, ImageFont, features

W, H, M = 1080, 1350, 80
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
RAQM = features.check("raqm")
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    SHAPER = True
except Exception:
    SHAPER = False

def _font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    eng = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size, layout_engine=eng)

def _prep(text):
    if RAQM or not SHAPER:
        return text
    return get_display(arabic_reshaper.reshape(text))

def _len(text, font):
    return font.getlength(_prep(text))

def wrap(text, font, maxw):
    lines = []
    for para in (text or "").split("\n"):
        cur = ""
        for w in para.split():
            t = (cur + " " + w).strip()
            if _len(t, font) <= maxw: cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        lines.append(cur)
    return lines

def _draw_rtl(d, y, text, font, fill, pad=0):
    t = _prep(text); w = font.getlength(t)
    kw = {"direction": "rtl", "language": "fa"} if RAQM else {}
    d.text((W - M - pad - w, y), t, font=font, fill=fill, **kw)

def make_card(headline: str, summary: str, source: str, official: bool, signature: str = "بروکر املاک") -> bytes:
    im = Image.new("RGB", (W, H), (14, 42, 71))
    d = ImageDraw.Draw(im)
    for i in range(H):                                   # گرادیان ساده
        c = int(14 + 26 * i / H); d.line([(0, i), (W, i)], fill=(c, 42 + c // 2, 71 + c))
    badge = "خبر رسمی" if official else "گزارش رسانه‌ای"
    bcol = (46, 160, 90) if official else (214, 158, 30)
    bf = _font(40); bw = _len(badge, bf) + 70
    d.rounded_rectangle([W - M - bw, 90, W - M, 160], 35, fill=bcol)
    _draw_rtl(d, 100, badge, bf, (255, 255, 255), pad=35)
    hf = _font(78); y = 260
    for ln in wrap(headline, hf, W - 2 * M)[:5]:
        _draw_rtl(d, y, ln, hf, (255, 255, 255)); y += 118
    d.line([(W - M - 220, y + 10), (W - M, y + 10)], fill=bcol, width=8); y += 60
    sf = _font(44, bold=False)
    for ln in wrap(summary, sf, W - 2 * M)[:6]:
        _draw_rtl(d, y, ln, sf, (214, 226, 240)); y += 76
    ff = _font(38)
    _draw_rtl(d, H - 190, f"منبع: {source}", ff, (160, 180, 205))
    _draw_rtl(d, H - 120, signature, ff, (255, 255, 255))
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
