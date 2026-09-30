"""01.10: отказ Twitch в закрытом чате виден в логе (случай проверяющего qa_moderation).

Запуск:  python tests/test_chat_refusal_notice.py
"""
import logging
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
for k, v in (("TWITCH_OAUTH_TOKEN", "oauth:x"), ("TWITCH_CLIENT_ID", "x"), ("TWITCH_CLIENT_SECRET", "x"),
             ("TWITCH_BOT_ID", "x"), ("TWITCH_CHANNEL_NAME", "x"), ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(k, v)

import main  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    passed, failed = (passed + 1, failed) if cond else (passed, failed + 1)
    print(("  OK   " if cond else "  FAIL ") + msg)


warnings = []


class Catch(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            warnings.append(record.getMessage())


main.logger.addHandler(Catch())

FOLLOWERS = ("@msg-id=msg_followersonly :tmi.twitch.tv NOTICE #qa_moderation "
             ":This room is in 10 minutes followers-only mode. Follow qa_moderation to join the community!")
key = main._note_chat_refusal(FOLLOWERS)
check(key == ("qa_moderation", "msg_followersonly"), "отказ «только фолловеры» распознан: канал и причина")
check(len(warnings) == 1 and "qa_moderation" in warnings[0] and "/mod shedoyrobot" in warnings[0],
      "в логе предупреждение с каналом и подсказкой, что делать")
main._note_chat_refusal(FOLLOWERS)
check(len(warnings) == 1, "повтор в течение часа не спамит лог")
check(main._note_chat_refusal("@msg-id=msg_subsonly :tmi.twitch.tv NOTICE #other :subs only") == ("other", "msg_subsonly"),
      "другой канал и причина — отдельное предупреждение")
check(len(warnings) == 2, "второе предупреждение записано")
check(main._note_chat_refusal("@msg-id=host_on :tmi.twitch.tv NOTICE #x :Now hosting") is None,
      "служебный NOTICE не про отказ — игнорируется")
check(main._note_chat_refusal(":tmi.twitch.tv NOTICE * :Login authentication failed") is None,
      "NOTICE без тегов и канала — не падает, игнорируется")
print("\n%d OK, %d FAIL" % (passed, failed))
sys.exit(0 if failed == 0 else 1)
