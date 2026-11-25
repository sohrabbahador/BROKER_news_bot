"""تحلیل خبر با Gemini + کنترل عددها (هر عدد خروجی باید در متن مبدأ باشد)."""
import asyncio, re
import httpx
import config

FA_D = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"; EN_D = "01234567890123456789"
def norm(s): return (s or "").translate(str.maketrans(FA_D, EN_D))

def numbers(s):
    s = norm(s).replace("٬", "").replace(",", "").replace("،", "")
    return {n for n in re.findall(r"\d+(?:\.\d+)?", s) if len(n) >= 2}

def unsupported_numbers(source: str, output: str):
    return sorted(numbers(output) - numbers(source))

SYSTEM = (
    "تو سردبیر کانال خبری «املاک و مسکن» هستی. فقط از متن خبر استفاده کن؛ هیچ عدد، تاریخ، نام یا ادعایی که در متن نیست ننویس و چیزی را حدس نزن. فارسی روان و ساده بنویس.\n"
    "خروجی را دقیقاً با این شش خط بده، هر کدام در یک خط جدا و بدون هیچ متن یا علامت اضافه:\n"
    "مرتبط: بله یا خیر\n"
    "تیتر: ...\n"
    "نسبت‌دهی: ...\n"
    "خلاصه: ...\n"
    "خلاصه که: ...\n"
    "اهمیت: ...\n\n"
    "قواعد:\n"
    "مرتبط = «بله» فقط اگر خبر مستقیماً درباره‌ی مسکن، خرید و فروش یا اجاره‌ی ملک، رهن، وام و تسهیلات مسکن، مالیات و عوارض ملک، سند و ثبت املاک و کدرهگیری، ساخت‌وساز و شهرسازی، قیمت و بازار ملک، طرح‌های مسکن دولتی (مثل نهضت ملی مسکن) یا قانون و دستوری باشد که روی مالک، خریدار، فروشنده یا مستأجر اثر دارد؛ حتی اگر از قوه قضاییه، دادستانی یا بانک مرکزی باشد. ورزش، سیاست، امنیت و دفاع، فرهنگ و هنر، سلامت، حوادث، اقتصاد عمومی (دلار، طلا، بورس) و راه و ترابری بدون ارتباط مستقیم با مسکن = «خیر».\n"
    "تیتر = حداکثر ۹ کلمه.\n"
    "نسبت‌دهی = یک عبارت کوتاه (حداکثر ۱۰ کلمه) که بگوید خبر یا دستور از کیست، فقط بر اساس متن؛ فرد یا نهاد، مثلاً «به دستور قوه قضاییه»، «به گفتهٔ وزیر راه و شهرسازی»، «بر اساس اعلام سازمان ثبت»، «طبق مصوبهٔ هیئت وزیران». خبرنگار، نویسنده و رسانه حساب نمی‌شوند. اگر فرد و نهاد هر دو در متن هست هر دو را بنویس. اگر واقعاً در متن نیست فقط بنویس: نامشخص\n"
    "خلاصه = حداکثر ۳ جمله، فقط واقعیت‌های متن.\n"
    "خلاصه که = ۱ تا ۲ جمله: نتیجه‌ی عملی برای خواننده (خریدار، فروشنده، مالک یا مستأجر) که مستقیم از واقعیت‌های همین متن گرفته شود. اگر متن برای نتیجه‌گیری کافی نیست فقط بنویس: ندارد\n"
    "اهمیت = فقط یک عدد ۱ تا ۵. ۵ = تغییر قانون، مالیات، وام یا هزینه که مستقیم روی خریدار، فروشنده یا مستأجر اثر دارد. ۳ = مفید برای مخاطب ملکی. ۱ = تشریفاتی یا تکراری."
)
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

_LABELS = ("خلاصه که", "نسبت‌دهی", "نسبت دهی", "مرتبط", "تیتر", "خلاصه", "اهمیت")
_LINE = re.compile(r"^\s*(?:[-•]\s*)?(" + "|".join(_LABELS) + r")\s*[:：]\s*(.*)$")

def parse_sections(txt: str):
    """خروجی مدل را خط‌به‌خط می‌خواند (حتی اگر مدل ستاره/تیتر مارک‌داون اضافه کرده باشد)."""
    fields, cur = {}, None
    for raw in (txt or "").replace("*", "").replace("#", "").splitlines():
        m = _LINE.match(raw)
        if m:
            cur = {"نسبت دهی": "نسبت‌دهی"}.get(m.group(1), m.group(1))
            fields[cur] = m.group(2).strip()
        elif cur and raw.strip():
            fields[cur] = (fields[cur] + " " + raw.strip()).strip()
    rel = fields.get("مرتبط", "").strip()
    related = True if rel.startswith("بله") else False if rel.startswith("خیر") else None
    m = re.search(r"[1-5۱-۵]", fields.get("اهمیت", ""))
    meaning = fields.get("خلاصه که", "").strip()
    if meaning.strip(" .") == "ندارد" or "اعلام نشده" in meaning:
        meaning = ""
    speaker = fields.get("نسبت‌دهی", "").strip().rstrip(":：").strip()
    return {"related": related, "headline": fields.get("تیتر", "").strip(), "speaker": speaker or "نامشخص",
            "summary": fields.get("خلاصه", "").strip(), "meaning": meaning,
            "importance": int(norm(m.group(0))) if m else 3}

def fallback(title: str, body: str):
    """وقتی هوش مصنوعی جواب نداد: خلاصه = جمله‌های اول خود خبر، بدون «خلاصه که» و بدون نسبت‌دهی ساختگی."""
    sents = [s.strip() for s in re.split(r"(?<=[.!؟?])\s+", body or "") if len(s.strip()) > 20][:2]
    return {"related": None, "headline": title[:80], "speaker": "نامشخص", "summary": " ".join(sents) or title,
            "meaning": "", "importance": 3}

async def analyze(title: str, body: str):
    """نتیجه: related (True/False/None=نامعلوم)، ai_failed، و فیلدهای متنی. دو بار تلاش می‌کند."""
    src = f"{title}\n{body}"
    data = {}
    for attempt in range(2):
        out = await gemini(f"عنوان: {title}\n\nمتن خبر:\n{body or title}", SYSTEM)
        data = parse_sections(out) if out else {}
        if data.get("summary") and data.get("related") is not None:
            break
        if attempt == 0:
            await asyncio.sleep(2)
    ai_failed = not (data.get("summary") and data.get("related") is not None)
    if ai_failed:
        data = fallback(title, body)
    data["ai_failed"] = ai_failed
    data["ai_error"] = LAST_ERROR if ai_failed else ""
    data["suspect_numbers"] = unsupported_numbers(src, " ".join(str(data.get(k, "")) for k in ("headline", "speaker", "summary", "meaning")))
    return data
