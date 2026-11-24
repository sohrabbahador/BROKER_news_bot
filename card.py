"""ساخت کارت خبری ثابت بروکر املاک؛ طراحی مینیمال سبز، طلایی و طوسی."""
import io
import os
from PIL import Image, ImageDraw, ImageFont, features

W, H = 1080, 1350
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
RAQM = features.check("raqm")

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    SHAPER = True
except Exception:
    SHAPER = False

# پالت ثابت برند
BG = (241, 243, 240)          # طوسی روشن
PANEL = (255, 255, 252)       # سفید گرم
GREEN = (15, 77, 53)          # سبز تیره
GREEN_2 = (28, 105, 72)
GOLD = (194, 151, 54)
INK = (35, 45, 40)
MUTED = (105, 113, 107)
BORDER = (224, 213, 184)

def _font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    layout = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size, layout_engine=layout)

def _prep(text):
    text = str(text or "")
    if RAQM or not SHAPER:
        return text
    return get_display(arabic_reshaper.reshape(text))

def _measure(text, font):
    return font.getlength(_prep(text))

def wrap(text, font, maxw):
    """شکستن متن فارسی با حفظ پاراگراف‌ها."""
    lines = []
    for para in str(text or "").replace("\r\n", "\n").split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            trial = (cur + " " + word).strip()
            if not cur or _measure(trial, font) <= maxw:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines

def _draw_rtl(draw, x_right, y, text, font, fill):
    shaped = _prep(text)
    kwargs = {"direction": "rtl", "language": "fa"} if RAQM else {}
    draw.text((x_right - font.getlength(shaped), y), shaped, font=font, fill=fill, **kwargs)

def _fit_lines(text, max_width, max_lines, start_size, min_size, bold=True):
    for size in range(start_size, min_size - 1, -2):
        font = _font(size, bold)
        lines = wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(min_size, bold)
    lines = wrap(text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            # از بریدن بی‌صدا جلوگیری می‌کنیم؛ انتهای متن با سه‌نقطه مشخص می‌شود.
            lines[-1] = lines[-1].rstrip(" ،؛:") + "…"
    return font, lines

def _rounded_panel(draw, box, radius=28, fill=PANEL, outline=BORDER, width=3):
    x1, y1, x2, y2 = box
    # سایه‌ی ظریف و بدون شلوغی
    draw.rounded_rectangle((x1 + 5, y1 + 7, x2 + 5, y2 + 7),
                           radius=radius, fill=(224, 227, 222))
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def make_card(headline: str, summary: str, source: str, official: bool,
              signature: str = "بروکر املاک") -> bytes:
    """کارت ۱۰۸۰×۱۳۵۰؛ رسمی/غیررسمی بودن در تصویر عمومی نمایش داده نمی‌شود."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # نوار بالایی و هویت رنگی
    d.rectangle((0, 0, W, 18), fill=GREEN)
    d.line((72, 82, W - 72, 82), fill=GOLD, width=3)
    tag = "اخبار املاک و مسکن"
    tag_font = _font(28, True)
    tag_w = _measure(tag, tag_font) + 44
    d.rounded_rectangle((W - 72 - tag_w, 105, W - 72, 158),
                        radius=25, fill=GREEN)
    _draw_rtl(d, W - 94, 115, tag, tag_font, (255, 255, 255))

    # تیتر اصلی
    title = str(headline or "خبر جدید بازار مسکن").strip()
    title_font, title_lines = _fit_lines(title, W - 160, 3, 66, 48, True)
    y = 205
    line_h = int(title_font.size * 1.48)
    for line in title_lines:
        _draw_rtl(d, W - 88, y, line, title_font, GREEN)
        y += line_h

    # خط طلایی زیر تیتر
    y += 14
    d.rounded_rectangle((W - 300, y, W - 88, y + 9), radius=5, fill=GOLD)
    y += 48

    # کارت خلاصه؛ اندازه‌ی فونت با فضای واقعی کارت تنظیم می‌شود تا متن زیر فوتر نرود.
    body = str(summary or "").strip()
    panel_top = y
    footer_top = 1095
    available_text_h = max(150, footer_top - panel_top - 145)
    body_font = _font(30, False)
    body_lines = wrap(body, body_font, W - 190)
    body_line_h = int(body_font.size * 1.58)
    for size in range(42, 27, -2):
        candidate = _font(size, False)
        candidate_lines = wrap(body, candidate, W - 190)
        candidate_line_h = int(size * 1.58)
        if len(candidate_lines) * candidate_line_h <= available_text_h:
            body_font, body_lines, body_line_h = candidate, candidate_lines, candidate_line_h
            break
    else:
        max_lines = max(1, available_text_h // body_line_h)
        if len(body_lines) > max_lines:
            body_lines = body_lines[:max_lines]
            body_lines[-1] = body_lines[-1].rstrip(" ،؛:") + "…"
    content_h = max(180, len(body_lines) * body_line_h + 105)
    panel_bottom = min(panel_top + content_h, footer_top - 25)
    _rounded_panel(d, (64, panel_top, W - 64, panel_bottom), radius=30)

    # عنوان کوچک پنل
    label = "خلاصه خبر"
    label_font = _font(30, True)
    label_w = _measure(label, label_font) + 52
    d.rounded_rectangle((W - 100 - label_w, panel_top - 23,
                         W - 100, panel_top + 30), radius=24, fill=GREEN_2)
    _draw_rtl(d, W - 126, panel_top - 14, label, label_font, (255, 255, 255))

    text_y = panel_top + 58
    for line in body_lines:
        if line:
            _draw_rtl(d, W - 105, text_y, line, body_font, INK)
        text_y += body_line_h

    # اگر متن بلند بود، منبع در نوار جداگانه‌ی پایینی می‌آید.
    d.rectangle((0, footer_top, W, H), fill=GREEN)
    d.rectangle((0, footer_top, W, footer_top + 7), fill=GOLD)

    source_text = ("منبع: " + str(source or "خبرگزاری"))[:100]
    source_font = _font(25, False)
    _draw_rtl(d, W - 82, footer_top + 34, source_text, source_font, (225, 231, 225))

    # امضای ثابت؛ فونت نستعلیق در فایل‌های ورودی وجود ندارد، بنابراین از فونت فارسی موجود استفاده می‌شود.
    sign_font = _font(43, True)
    sign = "سهراب بهادر"
    sign_w = _measure(sign, sign_font)
    _draw_rtl(d, (W + sign_w) // 2, footer_top + 76, sign, sign_font, (255, 255, 255))

    brand_font = _font(25, False)
    brand = "بروکر املاک"
    brand_w = _measure(brand, brand_font)
    _draw_rtl(d, (W + brand_w) // 2, footer_top + 132, brand, brand_font, (229, 218, 185))

    handle = "@BROKER_amlak"
    handle_font = _font(26, True)
    hw = _measure(handle, handle_font) + 46
    d.rounded_rectangle(((W - hw) // 2, footer_top + 180,
                         (W + hw) // 2, footer_top + 232),
                        radius=24, fill=(8, 58, 40), outline=GOLD, width=2)
    # متن لاتین چپ‌چین درون کپسول
    hb = d.textbbox((0, 0), handle, font=handle_font)
    d.text(((W - (hb[2] - hb[0])) // 2, footer_top + 189),
           handle, font=handle_font, fill=(255, 255, 255))

    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
