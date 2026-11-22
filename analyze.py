"""تحلیل خبر با Gemini + کنترل عددها (هر عدد خروجی باید در متن مبدأ باشد)."""
import re
import httpx
import config

FA_D = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"; EN_D = "01234567890123456789"
def norm(s): return (s or "").translate(str.maketrans(FA_D, EN_D))

def numbers(s):
    s = norm(s).replace("٬", "").replace(",", "").replace("،", "")
    return {n for n in re.findall(r"\d+(?:\.\d+)?", s) if len(n) >= 2}

def unsupported_numbers(source: str, output: str):
    return sorted(numbers(output) - numbers(source))

SYSTEM = ("تو سردبیر کانال خبری املاک هستی. فقط از متن خبر استفاده کن. هیچ عدد، تاریخ، درصد یا نامی که در متن نیست ننویس. "
          "فارسی روان و ساده بنویس. خروجی را دقیقاً با این چهار بخش بده و چیز دیگری اضافه نکن:\n"
          "تیتر: (حداکثر ۹ کلمه)\nخلاصه: (حداکثر ۳ جمله)\nبرای مردم یعنی: (۱ تا ۲ جمله برای خریدار، فروشنده یا مستأجر؛ اگر مطمئن نیستی بنویس «جزئیات بیشتر هنوز اعلام نشده»)\n"
          "اهمیت: (فقط یک عدد ۱ تا ۵. ۵ = تغییر قانون، مالیات، وام یا هزینه که مستقیم روی خریدار، فروشنده یا مستأجر اثر دارد. ۳ = مفید برای مخاطب ملکی. ۱ = بی‌ربط، تشریفاتی یا تکراری)")

LAST_ERROR = ""

async def gemini(prompt: str, system="", max_tokens=500):
    global LAST_ERROR
    LAST_ERROR = ""
    if not config.GEMINI_API_KEY:
        LAST_ERROR = "متغیر GEMINI_API_KEY خالی است"
        return None
    # مدل‌های جدید قبل از جواب «فکر» می‌کنند و از همین سقف مصرف می‌کنند؛ سقف کم = جواب خالی
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max(max_tokens, 1500), "temperature": 0.2}}
    if system: body["systemInstruction"] = {"parts": [{"text": system}]}
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent",
                             headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body)
        if r.status_code != 200:
            LAST_ERROR = f"HTTP {r.status_code}: {r.text[:160]}"
            return None
        cand = (r.json().get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])).strip()
        if not text:
            LAST_ERROR = f"جواب خالی (finishReason={cand.get('finishReason')})"
        return text or None
    except Exception as e:
        LAST_ERROR = f"{type(e).__name__}: {str(e)[:120]}"
        return None

def parse_sections(txt: str):
    def grab(label, nxt):
        m = re.search(rf"{label}\s*[:：]\s*(.+?)(?=\n\s*(?:{nxt})\s*[:：]|\Z)", txt, re.S)
        return m.group(1).strip() if m else ""
    m = re.search(r"اهمیت\s*[:：]\s*([1-5۱-۵])", txt)
    imp = int(norm(m.group(1))) if m else 3
    return {"headline": grab("تیتر", "خلاصه|برای مردم یعنی|اهمیت"),
            "summary": grab("خلاصه", "برای مردم یعنی|تیتر|اهمیت"),
            "meaning": grab("برای مردم یعنی", "تیتر|خلاصه|اهمیت"),
            "importance": imp}

def fallback(title: str, body: str):
    sents = [s.strip() for s in re.split(r"(?<=[.!؟?])\s+", body) if len(s.strip()) > 20][:2]
    return {"headline": title[:80], "summary": " ".join(sents) or title, "meaning": "جزئیات بیشتر هنوز اعلام نشده.", "importance": 3}

async def analyze(title: str, body: str):
    src = f"{title}\n{body}"
    out = await gemini(f"عنوان: {title}\n\nمتن خبر:\n{body or title}", SYSTEM)
    data = parse_sections(out) if out else {}
    if not data.get("summary"):
        data = fallback(title, body)
    data["suspect_numbers"] = unsupported_numbers(src, " ".join(str(v) for k, v in data.items() if k != "importance"))
    return data
