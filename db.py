import config
try:
    from pymongo import MongoClient
except Exception:          # برای تست بدون نصب pymongo
    MongoClient = None

class NS:
    """مجموعه‌های این ربات با پیشوند news_ داخل همان دیتابیس ربات‌ها ساخته می‌شوند.
    به مجموعه‌های ربات‌های فروش و اجاره دست نمی‌زند و به اجازه‌ی دیتابیس جدید نیاز ندارد."""
    def __init__(self, database, prefix="news_"):
        self._d, self._p = database, prefix
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._d[self._p + name]
    def command(self, *a, **k):
        return self._d.command(*a, **k)

_c = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=8000) if (MongoClient and config.MONGODB_URI) else None
db = NS(_c[config.NEWS_DB], config.NEWS_PREFIX) if _c is not None else None
