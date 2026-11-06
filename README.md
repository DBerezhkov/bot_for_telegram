# bot_for_telegram

Архив личных переписок Telegram: userbot на Telethon сохраняет все сообщения
из личек в SQLite и присылает в «Избранное» удалённые и изменённые собеседником
сообщения.

## Запуск

1. Получить `api_id` и `api_hash` на https://my.telegram.org/apps.
2. `cp .env.example .env` и вписать ключи.
3. Первый вход (спросит телефон и код) - в обычном терминале:
   ```
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/python3 bot.py
   ```
4. Удалённые сообщения в терминале: `.venv/bin/python3 bot.py --deleted 20`.

## Docker

Данные (сессия, база, медиа) лежат в `./data`:
```
mkdir -p data && cp session.session archive.db data/   # если вход уже был
docker compose up -d --build
```

`session.session` и `.env` дают полный доступ к аккаунту - не коммитить и не передавать.
Удаления, случившиеся пока бот выключен, и сообщения, которых нет в базе, восстановить нельзя.

## Railway

Терминала для входа по коду там нет, поэтому сессия передаётся строкой:
1. Локально (бот при этом должен быть остановлен):
   ```
   .venv/bin/python3 -c "from telethon.sync import TelegramClient; from telethon.sessions import StringSession; import os; from dotenv import load_dotenv; load_dotenv(); c = TelegramClient('session', int(os.environ['API_ID']), os.environ['API_HASH']); c.connect(); print(StringSession.save(c.session))"
   ```
2. В Railway: переменные `API_ID`, `API_HASH`, `TG_SESSION` (строка из п.1) и volume с mount path `/data` - иначе база теряется при каждом редеплое.
3. Одна сессия - один запущенный бот: локально и в Railway одновременно не запускать, Telegram отзовёт сессию (`AUTH_KEY_DUPLICATED`).
