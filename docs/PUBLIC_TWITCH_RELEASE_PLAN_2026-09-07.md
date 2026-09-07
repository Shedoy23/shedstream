# ShedLink: план публичного Twitch-релиза

Дата фиксации: 2026-09-07  
Baseline: `a380ad7b72eec79889ae99d7fb5d5886c3aa31d3`  
Рабочая ветка: `codex/public-release-readiness`

## Цель

Провести ближайшую версию Twitch Extension через Hosted Test и Twitch Review,
чтобы после одобрения любой стример мог установить ShedLink без Streamer
Allowlist. Manager и расширение набора игр не являются воротами этого релиза.

## Исходная точка

- На Twitch CDN публично работает `0.0.1`.
- Текущий кандидат — `0.0.5`. Действующий локальный архив:
  `C:\Users\Edward\Desktop\work\dist\shedlink-0.0.5.zip`, SHA-256
  `9200f6c229c17615032f27ef1c1a27ff16fe269203b36f1997ee66fb56204ee6`,
  MD5 `2e891a30588a28a3f85ca87c92c50cdb`.
- В Dev Console `0.0.5` находится в Hosted Test. Загруженный MD5
  `2e891a30588a28a3f85ca87c92c50cdb` совпадает с действующим архивом.
- Последний стрим разобран в `docs/POSTSTREAM_TRIAGE_2026-09-06.md`;
  найденные денежные и session-регрессии исправлены в baseline.
- Streamer Allowlist должен быть пустым при подаче. По документации Twitch
  пустой список означает global availability после одобрения; изменение
  непустого списка требует новой подачи.

## Scope релиза

В релиз входит уже существующая пользовательская поверхность `0.0.5`: общие
механики, Bannerlord, RimWorld и ShedColony, безопасный offline-режим,
словесные причины отказов и возвраты, кейсы с раскрытыми шансами, «Открыть
все», Крестики, Канат, Дуэли, питомцы, квесты, голосование и broadcaster
moderation для TTS.

До решения Twitch не добавляются новые механики и не меняется видимый frontend.
Manager, CK3, billing, marketplace и крупные архитектурные изменения не
блокируют подачу.

## Ворота релиза

### G0 — воспроизводимый кандидат

- [x] Архив существует и совпадает с записанными SHA-256/MD5.
- [x] Содержимое совпадает с зафиксированным frontend; допустима только
      вставленная сборщиком версия.
- [x] В архиве нет секретов, БД, backend-кода, source maps и OBS overlay.
- [x] Desktop и mobile содержат одинаковый набор скриптов и cache-bust.
- [x] Локальные release-gates зелёные, результаты записаны в журнале ниже.

### G1 — обязательные инварианты

- [x] Charge, enqueue и terminal result не оставляют платное действие без
      объяснимого эффекта или ровного возврата.
- [x] Duplicate request, ACK и failure не дают двойное списание, возврат или
      неконтролируемый повтор эффекта.
- [x] Lost ACK, reconnect и restart имеют проверенное поведение.
- [x] Queue, poll, ACK и state изолированы по `channel_id`.
- [x] Нельзя действовать от имени другого зрителя.
- [x] Offline-модуль и неизвестное состояние закрывают покупку безопасно.
- [x] TTS не проигрывает пользовательский текст без решения broadcaster.
- [ ] Fresh-install migrations и восстановление из backup проверяемы.

Автоматический тест или свежий live-артефакт подтверждает каждый пункт.
Отсутствие доказательства означает `не проверено`, а не `работает`.

### G2 — Hosted Test точного CDN-артефакта

Владелец проходит таблицу из
`Расширение/docs/REVIEWER_WALKTHROUGH.md` и записывает дату и результат:

- [ ] Вход через Twitch и первый шаг нового зрителя.
- [ ] Обычная покупка и заведомый отказ с возвратом.
- [ ] «Открыть все» и правильная сумма наград.
- [ ] Двойной клик по соседним кнопкам призыва.
- [ ] Основные шаги в mobile.
- [ ] Блоки о валюте, шансах и правилах видимы и раскрываются.
- [ ] Config view открывается; сохранение настройки проверяет владелец.
- [ ] DevTools не показывает CSP, mixed-content, 404 или uncaught errors.

Свежий постстрим-триаж принимается для игровых пунктов только при совпадении
версий backend/мода и наличии конкретных строк charge → delivery →
result/refund. UI-пункты триажем не закрываются.

### G3 — пакет Review

- [x] В Dev Console загружен действующий архив, его MD5 совпал.
- [x] URL Fetching, Image и Media allowlist содержат только `https://shedoy23.ru/`.
- [x] Streamer Allowlist пуст; Testing Account Allowlist заполнен отдельно.
- [ ] Review channel указан и расширение на нём активируется.
- [ ] В walkthrough указаны игра, окно доступности по UTC и способ связи.
- [ ] Changelog перечисляет именно изменения текущего архива.
- [x] Privacy Policy и Terms отвечают 200; support contact заполнен.
- [ ] Описание валюты, случайности, конкурсов и TTS совпадает с кодом.

### G4 — отправка и заморозка

- [ ] После фактического Submit for Review записаны дата, версия и хеши.
- [ ] В `scripts/deploy.ps1` включён review-lock frontend.
- [ ] Submitted ZIP сохранён неизменяемой копией.
- [ ] Во время Review выходят только обратно совместимые backend/mod fixes,
      не меняющие проверяемое поведение.

### G5 — после Approved

- [ ] Перед Release проверены prod health, backup, версии модов и выключатели.
- [ ] Release выполнен владельцем в наблюдаемое окно.
- [ ] Проверены viewer/config/mobile, бесплатное и платное действие.
- [ ] Новый внешний канал установил расширение без Streamer Allowlist.
- [ ] Проведены первый post-release stream и poststream triage.

## Ближайшая очередь

1. Прогнать локальные release-gates текущего HEAD и архива.
2. Закрыть подтверждённые дефекты G0/G1.
3. Сверить фактический архив и статус `0.0.5` в Dev Console.
4. Пройти ручные пункты Hosted Test по `REVIEWER_WALKTHROUGH.md`.
5. Заполнить review channel и окно доступности игры.
6. Проверить пустой Streamer Allowlist и настройки версии.
7. Зафиксировать финальный пакет и отправить в Review.
8. Включить frontend review-lock до вердикта.
9. После Approved выпустить и проверить внешний канал.

## Журнал доказательств

| Дата | Commit / артефакт | Проверка | Результат | Доказательство |
|---|---|---|---|---|
| 2026-09-07 | `a380ad7` | Архив и Dev Console | PASS | SHA-256 `9200f6c2…`, MD5 `2e891a30…`; 24/24 файлов совпали; Hosted Test |
| 2026-09-07 | `a380ad7` | `pack-extension.py --check` | PASS | 24 файла, 874.1 КБ до сжатия |
| 2026-09-07 | `a380ad7` | `lint_consistency.py` | PASS | одна ожидаемая warning: game assembly недоступна |
| 2026-09-07 | `a380ad7` | money / ACK / delivery / tenant / spoof / offline | PASS | 6 профильных тестов, включая critical tenant 107/107 |
| 2026-09-07 | `a380ad7` | TTS moderation | PASS | `test_tts_approval_gate.py`, `test_tts_moderation.py` |
| 2026-09-07 | `a380ad7` | fresh install / sessions / odds | PASS | 3 профильных теста |
| 2026-09-07 | `a380ad7` | frontend / «Открыть все» / onboarding | PASS | 7 профильных тестов; тест кейсов отвязан от локальной БД |
| 2026-09-07 | `a380ad7` | полный backend test suite | PASS | 83/83 теста, `exit 0` у каждого; 5 тестов отвязаны от локальной `viewers.db` |
| 2026-09-07 | CDN `0.0.5` | Config view | PARTIAL | iframe загрузился штатно; настройка не изменялась |
| 2026-09-07 | production URLs | health / privacy / terms | PASS | HTTP 200 |

## Стоп-условия

Не отправлять версию, если не совпал MD5, не завершён Hosted Test, Streamer
Allowlist непуст, reviewer flow требует скрытой настройки, есть необъяснённое
денежное расхождение или пользовательский контент публикуется без требуемой
модерации.

## Официальные основания Twitch

- Lifecycle и Access: <https://dev.twitch.tv/docs/extensions/life-cycle/#access>
- Guidelines and Policies: <https://dev.twitch.tv/docs/extensions/guidelines-and-policies/>
- Submission Best Practices:
  <https://dev.twitch.tv/docs/extensions/submission-best-practices/>

В кабинете Twitch 07.09 прямо подтверждено: пустой Streamer Allowlist делает
Released-версию доступной всем, а текущая `0.0.5` ещё находится в Hosted Test.
