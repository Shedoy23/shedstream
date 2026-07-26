# -*- coding: utf-8 -*-
"""fake-mod.py — программа, которая притворяется игровым модом.

ЗАЧЕМ. У RimWorld-модуля нет способа себя проверить: чтобы убедиться, что фикс
работает, надо запустить игру и поиграть. Владелец в RimWorld не играет, поэтому
модуль полтора месяца тихо расходился с реальностью (брошенная миграция M1 —
именно такой случай). Эта программа заменяет игру на время проверки: она
подключается к бэкенду ровно так же, как настоящий мод, — тот же Module API,
тот же токен, те же события и подтверждения.

ЧТО УМЕЕТ, ЧЕГО НЕ УМЕЕТ ЖИВАЯ ИГРА:
  * отказаться выполнять команду (проверка авто-рефанда),
  * исчезнуть посреди команды (проверка «зависших» команд),
  * подтвердить одну команду дважды (проверка идемпотентности),
  * ответить не сразу (проверка таймаутов).
Всё это в живой игре не воспроизвести по заказу.

ЭТО ИНСТРУМЕНТ РАЗРАБОТКИ. По умолчанию ходит на localhost. Чтобы направить его
на прод, надо явно передать --url И --i-know-this-is-prod: случайный запуск
против боевого бэкенда добавит настоящим зрителям настоящих событий.

ПРИМЕРЫ
  # обычная жизнь мода: слушать команды и выполнять их
  python scripts/fake-mod.py --token <токен> --channel 98319857

  # всё отклонять — проверяем, что деньги возвращаются
  python scripts/fake-mod.py --token <токен> --channel 98319857 --refuse-all

  # отправить событие и выйти
  python scripts/fake-mod.py --token <токен> --channel 98319857 \
      --send-event player.state_update --event-data '{"username":"tester"}'

ТОКЕН берётся на бэкенде:
  python -c "import sys; sys.path.insert(0,'.'); from routes.streamer import issue_module_token; print(issue_module_token(98319857,'rimworld'))"
(запускать из Расширение/backend)
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:8000"


def _say(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


class FakeMod:
    def __init__(self, base_url, module_id, channel_id, token, timeout=40):
        self.base = base_url.rstrip("/")
        self.module = module_id
        self.channel = int(channel_id)
        self.token = token
        self.timeout = timeout
        self.cursor = 0

    # ── транспорт ────────────────────────────────────────────────────────────
    def _call(self, method, path, body=None):
        url = "%s%s" % (self.base, path)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer %s" % self.token)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw[:400]}
        except urllib.error.URLError as e:
            return 0, {"error": "не достучался до %s: %s" % (url, e.reason)}

    # ── что делает настоящий мод ────────────────────────────────────────────
    def hello(self):
        code, body = self._call("POST", "/v1/module/%s/hello" % self.module,
                                {"channel_id": self.channel, "version": "fake-1.0"})
        _say("hello -> %s %s" % (code, json.dumps(body, ensure_ascii=False)[:200]))
        return code == 200

    def send_event(self, etype, data=None, kind="event"):
        env = {
            "id": "fake-%s" % uuid.uuid4().hex[:12],
            "kind": kind,
            "type": etype,
            "ts": int(time.time()),
            "data": data or {},
        }
        code, body = self._call("POST", "/v1/module/%s/events" % self.module,
                                {"channel_id": self.channel, "envelopes": [env]})
        acks = body.get("acks") or []
        ok = bool(acks) and acks[0].get("success")
        if code != 200:
            _say("событие %-28s ОТКАЗ HTTP %s: %s" % (etype, code, body))
        elif ok:
            _say("событие %-28s принято" % etype)
        else:
            err = (acks[0].get("error") if acks else "нет ack")
            # Самый частый случай: тип не объявлен в manifest.yaml -> бэк молча
            # выбрасывает. Именно этот класс дважды жил в проде незамеченным.
            _say("событие %-28s ОТВЕРГНУТО: %s" % (etype, err))
        return ok

    def poll_actions(self):
        code, body = self._call(
            "GET", "/v1/module/%s/actions?since=%d" % (self.module, self.cursor))
        if code != 200:
            _say("опрос команд -> HTTP %s %s" % (code, body))
            return []
        actions = body.get("actions") or []
        if body.get("cursor"):
            self.cursor = max(self.cursor, int(body["cursor"]))
        return actions

    def ack(self, action_id, success=True, error=None):
        payload = {"action_id": action_id, "success": success}
        if error and not success:
            payload["error"] = error
        code, body = self._call("POST", "/v1/module/%s/ack" % self.module, payload)
        _say("  подтвердил %s: %s -> %s" % (
            action_id, "выполнено" if success else "ОТКАЗ (%s)" % error, body))
        return body.get("acked")


def run_loop(mod, refuse_all=False, drop_all=False, double_ack=False, once=False):
    """Обычная жизнь мода: длинный опрос -> исполнение -> подтверждение."""
    mode = ("ОТКЛОНЯЮ ВСЁ (проверка рефанда)" if refuse_all else
            "МОЛЧУ (проверка зависших команд)" if drop_all else
            "подтверждаю ДВАЖДЫ (проверка идемпотентности)" if double_ack else
            "нормальная работа")
    _say("режим: %s. Ctrl+C чтобы выйти." % mode)
    try:
        while True:
            actions = mod.poll_actions()
            if not actions:
                if once:
                    _say("команд нет — выхожу (--once)")
                    return 0
                continue
            for a in actions:
                _say("получил команду %s (%s) data=%s"
                     % (a.get("action_id"), a.get("type"),
                        json.dumps(a.get("data"), ensure_ascii=False)[:160]))
                if drop_all:
                    _say("  ...и молча её теряю")
                    continue
                if refuse_all:
                    mod.ack(a["action_id"], False, "fake-mod: отказ по требованию")
                else:
                    mod.ack(a["action_id"], True)
                    if double_ack:
                        mod.ack(a["action_id"], True)
            if once:
                return 0
    except KeyboardInterrupt:
        _say("остановлен")
        return 0


def main():
    p = argparse.ArgumentParser(description="Притворяется игровым модом (Module API).")
    p.add_argument("--url", default=DEFAULT_URL, help="адрес бэкенда (по умолчанию локальный)")
    p.add_argument("--module", default="rimworld", help="rimworld / bannerlord / shedcolony")
    p.add_argument("--channel", required=True, type=int)
    p.add_argument("--token", required=True, help="module-token")
    p.add_argument("--i-know-this-is-prod", action="store_true",
                   help="разрешить не-локальный адрес (иначе отказ)")
    p.add_argument("--send-event", help="отправить одно событие и выйти")
    p.add_argument("--event-data", default="{}", help="JSON-данные события")
    p.add_argument("--refuse-all", action="store_true", help="отклонять все команды")
    p.add_argument("--drop-all", action="store_true", help="молча терять команды")
    p.add_argument("--double-ack", action="store_true", help="подтверждать дважды")
    p.add_argument("--once", action="store_true", help="один проход и выход")
    args = p.parse_args()

    local = any(h in args.url for h in ("127.0.0.1", "localhost", "::1"))
    if not local and not args.i_know_this_is_prod:
        print("ОТКАЗ: %s — не локальный адрес." % args.url)
        print("Этот инструмент пишет НАСТОЯЩИЕ события в базу. Если правда нужен")
        print("не-локальный бэкенд, добавь --i-know-this-is-prod.")
        return 2

    mod = FakeMod(args.url, args.module, args.channel, args.token)
    _say("притворяюсь модом '%s' канала %d на %s" % (args.module, args.channel, args.url))

    if not mod.hello():
        _say("hello не прошёл — дальше идти смысла нет (проверь токен и что бэк запущен)")
        return 1

    if args.send_event:
        try:
            data = json.loads(args.event_data)
        except ValueError as e:
            print("--event-data не разобрался как JSON: %s" % e)
            return 2
        return 0 if mod.send_event(args.send_event, data) else 1

    return run_loop(mod, args.refuse_all, args.drop_all, args.double_ack, args.once)


if __name__ == "__main__":
    sys.exit(main())
