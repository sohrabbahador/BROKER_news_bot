import os
def _e(k, d=""): return os.getenv(k, d).strip()

BALE_TOKEN = _e("BALE_TOKEN")
ADMIN_ID = int(_e("ADMIN_ID", "0") or 0)
CHANNEL_ID = _e("CHANNEL_ID")
MONGODB_URI = _e("MONGODB_URI")
NEWS_DB = _e("NEWS_DB", "broker_database")     # همان دیتابیس ربات‌ها (کاربر MongoDB شما فقط به آن اجازه دارد)
NEWS_PREFIX = _e("NEWS_PREFIX", "news_")
GEMINI_API_KEY = _e("GEMINI_API_KEY")
GEMINI_MODEL = _e("GEMINI_MODEL", "gemini-3.8-flash")
POLL_SECONDS = max(60, int(_e("POLL_SECONDS", "180")))
MIN_SCORE = int(_e("MIN_SCORE", "3"))      # خبرهای کم‌اهمیت‌تر از این به مدیر نمی‌رسند (۱ تا ۵)
RELAY_SECRET = _e("RELAY_SECRET")
PUBLIC_SIGNATURE = _e("PUBLIC_SIGNATURE", "⚖️ سهراب بهادر | بروکر املاک\n🆔 @BROKER_amlak\n📱 09123692401\n📱 09003692401").replace("\\n", "\n")
SEND_IMAGES = _e("SEND_IMAGES", "off").lower() in ("on", "1", "true", "yes")   # فعلاً خاموش؛ کد پوستر نگه داشته شده

# ردیف اول (رسمی) = 🟢 ؛ سیگنال رسانه‌ای = 🟡
SOURCES = [
    {"key": "mrud", "name": "وزارت راه و شهرسازی - سایت رسمی", "url": _e("NEWS_URL_MRUD", "https://news.mrud.ir"), "official": True},
    {"key": "mrud_tg", "name": "وزارت راه و شهرسازی - تلگرام", "url": "https://t.me/s/mrudNews", "official": True, "platform": "telegram"},
    {"key": "mrud_eitaa", "name": "وزارت راه و شهرسازی - ایتا", "url": "https://eitaa.com/mrudnews", "official": True, "platform": "eitaa"},
    {"key": "mrud_bale", "name": "وزارت راه و شهرسازی - بله", "url": "https://ble.ir/newsmrud", "official": True, "platform": "bale"},
    {"key": "ssaa", "name": "سازمان ثبت اسناد و املاک کشور", "url": _e("NEWS_URL_SSAA", "https://www.ssaa.ir"), "official": True},
    {"key": "tax", "name": "سازمان امور مالیاتی", "url": _e("NEWS_URL_TAX", "https://www.intamedia.ir"), "official": True},
    {"key": "cbi", "name": "بانک مرکزی جمهوری اسلامی ایران", "url": _e("NEWS_URL_CBI", "https://www.cbi.ir"), "official": True},
    {"key": "amar", "name": "مرکز آمار ایران", "url": _e("NEWS_URL_AMAR", "https://www.amar.org.ir"), "official": True},
    {"key": "mehr", "name": "خبرگزاری مهر (بخش مسکن)", "url": _e("NEWS_URL_MEHR", "https://www.mehrnews.com/service/markets/Housing"), "official": False, "topic": True},
    {"key": "irib", "name": "خبرگزاری صدا و سیما", "url": _e("NEWS_URL_IRIB", "https://www.irib-news.ir/fa/rss/allnews?"), "official": False},
    {"key": "irna", "name": "خبرگزاری ایرنا", "url": _e("NEWS_URL_IRNA", "https://www.irna.ir/rss"), "official": False},
    {"key": "isna", "name": "خبرگزاری ایسنا", "url": _e("NEWS_URL_ISNA", "https://www.isna.ir/rss"), "official": False},
    {"key": "tasnim", "name": "خبرگزاری تسنیم", "url": _e("NEWS_URL_TASNIM", "https://www.tasnimnews.ir/fa/rss/feed/0/0/8/1/TopStories"), "official": False},
]

for _i, _x in enumerate([p for p in _e("EXTRA_SOURCES").split(";") if "|" in p], 1):
    _n, _u = _x.split("|", 1)                      # EXTRA_SOURCES="نام|آدرس;نام|آدرس"
    SOURCES.append({"key": f"x{_i}", "name": _n.strip(), "url": _u.strip(), "official": False})

# منبع‌های سایت‌های ایرانی از رله‌ی داخل ایران می‌آیند؛ تلگرام و خبرگزاری‌ها مستقیم از Render خوانده می‌شوند.
_RELAY = [x.strip() for x in _e("RELAY_SOURCES", "mrud,ssaa,tax,cbi,amar,irib").split(",") if x.strip()]
# منبع‌های تأییدنشده (ایتا/بله) تا وقتی آدرس و ساختار صفحه‌شان بررسی نشده خاموش‌اند.
_DISABLED = {x.strip() for x in _e("DISABLED_SOURCES", "mrud_eitaa,mrud_bale").split(",") if x.strip()}
for _s in SOURCES:
    _s["relay"] = _s["key"] in _RELAY
    _s["disabled"] = _s["key"] in _DISABLED

KEYWORDS = ["مسکن", "اجاره", "رهن", "مستأجر", "مستاجر", "املاک", "ملک", "مالکیت", "آپارتمان", "اجاره‌بها", "اجاره بها",
            "اجاره‌نامه", "قولنامه", "قرارداد اجاره", "کدرهگیری", "کد رهگیری", "سند ملکی", "سند رسمی", "سند مالکیت",
            "سند تک‌برگ", "سند تک برگ", "ثبت اسناد", "ثبت املاک", "وام مسکن", "وام ودیعه", "وام اجاره", "وام خرید",
            "وام ساخت", "تسهیلات مسکن", "ودیعه", "نهضت ملی", "مسکن ملی", "ساخت‌وساز", "ساخت و ساز", "ساختمان",
            "شهرسازی", "شهر جدید", "شهرهای جدید", "بنگاه", "مشاور املاک", "مشاوران املاک", "معاملات مسکن",
            "معامله ملک", "معاملات ملکی", "نقل و انتقال", "نقل‌وانتقال", "زمین و مسکن", "قیمت مسکن", "بازار مسکن",
            "بازار ملک", "پیش‌فروش", "پیش فروش", "مالیات اجاره", "مالیات خانه", "خانه خالی", "خانه‌های خالی",
            "عایدی سرمایه", "مالیات نقل"]
REQUIRED_ENV = ["BALE_TOKEN", "ADMIN_ID", "CHANNEL_ID", "MONGODB_URI"]

def missing_env():
    return [k for k in REQUIRED_ENV if not _e(k) or (k == "ADMIN_ID" and ADMIN_ID == 0)]
