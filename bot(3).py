"""منطق ربات: پایش منابع، پیش‌نویس، دکمه‌های تأیید/ویرایش/رد، انتشار در کانال."""
import asyncio, time
import config, bale, sources, analyze, card
from db import db

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
KB = lambda i: [[{"text": "✅ تأیید و انتشار", "callback_data": f"ok:{i}"}],
                [{"text": "✏️ ویرایش متن", "callback_data": f"ed:{i}"}, {"text": "🔄 بازنویسی", "callback_data": f"re:{i}"}],
                [{"text": "❌ رد", "callback_data": f"no:{i}"}]]

def build_caption(d):
    label = "🟢 خبر رسمی" if d["official"] else "🟡 گزارش رسانه‌ای (تأیید رسمی نشده)"
    parts = [f"{label}\n\n🏛 {d['headline']}", d["summary"], f"💡 برای مردم یعنی: {d['meaning']}",
             f"📌 منبع: {d['source']}" + (f"\n🔗 {d['url']}" if d.get("url") else ""), config.SIGNATURE]
    return "\n\n".join(p for p in parts if p)

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
    d = {"_id": i, "headline": a["headline"] or title[:80], "summary": a["summary"], "meaning": a["meaning"],
         "source": source_name, "official": official, "url": url, "status": "draft", "created": time.time(),
         "custom_caption": None, "importance": a.get("importance", 3)}
    db.drafts.insert_one(d)
    await show_draft(d, a.get("suspect_numbers"))
    return True

async def show_draft(d, suspect=None):
    cap = d.get("custom_caption") or build_caption(d)
    warn = ""
    if suspect:
        warn = f"\n\n⚠️ این عددها در متن مبدأ پیدا نشد؛ قبل از انتشار حتماً بررسی کنید: {', '.join(suspect)}"
    head = f"📝 پیش‌نویس #{d['_id']} | ⭐ اهمیت {d.get('importance', 3)}/5"
    try:
        r = await bale.send_photo(config.ADMIN_ID, _card(d), head)
        if not r.get("ok"):
            raise RuntimeError(r.get("description", "sendPhoto failed"))
    except Exception as e:                       # تصویر شکست بخورد هم پیش‌نویس گم نشود
        await bale.send_message(config.ADMIN_ID, f"{head}\n(⚠️ تصویر ساخته یا ارسال نشد: {type(e).__name__}: {str(e)[:150]})")
    await bale.send_message(config.ADMIN_ID, cap + warn, KB(d["_id"]))

async def publish(d):
    cap = d.get("custom_caption") or build_caption(d)
    r = await bale.send_photo(config.CHANNEL_ID, _card(d), cap if len(cap) <= 1000 else d["headline"])
    if r.get("ok") and len(cap) > 1000:
        await bale.send_message(config.CHANNEL_ID, cap)
    return r

# ---------- پایش منابع ----------
async def process_items(src, items, bodies=None, limit=5):
    """items جدید را فیلتر و پیش‌نویس می‌کند. bodies: متن آماده (از رله)؛ وگرنه از سایت گرفته می‌شود."""
    first_run = db.seen.count_documents({"src": src["key"]}) == 0
    created = 0
    for it in items[:40]:
        u = sources.uid(it["url"])
        if db.seen.find_one({"_id": u}):
            continue
        db.seen.insert_one({"_id": u, "src": src["key"], "title": it["title"], "t": time.time()})
        if first_run or (not src.get("topic") and not sources.is_relevant(it["title"])):
            continue                         # اجرای اول فقط خط پایه است؛ خبرهای قدیمی ارسال نمی‌شود
        body = (bodies or {}).get(it["url"]) or it.get("body") or ""
        if not body and bodies is None:
            try: body = await sources.article_text(it["url"])
            except Exception: body = ""
        try:
            if await make_draft(it["title"], body, src["name"], src["official"], it["url"], min_score=config.MIN_SCORE):
                created += 1
        except Exception as e:
            await alert(f"❌ ساخت پیش‌نویس ناموفق بود\nخبر: {it['title'][:80]}\nخطا: {type(e).__name__}: {str(e)[:200]}", key="draft:" + type(e).__name__)
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
    action, _, sid = (cb.get("data") or "").partition(":")
    d = db.drafts.find_one({"_id": int(sid)}) if sid.isdigit() else None
    if not d or d["status"] != "draft":
        await bale.answer_callback(cb["id"], "این پیش‌نویس دیگر فعال نیست"); return
    if action == "ok":
        r = await publish(d)
        db.drafts.update_one({"_id": d["_id"]}, {"$set": {"status": "published" if r.get("ok") else "draft"}})
        await bale.answer_callback(cb["id"], "منتشر شد ✅" if r.get("ok") else "انتشار ناموفق")
        if not r.get("ok"):
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
        db.drafts.update_one({"_id": d["_id"]}, {"$set": {"summary": a["summary"], "meaning": a["meaning"], "custom_caption": None}})
        await show_draft(db.drafts.find_one({"_id": d["_id"]}))

async def handle_message(m):
    global PAUSED
    if (m.get("from") or {}).get("id") != config.ADMIN_ID:
        return
    text = (m.get("text") or m.get("caption") or "").strip()
    if text.startswith("/start"):
        await bale.send_message(config.ADMIN_ID, "سلام 👋 ربات خبری بروکر املاک آماده است.\n/demo یک پیش‌نویس نمونه\n/latest سه پیش‌نویس از تازه‌ترین خبرها\n/test تست دسترسی\n/now بررسی فوری منابع\n/status وضعیت\n/pause و /resume توقف و ادامه\n\nهر متن خبری را برایم بفرستید یا فوروارد کنید تا پیش‌نویس بسازم.")
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
        await bale.send_message(config.ADMIN_ID, "\n".join(lines))
    elif text and not text.startswith("/"):
        st = db.state.find_one_and_delete({"_id": "edit"})
        if st:
            db.drafts.update_one({"_id": st["draft"]}, {"$set": {"custom_caption": text}})
            await show_draft(db.drafts.find_one({"_id": st["draft"]}))
        elif len(text) >= 40:
            await make_draft(text.split("\n")[0][:90], text, "ارسال دستی مدیر", False)
        else:
            await bale.send_message(config.ADMIN_ID, "متن خبر را کامل‌تر بفرستید (حداقل چند جمله).")

async def poll_updates():
    offset = None
    while True:
        try:
            r = await bale.get_updates(offset, timeout=30)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if u.get("callback_query"): await handle_callback(u["callback_query"])
                elif u.get("message"): await handle_message(u["message"])
        except Exception as e:
            print("updates error:", e)
            await alert(f"❌ خطای ربات هنگام پردازش پیام: {type(e).__name__}: {str(e)[:200]}", key="upd")
            await asyncio.sleep(5)

async def scheduler():
    await asyncio.sleep(15)
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
