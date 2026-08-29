# UX/polish gap audit — ideal 0.0.2

**Автор:** Dwight

**Дата:** 2026-08-28

**Режим:** read-only; frontend frozen; compliance verdicts вне scope.

## Summary

Главный UX-блокер — поздние отказы Bannerlord: обычный paid HTTP path показывает любой новый `result.message`, но async mod refund проходит через frozen JS-словарь и неизвестная причина становится «Действие не удалось». Далее: deferred paid actions не имеют системно обязательного action-specific toast; ряд цен, лимитов и каталогов заморожен во фронте. `extension.html` и `mobile.html` по viewer-facing markup совпадают: diff содержит только комментарии.

## P0 — неизвестная причина позднего отказа теряется

**Evidence:** `frontend/viewer-bannerlord.js:43-47`, `:49-96`, `:97-105`; thin-front rule `CLAUDE.md:161-169`.

`recent_refunds[].reason` проходит через `BNR_REFUSE_REASON_RU`; любой новый code сворачивается в «Действие не удалось» (`:95`). Viewer получает refund, но не понимает причину и повторяет действие. Backend/mod fix нельзя донести без Twitch frontend review.

**Direction:** backend должен отдавать viewer-safe `message`/`reason_text`; frontend показывает его safely, code оставляет для telemetry/fallback. Добавить unknown-reason contract test.

## P1 — deferred paid-action toast не гарантирован контрактом

**Evidence:** `frontend/viewer-actions.js:65-77`, `:119-121`; `frontend/viewer-bannerlord.js:790-810`, `:1950-1954`, `:2537-2563`, `:4774-4783`.

`ShedLink.buyAction()` поддерживает `successMessage`, но `_bannerlordBuyAction()` не прокидывает opts. War/peace/recruit-vassal вручную заменяют generic toast вторым специальным. `hero.create_vassal_clan` явно ждёт engine apply (`setTimeout(..., 2000)`), но не гарантирует «заявка принята, исход позже». Viewer может принять быстрый ACK за применённый результат и нажать снова; replace-style toast даёт нестабильный двойной feedback.

**Direction:** прокинуть opts; backend-declared `pending/deferred` обязан иметь viewer-safe confirmation. Contract test для всех paid+async actions.

## P1 — hardcoded цены/лимиты замораживают ложную витрину

- TTS: `frontend/viewer.js:1231-1235`, `:1244-1265`, `:1285-1300` — `5000💎`, max `200`, локальный disabled.
- RimWorld: `frontend/viewer-rimworld.js:248-257` — remove trait `300💎`; `:387-403` — create pawn `200💎`.
- Marriage proposal: `frontend/viewer-bannerlord.js:3079-3088` — `100💎` в confirm и payload.
- Detachment: `frontend/viewer-bannerlord.js:3170-3227`, `:3233-3240` — `10/30💎` в markup/data/payload.
- Stale fallbacks: `frontend/viewer-bannerlord.js:1252-1257`, `:3603-3604`, `:4286`, `:4420`, `:4525`.

**Viewer impact:** backend-only rebalance оставляет неверный confirm/disable; config failure выглядит как уверенная старая цена.

**Direction:** config/catalog supplies price/limit/availability; без значения показывать «цену уточняем», не authoritative disable. Server enforces.

## P2 — mutable catalog/description заморожен

**Evidence:** `frontend/viewer-bannerlord.js:154-175` (`BNR_POWER_META`), `:1226-1238` (`_BNR_WORKSHOP_TYPES`). `CLAUDE.md:161-166` относит каталоги к server data. Комментарии `:159-166` уже фиксируют прежние stale descriptions.

**Impact:** новый/renamed item показывает raw id или старое описание до review. Backend catalog должен отдавать id, viewer label, plain-text description, availability.

## P2 — локальная формула обещает награду

**Evidence:** `frontend/viewer.js:1372-1394` вычисляет next streak bonus как `(current_streak + 1) * 1000`.

Server formula change оставит неверное обещание. Endpoint должен отдавать `next_reward` и progress target.

## Positive controls

- Unknown ordinary HTTP refusal — PASS: `frontend/viewer-actions.js:112-121` показывает arbitrary `result.message`.
- Overpay barriers — PASS: `viewer-actions.js:32-36`, `:90-101` single-flight + `client_action_id`; `:173-178` refresh balance.
- Known deferred confirmations — PASS with structural debt: war/peace `viewer-bannerlord.js:2537-2563`, recruit-vassal `:4774-4783`.
- Shell parity — PASS: `extension.html` vs `mobile.html` diff is comments only.
- Dynamic catalogs — PASS examples: RimWorld `ev.cost` (`viewer-rimworld.js:160-175`, `:206-235`); Bannerlord `it.price/action_type` (`viewer-bannerlord.js:3356-3420`).

## Recommended order after unfreeze

1. Late-refund viewer-safe reason contract + unknown-reason test.
2. Deferred confirmation in shared paid-action contract.
3. Prices/limits into config/catalog; remove confident stale fallbacks.
4. Mutable labels/descriptions and streak `next_reward` from backend.
5. DOM/script-order parity test for extension/mobile with comments stripped.
