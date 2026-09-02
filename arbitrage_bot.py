"""
Telegram-бот для поиска арбитражных возможностей между криптобиржами.

Бот периодически опрашивает несколько бирж через ccxt, сравнивает цены
одинаковых торговых пар и присылает уведомление, когда разница между
самой дешёвой и самой дорогой ценой превышает заданный порог.
"""
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import ccxt.async_support as ccxt
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# ============ КОНФИГУРАЦИЯ ============

BOT_TOKEN = os.environ.get("ARBITRAGE_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit(
        "Не задан токен бота. Установите переменную окружения ARBITRAGE_BOT_TOKEN "
        "(возьмите у @BotFather и никогда не храните в коде)."
    )

# По умолчанию берём максимально широкий набор крупных бирж с публичным API тикеров.
DEFAULT_EXCHANGES = "binance,bybit,okx,kucoin,gateio,mexc,htx,bitget,coinex,bingx"
EXCHANGE_IDS = [
    x.strip().lower()
    for x in os.environ.get("EXCHANGES", DEFAULT_EXCHANGES).split(",")
    if x.strip()
]

MIN_SPREAD_PERCENT = float(os.environ.get("MIN_SPREAD_PERCENT", "1.0"))
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "45"))
ALERT_COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "900"))
SPREAD_INCREASE_TO_REALERT = float(os.environ.get("SPREAD_INCREASE_TO_REALERT", "0.5"))
MAX_ALERTS_PER_MESSAGE = int(os.environ.get("MAX_ALERTS_PER_MESSAGE", "15"))
# Отсекаем неликвидные пары (по 24ч обороту в котируемой валюте), чтобы не ловить
# "фантомные" спреды на монетах, которыми почти никто не торгует.
MIN_QUOTE_VOLUME_USD = float(os.environ.get("MIN_QUOTE_VOLUME_USD", "50000"))
FETCH_TIMEOUT_SECONDS = int(os.environ.get("FETCH_TIMEOUT_SECONDS", "20"))

SUBSCRIBERS_FILE = Path(os.environ.get("SUBSCRIBERS_FILE", "arbitrage_subscribers.json"))

# Плечевые токены (BTCUP/USDT, ETH3L/USDT и т.п.) торгуются не как обычный спот
# и дают ложные "арбитражные" спреды — отфильтровываем по названию базового актива.
LEVERAGED_TOKEN_RE = re.compile(r"(^\d+[LS]$|UP$|DOWN$|BULL$|BEAR$)", re.IGNORECASE)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("arbitrage_bot")


# ============ ХРАНИЛИЩЕ ПОДПИСЧИКОВ ============

def load_subscribers() -> set:
    if SUBSCRIBERS_FILE.exists():
        try:
            return set(json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            logger.warning("Не удалось прочитать %s, начинаю с пустого списка", SUBSCRIBERS_FILE)
    return set()


def save_subscribers(subscribers: set) -> None:
    SUBSCRIBERS_FILE.write_text(
        json.dumps(sorted(subscribers), ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ============ РАБОТА С БИРЖАМИ ============

class ExchangeHub:
    """Держит открытые соединения с биржами и забирает тикеры со всех сразу."""

    def __init__(self, exchange_ids: List[str]):
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        for ex_id in exchange_ids:
            exchange_class = getattr(ccxt, ex_id, None)
            if exchange_class is None:
                logger.warning("Биржа '%s' не поддерживается ccxt, пропускаю", ex_id)
                continue
            self.exchanges[ex_id] = exchange_class(
                {"enableRateLimit": True, "timeout": FETCH_TIMEOUT_SECONDS * 1000}
            )

    async def load_markets(self) -> None:
        results = await asyncio.gather(
            *(ex.load_markets() for ex in self.exchanges.values()),
            return_exceptions=True,
        )
        failed = []
        for ex_id, result in zip(list(self.exchanges), results):
            if isinstance(result, Exception):
                logger.warning("Не удалось загрузить рынки %s: %s", ex_id, result)
                failed.append(ex_id)
        for ex_id in failed:
            await self.exchanges[ex_id].close()
            del self.exchanges[ex_id]

    async def close(self) -> None:
        await asyncio.gather(*(ex.close() for ex in self.exchanges.values()), return_exceptions=True)

    async def _fetch_one(self, ex_id: str, exchange: ccxt.Exchange) -> Tuple[str, Optional[dict]]:
        try:
            tickers = await asyncio.wait_for(exchange.fetch_tickers(), timeout=FETCH_TIMEOUT_SECONDS)
            return ex_id, tickers
        except Exception as exc:  # биржа может упасть по любой причине (сеть, лимиты, maintenance)
            logger.warning("Ошибка получения тикеров с %s: %s", ex_id, exc)
            return ex_id, None

    async def fetch_all_tickers(self) -> Dict[str, dict]:
        results = await asyncio.gather(
            *(self._fetch_one(ex_id, ex) for ex_id, ex in self.exchanges.items())
        )
        return {ex_id: tickers for ex_id, tickers in results if tickers}


def is_valid_symbol(exchange: ccxt.Exchange, symbol: str) -> bool:
    if ":" in symbol:  # деривативы/фьючерсы (например BTC/USDT:USDT)
        return False
    if "/" not in symbol:
        return False
    base = symbol.split("/")[0]
    if LEVERAGED_TOKEN_RE.search(base):
        return False
    market = exchange.markets.get(symbol)
    if market is not None and not market.get("spot", True):
        return False
    return True


def find_opportunities(hub: ExchangeHub, all_tickers: Dict[str, dict]) -> List[dict]:
    """Считает спред по каждой паре, которая торгуется минимум на двух биржах."""
    prices_by_symbol: Dict[str, List[Tuple[str, float, float]]] = {}

    for ex_id, tickers in all_tickers.items():
        exchange = hub.exchanges[ex_id]
        for symbol, ticker in tickers.items():
            if not is_valid_symbol(exchange, symbol):
                continue
            last = ticker.get("last") or ticker.get("close")
            volume = ticker.get("quoteVolume") or 0.0
            if not last or last <= 0:
                continue
            prices_by_symbol.setdefault(symbol, []).append((ex_id, float(last), float(volume)))

    opportunities = []
    for symbol, entries in prices_by_symbol.items():
        if len(entries) < 2:
            continue
        if MIN_QUOTE_VOLUME_USD > 0:
            entries = [e for e in entries if e[2] >= MIN_QUOTE_VOLUME_USD]
        if len(entries) < 2:
            continue
        cheapest = min(entries, key=lambda e: e[1])
        priciest = max(entries, key=lambda e: e[1])
        if cheapest[0] == priciest[0]:
            continue
        spread_percent = (priciest[1] - cheapest[1]) / cheapest[1] * 100
        if spread_percent < MIN_SPREAD_PERCENT:
            continue
        opportunities.append(
            {
                "symbol": symbol,
                "buy_exchange": cheapest[0],
                "buy_price": cheapest[1],
                "sell_exchange": priciest[0],
                "sell_price": priciest[1],
                "spread_percent": spread_percent,
            }
        )

    opportunities.sort(key=lambda o: o["spread_percent"], reverse=True)
    return opportunities


# ============ АЛЕРТЫ И COOLDOWN ============

def format_opportunity(o: dict) -> str:
    return (
        f"*{o['symbol']}*: `{o['spread_percent']:.2f}%`\n"
        f"  купить на *{o['buy_exchange']}* по `{o['buy_price']:.8g}`\n"
        f"  продать на *{o['sell_exchange']}* по `{o['sell_price']:.8g}`"
    )


def select_alerts(opportunities: List[dict], last_alerted: Dict[str, dict], now: float) -> List[dict]:
    """Пропускает возможности через cooldown, чтобы не спамить одним и тем же спредом."""
    to_alert = []
    for o in opportunities:
        prev = last_alerted.get(o["symbol"])
        if prev is None:
            to_alert.append(o)
        else:
            elapsed = now - prev["time"]
            spread_grew = o["spread_percent"] - prev["spread_percent"] >= SPREAD_INCREASE_TO_REALERT
            if elapsed >= ALERT_COOLDOWN_SECONDS or spread_grew:
                to_alert.append(o)
        if len(to_alert) >= MAX_ALERTS_PER_MESSAGE:
            break
    return to_alert


# ============ TELEGRAM ============

def hub_exchange_ids(context: ContextTypes.DEFAULT_TYPE) -> List[str]:
    hub: ExchangeHub = context.bot_data["hub"]
    return list(hub.exchanges)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: set = context.bot_data.setdefault("subscribers", set())
    subscribers.add(update.effective_chat.id)
    save_subscribers(subscribers)
    await update.message.reply_text(
        "Бот запущен ✅\n\n"
        f"Слежу за биржами: {', '.join(sorted(hub_exchange_ids(context)))}\n"
        f"Порог оповещения: {MIN_SPREAD_PERCENT}%\n"
        f"Интервал проверки: {POLL_INTERVAL_SECONDS} сек\n\n"
        "Команды:\n"
        "/top [N] — топ спредов прямо сейчас\n"
        "/status — текущие настройки\n"
        "/stop — отписаться от рассылки"
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: set = context.bot_data.setdefault("subscribers", set())
    subscribers.discard(update.effective_chat.id)
    save_subscribers(subscribers)
    await update.message.reply_text("Вы отписаны от оповещений. Наберите /start, чтобы подписаться снова.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last_scan = context.bot_data.get("last_scan")
    if last_scan:
        _, opportunities = last_scan
        scan_info = f"Последнее сканирование: найдено {len(opportunities)} возможностей"
    else:
        scan_info = "Сканирование ещё не выполнялось"
    await update.message.reply_text(
        "Настройки:\n"
        f"Биржи: {', '.join(sorted(hub_exchange_ids(context)))}\n"
        f"Порог: {MIN_SPREAD_PERCENT}%\n"
        f"Интервал: {POLL_INTERVAL_SECONDS} сек\n"
        f"Мин. объём за 24ч: ${MIN_QUOTE_VOLUME_USD:,.0f}\n"
        f"{scan_info}"
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    n = 10
    if context.args:
        try:
            n = max(1, min(30, int(context.args[0])))
        except ValueError:
            pass
    last_scan = context.bot_data.get("last_scan")
    if not last_scan:
        await update.message.reply_text("Данные ещё собираются, попробуйте через минуту.")
        return
    _, opportunities = last_scan
    if not opportunities:
        await update.message.reply_text(f"Сейчас нет спредов больше {MIN_SPREAD_PERCENT}%.")
        return
    text = f"Топ-{n} спредов прямо сейчас:\n\n" + "\n\n".join(
        format_opportunity(o) for o in opportunities[:n]
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    hub: ExchangeHub = context.bot_data["hub"]
    try:
        all_tickers = await hub.fetch_all_tickers()
        opportunities = find_opportunities(hub, all_tickers)
    except Exception:
        logger.exception("Ошибка во время сканирования")
        return

    now = time.time()
    context.bot_data["last_scan"] = (now, opportunities)

    last_alerted: Dict[str, dict] = context.bot_data.setdefault("last_alerted", {})
    to_alert = select_alerts(opportunities, last_alerted, now)
    if not to_alert:
        return

    for o in to_alert:
        last_alerted[o["symbol"]] = {"time": now, "spread_percent": o["spread_percent"]}

    text = "\U0001F514 Найдены арбитражные возможности:\n\n" + "\n\n".join(
        format_opportunity(o) for o in to_alert
    )

    subscribers: set = context.bot_data.setdefault("subscribers", set())
    for chat_id in list(subscribers):
        try:
            await context.bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)
        except Exception as exc:
            logger.warning("Не удалось отправить сообщение %s: %s", chat_id, exc)


async def post_init(application: Application) -> None:
    hub = ExchangeHub(EXCHANGE_IDS)
    await hub.load_markets()
    if not hub.exchanges:
        raise SystemExit("Ни одна биржа не была успешно инициализирована")
    application.bot_data["hub"] = hub
    application.bot_data["subscribers"] = load_subscribers()
    logger.info("Инициализировано бирж: %s", ", ".join(hub.exchanges))


async def post_shutdown(application: Application) -> None:
    hub: Optional[ExchangeHub] = application.bot_data.get("hub")
    if hub:
        await hub.close()


def main() -> None:
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("top", cmd_top))

    application.job_queue.run_repeating(scan_job, interval=POLL_INTERVAL_SECONDS, first=10)

    logger.info("Бот запускается...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
