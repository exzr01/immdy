# smart_congestion_bot.py
import os, asyncio, time, math
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

TOKEN = os.getenv("TG_TOKEN")                  # Telegram Bot Token
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # твой Telegram ID для алертов

# === Пороговые настройки ===
SERVERS_THRESHOLD = int(os.getenv("SERVERS_THRESHOLD", "65"))
POOLS_THRESHOLD   = int(os.getenv("POOLS_THRESHOLD", "45"))
NETWORK_MAX       = int(os.getenv("NETWORK_MAX", "30"))

# === Эндпоинты (вставишь свои) ===
# Пример: https://ton.diamonds/api/v1/metrics/servers  -> { "congestion": 73 }
DIAMONDS_SERVERS_URL = os.getenv("DIAMONDS_SERVERS_URL", "https://ton.diamonds/api/v1/metrics/servers")
DIAMONDS_POOLS_URL   = os.getenv("DIAMONDS_POOLS_URL",   "https://ton.diamonds/api/v1/metrics/pools")

# Для сети TON можно сделать свой расчёт или подключить готовый показатель:
# Плейсхолдер: вернём 15..35% как пример. Заменишь функцией расчёта через tonapi/toncenter.
TON_NETWORK_URL      = os.getenv("TON_NETWORK_URL", "https://example.com/ton/network_load_percent")

# Параметры опроса
POLL_PERIOD_SEC = int(os.getenv("POLL_PERIOD_SEC", "120"))
COOLDOWN_SEC    = int(os.getenv("COOLDOWN_SEC", "300"))  # не слать одинаковые оповещения чаще, чем раз в 5 минут

bot = Bot(TOKEN)
dp = Dispatcher()

last_state = None         # "WORK" / "WAIT"
last_notify_ts = 0

def decide_status(servers:int, pools:int, network:int) -> str:
    work = ((servers >= SERVERS_THRESHOLD) or (pools >= POOLS_THRESHOLD)) and (network <= NETWORK_MAX)
    return "WORK" if work else "WAIT"

def colored(value:int) -> str:
    if value >= 65:  # красная зона
        return f"{value}% 🔴"
    elif value >= 35: # жёлтая (можно не использовать)
        return f"{value}% 🟡"
    else:
        return f"{value}% 🟢"

async def fetch_json(session:aiohttp.ClientSession, url:str, default:dict|int|None=None):
    try:
        async with session.get(url, timeout=10) as r:
            r.raise_for_status()
            return await r.json()
    except Exception:
        return default

async def get_diamonds_servers(session) -> int:
    data = await fetch_json(session, DIAMONDS_SERVERS_URL, default={"congestion": None})
    return int(data.get("congestion") or 0)

async def get_diamonds_pools(session) -> int:
    data = await fetch_json(session, DIAMONDS_POOLS_URL, default={"congestion": None})
    return int(data.get("congestion") or 0)

async def get_ton_network(session) -> int:
    # TODO: заменить на реальный расчёт через tonapi/toncenter.
    data = await fetch_json(session, TON_NETWORK_URL, default={"network_load": 20})
    return int(data.get("network_load") or 20)

def render_text(servers:int, pools:int, network:int, status:str) -> str:
    lines = []
    if status == "WORK":
        lines.append("🚨 CONGESTION WINDOW DETECTED! 🚨")
    else:
        lines.append("Status TDC BOT — 👍")

    lines += [
        f"TON Diamonds Servers Congestion — {colored(servers)}",
        f"TON Diamonds Pools Congestion — {colored(pools)}",
        "────────────",
        f"TON Network — {colored(network)}",
        "",
        f"Work Status: **{status}!**"
    ]
    return "\n".join(lines)

def keyboard_refresh():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Refresh", callback_data="refresh")]
    ])
    return kb

async def snapshot():
    async with aiohttp.ClientSession() as session:
        servers = await get_diamonds_servers(session)
        pools = await get_diamonds_pools(session)
        network = await get_ton_network(session)
    status = decide_status(servers, pools, network)
    text = render_text(servers, pools, network, status)
    return status, text

@dp.message(Command("start"))
async def cmd_start(m: Message):
    status, text = await snapshot()
    await m.answer(text, reply_markup=keyboard_refresh(), parse_mode="Markdown")

@dp.callback_query(F.data == "refresh")
async def cb_refresh(c: CallbackQuery):
    status, text = await snapshot()
    await c.message.edit_text(text, reply_markup=keyboard_refresh(), parse_mode="Markdown")
    await c.answer("Updated")

async def poller():
    global last_state, last_notify_ts
    await bot.delete_webhook(drop_pending_updates=True)
    while True:
        try:
            status, text = await snapshot()
            now = time.time()
            if status != last_state and (now - last_notify_ts) > COOLDOWN_SEC:
                last_state = status
                last_notify_ts = now
                if ADMIN_CHAT_ID:
                    await bot.send_message(ADMIN_CHAT_ID, text, reply_markup=keyboard_refresh(), parse_mode="Markdown")
        except Exception as e:
            # можно логировать
            pass
        await asyncio.sleep(POLL_PERIOD_SEC)

async def main():
    asyncio.create_task(poller())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
