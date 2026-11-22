import asyncio
from fastapi import FastAPI
import config

app = FastAPI(title="Broker News Bot")
_miss = config.missing_env()
if _miss:                                    # بدون تنظیمات ضروری بالا نمی‌آید
    raise RuntimeError("Missing required environment variables: " + ", ".join(_miss))

import bot

@app.get("/")
def home():
    return {"status": "running", "paused": bot.PAUSED}

@app.on_event("startup")
async def startup():
    asyncio.create_task(bot.poll_updates())
    asyncio.create_task(bot.scheduler())
