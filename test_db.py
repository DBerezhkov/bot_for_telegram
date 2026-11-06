import bot

def row(chat_id, msg_id, is_channel=0, out=0, text="hi"):
    return dict(chat_id=chat_id, msg_id=msg_id, is_channel=is_channel, chat_title="c",
                sender_id=1, sender_name="Вася", outgoing=out, date="d", text=text, media_path=None)

db = bot.db_connect(":memory:")
bot.save_message(db, row(100, 5, text="привет"))
bot.save_message(db, row(-1001, 5, is_channel=1, text="канал"))
assert bot.save_edit(db, 100, 5, "привет!") == "привет"
assert bot.save_edit(db, 100, 5, "привет!") is None
# удаление в личке (chat_id неизвестен) не должно задеть канал с тем же msg_id
r = bot.mark_deleted(db, None, [5])
assert [x["chat_id"] for x in r] == [100] and r[0]["text"] == "привет!"
assert bot.mark_deleted(db, None, [5]) == []          # повторно не шлём
r = bot.mark_deleted(db, -1001, [5])
assert [x["text"] for x in r] == ["канал"]
print(bot.format_report("🗑 Сообщение удалено", r[0]))
print("OK")
