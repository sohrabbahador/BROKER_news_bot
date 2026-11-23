import sys, os, types, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object))      # بدون شبکه
sys.modules["db"] = types.SimpleNamespace(db=None)
import sources, analyze, card, config, bot

HTML = """<html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml"></head><body>
<nav><a href="/x">خانه</a><a href="/think">اندیشمندان و اندیشکده ها</a><a href="/it">فناوری اطلاعات و ارتباطات</a></nav>
<a href="/news/1">اعلام ضوابط جدید ثبت قراردادهای اجاره در سامانه کدرهگیری</a>
<a href="https://other.com/n">لینک بیرونی که نباید بیاید و طولانی است</a>
<a href="/news/2">تمدید مهلت ثبت‌نام طرح ملی مسکن تا پایان ماه جاری</a>
<a href="/news/1">اعلام ضوابط جدید ثبت قراردادهای اجاره در سامانه کدرهگیری</a>
<p>سازمان اعلام کرد ثبت قرارداد تا ۳۰ روز دیگر ممکن است و ۱۲۰۰ نفر ثبت‌نام کرده‌اند.</p>
<footer><p>تمامی حقوق این سایت برای سازمان محفوظ است و نباید بیاید.</p></footer></body></html>"""

class T(unittest.TestCase):
    def test_links(self):
        items, feeds = sources.extract_links(HTML, "https://www.ssaa.ir")
        self.assertEqual(len(items), 2)                       # بدون تکراری و بدون لینک بیرونی/منو
        self.assertEqual(feeds, ["https://www.ssaa.ir/rss.xml"])

    def test_menu_links_skipped(self):
        items, _ = sources.extract_links(HTML, "https://www.ssaa.ir")
        self.assertFalse(any("اندیشمندان" in i["title"] or "فناوری" in i["title"] for i in items))

    def test_config_relay_flags(self):
        self.assertTrue(all(s["relay"] for s in config.SOURCES if s["key"] in ("mrud", "ssaa", "tax")))
        self.assertFalse([s for s in config.SOURCES if s["key"] == "mehr"][0]["relay"])

    def test_text_skips_footer(self):
        t = sources.extract_text(HTML)
        self.assertIn("۳۰ روز", t); self.assertNotIn("محفوظ", t)

    def test_feed(self):
        x = "<rss><channel><item><title>خبر آزمایشی مسکن</title><link>https://a.ir/1</link></item></channel></rss>"
        self.assertEqual(sources.parse_feed(x)[0]["url"], "https://a.ir/1")

    def test_relevance(self):
        self.assertTrue(sources.is_relevant("افزایش مالیات اجاره"))
        self.assertFalse(sources.is_relevant("جلسه‌ی ورزشی کارکنان وزارتخانه"))

    def test_number_guard(self):
        src = "ثبت‌نام تا ۳۰ روز دیگر و ۱٬۲۰۰ نفر"
        self.assertEqual(analyze.unsupported_numbers(src, "تا 30 روز و 1200 نفر"), [])
        self.assertEqual(analyze.unsupported_numbers(src, "تا ۴۵ روز و ۳۰ درصد"), ["45"])

    def test_sections(self):
        s = analyze.parse_sections("تیتر: الف ب\nخلاصه: جمله اول. جمله دوم.\nبرای مردم یعنی: مستأجران بدانند.")
        self.assertEqual((s["headline"], s["meaning"]), ("الف ب", "مستأجران بدانند."))
        s2 = analyze.parse_sections("تیتر: خبر\nگوینده: وزیر راه و شهرسازی\nخلاصه: متن\nبرای مردم یعنی: نتیجه")
        self.assertEqual(s2["speaker"], "وزیر راه و شهرسازی")

    def test_importance(self):
        s = analyze.parse_sections("تیتر: الف\nخلاصه: ب.\nبرای مردم یعنی: ج.\nاهمیت: ۵")
        self.assertEqual((s["importance"], s["meaning"]), (5, "ج."))
        self.assertEqual(analyze.parse_sections("تیتر: الف\nخلاصه: ب.")["importance"], 3)   # پیش‌فرض

    def test_collection_prefix(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("db_real", os.path.join(os.path.dirname(__file__), "..", "db.py"))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        ns = m.NS({"news_seen": "A", "news_drafts": "B"}, "news_")
        self.assertEqual((ns.seen, ns.drafts), ("A", "B"))

    def test_short_url(self):
        u = "https://www.mehrnews.com/news/7012591/%D9%85%D8%B3%D8%AA%D8%A7%D8%AC%D8%B1%D8%A7%D9%86-%D8%A8"
        self.assertEqual(bot.short_url(u), "https://www.mehrnews.com/news/7012591")
        self.assertEqual(bot.short_url("https://x.ir/a/b"), "https://x.ir/a/b")

    def test_menu_complete(self):
        labels = [x for row in bot.MENU for x in row]
        self.assertTrue(all(l in bot.MENU_CMD for l in labels))
        cbs = [b["callback_data"][2:] for row in bot.INLINE_MENU for b in row]
        self.assertTrue(all("/" + c in bot.MENU_CMD.values() for c in cbs))

    def test_similar_titles(self):
        self.assertTrue(bot.similar("وام مسکن در کمتر از ۳ روز پرداخت می‌شود", "وام مسکن در کمتر از 3 روز پرداخت می شود"))
        self.assertFalse(bot.similar("وام مسکن در کمتر از ۳ روز پرداخت می‌شود", "ثبت‌نام مسکن حمایتی دی‌ماه آغاز می‌شود"))

    def test_caption_labels(self):
        d = {"headline": "ت", "summary": "خ", "meaning": "م", "source": "س", "official": False, "url": "https://x.ir"}
        c = bot.build_caption(d)
        self.assertIn("<b>ت</b>", c)
        self.assertIn("خلاصه که؛", c)
        self.assertIn("@BROKER_amlak", c)
        self.assertNotIn("https://x.ir", c)
        self.assertNotIn("تأیید رسمی نشده", c)
        admin = bot.build_admin_caption(d)
        self.assertIn("تأیید رسمی نشده", admin); self.assertIn("https://x.ir", admin)
        d["official"] = True; self.assertIn("🟢 خبر رسمی", bot.build_admin_caption(d))

    def test_card_png(self):
        png = card.make_card("تیتر آزمایشی", "متن خلاصه " * 12, "سازمان", True)
        self.assertTrue(png.startswith(b"\x89PNG"))

if __name__ == "__main__":
    unittest.main()
