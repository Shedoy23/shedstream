# Production Manager backend deploy — 2026-08-16

## Результат

Manager API и migrations M109–M112 развёрнуты на production штатным backend
deploy. Сервис и публичный сайт остались доступны. Следующий блокер находится
не на сервере: нужен реальный запуск Manager + RimWorld для полного
`Technical Ready`.

## До изменения

- `twitchbot` был `RUNNING`, `/health` возвращал `200`, `db=ok`;
- свежих backend errors не было;
- Twitch channel token прошёл проверку;
- игра и стрим были выключены, поэтому preflight game-mod gate ожидаемо был
  красным;
- `/v1/module/rimworld/auth-check` возвращал `404`;
- M109–M112 отсутствовали в production migration ledger.

## Точки восстановления

- production DB backup:
  `/root/twitch-extension/backups/viewers.predeploy.20260816T130936Z.db.zst`;
- локальная offsite-копия:
  `C:\Users\Edward\shedstream-backups\viewers.predeploy.20260816T130936Z.db.zst`;
- SHA-256 обеих копий:
  `dce2cadced97ba779cfc46a29f9786ed7b21c0d19a0de325022332e31ab73a52`;
- архив предыдущего backend/frontend/admin:
  `/root/deploy-backups/twitch-extension.pre-manager.20260816T1320Z.tar.zst`;
- SHA-256 архива кода:
  `bf31c281d8c430e2783f4ecceeeab47d95087397e0f062285b56d0593c0d9bff`;
- backup production env:
  `/root/twitch-extension/backend/.env.pre-manager.20260816T1320Z`.

DB backup был скачан и реально восстановлен локально: размер распакованной базы
`86,130,688` bytes, `integrity_check=ok`, обязательные таблицы читаются.

## Изменение

- создан отдельный `MANAGER_CREDENTIAL_PEPPER` длиной более 32 символов; значение
  не выводилось и не сохранялось в repository;
- развернут только backend, без изменения Twitch CDN release;
- deploy gate: 107 critical tenant/security checks, failures `0`;
- зависимости синхронизированы до перезапуска;
- M109, M110, M111 и M112 применились при startup.

## После изменения

- `twitchbot` — `RUNNING`;
- `/health` — `200`, `db=ok`;
- `/`, `/extension.html`, `/overlay.html`, `/privacy.html`, `/terms.html` — `200`;
- immutable release `/releases/RimLink-0.1.1.zip` — `200`;
- unauthenticated RimWorld `auth-check` — ожидаемый `401`, не `404`;
- Manager pairing API создал тестовую pending-запись через HTTPS, подтвердив
  загрузку pepper и запись в DB; тестовая запись удалена, итоговый count `0`;
- DB `quick_check=ok`;
- все четыре migration ledger entries и пять требуемых таблиц присутствуют;
- `negative_viewer_points=0`;
- `module_actions`: только terminal `acked=8088`, `failed=1226`, pending нет;
- Manager pairings/sessions/credentials/diagnostics после проверки пусты.

## Что ещё требует ручной проверки

Открыть актуальный EXE, пройти Twitch pairing, установить RimLink в найденную
RimWorld, затем запустить игру. Успех — Manager видит свежий heartbeat и получает
ACK безопасного diagnostic action. Это одновременно закроет signed-install
проверку на реальной машине и оставшийся live-gate.
