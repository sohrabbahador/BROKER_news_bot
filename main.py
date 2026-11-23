import asyncio, hmac, os
from fastapi import FastAPI, Request, HTTPException
import config

app = FastAPI(title="Broker News Bot")
_miss = config.missing_env()
if _miss:                                    # بدون تنظیمات ضروری بالا نمی‌آید
    raise RuntimeError("Missing required environment variables: " + ", ".join(_miss))

import bot

@app.api_route("/", methods=["GET", "HEAD"])
def home():
    return {"status": "running", "paused": bot.PAUSED}

@app.post("/relay")
async def relay(request: Request):
    """دریافت خبر از رله‌ی داخل ایران (برای سایت‌هایی که Render به آن‌ها دسترسی ندارد)."""
    if not config.RELAY_SECRET or not hmac.compare_digest(request.headers.get("X-Relay-Secret", ""), config.RELAY_SECRET):
        raise HTTPException(403)
    data = await request.json()
    n = await bot.ingest_relay(data.get("source", ""), data.get("items", []))
    if n < 0:
        raise HTTPException(400, "unknown source")
    return {"drafts": n}

async def keepalive():
    """سرویس رایگان Render بعد از ۱۵ دقیقه بدون بازدید می‌خوابد؛ هر ۸ دقیقه آدرس خودش را باز می‌کند تا نخوابد."""
    url = os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        print("keepalive: no URL configured"); return
    import httpx
    print("keepalive active:", url)
    while True:
        await asyncio.sleep(480)
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                await c.get(url)
        except Exception as e:
            print("keepalive error:", type(e).__name__)

@app.on_event("startup")
async def startup():
    asyncio.create_task(bot.poll_updates())
    asyncio.create_task(bot.scheduler())
    asyncio.create_task(keepalive())
