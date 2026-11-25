"""منطق ربات: پایش منابع، پیش‌نویس، تأیید/زمان‌بندی/انتشار در کانال و فرمان‌های مدیر.

قواعد پایدار:
- فقط ادمین (ADMIN_ID) می‌تواند دستور بدهد؛ پیام و دکمه‌ی دیگران نادیده گرفته می‌شود.
- خبر فقط وقتی پیش‌نویس می‌شود که هوش مصنوعی آن را «مرتبط با املاک» بداند. خطای هوش مصنوعی یعنی رد، نه عبور.
- برچسب رسمی/غیررسمی، منبع و لینک فقط در پیام مدیر هستند؛ متن کانال از compose.public_text ساخته می‌شود.
"""
import asyncio, re, time
from datetime import datetime, timedelta
import config, bale, sources, analyze, card, compose, jalali
from db import db

PAUSED = False
STALE_HOURS = 48
MAX_DRAFTS_PER_CYCLE = 6
_ALERTED = {}
_TASKS = set()

# ---------- ابزارهای عمومی ----------
def _spawn(coro):
    """کار را در پس‌زمینه اجرا می‌کند و مرجعش را نگه می‌دارد تا جمع‌آوری نشود."""
    t = asyncio.create_task(_guard(coro))
    _TASKS.add(t); t.add_done_callback(_TASKS.discard)

async def _guard(coro):
    try:
        await coro
    except Exception as e:
        print("task error:", type(e).__name__, e)
        await alert(f"❌ خطا: {type(e).__name__}: {str(e)[:200]}", key="task:" + type(e).__name__)

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

async def announce():
    """پیام روشن‌شدن (حداکثر هر ۳۰ دقیقه) + نصب کلیدهای ثابت پایین چت."""
    h = db.health.find_one({"_id": "startup"}) or {}
    if time.time() - h.get("t", 0) < 1800:
        return
    db.health.update_one({"_id": "startup"}, {"$set": {"t": time.time()}}, upsert=True)
    await bale.send_message(config.ADMIN_ID, "✅ ربات خبری روشن و آماده است.\nاز دکمه‌های پایین صفحه استفاده کنید.", reply_keyboard=MENU)

def is_duplicate(title):
    since = time.time() - 3 * 86400
    for d in db.drafts.find({"created": {"$gt": since}}, {"orig_title": 1, "headline": 1}):
        if compose.similar(title, d.get("orig_title") or d.get("headline", "")):
            return True
    for d in db.skipped.find({"t": {"$gt": since}}, {"title": 1}):
        if compose.similar(title, d.get("title", "")):
            return True
    return False

# ---------- ارسال (متن؛ پوستر فقط اگر SEND_IMAGES روشن باشد) ----------
def _card(d):
    return card.make_card(d["headline"], d["summary"], d.get("source", ""), bool(d.get("official")), "بروکر املاک")

async def send_post(chat_id, d, text, keyboard=None):
    if config.SEND_IMAGES:
        try:
            png = _card(d)
        except Exception as e:
            print("card error:", type(e).__name__, e); png = None
        if png:
            short = len(text) <= 1000
            r = await bale.send_photo(chat_id, png, caption=text if short else compose.plain(d.get("headline", ""))[:200],
                                      keyboard=keyboard if short else None)
            if r.get("ok"):
                return r if short else await bale.send_message(chat_id, text, keyboard=keyboard)
    return await bale.send_message(chat_id, text, keyboard=keyboard)

def _next_id():
    r = db.counters.find_one_and_update({"_id": "draft"}, {"$inc": {"n": 1}}, upsert=True, return_document=True)
    return r["n"]

async def make_draft(title, body, source_name, official, url="", min_score=0, manual=False):
    """True = پیش‌نویس ساخته و فرستاده شد؛ False = نامرتبط/کم‌اهمیت (ثبت می‌شود)؛ خطا = استثنا (دور بعد دوباره تلاش می‌شود)."""
    a = await analyze.analyze(title, body)
    if not manual:
        if a["ai_failed"]:
            raise RuntimeError("تحلیل هوش مصنوعی انجام نشد: " + (a.get("ai_error") or "پاسخ نامعتبر"))
        if a["related"] is not True or a["importance"] < min_score:
            db.skipped.insert_one({"title": title[:120], "source": source_name, "score": a["importance"],
                                   "reason": "نامرتبط" if a["related"] is not True else "کم‌اهمیت", "t": time.time()})
            return False
    d = {"_id": _next_id(), "headline": a["headline"] or title[:80], "speaker": a["speaker"], "summary": a["summary"],
         "meaning": a["meaning"], "source": source_name, "official": official, "url": url, "status": "draft",
         "created": time.time(), "custom_caption": None, "importance": a["importance"], "orig_title": title[:200],
         "body": (body or "")[:4500], "ai_failed": a["ai_failed"], "ai_error": a.get("ai_error", "")}
    db.drafts.insert_one(d)
    await show_draft(d, a.get("suspect_numbers"))
    return True

async def show_draft(d, suspect=None):
    warn = ""
    if suspect:
        warn = f"\n\n⚠️ این عددها در متن مبدأ پیدا نشد؛ قبل از انتشار حتماً بررسی کنید: {', '.join(suspect)}"
    r = await send_post(config.ADMIN_ID, d, compose.admin_text(d, warn), keyboard=KB(d["_id"]))
    if not (r and r.get("ok")):
        await bale.send_message(config.ADMIN_ID, f"❌ ارسال پیش‌نویس #{d['_id']} ناموفق بود: {(r or {}).get('description', '')}")

async def publish(d):
    return await send_post(config.CHANNEL_ID, d, compose.public_text(d))

# ---------- زمان‌بندی (تقویم شمسی؛ وضعیت هر پیش‌نویس جدا نگه داشته می‌شود) ----------
def _sch(draft_id):
    return db.state.find_one({"_id": f"sch:{draft_id}"}) or {}

def _sch_set(draft_id, **kw):
    db.state.update_one({"_id": f"sch:{draft_id}"}, {"$set": {"draft": draft_id, **kw}}, upsert=True)

def _set_kb(st, rows):
    return bale.edit_message_keyboard(st["chat_id"], st["message_id"], rows)

def _menu_kb(i):
    return [[{"text": "🚀 انتشار فوری", "callback_data": f"now:{i}"}],
            [{"text": "امروز", "callback_data": f"sctoday:{i}"}, {"text": "فردا", "callback_data": f"sctomorrow:{i}"}],
            [{"text": "📅 انتخاب تاریخ", "callback_data": f"scalendar:{i}"}, {"text": "✖ انصراف", "callback_data": f"sccancel:{i}"}]]

def _time_kb(i):
    return [[{"text": "۰۹:۰۰", "callback_data": f"caltime:{i}:09:00"}, {"text": "۱۲:۰۰", "callback_data": f"caltime:{i}:12:00"}],
            [{"text": "۱۸:۰۰", "callback_data": f"caltime:{i}:18:00"}, {"text": "۲۱:۰۰", "callback_data": f"caltime:{i}:21:00"}],
            [{"text": "⌨️ ورود ساعت دلخواه", "callback_data": f"scmanual:{i}"}, {"text": "↩ بازگشت", "callback_data": f"scback:{i}"}]]

def _scheduled_kb(i, label):
    return [[{"text": f"🕒 {label}", "callback_data": "calnoop"}], [{"text": "↩ لغو زمان‌بندی", "callback_data": f"unsched:{i}"}]]

async def _finish_schedule(draft_id, jy, jm, jd, hh, mm):
    """پیش‌نویس را زمان‌بندی می‌کند و برچسب زمان را برمی‌گرداند؛ ValueError برای زمان نامعتبر/گذشته، LookupError اگر پیش‌نویس فعال نیست."""
    ts = jalali.to_timestamp(jy, jm, jd, hh, mm)
    if ts <= time.time():
        raise ValueError("زمان باید در آینده باشد")
    if not db.drafts.find_one_and_update({"_id": draft_id, "status": "draft"}, {"$set": {"status": "scheduled", "scheduled_at": ts}}):
        raise LookupError("این پیش‌نویس دیگر قابل زمان‌بندی نیست")
    return jalali.datetime_label(datetime.fromtimestamp(ts, jalali.TEHRAN))

async def _cb_schedule(cb, action, parts, d, chat_id, message_id):
    did = d["_id"]
    if message_id:
        _sch_set(did, chat_id=chat_id, message_id=message_id)
    st = _sch(did)
    ack = lambda text="": bale.answer_callback(cb["id"], text)
    if action in ("schedule", "scback"):
        await ack(); await _set_kb(st, _menu_kb(did))
    elif action in ("sccancel", "calcancel"):
        db.state.delete_one({"_id": f"sch:{did}"}); db.state.delete_one({"_id": "awaiting_time", "draft": did})
        await ack("انصراف"); await _set_kb(st, KB(did))
    elif action in ("sctoday", "sctomorrow"):
        day = jalali.tehran_now() + (timedelta(days=1) if action == "sctomorrow" else timedelta(0))
        jy, jm, jd = jalali.gregorian_to_jalali(day.year, day.month, day.day)
        _sch_set(did, jy=jy, jm=jm, jd=jd)
        await ack(f"{jy}/{jm:02d}/{jd:02d}"); await _set_kb(st, _time_kb(did))
    elif action == "scalendar":
        jy, jm, _ = jalali.today_jalali()
        await ack(); await _set_kb(st, jalali.calendar_rows(jy, jm, did) + [[{"text": "↩ بازگشت", "callback_data": f"scback:{did}"}]])
    elif action in ("calprev", "calnext"):
        jy, jm = int(parts[2]), int(parts[3])
        jm += -1 if action == "calprev" else 1
        if jm < 1: jy, jm = jy - 1, 12
        if jm > 12: jy, jm = jy + 1, 1
        await ack(); await _set_kb(st, jalali.calendar_rows(jy, jm, did) + [[{"text": "↩ بازگشت", "callback_data": f"scback:{did}"}]])
    elif action == "calday":
        jy, jm, jd = int(parts[2]), int(parts[3]), int(parts[4])
        _sch_set(did, jy=jy, jm=jm, jd=jd)
        await ack(f"{jy}/{jm:02d}/{jd:02d}"); await _set_kb(st, _time_kb(did))
    elif action == "caltime":
        st = _sch(did)
        if not st.get("jy"):
            await ack("ابتدا تاریخ را انتخاب کن"); return
        try:
            label = await _finish_schedule(did, st["jy"], st["jm"], st["jd"], int(parts[2]), int(parts[3]))
        except (ValueError, LookupError) as e:
            await ack(str(e)); return
        db.state.delete_one({"_id": f"sch:{did}"})
        await ack("زمان‌بندی شد ✅"); await _set_kb(st, _scheduled_kb(did, label))
        await bale.send_message(config.ADMIN_ID, f"✅ خبر #{did} برای {label} زمان‌بندی شد.")
    elif action == "scmanual":
        if not st.get("jy"):
            await ack("ابتدا تاریخ را انتخاب کن"); return
        db.state.update_one({"_id": "awaiting_time"}, {"$set": {"draft": did}}, upsert=True)
        await ack()
        await bale.send_message(config.ADMIN_ID, f"⌨️ ساعت انتشار خبر #{did} را بفرست، مثل ۱۸:۳۰ (برای انصراف بنویس: لغو)")
    else:
        await ack()

# ---------- دکمه‌ها ----------
async def handle_callback(cb):
    if (cb.get("from") or {}).get("id") != config.ADMIN_ID:
        return
    data = cb.get("data") or ""
    if data == "calnoop":
        await bale.answer_callback(cb["id"]); return
    if data.startswith("m:"):                          # منوی سریع
        await bale.answer_callback(cb["id"])
        await handle_message({"from": cb["from"], "text": "/" + data[2:]}); return
    parts = data.split(":")
    action = parts[0]
    try:
        did = int(parts[1])
    except (IndexError, ValueError):
        await bale.answer_callback(cb["id"], "دکمه نامعتبر"); return
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id", config.ADMIN_ID)
    message_id = msg.get("message_id")
    d = db.drafts.find_one({"_id": did})
    if action == "unsched":
        if d and db.drafts.find_one_and_update({"_id": did, "status": "scheduled"}, {"$set": {"status": "draft", "scheduled_at": None}}):
            await bale.answer_callback(cb["id"], "زمان‌بندی لغو شد")
            await bale.edit_message_keyboard(chat_id, message_id, KB(did))
        else:
            await bale.answer_callback(cb["id"], "قابل لغو نیست")
        return
    if not d or d["status"] != "draft":
        await bale.answer_callback(cb["id"], "این پیش‌نویس دیگر فعال نیست"); return

    if action in ("now", "ok"):
        if time.time() - d["created"] > STALE_HOURS * 3600:
            db.drafts.update_one({"_id": did}, {"$set": {"status": "expired"}})
            await bale.answer_callback(cb["id"], "قدیمی شده؛ خبر را دوباره بگیرید"); return
        if not db.drafts.find_one_and_update({"_id": did, "status": "draft"}, {"$set": {"status": "publishing"}}):   # قفل: دوبار زدن، دوبار منتشر نکند
            await bale.answer_callback(cb["id"], "قبلاً بررسی شده"); return
        try:
            r = await publish(d)
        except Exception as e:
            r = {"ok": False, "description": f"{type(e).__name__}: {str(e)[:120]}"}
        ok = bool(r.get("ok"))
        db.drafts.update_one({"_id": did}, {"$set": {"status": "published", "published_at": time.time()} if ok else {"status": "draft"}})
        await bale.answer_callback(cb["id"], "منتشر شد ✅" if ok else "انتشار ناموفق")
        if ok:
            await bale.edit_message_keyboard(chat_id, message_id, [[{"text": "✅ منتشر شد", "callback_data": "calnoop"}]])
        else:
            await bale.send_message(config.ADMIN_ID, f"❌ انتشار #{did} ناموفق: {r.get('description', '')}")
    elif action == "no":
        db.drafts.update_one({"_id": did}, {"$set": {"status": "rejected"}})
        await bale.answer_callback(cb["id"], "رد شد")
        await bale.edit_message_keyboard(chat_id, message_id, [[{"text": "❌ رد شد", "callback_data": "calnoop"}]])
    elif action == "ed":
        db.state.update_one({"_id": "edit"}, {"$set": {"draft": did}}, upsert=True)
        await bale.answer_callback(cb["id"])
        await bale.send_message(config.ADMIN_ID, f"✏️ متن پست #{did} را بفرست. تیتر (بولد) و امضا خودکار اضافه می‌شوند؛ برای انصراف بنویس: لغو")
    elif action == "re":
        await bale.answer_callback(cb["id"], "در حال بازنویسی…")
        a = await analyze.analyze(d.get("orig_title") or d["headline"], d.get("body") or d["summary"])
        if a["ai_failed"]:
            await bale.send_message(config.ADMIN_ID, "❌ بازنویسی انجام نشد: " + (a.get("ai_error") or "پاسخ نامعتبر")); return
        db.drafts.update_one({"_id": did}, {"$set": {"headline": a["headline"] or d["headline"], "speaker": a["speaker"], "summary": a["summary"],
                                                     "meaning": a["meaning"], "importance": a["importance"], "ai_failed": False,
                                                     "ai_error": "", "custom_caption": None}})
        await show_draft(db.drafts.find_one({"_id": did}), a.get("suspect_numbers"))
    elif action == "schedule" or action.startswith(("sc", "cal")):
        await _cb_schedule(cb, action, parts, d, chat_id, message_id)
    else:
        await bale.answer_callback(cb["id"])

# ---------- پایش منابع ----------
async def process_items(src, items, bodies=None, limit=MAX_DRAFTS_PER_CYCLE):
    """خبر جدید را فیلتر و پیش‌نویس می‌کند. اگر ساخت پیش‌نویس خطا بدهد، خبر گم نمی‌شود و دور بعد دوباره تلاش می‌شود (حداکثر ۳ بار)."""
    first_run = db.seen.count_documents({"src": src["key"]}) == 0
    created = 0
    for it in items[:40]:
        u = sources.uid(it["url"])
        if db.seen.find_one({"_id": u}):
            continue
        rec = {"_id": u, "src": src["key"], "title": it["title"], "t": time.time()}
        if first_run or (not src.get("topic") and not sources.is_relevant(it["title"])) or is_duplicate(it["title"]):
            db.seen.insert_one(rec)           # اجرای اول فقط خط پایه است؛ نامرتبط و تکراری هم کنار گذاشته می‌شود
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

async def _list_safe(src):
    try:
        return src, await sources.list_items(src), None
    except Exception as e:
        return src, None, e

def _source_ok(src, count):
    db.health.update_one({"_id": src["key"]}, {"$set": {"error": None, "ok_at": time.time(), "count": count, "fails": 0}}, upsert=True)

async def _source_failed(src, err):
    h = db.health.find_one_and_update({"_id": src["key"]}, {"$set": {"error": f"{type(err).__name__}: {str(err)[:150]}", "t": time.time()}, "$inc": {"fails": 1}},
                                      upsert=True, return_document=True)
    n = h.get("fails", 1)
    if n == 5 or (n > 5 and n % 480 == 0):     # بعد از ۵ شکست پیاپی (~۱۵ دقیقه) و بعد روزی یک‌بار
        await bale.send_message(config.ADMIN_ID, f"⚠️ «{src['name']}» چند بار پیاپی باز نشد ({type(err).__name__}). "
                                "اگر از Render بسته است، آن را به رله بدهید (RELAY_SOURCES) یا در DISABLED_SOURCES بگذارید.")

async def poll_sources(force=False):
    if PAUSED and not force:
        return 0
    active = [s for s in config.SOURCES if not s.get("relay") and not s.get("disabled")]
    results = await asyncio.gather(*[_list_safe(s) for s in active])      # دریافت هم‌زمان؛ یک منبع کند بقیه را معطل نمی‌کند
    created = 0
    for src, items, err in results:
        if err is not None:
            await _source_failed(src, err); continue
        _source_ok(src, len(items))
        if created < MAX_DRAFTS_PER_CYCLE:
            created += await process_items(src, items, limit=MAX_DRAFTS_PER_CYCLE - created)
    return created

async def ingest_relay(key, items):
    src = next((s for s in config.SOURCES if s["key"] == key), None)
    if not src:
        return -1
    db.health.update_one({"_id": key}, {"$set": {"error": None, "ok_at": time.time(), "count": len(items), "via": "relay", "fails": 0}}, upsert=True)
    return await process_items(src, items, bodies={})

# ---------- تست دسترسی ----------
async def _probe(src):
    if src.get("disabled"):
        return [f"⛔ {src['name']}: غیرفعال"]
    if src.get("relay"):
        h = db.health.find_one({"_id": src["key"]}) or {}
        return [f"✅ {src['name']}: دریافت از رله | {h.get('count', 0)} خبر" if h.get("ok_at")
                else f"⏳ {src['name']}: از مسیر رله؛ هنوز نتیجه‌ای ثبت نشده"]
    try:
        t0 = time.time()
        items = await sources.list_items(src)
        out = [f"✅ {src['name']}: {len(items)} خبر | {round(time.time() - t0, 1)}s"]
        return out + [f"   • {it['title'][:70]}" for it in items[:2]]
    except Exception as e:
        return [f"❌ {src['name']}: باز نشد ({type(e).__name__})"]

async def diagnose():
    lines = ["🔎 نتیجه‌ی تست دسترسی (از سرور Render):"]
    for chunk in await asyncio.gather(*[_probe(s) for s in config.SOURCES]):
        lines += chunk
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
    lines.append("🖼 پوستر: " + ("روشن" if config.SEND_IMAGES else "خاموش"))
    return "\n".join(lines)

# ---------- دستورها و متن‌ها ----------
async def _handle(m):
    global PAUSED
    text = m["text"]
    if text.startswith("/start") or text.startswith("/menu"):
        await bale.send_message(config.ADMIN_ID, "سلام 👋 ربات خبری بروکر املاک آماده است.\nبرای همه‌ی کارها از کلیدهای ثابت پایین صفحه استفاده کنید؛ لازم نیست چیزی تایپ کنید.\nهر متن خبر را هم می‌توانید فوروارد کنید تا پیش‌نویس شود.", reply_keyboard=MENU)
        await bale.send_message(config.ADMIN_ID, "منوی سریع:", keyboard=INLINE_MENU)
    elif text.startswith("/test"):
        await bale.send_message(config.ADMIN_ID, await diagnose())
    elif text.startswith("/now"):
        n = await poll_sources(force=True)
        await bale.send_message(config.ADMIN_ID, f"بررسی انجام شد. پیش‌نویس جدید: {n}")
    elif text.startswith("/demo"):
        src = next((s for s in config.SOURCES if not s["relay"] and not s.get("disabled")), None)
        items = await sources.list_items(src) if src else []
        it = next((i for i in items if sources.is_relevant(i["title"])), None) or (items[0] if items else None)
        if not it:
            await bale.send_message(config.ADMIN_ID, "هیچ خبری از منبع پیدا نشد."); return
        await bale.send_message(config.ADMIN_ID, f"⏳ در حال ساخت نمونه از: {it['title'][:80]}")
        try: body = await sources.article_text(it["url"])
        except Exception: body = ""
        await make_draft(it["title"], body, src["name"], src["official"], it["url"], manual=True)
    elif text.startswith("/latest"):
        parts = text.split()
        n = min(int(parts[1]), 5) if len(parts) > 1 and parts[1].isdigit() else 3
        made = tried = 0
        await bale.send_message(config.ADMIN_ID, f"⏳ در حال بررسی تازه‌ترین خبرها برای ساخت حداکثر {n} پیش‌نویس (چند دقیقه طول می‌کشد)…")
        for src in [s for s in config.SOURCES if not s["relay"] and not s.get("disabled")]:
            try:
                items = await sources.list_items(src)
            except Exception as e:
                print(f"latest source skipped: {src['key']}: {type(e).__name__}"); continue
            for it in items:
                if made >= n or tried >= 12: break
                if not src.get("topic") and not sources.is_relevant(it["title"]): continue
                if db.drafts.find_one({"url": it["url"]}): continue
                tried += 1
                try: body = await sources.article_text(it["url"])
                except Exception: body = ""
                try:
                    if await make_draft(it["title"], body, src["name"], src["official"], it["url"], min_score=config.MIN_SCORE):
                        made += 1
                except Exception as e:
                    print("latest draft error:", type(e).__name__, e)
        await bale.send_message(config.ADMIN_ID, f"✅ {made} پیش‌نویس ساخته شد" + ("" if made >= n else " (بقیه نامرتبط یا کم‌اهمیت بودند)") + ".")
    elif text.startswith("/pause"):
        PAUSED = True; await bale.send_message(config.ADMIN_ID, "⏸ پایش متوقف شد.")
    elif text.startswith("/resume"):
        PAUSED = False; await bale.send_message(config.ADMIN_ID, "▶️ پایش ادامه یافت.")
    elif text.startswith("/status"):
        now = time.time()
        hb = db.health.find_one({"_id": "scheduler"}) or {}
        lines = ["📊 وضعیت منابع:",
                 f"🕒 آخرین چرخه‌ی پایش: {int((now - hb['t']) / 60)} دقیقه پیش" + (f" | خطا: {hb['error']}" if hb.get("error") else "") if hb.get("t")
                 else "🕒 هنوز هیچ چرخه‌ی پایشی اجرا نشده"]
        for s in config.SOURCES:
            h = db.health.find_one({"_id": s["key"]}) or {}
            if s.get("disabled"):
                lines.append(f"⛔ {s['name']}: غیرفعال")
            elif s.get("relay") and not h.get("ok_at"):
                lines.append(f"⏳ {s['name']}: در انتظار دریافت از رله")
            else:
                lines.append(f"{'✅' if not h.get('error') and h.get('ok_at') else '❌'} {s['name']}: {h.get('count', '—')} لینک" + (f" | خطا: {h['error'][:60]}" if h.get("error") else ""))
        c = db.drafts.count_documents
        lines.append(f"پیش‌نویس منتظر: {c({'status': 'draft'})} | زمان‌بندی‌شده: {c({'status': 'scheduled'})}")
        lines.append(f"رد شده‌ی خودکار (۷ روز): {db.skipped.count_documents({'t': {'$gt': now - 7 * 86400}})}")
        lines.append(f"📤 منتشرشده: امروز {c({'status': 'published', 'published_at': {'$gt': now - 86400}})} | ۷ روز {c({'status': 'published', 'published_at': {'$gt': now - 7 * 86400}})}")
        await bale.send_message(config.ADMIN_ID, "\n".join(lines))
    elif text and not text.startswith("/"):
        aw = db.state.find_one({"_id": "awaiting_time"})
        if aw:                                              # ورود ساعت دلخواه برای زمان‌بندی
            did = int(aw["draft"]); st = _sch(did)
            if text.strip() == "لغو":
                db.state.delete_one({"_id": "awaiting_time"})
                await bale.send_message(config.ADMIN_ID, "انصراف داده شد."); return
            try:
                hh, mm = jalali.parse_time(text)
                if not st.get("jy"):
                    raise ValueError("ابتدا تاریخ را از دکمه‌ها انتخاب کن")
                label = await _finish_schedule(did, st["jy"], st["jm"], st["jd"], hh, mm)
            except (ValueError, LookupError) as e:
                await bale.send_message(config.ADMIN_ID, f"❌ {e}\nساعت را مثل ۱۸:۳۰ بفرست یا بنویس: لغو"); return
            db.state.delete_one({"_id": "awaiting_time"}); db.state.delete_one({"_id": f"sch:{did}"})
            if st.get("message_id"):
                await _set_kb(st, _scheduled_kb(did, label))
            await bale.send_message(config.ADMIN_ID, f"✅ خبر #{did} برای {label} زمان‌بندی شد.")
            return
        ed = db.state.find_one({"_id": "edit"})
        if ed:                                              # ویرایش متن پیش‌نویس
            db.state.delete_one({"_id": "edit"})
            if text.strip() == "لغو":
                await bale.send_message(config.ADMIN_ID, "انصراف داده شد."); return
            db.drafts.update_one({"_id": ed["draft"], "status": "draft"}, {"$set": {"custom_caption": text}})
            d = db.drafts.find_one({"_id": ed["draft"]})
            if d: await show_draft(d)
        elif len(text) >= 40:                               # خبر فورواردشده/دستی مدیر: بدون فیلتر موضوع
            await make_draft(text.split("\n")[0][:90], text, "ارسال دستی مدیر", False, manual=True)
        else:
            await bale.send_message(config.ADMIN_ID, "متن خبر را کامل‌تر بفرستید (حداقل چند جمله).")

async def handle_message(m):
    """فقط مدیر؛ کلیدهای ثابت به دستور تبدیل می‌شوند و هر کار در پس‌زمینه اجرا می‌شود تا دریافت پیام‌ها قفل نشود."""
    if (m.get("from") or {}).get("id") != config.ADMIN_ID:
        return
    text = (m.get("text") or m.get("caption") or "").strip()
    _spawn(_handle({**m, "text": MENU_CMD.get(text, text)}))

async def poll_updates():
    offset = None
    while True:
        try:
            r = await bale.get_updates(offset, timeout=30)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if u.get("callback_query"): _spawn(handle_callback(u["callback_query"]))
                elif u.get("message"): await handle_message(u["message"])
        except Exception as e:
            print("updates error:", e)
            await alert(f"❌ خطای ربات هنگام پردازش پیام: {type(e).__name__}: {str(e)[:200]}", key="upd")
            await asyncio.sleep(5)

# ---------- انتشار زمان‌بندی‌شده و چرخه‌ی پایش (دو حلقه‌ی جدا) ----------
async def publish_scheduled():
    """انتشار خبرهایی که زمان تعیین‌شده‌شان رسیده است."""
    now = time.time()
    for d in list(db.drafts.find({"status": "scheduled", "scheduled_at": {"$lte": now}}).limit(20)):
        if not db.drafts.find_one_and_update({"_id": d["_id"], "status": "scheduled"}, {"$set": {"status": "publishing"}}):
            continue
        try:
            r = await publish(d)
            ok, why = bool(r.get("ok")), (r.get("description") or "")
        except Exception as e:
            ok, why = False, f"{type(e).__name__}: {str(e)[:100]}"
        if ok:
            db.drafts.update_one({"_id": d["_id"]}, {"$set": {"status": "published", "published_at": time.time(), "scheduled_at": None}})
        else:
            db.drafts.update_one({"_id": d["_id"]}, {"$set": {"status": "scheduled", "scheduled_at": now + 300}})
            await alert(f"❌ انتشار زمان‌بندی‌شده #{d['_id']} ناموفق بود ({why}); ۵ دقیقه دیگر دوباره تلاش می‌شود.", key=f"sched-pub:{d['_id']}")

async def schedule_runner():
    await asyncio.sleep(20)
    while True:
        try:
            await publish_scheduled()
        except Exception as e:
            print("schedule runner error:", e)
            await alert(f"❌ خطا در انتشار زمان‌بندی‌شده: {type(e).__name__}: {str(e)[:150]}", key="runner")
        await asyncio.sleep(15)

async def scheduler():
    await asyncio.sleep(10)
    try:
        await announce()
    except Exception as e:
        print("announce error:", e)
    await asyncio.sleep(5)
    while True:
        try:
            n = await poll_sources()
            print(f"poll cycle ok, new drafts: {n}")
            db.health.update_one({"_id": "scheduler"}, {"$set": {"t": time.time(), "drafts": n, "error": None}}, upsert=True)
        except Exception as e:
            print("scheduler error:", e)
            db.health.update_one({"_id": "scheduler"}, {"$set": {"t": time.time(), "error": f"{type(e).__name__}: {str(e)[:150]}"}}, upsert=True)
            await alert(f"❌ خطا در چرخه‌ی پایش: {type(e).__name__}: {str(e)[:200]}", key="sched")
        await asyncio.sleep(config.POLL_SECONDS)
