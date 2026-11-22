"""رله: روی هر دستگاه با آی‌پی داخل ایران اجرا شود (سرور ایرانی، کامپیوتر یا گوشی با Termux).
سایت‌های دولتی را می‌خواند و فقط خبرهای جدید را به ربات می‌فرستد. فقط کتابخانه‌ی استاندارد پایتون.
اجرا:  BOT_URL=https://xxx.onrender.com RELAY_SECRET=... python relay.py        (هر ۵ دقیقه با cron / حلقه‌ی داخلی)
"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources, config

BOT_URL = os.getenv("BOT_URL", "").rstrip("/")
SECRET = os.getenv("RELAY_SECRET", "")
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "relay_seen.json")
EVERY = int(os.getenv("RELAY_EVERY", "300"))
RELAY_KEYS = [s for s in config.SOURCES if s["official"]]

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=sources.UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")

def post(payload):
    req = urllib.request.Request(BOT_URL + "/relay", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Relay-Secret": SECRET})
    return urllib.request.urlopen(req, timeout=60).read().decode()

def run_once():
    seen = set(json.load(open(STATE))) if os.path.exists(STATE) else set()
    for src in RELAY_KEYS:
        try:
            html = get(src["url"])
            items, _ = sources.extract_links(html, src["url"])
            new = [i for i in items if sources.uid(i["url"]) not in seen]
            send = []
            for it in new[:15]:
                if sources.is_relevant(it["title"]):
                    try: it["body"] = sources.extract_text(get(it["url"]))
                    except Exception: it["body"] = ""
                send.append(it)
            if send or new:
                post({"source": src["key"], "items": send if send else new})
            seen.update(sources.uid(i["url"]) for i in items)
            print(time.strftime("%H:%M"), src["key"], "links:", len(items), "new:", len(new))
        except Exception as e:
            print(src["key"], "error:", type(e).__name__, str(e)[:100])
    json.dump(sorted(seen)[-3000:], open(STATE, "w"))

if __name__ == "__main__":
    if not BOT_URL or not SECRET:
        sys.exit("BOT_URL و RELAY_SECRET را تنظیم کنید")
    while True:
        run_once(); time.sleep(EVERY)
