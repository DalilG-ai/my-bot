"""
Разовый скрипт: получить строку сессии Telethon, чтобы бот мог читать
публичные каналы под вашим обычным Telegram-аккаунтом.

Запустите ЛОКАЛЬНО (не в проде), интерактивно:
    python telethon_login.py

Понадобятся:
- API_ID и API_HASH — получить на https://my.telegram.org/apps
- Ваш номер телефона и код подтверждения из Telegram (и пароль 2FA, если включён)

Скрипт напечатает строку сессии — сохраните её в переменную окружения
TELEGRAM_SESSION_STRING на сервере, где будет работать бот. Никому её не
передавайте — это равнозначно доступу к вашему аккаунту Telegram.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID (с my.telegram.org): ").strip())
api_hash = input("API_HASH (с my.telegram.org): ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()
    print("\nГотово. Сохраните это значение как TELEGRAM_SESSION_STRING:\n")
    print(session_string)
