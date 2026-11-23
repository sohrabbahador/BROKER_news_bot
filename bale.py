import httpx
import config

BASE = f"https://tapi.bale.ai/bot{config.BALE_TOKEN}"

async def call(method, **payload):
    async with httpx.AsyncClient(timeout=70) as c:
        r = await c.post(f"{BASE}/{method}", json=payload)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "description": f"HTTP {r.status_code}"}

async def send_message(chat_id, text, keyboard=None, reply_keyboard=None, parse_mode=None):
    """keyboard = دکمه‌های زیر پیام (inline)؛ reply_keyboard = کلیدهای ثابت پایین صفحه‌ی چت."""
    p = {"chat_id": chat_id, "text": text[:4000]}
    if parse_mode: p["parse_mode"] = parse_mode
    if keyboard:
        p["reply_markup"] = {"inline_keyboard": keyboard}
    elif reply_keyboard:
        p["reply_markup"] = {"keyboard": [[{"text": t} for t in row] for row in reply_keyboard], "resize_keyboard": True}
    return await call("sendMessage", **p)

async def send_photo(chat_id, png: bytes, caption="", keyboard=None):
    import json
    data = {"chat_id": str(chat_id), "caption": caption[:1000]}
    if keyboard: data["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{BASE}/sendPhoto", data=data, files={"photo": ("news.png", png, "image/png")})
    try: return r.json()
    except Exception: return {"ok": False}

async def edit_message_keyboard(chat_id, message_id, keyboard=None):
    """فقط صفحه‌کلید زیر همان پیام را عوض می‌کند؛ متن خبر دست‌نخورده می‌ماند."""
    markup = {"inline_keyboard": keyboard} if keyboard else {"inline_keyboard": []}
    return await call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup=markup)

async def answer_callback(cb_id, text=""):
    return await call("answerCallbackQuery", callback_query_id=cb_id, text=text)

async def get_updates(offset=None, timeout=30):
    p = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset: p["offset"] = offset
    return await call("getUpdates", **p)
