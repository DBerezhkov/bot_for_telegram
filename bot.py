"""Архив своего Telegram-аккаунта: сохраняет все сообщения в SQLite,
ловит удаления и правки и присылает их тебе в «Избранное».

Запуск:
    python3 bot.py               # загрузить историю личек и слушать в реальном времени
    python3 bot.py --deleted 20  # показать последние 20 удалённых сообщений из базы

Работает только с личками: группы и каналы не сохраняются.
"""
import argparse
import asyncio
import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.sessions import StringSession

load_dotenv()
# всё, что нельзя терять и отдавать (сессия, база, медиа), - в DATA_DIR
BASE = os.getenv("DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(BASE, exist_ok=True)
DB_PATH = os.path.join(BASE, "archive.db")
# сколько старых сообщений из каждой лички выкачать при первом запуске
PRIVATE_HISTORY = int(os.getenv("PRIVATE_HISTORY", "5000"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    chat_id     INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    is_channel  INTEGER NOT NULL,   -- 1: канал/супергруппа (id сообщений свои в каждом чате)
    chat_title  TEXT,
    sender_id   INTEGER,
    sender_name TEXT,
    outgoing    INTEGER NOT NULL,
    date        TEXT,
    text        TEXT,
    media_path  TEXT,
    deleted_at  TEXT,
    PRIMARY KEY (chat_id, msg_id)
);
CREATE TABLE IF NOT EXISTS backfilled (chat_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS edits (
    chat_id  INTEGER NOT NULL,
    msg_id   INTEGER NOT NULL,
    edited_at TEXT,
    old_text TEXT
);
"""


def db_connect(path=DB_PATH):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_message(db, row):
    db.execute(
        """INSERT INTO messages (chat_id, msg_id, is_channel, chat_title, sender_id,
               sender_name, outgoing, date, text, media_path)
           VALUES (:chat_id, :msg_id, :is_channel, :chat_title, :sender_id,
               :sender_name, :outgoing, :date, :text, :media_path)
           ON CONFLICT(chat_id, msg_id) DO UPDATE SET
               text = excluded.text,
               media_path = COALESCE(excluded.media_path, messages.media_path)""",
        row,
    )
    db.commit()


def save_edit(db, chat_id, msg_id, new_text):
    """Сохраняет старый текст в историю правок. Возвращает старый текст или None."""
    old = db.execute(
        "SELECT text FROM messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)
    ).fetchone()
    if old is None or old["text"] == new_text:
        return None
    db.execute(
        "INSERT INTO edits VALUES (?, ?, ?, ?)", (chat_id, msg_id, now(), old["text"])
    )
    db.execute(
        "UPDATE messages SET text=? WHERE chat_id=? AND msg_id=?",
        (new_text, chat_id, msg_id),
    )
    db.commit()
    return old["text"]


def mark_deleted(db, chat_id, msg_ids):
    """Помечает сообщения удалёнными и возвращает их строки.

    В личках и обычных группах Telegram не сообщает chat_id удаления, но там id
    сообщений уникальны на весь аккаунт - ищем среди не-каналов.
    """
    marks = ",".join("?" * len(msg_ids))
    if chat_id is None:
        where, args = f"is_channel=0 AND msg_id IN ({marks})", list(msg_ids)
    else:
        where, args = f"chat_id=? AND msg_id IN ({marks})", [chat_id, *msg_ids]
    rows = db.execute(
        f"SELECT * FROM messages WHERE deleted_at IS NULL AND {where}", args
    ).fetchall()
    db.execute(f"UPDATE messages SET deleted_at=? WHERE {where}", [now(), *args])
    db.commit()
    return rows


async def message_row(msg):
    """Только текст: картинки, видео и прочие медиа не скачиваются."""
    chat = await msg.get_chat()
    sender = await msg.get_sender()
    return {
        "chat_id": msg.chat_id,
        "msg_id": msg.id,
        "is_channel": int(msg.is_channel),
        "chat_title": utils.get_display_name(chat) if chat else None,
        "sender_id": msg.sender_id,
        "sender_name": utils.get_display_name(sender) if sender else None,
        "outgoing": int(msg.out),
        "date": msg.date.isoformat() if msg.date else None,
        "text": msg.raw_text or "",
        "media_path": None,
    }


def format_report(title, row, extra=""):
    chat = row["chat_title"] or row["chat_id"]
    who = row["sender_name"] or row["sender_id"]
    head = f"{title}\nЧат: {chat}\nОт: {who}\nОтправлено: {row['date']}"
    return f"{head}\n{extra}\n\n{row['text'] or '(без текста)'}".strip()


async def notify(client, text, file=None):
    if file and os.path.exists(file):
        await client.send_file("me", file, caption=text[:1000])
        if len(text) > 1000:
            await client.send_message("me", text)
    else:
        for i in range(0, len(text), 4000):
            await client.send_message("me", text[i:i + 4000])


async def backfill(client, db, me_id, limit):
    """Выкачивает историю личек. Чат, чья история уже загружена целиком, -
    только то, что новее последнего сохранённого (пришло, пока бот был выключен)."""
    async for dialog in client.iter_dialogs():
        if dialog.id == me_id or not dialog.is_user:
            continue
        done = db.execute("SELECT 1 FROM backfilled WHERE chat_id=?", (dialog.id,)).fetchone()
        last = done and db.execute(
            "SELECT MAX(msg_id) FROM messages WHERE chat_id=?", (dialog.id,)
        ).fetchone()[0]
        n = 0
        async for msg in client.iter_messages(dialog, limit=None if last else limit,
                                              min_id=last or 0):
            save_message(db, await message_row(msg))
            n += 1
        db.execute("INSERT OR IGNORE INTO backfilled VALUES (?)", (dialog.id,))
        db.commit()
        if n:
            print(f"история: {dialog.name}: {n}")


async def run():
    # на хостинге (Railway) нет терминала для входа по коду - сессия берётся из
    # переменной TG_SESSION (строка из StringSession), иначе - файл session.session
    session = os.getenv("TG_SESSION")
    client = TelegramClient(
        StringSession(session) if session else os.path.join(BASE, "session"),
        int(os.environ["API_ID"]), os.environ["API_HASH"],
    )
    db = db_connect()
    if session:
        await client.connect()
        if not await client.is_user_authorized():
            raise SystemExit("TG_SESSION недействительна - сгенерируй заново (см. README)")
    else:
        await client.start()
    me = await client.get_me()
    print(f"вошёл как {utils.get_display_name(me)}, слушаю...")

    @client.on(events.NewMessage(func=lambda e: e.is_private))
    async def on_new(event):
        if event.chat_id == me.id:  # своё «Избранное» не архивируем - туда пишут отчёты
            return
        save_message(db, await message_row(event.message))

    @client.on(events.MessageEdited(func=lambda e: e.is_private))
    async def on_edit(event):
        if event.chat_id == me.id:
            return
        msg = event.message
        old = save_edit(db, msg.chat_id, msg.id, msg.raw_text or "")
        if old is None:
            save_message(db, await message_row(msg))
            return
        if not msg.out:
            row = db.execute(
                "SELECT * FROM messages WHERE chat_id=? AND msg_id=?", (msg.chat_id, msg.id)
            ).fetchone()
            await notify(client, format_report("✏️ Сообщение изменено", row,
                                               f"Было:\n{old}\n\nСтало:"))

    @client.on(events.MessageDeleted())
    async def on_delete(event):
        if event.chat_id is not None:  # chat_id приходит только для каналов/супергрупп
            return
        for row in mark_deleted(db, event.chat_id, event.deleted_ids):
            # своё сообщение собеседник тоже может удалить у обоих - присылаем и его
            title = "🗑 Удалено ТВОЁ сообщение" if row["outgoing"] else "🗑 Сообщение удалено"
            await notify(client, format_report(title, row), row["media_path"])

    # история личек - чтобы удаление старых сообщений тоже ловилось
    await backfill(client, db, me.id, PRIVATE_HISTORY)
    print("история загружена")
    await client.run_until_disconnected()


def show_deleted(limit):
    db = db_connect()
    rows = db.execute(
        "SELECT * FROM messages WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    for row in rows:
        print(format_report(f"🗑 удалено {row['deleted_at']}", row), "\n" + "-" * 40)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--deleted", type=int, help="показать N последних удалённых и выйти")
    a = p.parse_args()
    if a.deleted:
        show_deleted(a.deleted)
    else:
        asyncio.run(run())
