"""تست‌های ماژول‌های خالص (بدون دیتابیس و شبکه)."""
import os, sys, types, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object))
import config, sources, analyze, compose, jalali

OFF_TOPIC = ["آمادگی تیم ملی در زمینه تاکتیک و حریف جدید", "زمین‌لرزه ۴.۵ ریشتری آذربایجان شرقی را لرزاند",
             "مشاور رئیس‌جمهور از برنامه‌های جدید دولت خبر داد", "ساخت پهپاد جدید توسط نیروهای مسلح رونمایی شد",
             "سندرم خستگی مزمن در کارکنان؛ علائم و درمان", "خانه‌ی سینما میزبان جشنواره فیلم کوتاه شد",
             "قرارداد جدید باشگاه با مهاجم خارجی امضا شد", "وام ازدواج جدید در بانک‌ها پرداخت می‌شود"]
ON_TOPIC = ["وام مسکن در کمتر از ۳ روز پرداخت می‌شود", "معاملات مسکن در منطقه ۲۲ تهران خارج از شبکه رسمی انجام می‌شود",
            "دستور قوه قضاییه درباره سند ملکی و ثبت املاک", "مالیات خانه‌های خالی از سال آینده",
            "اجاره‌بها در تهران ۳۰ درصد گران شد", "سامانه ثبت‌نام جدید مسکن‌های حمایتی دی‌ماه باز می‌شود",
            "نهضت ملی مسکن در سهند", "مستأجران بخوانند؛ سرنوشت قرارداد اجاره"]

class Sources(unittest.TestCase):
    def test_keyword_filter(self):
        self.assertFalse([t for t in OFF_TOPIC if sources.is_relevant(t)])
        self.assertTrue(all(sources.is_relevant(t) for t in ON_TOPIC))

    def test_links_skip_menus_and_external(self):
        html = '''<nav><a href="/x">اندیشمندان و اندیشکده ها</a></nav>
        <a href="/news/123456/a">اعلام ضوابط جدید ثبت قراردادهای اجاره در سامانه کدرهگیری</a>
        <a href="https://other.com/news/9">لینک بیرونی که نباید بیاید و طولانی است</a>
        <a href="/news/123456/a">اعلام ضوابط جدید ثبت قراردادهای اجاره در سامانه کدرهگیری</a>'''
        items, _ = sources.extract_links(html, "https://www.ssaa.ir")
        self.assertEqual(len(items), 1)

    def test_article_text_skips_footer(self):
        t = sources.extract_text("<p>متن اصلی خبر درباره وام مسکن و شرایط آن</p><footer><p>تمامی حقوق این سایت محفوظ است و نباید بیاید</p></footer>")
        self.assertIn("وام مسکن", t); self.assertNotIn("محفوظ", t)

    def test_feed(self):
        x = "<rss><channel><item><title>خبر آزمایشی مسکن</title><link>https://a.ir/1</link></item></channel></rss>"
        self.assertEqual(sources.parse_feed(x)[0]["url"], "https://a.ir/1")

    def test_eitaa_posts_get_distinct_ids(self):
        html = '''<div class="message-text">پست اول درباره‌ی وام مسکن و شرایط جدید پرداخت آن برای مردم</div>
                  <div class="message-text">پست دوم درباره‌ی مالیات اجاره و تغییرات جدید قانون برای مستاجران</div>'''
        items = sources.extract_channel_items(html, {"key": "e", "url": "https://eitaa.com/x", "platform": "eitaa"})
        self.assertEqual(len(items), 2); self.assertEqual(len({sources.uid(i["url"]) for i in items}), 2)

    def test_unclosed_br_does_not_break_parser(self):
        html = '<div class="message-text">این پست طولانی درباره‌ی وام مسکن است <br> و ادامه‌ی خبر برای مستأجران</div>'
        items = sources.extract_channel_items(html, {"key": "e", "url": "https://eitaa.com/x", "platform": "eitaa"})
        self.assertEqual(len(items), 1); self.assertIn("ادامه", items[0]["body"])

    def test_telegram_url_not_overwritten_by_inner_link(self):
        html = '''<div class="tgme_widget_message_wrap" data-post="mrudNews/101"><div class="tgme_widget_message_text">متن خبر وام مسکن <br/> جزئیات در <a href="https://t.me/other_channel">کانال</a> آمده است برای مردم</div></div>
                  <div class="tgme_widget_message_wrap" data-post="mrudNews/102"><div class="tgme_widget_message_text">خبر دوم درباره‌ی مالیات خانه‌های خالی و جزئیات آن برای مالکان</div></div>'''
        items = sources.extract_channel_items(html, {"key": "t", "url": "https://t.me/s/mrudNews", "platform": "telegram"})
        self.assertEqual([i["url"] for i in items], ["https://t.me/mrudNews/101", "https://t.me/mrudNews/102"])

class Analyze(unittest.TestCase):
    def test_parse_full(self):
        r = analyze.parse_sections("مرتبط: بله\n**تیتر:** دستور قوه قضاییه درباره سند\nنسبت‌دهی: به دستور قوه قضاییه:\nخلاصه: قوه قضاییه دستور داد.\nادامه‌ی خلاصه.\nخلاصه که: مالکان باید سند را ثبت کنند.\nاهمیت: ۴")
        self.assertEqual((r["related"], r["speaker"], r["importance"]), (True, "به دستور قوه قضاییه", 4))
        self.assertIn("ادامه", r["summary"]); self.assertEqual(r["meaning"], "مالکان باید سند را ثبت کنند.")

    def test_not_related_and_empty_meaning(self):
        r = analyze.parse_sections("مرتبط: خیر\nتیتر: الف\nخلاصه: ب\nخلاصه که: ندارد\nاهمیت: 1")
        self.assertEqual((r["related"], r["meaning"]), (False, ""))
        self.assertEqual(analyze.parse_sections("مرتبط: بله\nتیتر: الف\nخلاصه: ب\nخلاصه که: جزئیات بیشتر هنوز اعلام نشده\nاهمیت: 2")["meaning"], "")

    def test_missing_related_is_unknown(self):
        self.assertIsNone(analyze.parse_sections("تیتر: الف\nخلاصه: ب")["related"])

    def test_fallback_has_no_fake_meaning_or_speaker(self):
        f = analyze.fallback("عنوان", "جمله اول خیلی طولانی برای تست است. جمله دوم هم کافی است برای آزمایش.")
        self.assertEqual((f["meaning"], f["speaker"], f["related"]), ("", "نامشخص", None))

    def test_number_guard(self):
        self.assertEqual(analyze.unsupported_numbers("ثبت‌نام تا ۳۰ روز دیگر و ۱٬۲۰۰ نفر", "تا 30 روز و 1200 نفر"), [])
        self.assertEqual(analyze.unsupported_numbers("ثبت‌نام تا ۳۰ روز", "تا ۴۵ روز و ۳۰ درصد"), ["45"])

class Compose(unittest.TestCase):
    D = {"_id": 7, "headline": "قوه قضاییه سند را الزامی کرد", "speaker": "به دستور قوه قضاییه", "summary": "ثبت سند الزامی شد.",
         "meaning": "مالکان باید سند را ثبت کنند.", "source": "خبرگزاری مهر (بخش مسکن)", "official": False,
         "url": "https://www.mehrnews.com/news/7018461/%D9%85%D8%B3", "importance": 4}

    def test_public_text_is_clean(self):
        t = compose.public_text(self.D)
        self.assertTrue(t.startswith("*قوه قضاییه سند را الزامی کرد*"))
        self.assertIn("به دستور قوه قضاییه:\nثبت سند الزامی شد.", t)
        self.assertIn("💡 *خلاصه که؛*\nمالکان باید سند را ثبت کنند.", t)
        for secret in ("منبع", "http", "مهر", "رسانه", "اهمیت", "مشخص نشده"):
            self.assertNotIn(secret, t)
        self.assertTrue(t.endswith(config.PUBLIC_SIGNATURE)); self.assertIn("09123692401", t); self.assertIn("@BROKER_amlak", t)

    def test_unknown_speaker_and_empty_meaning_print_nothing_extra(self):
        t = compose.public_text({**self.D, "speaker": "نامشخص", "meaning": ""})
        self.assertNotIn("نامشخص", t); self.assertNotIn("خلاصه که", t); self.assertNotIn("مشخص نشده", t)

    def test_stars_from_model_cannot_break_bold(self):
        t = compose.public_text({**self.D, "headline": "*تیتر* با `ستاره`", "summary": "متن **بولد** و `کد`"})
        body = t.split("\n\n")
        self.assertEqual(body[0].count("*"), 2); self.assertNotIn("`", t)
        self.assertEqual(t.count("*"), 2 + 2)       # تیتر + «خلاصه که؛»

    def test_custom_caption_keeps_headline_and_signature(self):
        t = compose.public_text({**self.D, "custom_caption": "متن ویرایش‌شده توسط مدیر"})
        self.assertIn("متن ویرایش‌شده توسط مدیر", t); self.assertNotIn("ثبت سند الزامی شد", t)
        self.assertTrue(t.startswith("*")); self.assertTrue(t.endswith(config.PUBLIC_SIGNATURE))

    def test_admin_text_has_private_info(self):
        t = compose.admin_text(self.D)
        for need in ("🟡", "منبع: خبرگزاری مهر", "mehrnews.com/news/7018461", "اهمیت 4/5", compose.public_text(self.D)):
            self.assertIn(need, t)
        self.assertNotIn("%D9", t)
        self.assertIn("🟢", compose.admin_text({**self.D, "official": True}))

    def test_ai_failed_note_for_admin_only(self):
        d = {**self.D, "ai_failed": True, "ai_error": "HTTP 429", "meaning": ""}
        self.assertIn("تحلیل هوش مصنوعی انجام نشد", compose.admin_text(d))
        self.assertNotIn("تحلیل هوش مصنوعی", compose.public_text(d))

    def test_helpers(self):
        self.assertEqual(compose.short_url("https://www.mehrnews.com/news/7012591/%D9%85"), "https://www.mehrnews.com/news/7012591")
        self.assertEqual(compose.clean_text("a\\nb\\r\\nc"), "a\nb\nc")
        self.assertTrue(compose.similar("وام مسکن در کمتر از ۳ روز پرداخت می‌شود", "وام مسکن در کمتر از 3 روز پرداخت می شود"))
        self.assertFalse(compose.similar("وام مسکن در کمتر از ۳ روز پرداخت می‌شود", "ثبت‌نام مسکن حمایتی دی‌ماه آغاز می‌شود"))

class Jalali(unittest.TestCase):
    def test_known_dates(self):
        for j, g in [((1405, 1, 1), (2026, 3, 21)), ((1404, 12, 29), (2026, 3, 20)), ((1405, 9, 1), (2026, 11, 22)), ((1403, 12, 30), (2025, 3, 20))]:
            self.assertEqual(jalali.jalali_to_gregorian(*j), g); self.assertEqual(jalali.gregorian_to_jalali(*g), j)

    def test_parse_time(self):
        for s, want in [("18:30", (18, 30)), ("۱۸:۳۰", (18, 30)), ("۱۸٫۳۰", (18, 30)), ("9:05", (9, 5)), (" 07 : 00 ", (7, 0)), ("18.30", (18, 30))]:
            self.assertEqual(jalali.parse_time(s), want, s)
        for bad in ("25:00", "12:75", "abc", "", "1830"):
            with self.assertRaises(ValueError): jalali.parse_time(bad)

    def test_calendar_and_timestamp(self):
        rows = jalali.calendar_rows(1405, 9, 3)
        self.assertEqual(sum(1 for r in rows[2:] for b in r if b["callback_data"].startswith("calday:3:1405:9:")), 30)
        self.assertEqual(jalali.month_days(1405, 12), 29); self.assertEqual(jalali.month_days(1403, 12), 30); self.assertEqual(jalali.month_days(1405, 1), 31)
        from datetime import datetime
        self.assertEqual(jalali.to_timestamp(1405, 1, 1, 9, 30), datetime(2026, 3, 21, 9, 30, tzinfo=jalali.TEHRAN).timestamp())

class Config(unittest.TestCase):
    def test_flags(self):
        by = {s["key"]: s for s in config.SOURCES}
        self.assertTrue(all(by[k]["relay"] for k in ("mrud", "ssaa", "tax", "cbi", "amar", "irib")))
        self.assertFalse(by["mehr"]["relay"]); self.assertFalse(by["mrud_tg"]["relay"])
        self.assertTrue(by["mrud_eitaa"]["disabled"] and by["mrud_bale"]["disabled"])
        self.assertFalse(config.SEND_IMAGES)

if __name__ == "__main__":
    unittest.main()
