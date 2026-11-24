"""ساخت متن عمومی کانال و متن مدیریتی پیش‌نویس. بدون وابستگی به دیتابیس/شبکه؛ کاملاً قابل تست.

قواعد:
- در بله فقط «*متن*» (ستاره در ابتدا و انتها) بولد می‌شود؛ پس parse_mode ارسال نمی‌شود و ستاره‌های متن مدل پاک می‌شوند.
- برچسب رسمی/غیررسمی، اهمیت، نام منبع و لینک منبع فقط در متن مدیر می‌آیند؛ هرگز در متن کانال.
"""
import re
import config
from analyze import norm

def clean_text(value):
    """نویسه‌های خط جدیدِ خام (\\n) را به خط جدید واقعی تبدیل می‌کند و خط‌های خالی اضافه را جمع می‌کند."""
    v = str(value or "")
    for raw in ("\\r\\n", "\\n", "\\r"):
        v = v.replace(raw, "\n")
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", v).strip()

def plain(value):
    """متن مدل را بدون ستاره و بک‌تیک می‌کند تا فقط بولدهای خودمان فعال باشد."""
    return clean_text(value).replace("*", "").replace("`", "").strip()

def has_meaning(meaning):
    m = plain(meaning)
    return bool(m) and "هنوز اعلام نشده" not in m

def short_url(u):
    """لینک خبر بدون بخش طولانی عنوان (مثلاً mehrnews.com/news/7012591)."""
    m = re.match(r"(https?://[^/#?]+/news/\d+)", u or "")
    return m.group(1) if m else (u or "")

def _tokens(s):
    return {w for w in re.findall(r"[\w\u0600-\u06FF]+", norm(s or "")) if len(w) > 2}

def similar(a, b, th=0.7):
    """شباهت دو تیتر (نسبت کلمات مشترک)؛ برای حذف خبر تکراری."""
    A, B = _tokens(a), _tokens(b)
    return bool(A and B) and len(A & B) / len(A | B) >= th

def public_text(d):
    """دقیقاً همان متنی که در کانال منتشر می‌شود."""
    headline = plain(d.get("headline") or d.get("orig_title") or "خبر جدید بازار مسکن").replace("\n", " ")
    parts = [f"*{headline}*"]
    custom = clean_text(d.get("custom_caption"))
    if custom:                                   # متن ویرایش‌شده‌ی مدیر؛ تیتر و امضا خودکار اضافه می‌شوند
        parts.append(custom)
    else:
        summary = plain(d.get("summary"))
        speaker = plain(d.get("speaker"))
        if summary:
            parts.append(f"به گفتهٔ {speaker}:\n{summary}" if speaker and speaker != "نامشخص" else summary)
        if has_meaning(d.get("meaning")):
            parts.append(f"💡 *خلاصه که؛*\n{plain(d.get('meaning'))}")
    parts.append(config.PUBLIC_SIGNATURE)
    return "\n\n".join(p for p in parts if p)

def admin_text(d, warn=""):
    """پیش‌نویس برای مدیر: اطلاعات محرمانه بالا، سپس متن دقیق کانال."""
    label = "🟢 خبر رسمی" if d.get("official") else "🟡 گزارش رسانه‌ای (تأیید رسمی نشده)"
    lines = [f"{label} | ⭐ اهمیت {d.get('importance', 3)}/5", f"📌 منبع: {d.get('source', '')}"]
    if d.get("url"):
        lines.append(f"🔗 {short_url(d['url'])}")
    if d.get("ai_failed"):
        lines.append("⚠️ تحلیل هوش مصنوعی انجام نشد؛ خلاصه از جمله‌های اول خود خبر است. قبل از انتشار بخوانید.")
    head = "\n".join(lines)
    return f"📝 پیش‌نویس #{d['_id']}\n{head}\n━━━━━━━━━━\n{public_text(d)}{warn}"
