"""تست مسیرهای کامل ربات با دیتابیس و بله‌ی مجازی: پیش‌نویس، فیلتر موضوع، انتشار، زمان‌بندی، ویرایش، رله، خطاها."""
import asyncio, os, sys, time, types, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object))
import fakes
FDB, FBALE = fakes.FakeDB(), fakes.FakeBale()
sys.modules["db"] = types.SimpleNamespace(db=FDB)
sys.modules["bale"] = FBALE
import config, sources, analyze, jalali
import bot

config.ADMIN_ID, config.CHANNEL_ID = 111, "@chan"
GOOD = {"related": True, "headline": "قوه قضاییه سند را الزامی کرد", "speaker": "به دستور قوه قضاییه", "summary": "ثبت سند الزامی شد.",
        "meaning": "مالکان باید سند را ثبت کنند.", "importance": 4, "ai_failed": False, "ai_error": "", "suspect_numbers": []}

def run(coro): return asyncio.run(coro)

def cb(data, mid=55, user=111):
    return {"id": "cb1", "from": {"id": user}, "message": {"chat": {"id": 111}, "message_id": mid}, "data": data}

class Base(unittest.TestCase):
    def setUp(self):
        FDB._c.clear(); FBALE.reset(); bot._ALERTED.clear(); bot.PAUSED = False
        self._orig = (analyze.analyze, sources.article_text, sources.list_items)
        self.result = dict(GOOD)
        async def fake_analyze(title, body): return dict(self.result)
        async def fake_text(url): return "متن کامل خبر درباره سند ملکی و ثبت آن. " * 5
        analyze.analyze, sources.article_text = fake_analyze, fake_text
    def tearDown(self):
        analyze.analyze, sources.article_text, sources.list_items = self._orig
    def draft(self, **kw):
        ok = run(bot.make_draft("عنوان خبر درباره سند ملکی", "متن", "خبرگزاری مهر (بخش مسکن)", False, "https://www.mehrnews.com/news/7018461/x", **kw))
        FBALE.reset(); return ok
    def press(self, data, **kw): run(bot.handle_callback(cb(data, **kw)))
    def channel_msgs(self): return [c for c in FBALE.calls if c[0] == "send_message" and c[1] == "@chan"]
    def answers(self): return [c[2] for c in FBALE.calls if c[0] == "answer"]

class Draft(Base):
    def test_related_news_creates_draft_with_private_info_only_for_admin(self):
        FBALE.reset()
        self.assertTrue(run(bot.make_draft("عنوان", "متن", "خبرگزاری مهر (بخش مسکن)", False, "https://www.mehrnews.com/news/7018461/x")))
        msgs = FBALE.of("send_message", 111)
        self.assertEqual(len(msgs), 1)
        text, kb = msgs[0][2], msgs[0][3]
        for need in ("منبع: خبرگزاری مهر", "mehrnews.com/news/7018461", "🟡", "━━━"):
            self.assertIn(need, text)
        self.assertEqual(kb[0][0]["callback_data"], "now:1")
        self.assertFalse(FBALE.of("send_photo"))       # پوستر خاموش است
        self.assertFalse(self.channel_msgs())

    def test_unrelated_news_is_skipped_and_not_sent(self):
        self.result["related"] = False
        FBALE.reset()
        self.assertFalse(run(bot.make_draft("فوتبال", "متن", "منبع", False, "u")))
        self.assertEqual(FDB.drafts.count_documents({}), 0); self.assertEqual(FDB.skipped.count_documents({}), 1)
        self.assertFalse(FBALE.calls)

    def test_low_importance_is_skipped(self):
        self.result["importance"] = 2
        self.assertFalse(run(bot.make_draft("عنوان", "متن", "منبع", False, "u", min_score=3)))

    def test_ai_failure_means_reject_not_pass(self):
        self.result.update({"related": None, "ai_failed": True, "ai_error": "HTTP 429"})
        with self.assertRaises(RuntimeError): run(bot.make_draft("عنوان", "متن", "منبع", False, "u"))
        self.assertEqual(FDB.drafts.count_documents({}), 0)

    def test_manual_news_skips_gate_but_warns_on_ai_failure(self):
        self.result.update({"related": None, "ai_failed": True, "ai_error": "x", "meaning": ""})
        FBALE.reset()
        self.assertTrue(run(bot.make_draft("عنوان", "متن", "ارسال دستی مدیر", False, manual=True)))
        self.assertIn("تحلیل هوش مصنوعی انجام نشد", FBALE.of("send_message", 111)[0][2])

class Publish(Base):
    def test_publish_now_text_only_and_clean(self):
        self.draft(); self.press("now:1")
        msgs = self.channel_msgs(); self.assertEqual(len(msgs), 1)
        t = msgs[0][2]
        self.assertTrue(t.startswith("*قوه قضاییه سند را الزامی کرد*")); self.assertIn("*خلاصه که؛*", t)
        self.assertIn("به دستور قوه قضاییه:", t); self.assertIn("09003692401", t)
        for secret in ("منبع", "http", "رسانه", "اهمیت", "مشخص نشده"): self.assertNotIn(secret, t)
        self.assertFalse(FBALE.of("send_photo"))
        self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "published")
        self.assertIn("منتشر شد ✅", self.answers())

    def test_double_press_publishes_once(self):
        self.draft(); self.press("now:1"); self.press("now:1")
        self.assertEqual(len(self.channel_msgs()), 1)

    def test_failed_publish_returns_to_draft_and_tells_admin(self):
        self.draft(); FBALE.fail_next_publish = True; self.press("now:1")
        self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "draft")
        self.assertTrue(any("ناموفق" in c[2] for c in FBALE.of("send_message", 111)))
        self.press("now:1"); self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "published")

    def test_stale_draft_expires(self):
        self.draft(); FDB.drafts.update_one({"_id": 1}, {"$set": {"created": time.time() - 49 * 3600}})
        self.press("now:1"); self.assertFalse(self.channel_msgs()); self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "expired")

    def test_reject(self):
        self.draft(); self.press("no:1")
        self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "rejected"); self.press("now:1"); self.assertFalse(self.channel_msgs())

    def test_other_users_are_ignored(self):
        self.draft(); self.press("now:1", user=999)
        self.assertFalse(self.channel_msgs()); self.assertFalse(FBALE.calls)
        run(bot.handle_message({"from": {"id": 999}, "text": "/status"})); self.assertFalse(FBALE.calls)

class Edit(Base):
    def test_edit_flow_keeps_bold_headline_and_signature(self):
        self.draft(); self.press("ed:1")
        run(bot._handle({"from": {"id": 111}, "text": "متن جدید و ویرایش‌شده"}))
        self.assertEqual(FDB.drafts.find_one({"_id": 1})["custom_caption"], "متن جدید و ویرایش‌شده")
        self.assertIn("متن جدید و ویرایش‌شده", FBALE.of("send_message", 111)[-1][2])
        self.press("now:1"); t = self.channel_msgs()[0][2]
        self.assertTrue(t.startswith("*")); self.assertIn("متن جدید و ویرایش‌شده", t); self.assertTrue(t.endswith(config.PUBLIC_SIGNATURE))
        self.assertNotIn("ثبت سند الزامی شد", t)

    def test_edit_cancel(self):
        self.draft(); self.press("ed:1"); run(bot._handle({"from": {"id": 111}, "text": "لغو"}))
        self.assertIsNone(FDB.drafts.find_one({"_id": 1})["custom_caption"])

    def test_rewrite_uses_original_body(self):
        self.draft(); self.result.update({"summary": "خلاصه‌ی جدید", "importance": 5}); FBALE.reset()
        self.press("re:1"); d = FDB.drafts.find_one({"_id": 1})
        self.assertEqual((d["summary"], d["importance"]), ("خلاصه‌ی جدید", 5))

class Schedule(Base):
    def go_tomorrow(self): self.press("schedule:1"); self.press("sctomorrow:1")
    def test_quick_buttons_flow_and_publish_on_time(self):
        self.draft(); self.go_tomorrow(); self.press("caltime:1:21:00")
        d = FDB.drafts.find_one({"_id": 1})
        self.assertEqual(d["status"], "scheduled"); self.assertGreater(d["scheduled_at"], time.time())
        self.assertIn("زمان‌بندی شد ✅", self.answers())
        self.assertTrue(any("🕒" in b["text"] for c in FBALE.of("edit_kb") for row in (c[3] or []) for b in row))
        run(bot.publish_scheduled()); self.assertFalse(self.channel_msgs())            # هنوز وقتش نرسیده
        FDB.drafts.update_one({"_id": 1}, {"$set": {"scheduled_at": time.time() - 5}})
        run(bot.publish_scheduled()); self.assertEqual(len(self.channel_msgs()), 1)
        self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "published")
        run(bot.publish_scheduled()); self.assertEqual(len(self.channel_msgs()), 1)    # دوباره منتشر نمی‌شود

    def test_manual_time_valid_and_invalid(self):
        self.draft(); self.go_tomorrow(); self.press("scmanual:1")
        self.assertTrue(FDB.state.find_one({"_id": "awaiting_time"}))
        run(bot._handle({"from": {"id": 111}, "text": "25:99"}))
        self.assertTrue(any("❌" in c[2] for c in FBALE.of("send_message", 111)))
        self.assertTrue(FDB.state.find_one({"_id": "awaiting_time"}))                  # هنوز منتظر ساعت درست
        run(bot._handle({"from": {"id": 111}, "text": "۱۸:۳۰"}))
        d = FDB.drafts.find_one({"_id": 1}); self.assertEqual(d["status"], "scheduled")
        self.assertEqual(time.strftime("%H:%M", time.gmtime(d["scheduled_at"] + 3.5 * 3600)), "18:30")
        self.assertIsNone(FDB.state.find_one({"_id": "awaiting_time"}))

    def test_calendar_pick_and_past_time_rejected(self):
        self.draft(); self.press("schedule:1"); self.press("scalendar:1")
        rows = [c[3] for c in FBALE.of("edit_kb")][-1]
        days = [b["callback_data"] for r in rows for b in r if b["callback_data"].startswith("calday:1:")]
        self.assertGreaterEqual(len(days), 29)
        jy, jm, jd = jalali.today_jalali(); self.press(f"calday:1:{jy}:{jm}:{jd}")
        FBALE.reset(); self.press("caltime:1:00:00")                                 # امروز ساعت ۰۰:۰۰ گذشته است
        self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "draft")
        self.assertIn("زمان باید در آینده باشد", self.answers())

    def test_month_navigation_wraps_year(self):
        self.draft(); self.press("calnext:1:1405:12"); self.press("calprev:1:1405:1")
        shown = [c[3][0][1]["text"] for c in FBALE.of("edit_kb")]        # عنوان ماهِ نمایش‌داده‌شده در هر صفحه
        self.assertEqual(shown, ["فروردین 1406", "اسفند 1404"])

    def test_unschedule_and_cancel(self):
        self.draft(); self.go_tomorrow(); self.press("caltime:1:09:00")
        self.press("unsched:1"); self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "draft")
        self.press("schedule:1"); self.press("sccancel:1"); self.assertEqual(FDB.drafts.find_one({"_id": 1})["status"], "draft")

    def test_two_drafts_scheduling_do_not_clash(self):
        self.draft(); self.result["headline"] = "خبر دوم درباره اجاره"; run(bot.make_draft("عنوان دوم", "متن", "منبع", False, "u2")); FBALE.reset()
        self.press("schedule:1", mid=55); self.press("sctomorrow:1", mid=55)
        self.press("schedule:2", mid=66); self.press("sctomorrow:2", mid=66)
        self.press("caltime:1:09:00", mid=55); self.press("caltime:2:21:00", mid=66)
        a, b = FDB.drafts.find_one({"_id": 1}), FDB.drafts.find_one({"_id": 2})
        self.assertEqual((a["status"], b["status"]), ("scheduled", "scheduled")); self.assertLess(a["scheduled_at"], b["scheduled_at"])

    def test_failed_scheduled_publish_retries_later(self):
        self.draft(); self.go_tomorrow(); self.press("caltime:1:09:00")
        FDB.drafts.update_one({"_id": 1}, {"$set": {"scheduled_at": time.time() - 5}}); FBALE.fail_next_publish = True
        run(bot.publish_scheduled()); d = FDB.drafts.find_one({"_id": 1})
        self.assertEqual(d["status"], "scheduled"); self.assertGreater(d["scheduled_at"], time.time())

class Monitoring(Base):
    def items(self, *titles): return [{"title": t, "url": f"https://x.ir/news/{abs(hash(t)) % 10**7}"} for t in titles]
    SRC = {"key": "mehr", "name": "خبرگزاری مهر (بخش مسکن)", "official": False, "topic": True}

    def test_first_run_is_baseline_then_new_items_become_drafts(self):
        its = self.items("وام مسکن جدید اعلام شد برای متقاضیان")
        self.assertEqual(run(bot.process_items(self.SRC, its)), 0); self.assertEqual(FDB.seen.count_documents({}), 1)
        its2 = its + self.items("اجاره‌بها در تهران گران شد و مستاجران نگران‌اند")
        self.assertEqual(run(bot.process_items(self.SRC, its2)), 1); self.assertEqual(FDB.drafts.count_documents({}), 1)
        self.assertEqual(run(bot.process_items(self.SRC, its2)), 0)               # دوباره تکرار نمی‌شود

    def test_keyword_gate_for_non_topic_sources(self):
        src = {"key": "irna", "name": "ایرنا", "official": False}
        run(bot.process_items(src, self.items("خبر قدیمی")))
        n = run(bot.process_items(src, self.items("خبر قدیمی", "پیروزی تیم ملی در زمینه ورزش", "وام مسکن جدید برای مستاجران اعلام شد")))
        self.assertEqual(n, 1)

    def test_duplicate_titles_suppressed(self):
        run(bot.process_items(self.SRC, self.items("پایه")))
        run(bot.process_items(self.SRC, self.items("پایه", "وام مسکن در کمتر از سه روز پرداخت می‌شود")))
        n = run(bot.process_items(self.SRC, self.items("پایه", "وام مسکن در کمتر از سه روز پرداخت می‌شود", "وام مسکن در کمتر از سه روز پرداخت می شود")))
        self.assertEqual(n, 0)

    def test_ai_failure_retries_then_gives_up_after_three(self):
        run(bot.process_items(self.SRC, self.items("پایه")))
        self.result.update({"related": None, "ai_failed": True, "ai_error": "HTTP 500"})
        its = self.items("پایه", "وام مسکن جدید اعلام شد برای متقاضیان ملکی")
        for i in range(2):
            run(bot.process_items(self.SRC, its)); self.assertEqual(FDB.seen.count_documents({}), 1, f"try {i}")   # هنوز دوباره تلاش می‌شود
        run(bot.process_items(self.SRC, its)); self.assertEqual(FDB.seen.count_documents({}), 2)                   # سومی: تسلیم
        self.assertEqual(FDB.drafts.count_documents({}), 0)

    def test_relay_ingest_accepts_irib_and_rejects_unknown(self):
        self.assertEqual(run(bot.ingest_relay("zzz", [])), -1)
        run(bot.ingest_relay("irib", [{"title": "پایه", "url": "https://a.ir/n/1", "body": "متن"}]))
        n = run(bot.ingest_relay("irib", [{"title": "پایه", "url": "https://a.ir/n/1", "body": "متن"}, {"title": "وام مسکن جدید برای مستاجران اعلام شد", "url": "https://a.ir/n/2", "body": "متن کامل خبر"}]))
        self.assertEqual(n, 1); self.assertTrue(FDB.health.find_one({"_id": "irib"})["ok_at"])

    def test_failing_source_alerts_once_after_five_failures(self):
        async def boom(src): raise ConnectionError("blocked")
        sources.list_items = boom
        direct = [s for s in config.SOURCES if not s["relay"] and not s["disabled"]]
        for _ in range(4): run(bot.poll_sources())
        self.assertFalse([c for c in FBALE.of("send_message", 111) if "چند بار پیاپی" in c[2]])
        run(bot.poll_sources()); alerts = [c for c in FBALE.of("send_message", 111) if "چند بار پیاپی" in c[2]]
        self.assertEqual(len(alerts), len(direct))
        run(bot.poll_sources()); self.assertEqual(len([c for c in FBALE.of("send_message", 111) if "چند بار پیاپی" in c[2]]), len(direct))
        sources.list_items = self._orig[2]

    def test_poll_skips_relay_and_disabled_sources(self):
        seen = []
        async def rec(src): seen.append(src["key"]); return []
        sources.list_items = rec; run(bot.poll_sources())
        self.assertEqual(set(seen), {"mrud_tg", "mehr", "irna", "isna", "tasnim"})

    def test_pause(self):
        sources.list_items = lambda s: (_ for _ in ()).throw(AssertionError("should not poll"))
        bot.PAUSED = True; self.assertEqual(run(bot.poll_sources()), 0)

class Commands(Base):
    def test_menu_buttons_map_to_commands(self):
        labels = [x for row in bot.MENU for x in row]
        self.assertTrue(all(l in bot.MENU_CMD for l in labels))
        self.assertTrue(all("/" + c["callback_data"][2:] in bot.MENU_CMD.values() for row in bot.INLINE_MENU for c in row))

    def test_start_installs_persistent_keyboard(self):
        run(bot._handle({"from": {"id": 111}, "text": "/start"}))
        self.assertTrue(FBALE.of("send_message", 111)[0][4])

    def test_status_text_has_no_errors_and_counts(self):
        self.draft(); run(bot._handle({"from": {"id": 111}, "text": "/status"}))
        t = FBALE.of("send_message", 111)[-1][2]
        self.assertIn("پیش‌نویس منتظر: 1", t); self.assertIn("⛔", t); self.assertIn("⏳", t)

    def test_forwarded_news_becomes_draft_and_short_text_is_refused(self):
        run(bot._handle({"from": {"id": 111}, "text": "کوتاه"})); self.assertIn("کامل‌تر", FBALE.of("send_message", 111)[-1][2])
        run(bot._handle({"from": {"id": 111}, "text": "قوه قضاییه دستور داد که همه‌ی معاملات ملکی باید در سامانه ثبت شوند و سند صادر شود."}))
        self.assertEqual(FDB.drafts.count_documents({}), 1)

    def test_handle_message_runs_in_background_and_maps_buttons(self):
        async def go():
            await bot.handle_message({"from": {"id": 111}, "text": "📊 وضعیت"})
            await asyncio.gather(*list(bot._TASKS))
        run(go()); self.assertIn("📊 وضعیت منابع", FBALE.of("send_message", 111)[-1][2])

    def test_announce_only_every_30_minutes(self):
        run(bot.announce()); run(bot.announce()); self.assertEqual(len(FBALE.of("send_message", 111)), 1)

if __name__ == "__main__":
    unittest.main()
