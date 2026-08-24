# Отказ ревью Twitch по 0.0.2 (2026-08-24) — что пришло, что проверено, что дальше

## Что пришло

Версия `0.0.2` переведена в **Pending Approval**. Две причины:

1. **3.5 — мобильная оболочка.** «The Mobile view of your Extension contains
   content that exceeds Twitch's minimum App Store age rating (13+). Games with
   gambling orientation are not allowed for mobile due to legal age
   restrictions.»
2. **QA.** «Due to the nature of your Extension, it must be resubmitted using
   the "Streamer Allowlist" feature» — вкладка **Access** в Developer Console.

Правило 3.5 в доке Twitch звучит как «Mobile Extensions must be compliant with
section 4.7 of the Apple Review Guidelines» — то есть планка возрастного
рейтинга магазина, а не отдельный список запрещённых механик. Поэтому решает
не наша внутренняя правда, а то, как поверхность ЧИТАЕТСЯ.

## Что показывает мобильная оболочка (проверено по `mobile.html`)

Раздел «🎮 Игры»: **Крестики** (❌⭕), **Кубики** (🎲, «2d6 · бот/PvP»),
**Дуэли** (⚔️). Раздел «🎁 Награды»: **Кейсы** (🎁) и квесты.

## Что проверено в коде ПЕРЕД письмом (важно: письмо платформе не должно

содержать ни одного непроверенного утверждения)

| Утверждение | Проверка | Итог |
|---|---|---|
| Ставок за матч нет | `routes/dice.py`, `duel.py`, `tictactoe.py` — списаний перед матчем нет | верно |
| Выплата не за исход матча | `PRIZES = {1: 300_000, 2: 200_000, 3: 100_000}` выдаются при ротации сезона по месту в рейтинге | верно |
| Порог рейтинга | `PRIZE_ELO_GATE = 1100` во всех трёх играх | верно |
| Крустики нельзя купить/передать/вывести | `/api/points/transfer` и `/api/donate` удалены 2026-05-10 (`routes/misc.py`); платёжных интеграций нет | верно |
| Кейсы бесплатны, содержимое фиксировано тиром | `config.CASE_TIER_REWARDS`, случайность только в тире дропа, шансы раскрыты в оболочке | верно |

**Первая редакция письма была неверной.** В ней стояло «no payout tied to the
outcome» без оговорки: `dice.py:295` действительно вызывает `add_points_tx`, и
если бы платформа проверила, мы бы выглядели как те, кто скрывает выплату.
Выплата есть — но сезонная и по рейтингу. Формулировка исправлена до отправки.

## Письмо (черновик, отправляет владелец)

> Subject: Re: Extension Review — clarification on 3.5 (Mobile view)
>
> Hello,
>
> Thank you for the review. We would like to fix this on the first attempt, so
> could you confirm what exactly was flagged in the Mobile view?
>
> For context, none of the mini-games in our Extension involve wagering:
>
> - There is no entry cost and no stake. Playing is free.
> - No game pays out for the result of an individual match.
> - The only payouts are seasonal leaderboard prizes: when a two-week season
>   ends, the top three players by ELO rating receive internal points
>   (rating gate: ELO 1100 or higher).
> - The internal points cannot be purchased, transferred between users, or
>   cashed out. They are earned by watching the stream and participating.
> - Cases are always free and are granted by quests, streaks and watch time.
>   The contents of a case are fixed by its tier; the only random element is
>   which tier drops, and those odds are disclosed inside the Extension.
>
> The Mobile view currently offers: tic-tac-toe, dice (2d6), a
> rock-paper-scissors duel, and cases.
>
> Could you please confirm:
>
> 1. Which of these elements must be removed from the Mobile view?
> 2. Is the concern the mechanics (an outcome decided by chance) or the
>    presentation (dice imagery, the "case" framing)? If the presentation is
>    the issue, we would rather redesign it than remove the feature.
> 3. Is it sufficient to remove the flagged elements from the Mobile view while
>    keeping them in the desktop panel, or must they be removed from the
>    Extension entirely?
>
> We will resubmit using the Streamer Allowlist on the Access tab, as instructed.
>
> Thank you,
> Edward — ShedLink

## Два пути, пока ответа нет

**A. Ждать ответ, потом резать точно.** Плюс: не теряем механики зря. Минус:
цикл ревью — дни, а мы уже в очереди.

**B. Срезать консервативно сейчас** — из мобильной оболочки убрать кубики,
дуэли и кейсы, оставить крестики (игра на умение) и всё несоревновательное;
десктоп не трогать. Плюс: подача сразу. Минус: возможно, режем лишнее — если
претензия была только к кубикам, мобильные зрители теряют две механики зря.

Рекомендация: **письмо + подготовленная правка B в ветке.** Ответ определит,
что именно выкатывать; работа не простаивает, но и не режем вслепую.

## Что делает владелец руками

1. Отправить письмо (ответом на письмо ревью — они сами это предложили).
2. Developer Console → вкладка **Access** → включить **Streamer Allowlist**.
   Важно: список после одобрения меняется только через повторное ревью
   (`TWITCH_UPDATE_RELEASE_PLAYBOOK.md`, Грабля №1) — вносить всех, кто нужен
   на ближайшее время, сразу.

## Что НЕ делаем

- Не снимаем `$FrontendReviewOpen`: версия по-прежнему в ревью (Pending
  Approval — не отказ насовсем и не одобрение). Деплой фронта остаётся закрыт.
- Не правим сведения версии в консоли до решения: любая правка после Hosted
  Test отбрасывает в Local Test и сбрасывает место в очереди (Грабля №3).
