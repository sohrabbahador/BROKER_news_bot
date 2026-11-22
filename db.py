from pymongo import MongoClient
import config
_c = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=8000) if config.MONGODB_URI else None
db = _c["broker_news"] if _c is not None else None   # دیتابیس مستقل؛ به دیتابیس ربات‌ها دست نمی‌زند
