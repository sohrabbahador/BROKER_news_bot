import sys, os, types, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object))      # بدون شبکه
sys.modules["db"] = types.SimpleNamespace(db=None)
import sources, analyze, card, config, bot

HTML = """<html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml"></head><body>
<nav><a href="/x">خانه</a></nav>
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

    def test_caption_labels(self):
        d = {"headline": "ت", "summary": "خ", "meaning": "م", "source": "س", "official": False, "url": "https://x.ir"}
        c = bot.build_caption(d)
        self.assertIn("تأیید رسمی نشده", c); self.assertIn("https://x.ir", c)
        d["official"] = True; self.assertIn("🟢 خبر رسمی", bot.build_caption(d))

    def test_card_png(self):
        png = card.make_card("تیتر آزمایشی", "متن خلاصه " * 12, "سازمان", True)
        self.assertTrue(png.startswith(b"\x89PNG"))

if __name__ == "__main__":
    unittest.main()
