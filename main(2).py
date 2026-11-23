import asyncio, hmac
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

@app.on_event("startup")
async def startup():
    asyncio.create_task(bot.poll_updates())
    asyncio.create_task(bot.scheduler())
