"""منطق ربات: پایش منابع، پیش‌نویس، دکمه‌های تأیید/ویرایش/رد، انتشار در کانال."""
import asyncio, re, time, html
import config, bale, sources, analyze, card
from db import db

def _fa_to_en_digits(value):
    return str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def _jalali_to_gregorian(jy, jm, jd):
    jy -= 979
    jm -= 1
    jd -= 1
    j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4)
    j_month_days = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    j_day_no += sum(j_month_days[:jm]) + jd
    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097
    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False
    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365
    g_month_days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and g_day_no >= g_month_days[gm]:
        g_day_no -= g_month_days[gm]
        gm += 1
    return gy, gm + 1, g_day_no + 1


def _gregorian_to_jalali(gy, gm, gd):
    g_month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += sum(g_month_days[:gm2]) + gd2
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm = 1
    while jm <= 11 and j_day_no >= (31 if jm <= 6 else 30):
        j_day_no -= 31 if jm <= 6 else 30
        jm += 1
    return jy, jm, j_day_no + 1


def _tehran_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Tehran"))


def _jalali_datetime_label(dt):
    jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} ساعت {dt:%H:%M} (تهران)"

PAUSED = False
_ALERTED = {}

async def alert(text, key=None, every=3600):
    """خطا را در بله به مدیر می‌گوید (برای هر خطای مشابه حداکثر یک بار در ساعت)."""
    k = key or text[:60]
    if time.time() - _ALERTED.get(k, 0) < every:
        return
    _ALERTED[k] = time.time()
    try:
        await bale.send_message(config.ADMIN_ID, text)
    except Exception:
        pass
KB = lambda i: [[{"text": "🚀 انتشار فوری", "callback_data": f"now:{i}"},
                 {"text": "🕒 زمان‌بندی انتشار", "callback_data": f"schedule:{i}"}],
                [{"text": "✏️ ویرایش متن", "callback_data": f"ed:{i}"}, {"text": "🔄 بازنویسی", "callback_data": f"re:{i}"}],
                [{"text": "❌ رد خبر", "callback_data": f"no:{i}"}]]

MENU = [["📰 خبرهای تازه", "🧪 نمونه"], ["📊 وضعیت", "🔄 بررسی فوری"], ["🔎 تست سیستم"], ["⏸ توقف پایش", "▶️ ادامه پایش"]]
MENU_CMD = {"📰 خبرهای تازه": "/latest", "🧪 نمونه": "/demo", "📊 وضعیت": "/status", "🔄 بررسی فوری": "/now",
            "🔎 تست سیستم": "/test", "⏸ توقف پایش": "/pause", "▶️ ادامه پایش": "/resume"}
INLINE_MENU = [[{"text": "📰 خبرهای تازه", "callback_data": "m:latest"}, {"text": "🧪 نمونه", "callback_data": "m:demo"}],
               [{"text": "📊 وضعیت", "callback_data": "m:status"}, {"text": "🔄 بررسی فوری", "callback_data": "m:now"}],
               [{"text": "🔎 تست سیستم", "callback_data": "m:test"}]]
STALE_HOURS = 48

def _tokens(s):
    return {w for w in re.findall(r"[\w\u0600-\u06FF]+", analyze.norm(s or "")) if len(w) > 2}

def similar(a, b, th=0.7):
    """شباهت دو تیتر (نسبت کلمات مشترک)؛ برای حذف خبر تکراری."""
    A, B = _tokens(a), _tokens(b)
    return bool(A and B) and len(A & B) / len(A | B) >= th

def is_duplicate(title):
    since = time.time() - 3 * 86400
    for d in db.drafts.find({"created": {"$gt": since}}, {"orig_title": 1, "headline": 1}):
        if similar(title, d.get("orig_title") or d.get("headline", "")):
            return True
    for d in db.skipped.find({"t": {"$gt": since}}, {"title": 1}):
        if similar(title, d.get("title", "")):
            return True
    return False

async def _guard(coro):
    try:
        await coro
    except Exception as e:
        print("task error:", e)
        await alert(f"❌ خطا: {type(e).__name__}: {str(e)[:200]}", key="task:" + type(e).__name__)

async def announce():
    """پیام روشن‌شدن (حداکثر هر ۳۰ دقیقه) + نصب کلیدهای ثابت پایین چت."""
    h = db.health.find_one({"_id": "startup"}) or {}
    if time.time() - h.get("t", 0) < 1800:
        return
    db.health.update_one({"_id": "startup"}, {"$set": {"t": time.time()}}, upsert=True)
    await bale.send_message(config.ADMIN_ID, "✅ ربات خبری روشن و آماده است.\nاز دکمه‌های پایین صفحه استفاده کنید.", reply_keyboard=MENU)

def short_url(u):
    """لینک خبر بدون بخش طولانی و رمزشده‌ی عنوان (مثلاً mehrnews.com/news/7012591)."""
    m = re.match(r"(https?://[^/]+/news/\d+)", u or "")
    return m.group(1) if m else (u or "")

def _safe(value):
    return html.escape(str(value or ""), quote=False)


def _clean_message_text(value):
    """اصلاح شکست‌خط‌هایی که ممکن است به‌صورت متن خام \\n ذخیره شده باشند."""
    return str(value or "").replace("\\n", "\n").replace("\\r\n", "\n").strip()


def build_caption(d):
    """متن عمومی؛ تیتر با قالب بولد سازگار با بله."""
    headline = _clean_message_text(d.get("headline", "")).replace("*", "")
    summary = _clean_message_text(d.get("summary", ""))
    meaning = _clean_message_text(d.get("meaning", ""))
    speaker = _clean_message_text(d.get("speaker", ""))
    parts = [f"*{headline}*"]
    if speaker and speaker != "نامشخص":
        parts.append(f"به گفتهٔ {speaker}:\n{summary}")
    else:
        parts.append(f"در متن خبر، نام مقام یا صادرکننده دستور مشخص نشده است.\n{summary}")
    if meaning:
        parts.append(f"💡 *خلاصه که؛*\n{meaning}")
    parts.append("⚖️ سهراب بهادر | بروکر املاک\n🆔 @BROKER_amlak\n📱 09123692401\n📱 09003692401")
    return "\n\n".join(p for p in parts if p)


def build_admin_caption(d):
    """اطلاعات مدیریتی محرمانه؛ فقط برای مدیر."""
    label = "🟢 خبر رسمی" if d.get("official") else "🟡 گزارش رسانه‌ای (تأیید رسمی نشده)"
    parts = [label, build_caption(d), f"📌 منبع: {d.get('source', '')}"]
    if d.get("url"):
        parts.append(f"🔗 لینک منبع: {short_url(d['url'])}")
    return "\\n\\n".join(p for p in parts if p)

def _next_id():
    r = db.counters.find_one_and_update({"_id": "draft"}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
    return r["n"]

def _card(d):
    return card.make_card(d["headline"], d["summary"], d["source"], d["official"], "بروکر املاک")

async def make_draft(title, body, source_name, official, url="", min_score=0):
    a = await analyze.analyze(title, body)
    if a.get("importance", 3) < min_score:        # کم‌اهمیت: ثبت می‌شود ولی مزاحم مدیر نمی‌شود
        db.skipped.insert_one({"title": title[:120], "source": source_name, "score": a.get("importance"), "t": time.time()})
        return False
    i = _next_id()
    d = {"_id": i, "headline": a["headline"] or title[:80], "speaker": a.get("speaker", "نامشخص"), "summary": a["summary"], "meaning": a["meaning"],
         "source": source_name, "official": official, "url": url, "status": "draft", "created": time.time(),
         "custom_caption": None, "importance": a.get("importance", 3), "orig_title": title[:200]}
    db.drafts.insert_one(d)
    await show_draft(d, a.get("suspect_numbers"))
    return True

async def show_draft(d, suspect=None):
    cap = d.get("custom_caption") or build_caption(d)
    warn = ""
    if suspect:
        warn = f"\n\n⚠️ این عددها در متن مبدأ پیدا نشد؛ قبل از انتشار حتماً بررسی کنید: {', '.join(suspect)}"
    head = f"📝 پیش‌نویس #{d['_id']} | ⭐ اهمیت {d.get('importance', 3)}/5"
    admin_text = build_admin_caption(d) if not d.get("custom_caption") else build_admin_caption(d) + "\n\n✏️ متن ویرایش‌شده:\n" + _safe(cap)
    await bale.send_message(config.ADMIN_ID, f"{head}\n\n{admin_text}{warn}", KB(d["_id"]), parse_mode="HTML")

async def publish(d):
    cap = build_caption(d)
    if d.get("custom_caption"):
        edited = str(d["custom_caption"])
        cap = f"*{str(d.get('headline', '')).replace('*', '')}*\n\n{edited}"
    return await bale.send_message(config.CHANNEL_ID, cap, parse_mode="Markdown")

# ---------- پایش منابع ----------
async def process_items(src, items, bodies=None, limit=5):
    """خبر جدید را فیلتر و پیش‌نویس می‌کند. اگر ساخت پیش‌نویس خطا بدهد، خبر گم نمی‌شود و دور بعد دوباره تلاش می‌شود (حداکثر ۳ بار)."""
    first_run = db.seen.count_documents({"src": src["key"]}) == 0
    created = 0
    for it in items[:40]:
        u = sources.uid(it["url"])
        if db.seen.find_one({"_id": u}):
            continue
        rec = {"_id": u, "src": src["key"], "title": it["title"], "t": time.time()}
        if first_run or (not src.get("topic") and not sources.is_relevant(it["title"])) or is_duplicate(it["title"]):
            db.seen.insert_one(rec)          # اجرای اول فقط خط پایه است؛ تکراری و نامرتبط هم کنار گذاشته می‌شود
            continue
        body = (bodies or {}).get(it["url"]) or it.get("body") or ""
        if not body and bodies is None:
            try: body = await sources.article_text(it["url"])
            except Exception: body = ""
        try:
            ok = await make_draft(it["title"], body, src["name"], src["official"], it["url"], min_score=config.MIN_SCORE)
        except Exception as e:
            n = db.fails.find_one_and_update({"_id": u}, {"$inc": {"n": 1}}, upsert=True, return_document=True)["n"]
            await alert(f"❌ ساخت پیش‌نویس ناموفق ({n}/3)\nخبر: {it['title'][:80]}\nخطا: {type(e).__name__}: {str(e)[:200]}", key="draft:" + u)
            if n >= 3:
                db.seen.insert_one(rec)
            continue
        db.seen.insert_one(rec)
        if ok:
            created += 1
            if created >= limit:
                break
    return created

async def poll_sources(force=False):
    if PAUSED and not force:
        return 0
    created = 0
    for src in config.SOURCES:
        if src.get("relay"):
            continue                          # این منبع‌ها از رله می‌آیند
        try:
            items = await sources.list_items(src)
        except Exception as e:
            db.health.update_one({"_id": src["key"]}, {"$set": {"error": str(e)[:200], "t": time.time()}}, upsert=True)
            await alert(f"⚠️ خواندن «{src['name']}» ناموفق بود: {type(e).__name__}", key="src:" + src["key"])
            continue
        db.health.update_one({"_id": src["key"]}, {"$set": {"error": None, "ok_at": time.time(), "count": len(items)}}, upsert=True)
        created += await process_items(src, items)
    return created

async def ingest_relay(key, items):
    src = next((s for s in config.SOURCES if s["key"] == key), None)
    if not src:
        return -1
    db.health.update_one({"_id": key}, {"$set": {"error": None, "ok_at": time.time(), "count": len(items), "via": "relay"}}, upsert=True)
    return await process_items(src, items, bodies={})

# ---------- تست دسترسی ----------
async def diagnose():
    lines = ["🔎 نتیجه‌ی تست دسترسی (از سرور Render):"]
    for src in config.SOURCES:
        try:
            r, t = await sources.fetch(src["url"])
            items = await sources.list_items(src)
            _, feeds = sources.extract_links(r.text, src["url"])
            lines.append(f"{'✅' if r.status_code == 200 else '⚠️'} {src['name']}: کد {r.status_code} | {t}s | {len(items)} خبر | RSS: {'دارد' if feeds else 'ندارد'}")
            for it in items[:3]:
                lines.append(f"   • {it['title'][:70]}")
        except Exception as e:
            lines.append(f"❌ {src['name']}: باز نشد ({type(e).__name__}) — آی‌پی خارجی مسدود است؛ این منبع باید از «رله» بیاید")
    g = await analyze.gemini("بنویس: سلام", max_tokens=20)
    lines.append("✅ هوش مصنوعی Gemini: پاسخ داد" if g else f"❌ Gemini: {analyze.LAST_ERROR or 'پاسخ نداد'}")
    try:
        db.health.update_one({"_id": "selftest"}, {"$set": {"t": time.time()}}, upsert=True)
        db.health.find_one({"_id": "selftest"})
        lines.append("✅ دیتابیس: خواندن و نوشتن کار می‌کند")
    except Exception as e:
        lines.append(f"❌ دیتابیس: اجازه‌ی نوشتن ندارد ({type(e).__name__}: {str(e)[:120]})")
    ch = await bale.call("getChat", chat_id=config.CHANNEL_ID)
    lines.append("✅ کانال: ربات به کانال دسترسی دارد" if ch.get("ok") else f"❌ کانال: {ch.get('description', 'خطا')} (ربات را ادمین کانال کنید)")
    return "\n".join(lines)

# ---------- پیام‌ها و دکمه‌ها ----------
async def handle_callback(cb):
    if (cb.get("from") or {}).get("id") != config.ADMIN_ID:
        return
    data = cb.get("data") or ""
    if data.startswith("m:"):                      # منوی سریع زیر پیام
        await bale.answer_callback(cb["id"])
        await handle_message({"from": cb["from"], "text": "/" + data[2:]})
        return
    action, _, sid = data.partition(":")
    d = db.drafts.find_one({"_id": int(sid)}) if sid.isdigit() else None
    if not d or d["status"] != "draft":
        await bale.answer_callback(cb["id"], "این پیش‌نویس دیگر فعال نیست"); return
    if action == "schedule":
        db.state.update_one({"_id": "schedule"}, {"$set": {"draft": d["_id"]}}, upsert=True)
        await bale.answer_callback(cb["id"])
        await bale.send_message(config.ADMIN_ID, "🕒 زمان انتشار را به تاریخ شمسی و ساعت تهران بفرستید.\nقالب: ۱۴۰۵/۰۹/۰۳ ۱۸:۳۰\nبرای انتشار در ساعت مشخص امروز فقط ساعت را بفرستید: ۱۸:۳۰")
        return
    if action in ("now", "ok"):
        if time.time() - d["created"] > STALE_HOURS * 3600:
            db.drafts.update_one({"_id": d["_id"]}, {"$set": {"status": "expired"}})
            await bale.answer_callback(cb["id"], "قدیمی شده؛ خبر را دوباره بگیرید"); return
        # قفل اتمی: دو بار زدن دکمه، دو بار منتشر نکند
        if not db.drafts.find_one_and_update({"_id": d["_id"], "status": "draft"}, {"$set": {"status": "publishing"}}):
            await bale.answer_callback(cb["id"], "قبلاً بررسی شده"); return
        r = await publish(d)
        ok = bool(r.get("ok"))
        db.drafts.update_one({"_id": d["_id"]}, {"$set": {"status": "published", "published_at": time.time()} if ok else {"status": "draft"}})
        await bale.answer_callback(cb["id"], "منتشر شد ✅" if ok else "انتشار ناموفق")
        if not ok:
            await bale.send_message(config.ADMIN_ID, f"❌ انتشار #{sid} ناموفق: {r.get('description', '')}")
    elif action == "no":
        db.drafts.update_one({"_id": d["_id"]}, {"$set": {"status": "rejected"}})
        await bale.answer_callback(cb["id"], "رد شد")
    elif action == "ed":
        db.state.update_one({"_id": "edit"}, {"$set": {"draft": d["_id"]}}, upsert=True)
        await bale.answer_callback(cb["id"])
        await bale.send_message(config.ADMIN_ID, f"✏️ متن کامل پست #{sid} را بفرستید (جایگزین می‌شود).")
    elif action == "re":
        await bale.answer_callback(cb["id"], "در حال بازنویسی…")
        a = await analyze.analyze(d["headline"], d["summary"])
        db.drafts.update_one({"_id": d["_id"]}, {"$set": {"summary": a["summary"], "meaning": a["meaning"], "speaker": a.get("speaker", d.get("speaker", "نامشخص")), "custom_caption": None}})
        await show_draft(db.drafts.find_one({"_id": d["_id"]}))

async def _handle(m):
    global PAUSED
    text = m["text"]
    if text.startswith("/start") or text.startswith("/menu"):
        await bale.send_message(config.ADMIN_ID, "سلام 👋 ربات خبری بروکر املاک آماده است.\nبرای همه‌ی کارها از کلیدهای ثابت پایین صفحه استفاده کنید؛ لازم نیست چیزی تایپ کنید.\nهر متن خبری را هم می‌توانید فوروارد کنید تا پیش‌نویس شود.", reply_keyboard=MENU)
        await bale.send_message(config.ADMIN_ID, "منوی سریع:", keyboard=INLINE_MENU)
    elif text.startswith("/test"):
        await bale.send_message(config.ADMIN_ID, await diagnose())
    elif text.startswith("/now"):
        n = await poll_sources(force=True)
        await bale.send_message(config.ADMIN_ID, f"بررسی انجام شد. پیش‌نویس جدید: {n}")
    elif text.startswith("/demo"):
        try:
            src = next(s for s in config.SOURCES if not s["relay"])
            items = await sources.list_items(src)
            it = next((i for i in items if sources.is_relevant(i["title"])), None) or (items[0] if items else None)
            if not it:
                await bale.send_message(config.ADMIN_ID, "هیچ خبری از منبع پیدا نشد.")
            else:
                await bale.send_message(config.ADMIN_ID, f"⏳ در حال ساخت نمونه از: {it['title'][:80]}")
                try: body = await sources.article_text(it["url"])
                except Exception: body = ""
                await make_draft(it["title"], body, src["name"], src["official"], it["url"], min_score=0)
        except Exception as e:
            await bale.send_message(config.ADMIN_ID, f"❌ نمونه ساخته نشد: {type(e).__name__}: {str(e)[:300]}")
    elif text.startswith("/latest"):
        parts = text.split()
        n = min(int(parts[1]), 5) if len(parts) > 1 and parts[1].isdigit() else 3
        made = tried = 0
        try:
            await bale.send_message(config.ADMIN_ID, f"⏳ در حال ساخت {n} پیش‌نویس از تازه‌ترین خبرها (چند دقیقه طول می‌کشد)…")
            for src in [s for s in config.SOURCES if not s["relay"]]:
                items = await sources.list_items(src)
                for it in items:
                    if made >= n or tried >= 12: break
                    if not src.get("topic") and not sources.is_relevant(it["title"]): continue
                    if db.drafts.find_one({"url": it["url"]}): continue
                    tried += 1
                    try: body = await sources.article_text(it["url"])
                    except Exception: body = ""
                    if await make_draft(it["title"], body, src["name"], src["official"], it["url"], min_score=config.MIN_SCORE):
                        made += 1
            note = "" if made >= n else f" (بقیه امتیاز کمتر از {config.MIN_SCORE} گرفتند)"
            await bale.send_message(config.ADMIN_ID, f"✅ {made} پیش‌نویس ساخته شد{note}.")
        except Exception as e:
            await bale.send_message(config.ADMIN_ID, f"❌ خطا: {type(e).__name__}: {str(e)[:300]}")
    elif text.startswith("/pause"):
        PAUSED = True; await bale.send_message(config.ADMIN_ID, "⏸ پایش متوقف شد.")
    elif text.startswith("/resume"):
        PAUSED = False; await bale.send_message(config.ADMIN_ID, "▶️ پایش ادامه یافت.")
    elif text.startswith("/status"):
        lines = ["📊 وضعیت منابع:"]
        hb = db.health.find_one({"_id": "scheduler"}) or {}
        if hb.get("t"):
            lines.append(f"🕒 آخرین چرخه‌ی پایش: {int((time.time() - hb['t']) / 60)} دقیقه پیش" + (f" | خطا: {hb['error']}" if hb.get("error") else ""))
        else:
            lines.append("🕒 هنوز هیچ چرخه‌ی پایشی اجرا نشده")
        for s in config.SOURCES:
            h = db.health.find_one({"_id": s["key"]}) or {}
            lines.append(f"{'✅' if not h.get('error') and h.get('ok_at') else '❌'} {s['name']}: {h.get('count', '—')} لینک" + (f" | خطا: {h['error'][:60]}" if h.get("error") else ""))
        lines.append(f"پیش‌نویس‌های منتظر: {db.drafts.count_documents({'status': 'draft'})} | خبرهای کم‌اهمیت‌شده (۷ روز): {db.skipped.count_documents({'t': {'$gt': time.time() - 7 * 86400}})}")
        now = time.time()
        lines.append(f"📤 منتشرشده: امروز {db.drafts.count_documents({'status': 'published', 'published_at': {'$gt': now - 86400}})} | ۷ روز {db.drafts.count_documents({'status': 'published', 'published_at': {'$gt': now - 7 * 86400}})}")
        await bale.send_message(config.ADMIN_ID, "\n".join(lines))
    elif text and not text.startswith("/"):
        sched = db.state.find_one_and_delete({"_id": "schedule"})
        if sched:
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo
                value = _fa_to_en_digits(text.strip()).replace("-", "/")
                tz = ZoneInfo("Asia/Tehran")
                if re.fullmatch(r"\\d{1,2}:\\d{2}", value):
                    now_local = _tehran_now()
                    value = f"{_gregorian_to_jalali(now_local.year, now_local.month, now_local.day)[0]:04d}/{_gregorian_to_jalali(now_local.year, now_local.month, now_local.day)[1]:02d}/{_gregorian_to_jalali(now_local.year, now_local.month, now_local.day)[2]:02d} {value}"
                match = re.fullmatch(r"(\\d{4})/(\\d{1,2})/(\\d{1,2})\\s+(\\d{1,2}):(\\d{2})", value)
                if not match:
                    raise ValueError("قالب تاریخ و ساعت درست نیست")
                jy, jm, jd, hh, minute = map(int, match.groups())
                gy, gm, gd = _jalali_to_gregorian(jy, jm, jd)
                dt = datetime(gy, gm, gd, hh, minute, tzinfo=tz)
                if dt.timestamp() <= time.time():
                    raise ValueError("زمان باید در آینده باشد")
                target = db.drafts.find_one({"_id": sched["draft"], "status": "draft"})
                if not target:
                    await bale.send_message(config.ADMIN_ID, "❌ این پیش‌نویس دیگر قابل زمان‌بندی نیست.")
                else:
                    db.drafts.update_one({"_id": target["_id"], "status": "draft"},
                                         {"$set": {"status": "scheduled", "scheduled_at": dt.timestamp()}})
                    await bale.send_message(config.ADMIN_ID, f"✅ خبر #{target['_id']} برای {_jalali_datetime_label(dt)} زمان‌بندی شد.")
            except Exception:
                await bale.send_message(config.ADMIN_ID, "❌ تاریخ یا ساعت نامعتبر است یا در گذشته قرار دارد. نمونه: ۱۴۰۵/۰۹/۰۳ ۱۸:۳۰ یا ۱۸:۳۰")
        else:
            st = db.state.find_one_and_delete({"_id": "edit"})
            if st:
                db.drafts.update_one({"_id": st["draft"]}, {"$set": {"custom_caption": text}})
                await show_draft(db.drafts.find_one({"_id": st["draft"]}))
            elif len(text) >= 40:
                await make_draft(text.split("\n")[0][:90], text, "ارسال دستی مدیر", False)
            else:
                await bale.send_message(config.ADMIN_ID, "متن خبر را کامل‌تر بفرستید (حداقل چند جمله).")

async def handle_message(m):
    """فقط مدیر؛ کلیدهای ثابت به دستور تبدیل می‌شوند و هر کار در پس‌زمینه اجرا می‌شود تا پایش پیام‌ها قفل نشود."""
    if (m.get("from") or {}).get("id") != config.ADMIN_ID:
        return
    text = (m.get("text") or m.get("caption") or "").strip()
    text = MENU_CMD.get(text, text)
    asyncio.create_task(_guard(_handle({**m, "text": text})))

async def poll_updates():
    offset = None
    while True:
        try:
            r = await bale.get_updates(offset, timeout=30)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if u.get("callback_query"): asyncio.create_task(_guard(handle_callback(u["callback_query"])))
                elif u.get("message"): await handle_message(u["message"])
        except Exception as e:
            print("updates error:", e)
            await alert(f"❌ خطای ربات هنگام پردازش پیام: {type(e).__name__}: {str(e)[:200]}", key="upd")
            await asyncio.sleep(5)

async def publish_scheduled():
    """انتشار خبرهایی که زمان تعیین‌شده‌شان رسیده است."""
    now = time.time()
    due = list(db.drafts.find({"status": "scheduled", "scheduled_at": {"$lte": now}}).limit(20))
    for d in due:
        locked = db.drafts.find_one_and_update(
            {"_id": d["_id"], "status": "scheduled"},
            {"$set": {"status": "publishing"}}
        )
        if not locked:
            continue
        try:
            result = await publish(d)
            if result.get("ok"):
                db.drafts.update_one({"_id": d["_id"]},
                    {"$set": {"status": "published", "published_at": time.time(), "scheduled_at": None}})
            else:
                db.drafts.update_one({"_id": d["_id"]},
                    {"$set": {"status": "scheduled", "scheduled_at": now + 300}})
                await alert(f"❌ انتشار زمان‌بندی‌شده #{d['_id']} ناموفق بود؛ ۵ دقیقه دیگر دوباره تلاش می‌شود.")
        except Exception as e:
            db.drafts.update_one({"_id": d["_id"]},
                {"$set": {"status": "scheduled", "scheduled_at": now + 300}})
            await alert(f"❌ خطای انتشار زمان‌بندی‌شده #{d['_id']}: {type(e).__name__}")


async def scheduler():
    await asyncio.sleep(10)
    try:
        await announce()
    except Exception as e:
        print("announce error:", e)
    await asyncio.sleep(5)
    last_poll = 0
    while True:
        try:
            await publish_scheduled()
            if time.time() - last_poll >= config.POLL_SECONDS:
                n = await poll_sources()
                last_poll = time.time()
                print(f"poll cycle ok, new drafts: {n}")
                db.health.update_one({"_id": "scheduler"}, {"$set": {"t": time.time(), "drafts": n, "error": None}}, upsert=True)
        except Exception as e:
            print("scheduler error:", e)
            db.health.update_one({"_id": "scheduler"}, {"$set": {"t": time.time(), "error": f"{type(e).__name__}: {str(e)[:150]}"}}, upsert=True)
            await alert(f"❌ خطا در چرخه‌ی پایش: {type(e).__name__}: {str(e)[:200]}", key="sched")
        await asyncio.sleep(5)
