"""
Telegram-бот для поиска разницы в цене монет между биржами.

Два источника спредов, которые сливаются в один поток алертов:
1. Собственный расчёт: раз в CHECK_INTERVAL секунд бот забирает цены со всех
   бирж из EXCHANGES и сравнивает одинаковые пары.
2. Канал @funding_watchdog (или другой, см. CHANNEL_USERNAME): бот заходит
   туда как обычный пользователь (Telethon) и распознаёт спреды на новых
   скриншотах через Claude Vision. Это опциональная функция — без настройки
   Telethon/Anthropic бот просто работает по первому источнику.

Если разница по любому из источников больше MIN_SPREAD_PERCENT — подписчикам
уходит уведомление.
"""
import asyncio
import base64
import json
import logging
import os
import time

import ccxt.async_support as ccxt
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Подхватывает переменные из .env, если такой файл лежит рядом со скриптом
# (сам файл в git не попадает — см. .gitignore). Если .env нет, ничего не делает.
load_dotenv()

# ============ НАСТРОЙКИ: БИРЖИ ============

BOT_TOKEN = os.environ.get("ARBITRAGE_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit(
        "Задайте переменную окружения ARBITRAGE_BOT_TOKEN "
        "(токен от @BotFather, не храните его в коде)."
    )

EXCHANGES = ["binance", "bybit", "okx", "kucoin", "gateio", "mexc", "htx", "bitget"]
MIN_SPREAD_PERCENT = 1.0
CHECK_INTERVAL = 45  # секунд

# ============ НАСТРОЙКИ: ЧТЕНИЕ КАНАЛА С ФОТО ============

# Данные для входа в Telegram как обычный пользователь (my.telegram.org),
# нужны, чтобы читать чужой публичный канал — обычный Bot API так не умеет.
# Сессию получают один раз через telethon_login.py и кладут в переменную окружения.
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH")
TELEGRAM_SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")

CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "funding_watchdog")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
# Сколько секунд считаем распознанный со скриншота спред ещё актуальным
CHANNEL_SPREAD_TTL = 600

VISION_PROMPT = (
    "На картинке — скриншот из крипто-канала со спредами/разницей цен или "
    "funding rate между биржами. Извлеки все строки в виде JSON-массива "
    "объектов с полями: symbol (тикер монеты, например BTC), exchange_a и "
    "exchange_b (названия двух бирж из строки), spread_percent (число — "
    "разница в процентах, положительное). Если это funding rate — всё равно "
    "верни в spread_percent разницу между ставками в процентах. Строки, "
    "которые не удаётся уверенно разобрать, пропусти. "
    "Ответь ТОЛЬКО валидным JSON-массивом, без пояснений и без markdown."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

subscribers = set()
# symbol -> {"exchange_a", "exchange_b", "spread_percent", "ts"}
channel_spreads: dict = {}

# ============ БИРЖИ И ЦЕНЫ ============

async def connect_exchanges():
    exchanges = {}
    for ex_id in EXCHANGES:
        ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
        try:
            await ex.load_markets()
            exchanges[ex_id] = ex
        except Exception as e:
            logger.warning("Не удалось подключиться к %s: %s", ex_id, e)
            await ex.close()
    return exchanges


async def fetch_prices(exchanges: dict) -> dict:
    """Возвращает {символ: {биржа: цена}} по всем парам вида BASE/QUOTE."""
    prices: dict = {}

    async def fetch_one(ex_id, ex):
        try:
            tickers = await ex.fetch_tickers()
        except Exception as e:
            logger.warning("Ошибка получения цен с %s: %s", ex_id, e)
            return
        for symbol, ticker in tickers.items():
            if "/" not in symbol or ":" in symbol:  # пропускаем фьючерсы/свопы
                continue
            price = ticker.get("last")
            if not price:
                continue
            prices.setdefault(symbol, {})[ex_id] = price

    await asyncio.gather(*(fetch_one(ex_id, ex) for ex_id, ex in exchanges.items()))
    return prices


def find_spreads(prices: dict) -> list:
    """Для каждой пары, торгуемой на 2+ биржах, считает разницу в цене."""
    spreads = []
    for symbol, by_exchange in prices.items():
        if len(by_exchange) < 2:
            continue
        cheap_ex = min(by_exchange, key=by_exchange.get)
        expensive_ex = max(by_exchange, key=by_exchange.get)
        cheap_price = by_exchange[cheap_ex]
        expensive_price = by_exchange[expensive_ex]
        spread_percent = (expensive_price - cheap_price) / cheap_price * 100
        if spread_percent >= MIN_SPREAD_PERCENT:
            spreads.append(
                {
                    "symbol": symbol,
                    "spread_percent": spread_percent,
                    "source": "биржи",
                    "detail": f"купить на {cheap_ex} за {cheap_price:g}, продать на {expensive_ex} за {expensive_price:g}",
                }
            )
    return spreads


def get_channel_spreads() -> list:
    """Отдаёт ещё не устаревшие спреды, распознанные на фото из канала."""
    now = time.time()
    result = []
    for symbol, entry in list(channel_spreads.items()):
        if now - entry["ts"] > CHANNEL_SPREAD_TTL:
            del channel_spreads[symbol]
            continue
        if entry["spread_percent"] >= MIN_SPREAD_PERCENT:
            result.append(
                {
                    "symbol": symbol,
                    "spread_percent": entry["spread_percent"],
                    "source": f"@{CHANNEL_USERNAME}",
                    "detail": f"{entry['exchange_a']} ↔ {entry['exchange_b']}",
                }
            )
    return result


def format_message(spreads: list) -> str:
    spreads = sorted(spreads, key=lambda s: s["spread_percent"], reverse=True)[:10]
    lines = ["🔔 Разница в цене монет:"]
    for s in spreads:
        lines.append(f"\n{s['symbol']} ({s['source']}): {s['spread_percent']:.2f}%\n  {s['detail']}")
    return "\n".join(lines)


# ============ ФОНОВЫЙ ЦИКЛ ПРОВЕРКИ БИРЖ ============

async def check_loop(app: Application):
    exchanges = await connect_exchanges()
    if not exchanges:
        logger.error("Не удалось подключиться ни к одной бирже, останавливаюсь")
        return
    logger.info("Подключены биржи: %s", ", ".join(exchanges))

    try:
        while True:
            prices = await fetch_prices(exchanges)
            all_spreads = find_spreads(prices) + get_channel_spreads()
            if all_spreads and subscribers:
                text = format_message(all_spreads)
                for chat_id in list(subscribers):
                    try:
                        await app.bot.send_message(chat_id, text)
                    except Exception as e:
                        logger.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
            await asyncio.sleep(CHECK_INTERVAL)
    finally:
        await asyncio.gather(*(ex.close() for ex in exchanges.values()), return_exceptions=True)


# ============ РАСПОЗНАВАНИЕ СПРЕДОВ НА ФОТО ИЗ КАНАЛА ============

def extract_spreads_from_image(image_bytes: bytes) -> list:
    """Отправляет фото в Claude Vision и парсит ответ в список спредов."""
    from anthropic import Anthropic

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    b64 = base64.b64encode(image_bytes).decode()

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                        },
                        {"type": "text", "text": VISION_PROMPT},
                    ],
                }
            ],
        )
        text = response.content[0].text.strip().strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        raw_items = json.loads(text)
    except Exception as e:
        logger.warning("Не удалось распознать фото из канала: %s", e)
        return []

    entries = []
    for item in raw_items:
        try:
            symbol = str(item["symbol"]).upper().strip()
            exchange_a = str(item["exchange_a"]).strip()
            exchange_b = str(item["exchange_b"]).strip()
            spread_percent = float(item["spread_percent"])
        except (KeyError, ValueError, TypeError):
            continue
        if symbol and exchange_a and exchange_b and spread_percent > 0:
            entries.append(
                {"symbol": symbol, "exchange_a": exchange_a, "exchange_b": exchange_b, "spread_percent": spread_percent}
            )
    return entries


async def channel_watcher():
    """Слушает CHANNEL_USERNAME под обычным пользовательским аккаунтом Telegram
    и складывает распознанные с фото спреды в channel_spreads."""
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_SESSION_STRING and ANTHROPIC_API_KEY):
        logger.warning(
            "Чтение канала выключено: не заданы TELEGRAM_API_ID / TELEGRAM_API_HASH / "
            "TELEGRAM_SESSION_STRING / ANTHROPIC_API_KEY"
        )
        return

    from telethon import TelegramClient as TelethonClient, events
    from telethon.sessions import StringSession

    client = TelethonClient(StringSession(TELEGRAM_SESSION_STRING), int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await client.start()
    logger.info("Подключился к Telegram как пользователь, слежу за @%s", CHANNEL_USERNAME)

    @client.on(events.NewMessage(chats=CHANNEL_USERNAME))
    async def handler(event):
        if not event.photo:
            return
        try:
            image_bytes = await event.download_media(bytes)
        except Exception as e:
            logger.warning("Не удалось скачать фото из @%s: %s", CHANNEL_USERNAME, e)
            return
        entries = await asyncio.to_thread(extract_spreads_from_image, image_bytes)
        now = time.time()
        for entry in entries:
            channel_spreads[entry["symbol"]] = {**entry, "ts": now}
        if entries:
            logger.info("Распознано %d спредов из фото в @%s", len(entries), CHANNEL_USERNAME)

    await client.run_until_disconnected()


# ============ КОМАНДЫ БОТА ============

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribers.add(update.effective_chat.id)
    await update.message.reply_text(
        "Бот запущен ✅\n"
        f"Слежу за биржами: {', '.join(EXCHANGES)}\n"
        f"Плюс читаю фото со спредами из @{CHANNEL_USERNAME} (если настроено).\n"
        f"Пришлю сообщение, если разница в цене монеты превысит {MIN_SPREAD_PERCENT}%.\n\n"
        "/stop — отписаться"
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribers.discard(update.effective_chat.id)
    await update.message.reply_text("Вы отписались от уведомлений.")


async def on_startup(app: Application):
    app.create_task(check_loop(app))
    app.create_task(channel_watcher())


def main():
    # На Python 3.14 больше не создаётся event loop в основном потоке сам
    # по себе, а часть кода python-telegram-bot всё ещё вызывает
    # asyncio.get_event_loop() напрямую. Создаём и выставляем loop заранее,
    # чтобы такой вызов не падал с RuntimeError.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    logger.info("Бот запускается...")
    app.run_polling()


if __name__ == "__main__":
    main()
