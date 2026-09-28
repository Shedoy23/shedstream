# Twitch Compliance — shedcolony expansion (весь каталог действий)

**Дата:** 2026-07-03 · **Вердикт:** ✅ **ALLOWED_WITH_CONDITIONS** · **Confidence:** HIGH
**Метод:** live-fetch Channel Points AUP + Extensions Guidelines §5/§7 + Community Guidelines, адверсарная проверка (4 агента). Покрывает существующие + планируемые (Фазы A-E) действия shedcolony.

## Чисто (строить свободно)
Вся **детерминированная** механика: уход (feed/heal/cure/mourn/happiness), прокачка (xp/skill/job/home), реквесты (fulfill/deliver), гир (armor/weapon/shield/tool/guard-buffs), colony-wide (festival/visitor/quest/spy/recruitment), склад (donate/stock/min_stock/backlog), развитие (start/finish research), стройка (upgrade/repair/toggles), кастомизация без free-text (give_item/gender/teleport/skin).
**Почему:** фикс-цена → фикс-именованный результат, **ноль рандома** → удовлетворяет anti-gambling AUP напрямую (не нужен §5.3 disclosed-odds, т.к. нечего раскрывать). One-directional spend, без payout/transfer/cash-out. Refund-on-fail — НЕ нарушение (добровольный возврат той же внутр. валюты при недоставке ≠ cash-out). Ни одно действие не в запрещённых категориях.

## 🔴 ОБЯЗАТЕЛЬНО до запуска (must-have)
1. **Два free-text действия — блокер по Extension Guidelines §7 (UGC), пока не построена модерация:**
   - `colonist.shout` (реплика над колонистом) и `prestige` (название/титул здания или колониста; и legacy `rename`).
   - §7 требует **структурно**: (7.1) сабмит гейтится доступом к Twitch ID зрителя; (7.3) **показ Twitch-ника автора** рядом с текстом (в расширении + в игре); (7.2) стример может **review/reject/approve**; (7.4) стример может **удалить** опубликованный контент.
   - Профанити-фильтр — good practice, но **НЕ заменяет** контрол стримера (7.2/7.4). Название здания хуже реплики (standing-артефакт, виден долго) → нужен реальный delete/reset у стримера (дашборд — `routes/streamer.py`).
   - **Решение (реком.): отложить оба free-text действия** (они в Фазе E, низкий приоритет) до отдельного захода «UGC-модерация» — не строить ради 2 косметик целую модерационную подсистему. Остальной каталог от них не зависит.
2. **Capacity-disclosure (AUP scarcity):** для действий с конечным ресурсом (assign_job/assign_home/start_research-single-slot/любой single-slot colony) показывать **живой остаток слотов** и **гасить кнопку при нуле**, не полагаться только на accept-then-refund. (Частично уже есть: `ShedReporter`→`/capacity`→фронт серит недоступное; распространить на новые single-slot действия.)
3. **Code-verify детерминизма** для `colony.quest_unlock` и `colony.spy_boost` (самые loot-box-похожие имена) — подтвердить в коде, что нет скрытого RNG при выборе награды/квеста; иначе → детерминизировать или §5.3. Аналогично gear-тиры — фикс-цена→фикс-тир, без ролла.

## Nice-to-have
Профанити-фильтр на free-text (в дополнение к §7-контролу); length-cap + per-viewer cooldown на реплику (анти-спам); аудит-лог (кто/когда назвал здание) для откатов.

## Итог
Каталог compliant при 3 условиях. Практически: строим Фазы 0/A/C/D/B **свободно**; два free-text действия Фазы E — **отложены** до §7-модерации (или дропнуть). Источники fetched 2026-07-03.
