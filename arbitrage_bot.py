"""
Telegram-бот для поиска разницы в цене монет между биржами.

Раз в CHECK_INTERVAL секунд бот забирает цены со всех бирж из EXCHANGES,
сравнивает одинаковые пары и, если разница между самой дешёвой и самой
дорогой ценой больше MIN_SPREAD_PERCENT, шлёт уведомление подписчикам.
"""
import asyncio
import logging
import os

import ccxt.async_support as ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ============ НАСТРОЙКИ ============

BOT_TOKEN = os.environ.get("ARBITRAGE_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit(
        "Задайте переменную окружения ARBITRAGE_BOT_TOKEN "
        "(токен от @BotFather, не храните его в коде)."
    )

EXCHANGES = ["binance", "bybit", "okx", "kucoin", "gateio", "mexc", "htx", "bitget"]
MIN_SPREAD_PERCENT = 1.0
CHECK_INTERVAL = 45  # секунд

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

subscribers = set()

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
            spreads.append((symbol, cheap_ex, cheap_price, expensive_ex, expensive_price, spread_percent))
    spreads.sort(key=lambda row: row[5], reverse=True)
    return spreads


def format_message(spreads: list) -> str:
    lines = ["🔔 Разница в цене монет:"]
    for symbol, cheap_ex, cheap_price, expensive_ex, expensive_price, spread in spreads[:10]:
        lines.append(
            f"\n{symbol}: {spread:.2f}%\n"
            f"  купить на {cheap_ex} за {cheap_price:g}\n"
            f"  продать на {expensive_ex} за {expensive_price:g}"
        )
    return "\n".join(lines)


# ============ ФОНОВЫЙ ЦИКЛ ПРОВЕРКИ ============

async def check_loop(app: Application):
    exchanges = await connect_exchanges()
    if not exchanges:
        logger.error("Не удалось подключиться ни к одной бирже, останавливаюсь")
        return
    logger.info("Подключены биржи: %s", ", ".join(exchanges))

    try:
        while True:
            prices = await fetch_prices(exchanges)
            spreads = find_spreads(prices)
            if spreads and subscribers:
                text = format_message(spreads)
                for chat_id in list(subscribers):
                    try:
                        await app.bot.send_message(chat_id, text)
                    except Exception as e:
                        logger.warning("Не удалось отправить сообщение %s: %s", chat_id, e)
            await asyncio.sleep(CHECK_INTERVAL)
    finally:
        await asyncio.gather(*(ex.close() for ex in exchanges.values()), return_exceptions=True)


# ============ КОМАНДЫ БОТА ============

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribers.add(update.effective_chat.id)
    await update.message.reply_text(
        "Бот запущен ✅\n"
        f"Слежу за биржами: {', '.join(EXCHANGES)}\n"
        f"Пришлю сообщение, если разница в цене монеты между биржами превысит {MIN_SPREAD_PERCENT}%.\n\n"
        "/stop — отписаться"
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribers.discard(update.effective_chat.id)
    await update.message.reply_text("Вы отписались от уведомлений.")


async def on_startup(app: Application):
    app.create_task(check_loop(app))


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    logger.info("Бот запускается...")
    app.run_polling()


if __name__ == "__main__":
    main()
