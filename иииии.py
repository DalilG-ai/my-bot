import logging
import random
import json
import os
import aiohttp
from datetime import time, datetime, date
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ========================
# НАСТРОЙКИ
# ========================
BOT_TOKEN = "8276751042:AAHF01RI636XQvoqANRXQMytnFY0h9ZbKJ8"
DATA_FILE = "users_data.json"

SEND_TIMES = [
    time(4, 0),
    time(7, 0),
    time(10, 0),
    time(13, 0),
    time(16, 0),
    time(18, 0),
]

# ========================
# ЦИТАТЫ
# ========================
QURAN_QUOTES = [
    ("Сура Аш-Шарх (94:5–6)", "«Воистину, вместе с трудностью — облегчение. Воистину, вместе с трудностью — облегчение.»"),
    ("Сура Аз-Зумар (39:53)", "«Не отчаивайтесь в милости Аллаха. Поистине, Аллах прощает грехи все.»"),
    ("Сура Ар-Ра'д (13:11)", "«Аллах не меняет положения людей, пока они сами не изменят того, что есть в них.»"),
    ("Сура Аль-Бакара (2:286)", "«Аллах не возлагает на душу ничего, кроме возможного для неё.»"),
    ("Сура Аль-Имран (3:139)", "«Не слабейте и не печальтесь — вы будете выше, если вы истинно верующие.»"),
    ("Сура Аль-Анфаль (8:46)", "«Терпите! Поистине, Аллах — с терпеливыми.»"),
    ("Сура Аз-Зумар (39:10)", "«Воистину, терпеливым воздастся без счёта.»"),
    ("Сура Аль-Инширах (94:7–8)", "«Когда освободишься — трудись усердно, и к Господу своему стремись.»"),
    ("Хадис пророка ﷺ", "«Удивительно дело верующего: всё у него — к лучшему. Если постигает радость — он благодарит. Если постигает горе — он терпит. И это лучше для него.»"),
    ("Сура Аль-Мульк (67:2)", "«Он создал смерть и жизнь, чтобы испытать вас — кто из вас лучше по делам.»"),
    ("Сура Аль-Анкабут (29:69)", "«Тех, кто усердствует ради Нас, — Мы непременно поведём Нашими путями.»"),
    ("Сура Аль-Талак (65:3)", "«Кто уповает на Аллаха, тому Он достаточен.»"),
]

BIBLE_QUOTES = [
    ("Филиппийцам 4:13", "«Всё могу в укрепляющем меня Иисусе Христе.»"),
    ("Иеремия 29:11", "«Я знаю намерения, какие имею о вас... намерения во благо, а не во зло, чтобы дать вам будущность и надежду.»"),
    ("Римлянам 8:28", "«Любящим Бога... всё содействует ко благу.»"),
    ("Матфея 19:26", "«Человекам это невозможно, Богу же всё возможно.»"),
    ("Исаия 40:31", "«Надеющиеся на Господа обновятся в силе: поднимут крылья, как орлы, потекут — и не устанут.»"),
    ("Псалом 27:14", "«Надейся на Господа, мужайся, и да укрепляется сердце твоё.»"),
    ("Иакова 1:12", "«Блажен человек, который переносит искушение, потому что, быв испытан, он получит венец жизни.»"),
    ("Второзаконие 31:6", "«Будьте тверды и мужественны, не бойтесь... ибо Господь, Бог твой, Сам пойдёт с тобою.»"),
    ("Притчи 3:5–6", "«Надейся на Господа всем сердцем твоим... и Он направит стези твои.»"),
    ("Псалом 23:4", "«Если я пойду и долиною смертной тени, не убоюсь зла, потому что Ты со мной.»"),
    ("Иисус Навин 1:9", "«Будь тверд и мужествен; не страшись и не ужасайся, ибо с тобою Господь, Бог твой, везде, куда ни пойдёшь.»"),
    ("2 Тимофею 1:7", "«Бог дал нам духа не боязни, но силы и любви и целомудрия.»"),
]

MOTIVATION_QUOTES = [
    "💪 Каждый шаг вперёд — это победа над вчерашним собой.",
    "🔥 Ты не сдаёшься — ты просто делаешь перерыв перед рывком.",
    "🌟 Цель не исчезла. Ты просто устал. Отдохни и продолжай.",
    "🚀 Великие дела делаются не за один день. Главное — не останавливаться.",
    "🏆 Сложно сейчас? Значит, ты растёшь.",
    "⚡ Мотивация приходит в процессе действия. Начни — и она появится.",
    "🎯 Ты уже дальше, чем был вчера. Это важно.",
    "🌱 Маленький прогресс — всё равно прогресс.",
    "🔑 Ключ к успеху — это не талант. Это упорство.",
    "✨ Ты способен на большее, чем думаешь о себе в трудный момент.",
]

# ========================
# СОСТОЯНИЯ
# ========================
(
    ENTER_BOT_NAME,
    ENTER_GOAL,
    CHOOSE_RELIGION,
    WAITING_QUIZ_ANSWER,
    WAITING_RESULT,
    WAITING_RESTORE,
    WAITING_SURRENDER,
    WAITING_PRICE_SYMBOL,
) = range(8)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========================
# ХРАНИЛИЩЕ ДАННЫХ
# ========================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(user_id: int) -> dict:
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "bot_name": "Напарник",
            "goal": "",
            "religion": "neutral",
            "streak": 0,
            "last_active": "",
            "restore_used": False,
            "victories": [],
            "setup_done": False,
        }
        save_data(data)
    return data[uid]

def update_user(user_id: int, fields: dict):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        get_user(user_id)
        data = load_data()
    data[uid].update(fields)
    save_data(data)

def check_and_update_streak(user_id: int) -> tuple[int, bool]:
    user = get_user(user_id)
    today = date.today().isoformat()
    last = user.get("last_active", "")
    streak = user.get("streak", 0)

    if last == today:
        return streak, False

    if last == "":
        update_user(user_id, {"streak": 1, "last_active": today})
        return 1, False

    last_date = date.fromisoformat(last)
    delta = (date.today() - last_date).days

    if delta == 1:
        new_streak = streak + 1
        update_user(user_id, {"streak": new_streak, "last_active": today})
        return new_streak, False
    elif delta > 1:
        update_user(user_id, {"streak": 0, "last_active": today})
        return 0, True
    return streak, False

# ========================
# ПОЛУЧИТЬ ЦИТАТУ
# ========================
def get_quote(religion: str) -> str:
    if religion == "islam":
        title, text = random.choice(QURAN_QUOTES)
        return f"📖 {title}\n\n{text}"
    elif religion == "christianity":
        title, text = random.choice(BIBLE_QUOTES)
        return f"📖 {title}\n\n{text}"
    else:
        roll = random.random()
        if roll < 0.33:
            title, text = random.choice(QURAN_QUOTES)
            return f"📖 {title}\n\n{text}"
        elif roll < 0.66:
            title, text = random.choice(BIBLE_QUOTES)
            return f"📖 {title}\n\n{text}"
        else:
            return random.choice(MOTIVATION_QUOTES)

def get_streak_label(religion: str) -> str:
    if religion == "islam":
        return "Дни сабра"
    elif religion == "christianity":
        return "Дни веры"
    return "Дни силы"

def get_milestone_msg(streak: int, religion: str, bot_name: str) -> str | None:
    msgs = {
        7: {
            "islam": f"МашаАллах! 🔥 7 дней сабра! {bot_name} гордится тобой!",
            "christianity": f"Аминь! 🔥 7 дней веры! {bot_name} рядом с тобой!",
            "neutral": f"🔥 Неделя силы! {bot_name} видит твой прогресс!",
        },
        21: {
            "islam": f"МашаАллах! 🔥🔥 21 день! Привычка формируется, брат!",
            "christianity": f"Аминь! 🔥🔥 21 день с Господом на пути!",
            "neutral": f"🔥🔥 21 день! Ты уже другой человек!",
        },
        30: {
            "islam": f"МашаАллах! 🔥🔥🔥 30 дней сабра! Аллах видит твоё упорство!",
            "christianity": f"Слава Богу! 🔥🔥🔥 30 дней! Господь с тобой на каждом шагу!",
            "neutral": f"🔥🔥🔥 30 дней! Ты — легенда. Серьёзно.",
        },
        60: {
            "islam": f"60 дней! 🏆 Два месяца сабра. Это не случайность — это характер.",
            "christianity": f"60 дней! 🏆 Два месяца веры. Бог не забывает тех, кто не сдаётся.",
            "neutral": f"60 дней! 🏆 Два месяца. Ты серьёзно настроен.",
        },
        100: {
            "islam": f"100 дней! 🏆👑 МашаАллах! Ты не тот человек что начинал. Аллах с терпеливыми!",
            "christianity": f"100 дней! 🏆👑 Аминь! Сто дней с Господом. Ты не тот человек что начинал!",
            "neutral": f"100 дней! 🏆👑 Сто дней. Ты не тот человек что начинал. Это огромно.",
        },
    }
    if streak in msgs:
        return msgs[streak].get(religion, msgs[streak]["neutral"])
    return None

# ========================
# КЛАВИАТУРЫ
# ========================
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🔥 Мой огонёк"), KeyboardButton("📖 Цитата сейчас")],
        [KeyboardButton("😤 Хочу сдаться"), KeyboardButton("🧠 Поговорить")],
        [KeyboardButton("🏆 Мои победы"), KeyboardButton("🎯 Моя цель")],
        [KeyboardButton("💹 Цена монеты")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_religion_keyboard():
    keyboard = [
        [KeyboardButton("☪️ Ислам"), KeyboardButton("✝️ Христианство")],
        [KeyboardButton("🌍 Без религии")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# ========================
# ЦЕНЫ НА БИРЖАХ
# ========================
async def fetch_price_bingx(symbol: str) -> float | None:
    url = f"https://open-api.bingx.com/openApi/swap/v2/quote/price?symbol={symbol}-USDT"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return float(data["data"]["price"])
    except Exception:
        return None

async def fetch_price_mexc(symbol: str) -> float | None:
    url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}USDT"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return float(data["price"])
    except Exception:
        return None

async def fetch_price_gate(symbol: str) -> float | None:
    url = f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={symbol}_USDT"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return float(data[0]["last"])
    except Exception:
        return None

async def fetch_price_htx(symbol: str) -> float | None:
    url = f"https://api.huobi.pro/market/detail/merged?symbol={symbol.lower()}usdt"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return float(data["tick"]["close"])
    except Exception:
        return None

async def get_prices(symbol: str) -> dict:
    import asyncio
    results = await asyncio.gather(
        fetch_price_bingx(symbol),
        fetch_price_mexc(symbol),
        fetch_price_gate(symbol),
        fetch_price_htx(symbol),
    )
    return {
        "BingX": results[0],
        "MEXC":  results[1],
        "Gate":  results[2],
        "HTX":   results[3],
    }

def format_price_message(symbol: str, prices: dict) -> str:
    valid = {k: v for k, v in prices.items() if v is not None}

    if not valid:
        return f"❌ Не удалось получить цены для *{symbol}*. Проверь название монеты."

    max_price = max(valid.values())
    min_price = min(valid.values())
    max_diff_pct = ((max_price - min_price) / min_price) * 100

    lines = [f"💹 *{symbol.upper()}/USDT*\n"]
    for exchange, price in prices.items():
        if price is None:
            lines.append(f"  {exchange}: ❌ недоступно")
        else:
            diff = ((price - max_price) / max_price) * 100
            if diff == 0:
                lines.append(f"  {exchange}: `${price:,.4f}` ✅ макс")
            else:
                lines.append(f"  {exchange}: `${price:,.4f}` ({diff:+.3f}%)")

    lines.append(f"\n📊 Макс разница: *{max_diff_pct:.3f}%*")

    if max_diff_pct >= 0.3:
        lines.append("⚡ Арбитраж возможен!")

    return "\n".join(lines)

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введи символ монеты, например:\n`BTC`, `ETH`, `SOL`, `BNB`",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )
    return WAITING_PRICE_SYMBOL

async def handle_price_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "⬅️ Назад":
        await update.message.reply_text("Главное меню 😊", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    symbol = text.upper().replace("USDT", "").replace("/", "").strip()

    msg = await update.message.reply_text(f"⏳ Получаю цены для *{symbol}*...", parse_mode="Markdown")

    prices = await get_prices(symbol)
    result = format_price_message(symbol, prices)

    await msg.edit_text(result, parse_mode="Markdown")
    await update.message.reply_text(
        "Введи другой символ или вернись назад:",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )
    return WAITING_PRICE_SYMBOL

# ========================
# ОНБОРДИНГ
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! 👋\n\n"
        "Я буду твоим напарником на пути к цели.\n"
        "Буду рядом каждый день — поддержу, не дам сдаться, порадуюсь твоим победам.\n\n"
        "Как ты хочешь меня назвать? Придумай имя! 😊",
        reply_markup=ReplyKeyboardMarkup([[]], resize_keyboard=True)
    )
    return ENTER_BOT_NAME

async def enter_bot_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = update.message.text.strip()
    if not bot_name:
        await update.message.reply_text("Напиши имя — хоть одно слово 😊")
        return ENTER_BOT_NAME
    context.user_data["bot_name"] = bot_name
    await update.message.reply_text(
        f"Отлично, я — *{bot_name}*! 🤝\n\n"
        f"Теперь скажи: какая твоя главная цель?\n"
        f"Напиши одним предложением — что ты хочешь достичь.",
        parse_mode="Markdown"
    )
    return ENTER_GOAL

async def enter_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    goal = update.message.text.strip()
    if not goal:
        await update.message.reply_text("Напиши свою цель — одним предложением.")
        return ENTER_GOAL
    context.user_data["goal"] = goal
    await update.message.reply_text(
        f"Цель записана: *\"{goal}\"* 🎯\n\n"
        "Я буду возвращаться к ней каждый раз, когда тебе будет тяжело.\n\n"
        "Последний вопрос: какая у тебя религия?\n"
        "Я подберу цитаты специально для тебя. 🙏",
        parse_mode="Markdown",
        reply_markup=get_religion_keyboard()
    )
    return CHOOSE_RELIGION

async def choose_religion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if "Ислам" in text:
        religion = "islam"
        religion_label = "Ислам ☪️"
        welcome = "Буду присылать аяты из Корана и хадисы пророка ﷺ. БисмиЛлях — начинаем путь!"
    elif "Христианство" in text:
        religion = "christianity"
        religion_label = "Христианство ✝️"
        welcome = "Буду присылать стихи из Библии. Господь с тобой на этом пути!"
    else:
        religion = "neutral"
        religion_label = "Без религии 🌍"
        welcome = "Буду присылать мотивационные фразы, суры и стихи из Библии — лучшее из всего."

    bot_name = context.user_data.get("bot_name", "Напарник")
    goal = context.user_data.get("goal", "")

    update_user(user_id, {
        "bot_name": bot_name,
        "goal": goal,
        "religion": religion,
        "streak": 1,
        "last_active": date.today().isoformat(),
        "restore_used": False,
        "victories": [],
        "setup_done": True,
    })

    await update.message.reply_text(
        f"*{religion_label}* — принято! 🙏\n\n"
        f"{welcome}\n\n"
        f"🔥 День 1 — огонёк зажжён!\n\n"
        f"Сообщения приходят 6 раз в день. Я всегда рядом, {bot_name} на связи! 💪",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

    schedule_daily_messages(context, update.effective_chat.id)
    return ConversationHandler.END

# ========================
# ОГОНЁК
# ========================
async def show_streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    streak = user.get("streak", 0)
    religion = user.get("religion", "neutral")
    bot_name = user.get("bot_name", "Напарник")
    label = get_streak_label(religion)

    if streak == 0:
        msg = f"🔥 Огонёк погас...\n\nНо {bot_name} верит в тебя. Начни снова — нажми любую кнопку и ответь мне сегодня!"
    elif streak < 7:
        msg = f"🔥 {label}: *{streak}* {'день' if streak == 1 else 'дня' if streak < 5 else 'дней'}\n\nХорошее начало! Не останавливайся."
    elif streak < 30:
        msg = f"🔥🔥 {label}: *{streak}* дней\n\n{bot_name} видит твой огонь! Продолжай!"
    else:
        msg = f"🔥🔥🔥 {label}: *{streak}* дней\n\n*{bot_name}:* Ты настоящий. Это не случайность — это характер."

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

# ========================
# ЦИТАТА ПО ЗАПРОСУ
# ========================
async def send_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    quote = get_quote(user.get("religion", "neutral"))
    streak, lost = check_and_update_streak(user_id)
    user = get_user(user_id)

    text = quote
    if lost:
        text += f"\n\n😔 Огонёк погас... Но ты здесь — и это важно. День 1 начат заново."
        restore = user.get("restore_used", False)
        if not restore:
            text += "\n\n💡 У тебя есть *один шанс* восстановить стрик. Нажми 🔥 Мой огонёк."

    milestone = get_milestone_msg(streak, user.get("religion", "neutral"), user.get("bot_name", "Напарник"))
    if milestone and not lost:
        text += f"\n\n{milestone}"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# ========================
# ХОЧУ СДАТЬСЯ
# ========================
async def want_to_surrender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    bot_name = user.get("bot_name", "Напарник")
    await update.message.reply_text(
        f"*{bot_name}:* Эй... я здесь. 🤝\n\n"
        "Расскажи мне — что случилось? Что произошло?\n\n"
        "Я не буду читать лекцию. Просто расскажи.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
    )
    return WAITING_SURRENDER

async def handle_surrender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Назад":
        await update.message.reply_text("Хорошо. Я рядом. 🤝", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    user_id = update.effective_user.id
    user = get_user(user_id)
    bot_name = user.get("bot_name", "Напарник")
    goal = user.get("goal", "твоя цель")
    religion = user.get("religion", "neutral")
    streak = user.get("streak", 0)
    quote = get_quote(religion)

    response = (
        f"*{bot_name}:* Спасибо что рассказал. Это важно — не держать в себе. 🙏\n\n"
        f"{quote}\n\n"
        f"Помнишь, ты сам написал свою цель:\n"
        f"*\"{goal}\"*\n\n"
        f"Эта цель никуда не делась. Ты ещё не дошёл до неё — значит, рано останавливаться.\n\n"
        f"🔥 У тебя {streak} {'день' if streak == 1 else 'дней'} позади. Ты это заработал.\n\n"
        f"Один маленький шаг. Что можешь сделать прямо сейчас?"
    )
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=get_main_keyboard())
    return ConversationHandler.END

# ========================
# ПОГОВОРИТЬ
# ========================
async def talk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    bot_name = user.get("bot_name", "Напарник")
    goal = user.get("goal", "твоя цель")
    streak = user.get("streak", 0)
    quote = get_quote(user.get("religion", "neutral"))

    await update.message.reply_text(
        f"*{bot_name}:* Привет! Рад что ты здесь. 🤝\n\n"
        f"Твоя цель: *\"{goal}\"*\n"
        f"🔥 Стрик: *{streak}* дней\n\n"
        f"{quote}\n\n"
        f"Как дела? Что происходит сегодня на пути к цели?",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# ========================
# МОИ ПОБЕДЫ
# ========================
async def my_victories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    bot_name = user.get("bot_name", "Напарник")
    victories = user.get("victories", [])

    if not victories:
        await update.message.reply_text(
            f"*{bot_name}:* Побед пока нет в списке, но они есть!\n\n"
            "Каждый день что ты держишься — это уже победа. 💪\n\n"
            "Хочешь записать свою первую победу? Напиши её прямо сейчас!",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("✍️ Записать победу")], [KeyboardButton("⬅️ Назад")]],
                resize_keyboard=True
            )
        )
    else:
        text = f"*{bot_name}:* Смотри что ты уже сделал! 🏆\n\n"
        for i, v in enumerate(victories[-10:], 1):
            text += f"{i}. {v['text']} _{v['date']}_\n"
        text += f"\n*Всего побед: {len(victories)}* 🔥\n\nКаждая из них — настоящая."
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("✍️ Записать победу")], [KeyboardButton("⬅️ Назад")]],
                resize_keyboard=True
            )
        )
    return WAITING_RESULT

async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "⬅️ Назад":
        await update.message.reply_text("Возвращаемся! 😊", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    if text == "✍️ Записать победу":
        await update.message.reply_text(
            "Напиши свою победу — большую или маленькую, всё считается! 💪",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Назад")]], resize_keyboard=True)
        )
        return WAITING_RESULT

    user_id = update.effective_user.id
    user = get_user(user_id)
    victories = user.get("victories", [])
    victories.append({"text": text, "date": date.today().strftime("%d.%m.%Y")})
    update_user(user_id, {"victories": victories})

    bot_name = user.get("bot_name", "Напарник")
    await update.message.reply_text(
        f"*{bot_name}:* Записал! 🏆\n\n"
        f"*\"{text}\"*\n\n"
        f"Это настоящая победа. Теперь она всегда будет здесь — и я напомню о ней когда будет тяжело. 💪",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

# ========================
# МОЯ ЦЕЛЬ
# ========================
async def my_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    bot_name = user.get("bot_name", "Напарник")
    goal = user.get("goal", "не указана")
    streak = user.get("streak", 0)
    await update.message.reply_text(
        f"🎯 Твоя цель:\n\n*\"{goal}\"*\n\n"
        f"🔥 Стрик: *{streak}* дней\n\n"
        f"*{bot_name}:* Держи её в голове. Каждый день — шаг к ней.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

# ========================
# ВОССТАНОВЛЕНИЕ СТРИКА
# ========================
async def restore_streak_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    bot_name = user.get("bot_name", "Напарник")

    if user.get("restore_used"):
        await update.message.reply_text(
            f"*{bot_name}:* Ты уже использовал шанс восстановления. 😔\n\n"
            "Но ничего — начни заново. День 1 это не конец, это новое начало. 🔥",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"*{bot_name}:* Огонёк погас, но у тебя есть *один шанс* восстановить его. 🔥\n\n"
        "Расскажи — что помешало тебе вчера? Это засчитается как день.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("⬅️ Отмена")]], resize_keyboard=True)
    )
    return WAITING_RESTORE

async def handle_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "⬅️ Отмена":
        await update.message.reply_text("Хорошо.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    user_id = update.effective_user.id
    user = get_user(user_id)
    bot_name = user.get("bot_name", "Напарник")
    old_streak = user.get("streak", 0)
    restored = old_streak + 1 if old_streak > 0 else 1

    update_user(user_id, {
        "streak": restored,
        "restore_used": True,
        "last_active": date.today().isoformat(),
    })

    await update.message.reply_text(
        f"*{bot_name}:* Принято. 🔥 Огонёк восстановлен!\n\n"
        f"Стрик: *{restored}* дней\n\n"
        f"Этот шанс был один. Береги огонёк — он твой. 💪",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

# ========================
# АВТОМАТИЧЕСКИЕ УВЕДОМЛЕНИЯ
# ========================
SCHEDULED_MESSAGES = [
    lambda user: (
        f"🌅 Доброе утро!\n\n"
        f"{get_quote(user['religion'])}\n\n"
        f"🔥 День {user['streak']} — огонёк горит!\n\n"
        f"Что сделаешь сегодня для своей цели?\n*\"{user['goal']}\"*"
    ),
    lambda user: (
        f"☀️ *{user['bot_name']}:* Как утро? Уже сделал первый шаг?\n\n"
        f"🎯 Помни: *\"{user['goal']}\"*\n\n"
        f"{get_quote(user['religion'])}"
    ),
    lambda user: (
        f"🕐 Середина дня!\n\n"
        f"{get_quote(user['religion'])}\n\n"
        f"🔥 Огонёк горит уже *{user['streak']}* дней. Не гаси его сегодня!"
    ),
    lambda user: (
        f"💪 *{user['bot_name']}:* Ещё пару часов до конца дня.\n\n"
        f"Сделай хоть один маленький шаг для:\n*\"{user['goal']}\"*\n\n"
        f"{get_quote(user['religion'])}"
    ),
    lambda user: (
        f"🌆 Вечереет...\n\n"
        f"{get_quote(user['religion'])}\n\n"
        f"*{user['bot_name']}:* Как прошёл день? Сделал что-то для цели?"
    ),
    lambda user: (
        f"🌙 Итог дня\n\n"
        f"🔥 *{get_streak_label(user['religion'])}: {user['streak']} дней*\n\n"
        f"Огонёк горит! Не дай ему погаснуть — ответь мне сегодня.\n\n"
        f"Что сделал сегодня для своей цели?\n*\"{user['goal']}\"*"
    ),
]

async def scheduled_notification(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    msg_index = job.data.get("msg_index", 5)
    user_id = chat_id

    streak, lost = check_and_update_streak(user_id)
    user = get_user(user_id)

    if not user.get("setup_done"):
        return

    if lost:
        restore_used = user.get("restore_used", False)
        bot_name = user.get("bot_name", "Напарник")
        msg = (
            f"😔 *{bot_name}:* Огонёк погас...\n\n"
            f"Ты не отвечал мне вчера. Но я здесь — я никуда не ушёл.\n\n"
        )
        if not restore_used:
            msg += "💡 У тебя есть *один шанс* восстановить стрик! Нажми 🔥 Мой огонёк."
        else:
            msg += f"Начинаем заново. 🔥 День 1. Ты справишься, я знаю."
        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        return

    try:
        text = SCHEDULED_MESSAGES[msg_index](user)
        milestone = get_milestone_msg(streak, user.get("religion", "neutral"), user.get("bot_name", "Напарник"))
        if milestone:
            text += f"\n\n{milestone}"
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending scheduled message: {e}")

def schedule_daily_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    job_queue = context.application.job_queue
    if job_queue is None:
        logger.error("JobQueue не доступен!")
        return
    for i, send_time in enumerate(SEND_TIMES):
        job_name = f"daily_{chat_id}_{send_time.hour}"
        existing = job_queue.get_jobs_by_name(job_name)
        for job in existing:
            job.schedule_removal()
        job_queue.run_daily(
            scheduled_notification,
            time=send_time,
            chat_id=chat_id,
            name=job_name,
            data={"msg_index": i}
        )

# ========================
# ТЕКСТОВЫЕ СООБЩЕНИЯ
# ========================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user.get("setup_done"):
        await update.message.reply_text("Напиши /start чтобы начать! 😊")
        return

    streak, lost = check_and_update_streak(user_id)

    if text == "🔥 Мой огонёк":
        await show_streak(update, context)
    elif text == "📖 Цитата сейчас":
        await send_quote(update, context)
    elif text == "🎯 Моя цель":
        await my_goal(update, context)
    elif text == "🧠 Поговорить":
        await talk(update, context)
    else:
        bot_name = user.get("bot_name", "Напарник")
        quote = get_quote(user.get("religion", "neutral"))
        await update.message.reply_text(
            f"*{bot_name}:* Слышу тебя. 🤝\n\n{quote}",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Хорошо! 😊", reply_markup=get_main_keyboard())
    return ConversationHandler.END

# ========================
# ЗАПУСК
# ========================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    onboarding = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ENTER_BOT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_bot_name)],
            ENTER_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_goal)],
            CHOOSE_RELIGION: [MessageHandler(
                filters.Regex("^(☪️ Ислам|✝️ Христианство|🌍 Без религии)$"),
                choose_religion
            )],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    surrender_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^😤 Хочу сдаться$"), want_to_surrender)],
        states={
            WAITING_SURRENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_surrender)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    victories_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏆 Мои победы$"), my_victories)],
        states={
            WAITING_RESULT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_result)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    restore_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔥 Мой огонёк$"), restore_streak_ask)],
        states={
            WAITING_RESTORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_restore)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    price_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💹 Цена монеты$"), price_command)],
        states={
            WAITING_PRICE_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_symbol)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(onboarding)
    app.add_handler(surrender_handler)
    app.add_handler(victories_handler)
    app.add_handler(restore_handler)
    app.add_handler(price_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
