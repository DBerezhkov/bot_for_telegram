"""Новый вход в Telegram для Railway: спросит телефон, код и 2FA,
сохранит строку сессии в ~/.railway/tg_session.txt (на экран не выводит)."""
import os

from dotenv import load_dotenv
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
c = TelegramClient(StringSession(), int(os.environ["API_ID"]), os.environ["API_HASH"])
c.start()
path = os.path.expanduser("~/.railway/tg_session.txt")
with open(path, "w") as f:
    f.write(c.session.save())
os.chmod(path, 0o600)
c.disconnect()
print("ok")
