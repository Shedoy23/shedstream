# -*- coding: utf-8 -*-
"""Новый стример ждёт одобрения -> личка владельцу со ссылкой «одобрить» (30.09.2026).

Свойства:
  1. ссылка одобряет ровно свой канал: чужой номер или испорченная подпись — 403, база не тронута;
  2. без ADMIN_PASSWORD ссылки нет вовсе (нечем подписать — не выдаём неподписанную);
  3. ник экранируется в HTML сообщения, проверяющий Twitch помечен;
  4. одно сообщение на канал: повторный вход стримера не спамит.

Запуск:  python tests/test_pending_streamer_notify.py
"""
import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.chdir(pathlib.Path(__file__).resolve().parent.parent)
for _k, _v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"), ("TWITCH_CLIENT_SECRET", "x"),
               ("TWITCH_BOT_ID", "x"), ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_k, _v)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    passed, failed = (passed + 1, failed) if cond else (passed, failed + 1)
    print(("  OK   " if cond else "  FAIL ") + msg)


async def main():
    os.environ["ADMIN_PASSWORD"] = "test-admin-secret"
    import notifications
    import routes.admin as admin

    approved = []

    async def fake_set(channel_id, value):
        approved.append((channel_id, value))
        return channel_id in (260813553, 111)
    admin.set_channel_approval = fake_set

    url = admin.approve_link_url(260813553)
    check(url and url.startswith("https://shedoy23.ru/api/admin/approve-link?c=260813553&t="), "ссылка ведёт на одобрение этого канала")
    token = url.split("t=")[1]

    r = await admin.admin_approve_link(c=111, t=token)
    check(r.status_code == 403 and approved == [], "подпись одного канала не одобряет другой")
    r = await admin.admin_approve_link(c=260813553, t=token[:-1] + ("0" if token[-1] != "0" else "1"))
    check(r.status_code == 403 and approved == [], "испорченная подпись — 403, база не тронута")
    r = await admin.admin_approve_link(c=260813553, t="")
    check(r.status_code == 403 and approved == [], "без подписи — 403")
    r = await admin.admin_approve_link(c=260813553, t=token)
    check(r.status_code == 200 and approved == [(260813553, True)], "верная ссылка одобряет ровно свой канал")

    os.environ["ADMIN_PASSWORD"] = ""
    check(admin.approve_link_url(1) is None, "без ADMIN_PASSWORD ссылки нет — неподписанную не выдаём")
    r = await admin.admin_approve_link(c=1, t="")
    check(r.status_code == 403, "без ADMIN_PASSWORD пустая подпись не проходит")

    text = notifications.owner_message("qa_<b>x", 260813553, "https://s/a?c=1&t=2")
    check("qa_&lt;b&gt;x" in text and "<b>x" not in text.replace("<b>Новый", ""), "ник экранирован в HTML сообщения")
    check("проверяющего Twitch" in text, "логин qa_* помечен как вероятный проверяющий")
    check('href="https://s/a?c=1&amp;t=2"' in text, "ссылка одобрения в сообщении (амперсанд экранирован)")

    sent = []

    async def fake_post(token_, chat, text_):
        sent.append((chat, text_))
        return True
    notifications._post_telegram = fake_post
    os.environ["TELEGRAM_BOT_TOKEN"] = "bot"
    os.environ.pop("TELEGRAM_OWNER_CHAT_ID", None)
    check(await notifications.notify_owner_new_streamer("a", 5, None) is False and not sent,
          "без TELEGRAM_OWNER_CHAT_ID не пишем никуда (и не в канал анонсов)")
    os.environ["TELEGRAM_OWNER_CHAT_ID"] = "4242"
    await notifications.notify_owner_new_streamer("a", 5, None)
    await notifications.notify_owner_new_streamer("a", 5, None)
    await notifications.notify_owner_new_streamer("b", 6, None)
    check([c for c, _ in sent] == ["4242", "4242"], "одно сообщение на канал, адресат — личка владельца")

    print("\n%d OK, %d FAIL" % (passed, failed))
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
