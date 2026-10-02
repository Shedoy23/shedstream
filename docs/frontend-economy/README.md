# Frontend economic metadata: bounded migration

Local candidate, 2026-10-02. No backend, database, mod, frozen Twitch ZIP,
production or gameplay changes are part of this patch. The first-stage package
at `ede7517` remains separate.

## What this slice changes

Four expensive legacy actions now require validated metadata from the existing
`GET /api/bannerlord/config` response:

| Action | Gold key | Additional crustic key |
|---|---|---|
| `hero.create_clan` | `hero_gold_costs.create_clan` | None: backend own-pricing branch |
| `hero.create_kingdom`, including rebellion | `hero_gold_costs.create_kingdom` | None: backend own-pricing branch |
| `hero.create_vassal_clan` | `hero_gold_costs.create_vassal_clan` | `action_prices["hero.create_vassal_clan"]` |
| `hero.recruit_vassal_clan` | `hero_gold_costs.recruit_vassal` | `action_prices["hero.recruit_vassal_clan"]` |

The last two crustic amounts are currently zero. Missing is distinct from zero;
if the server supplies a nonzero crustic component, it is displayed alongside
gold. Do not require invented `action_prices` entries for the first two actions.

Only finite nonnegative JSON numbers are valid in this strict path. Missing,
null, strings, booleans, negative and nonfinite values disable the relevant
purchase. `_bnrPrice` / `_bnrGold` without a fallback use strict reads; existing
callers that explicitly pass a fallback keep their legacy behaviour.
Unknown gold is formatted as `цена не загружена`, never zero.

The disabled control has a reason and `Обновить цены`. Retry is single-flight
within a lifecycle/token; a new owner can start its own request. A late response
cannot overwrite the new owner. Labels and buttons update in place, preserving
the typed name and heir selector. Click/Enter and the shared Bannerlord action
wrapper recheck the four-action quote. Recruitment confirmation is invalidated
by a locally changed quote, stop, token rotation or unavailable metadata.

This is **not a quote lock**: the server may change its price between the config
GET and action POST. There is no new expected-price/revision protocol. Backend
and mod continue to validate and charge under their existing contracts.

## Cooldowns in this slice

The two diplomacy-vote buttons now use the existing `data-bnr-cd` clock and
`_bnrCdRemaining`, fed by `/action` fields `cooldown_applied_s` and
`cooldown_remaining_s`, and `/my-buffs` entries `{power_key, remaining_s}`.
The old local 300-second copy and unconditional start after failure are removed.

Buff reads are fenced by lifecycle/token, monotonic completed-request order,
and action-cooldown revision. A pre-action GET cannot erase a later action
reply; a genuinely later authoritative poll can clear it. Slow overlapping
polls can still apply completed snapshots. No second countdown clock was added.

## Remaining hardcodes and fallback policy

Inventory below comes from current literal call-site searches, not historical
documentation counts. These are explicit residuals, not claims that their
fallbacks bypass backend charging. Revisit one bounded family at a time.

### Monetary display/purchase risk

1. **Other Bannerlord scalar actions:** 36 literal `_bnrPrice(action, fallback)`
   calls covering 20 keys remain: army creation, eight detachment/attach actions,
   child rename/looks/respec/marriage proposal, vassal rename, party orders,
   enact policy, direct peace, war/peace proposals and ransom. They already
   prefer `action_prices`, but missing/invalid data falls back. The fallback
   accessor still accepts numeric coercion; this patch deliberately changes only
   the no-fallback path used by the four selected actions.
2. **Other Bannerlord gold actions:** nine `_bnrGoldLabel(key, fallback)` calls
   across `marry`, `join_clan`, `join_kingdom`, `create_party`; one direct
   `_bnrGold('marry', 50000)` balance gate. Selected four-action fallbacks have
   been removed from all their live labels/confirmations.
3. **Bannerlord separate fields/tables:** workshop/caravan summary and purchase
   forms, summon sides, reforge, gender/baby, focus/attribute costs, retinue
   tier/elite costs, gear-tier prices, gold/XP presets and tournament prizes
   still use local defaults. Each has an existing `/config` source. Retinue
   price estimates still contain tier-cap mechanics and a default capacity;
   do not silently migrate game rules while moving display metadata.
4. **Core:** `corePrice` fallbacks remain for guild creation (100000 crustics),
   TTS, divorce, voting minima and TTS length. Existing `/api/core/config`
   supplies their server values. Guild minimum contribution currently reuses
   `voting_min_pledge`; this was observed, not changed.
5. **ShedColony:** 33 action entries in `SC` retain fallback prices, including
   75000-crustic minimum-stock/research actions. `/api/shedcolony/config`
   hydrates them from the backend price dictionary. Missing fields keep old
   defaults; catalog fallback lists are a separate game-data problem.
6. **RimWorld:** `rimworldPrice` still falls back for spawn/heal/resurrect and
   trait/gene removal. Static shell prices remain until hydration. The existing
   `/api/rimworld/config` contract is reusable; it does not include heal cooldown.

### Cooldowns, limits and availability

- RimWorld heal success uses `15 * 60` locally. Existing
  `/api/rimworld/heal-cooldown/{username}` returns `cooldown_left`; heal POST
  success currently does not. `startBtnCountdown` decrements a local counter.
- `checkCooldown` callers include short click-throttles (shop, trait/gene,
  duels, promo). Distinguish client debouncing from server gameplay cooldowns
  before replacing constants.
- Existing backend-derived limits still have frontend defaults: workshop cap,
  retinue capacity, rebellion supporters/relations. Children/vassal caps and
  legacy tournament queue/round counts are copied locally. Not all needed
  limit/availability fields currently exist in `/config`; no schema was added.
- New equipment/build paths already consume `can_buy`, `can_manage`, `pending`,
  `reason`, `message` and quoted prices. They were not globally blocked behind
  this legacy config. Backend denial text remains authoritative.
- React tournament pilot validates the existing tournament response, requires
  an explicit zero join price, and refuses missing config. Its free action
  contract was not changed into a paid-entry flow.

### Game catalogs, not economics-only cleanup

Legacy policy/workshop-type arrays, retinue branch-tier assumptions, skill and
power descriptions, and ShedColony item lists remain separate from this patch.
Catalog contents and game facts should come mod → backend → frontend; replacing
them must not invent a competing frontend game model.

## Reproduction and tests

- `node scripts/test-frontend-bannerlord-diplomacy-cooldowns.mjs`
- `node scripts/test-frontend-bannerlord-economic-config.mjs`
- `npm run test:frontend`
- `npm run lint:js`
- `HOME=/tmp/shedlink-test-home /tmp/shedlink-frontend-venv/bin/python scripts/lint_consistency.py`

The tests execute actual renderers, purchase handlers, config/buff loaders and
the shared dispatcher. Price tests were observed failing against `8bef737`;
cooldown regressions were separately committed red before their fixes. Existing
fallback-expecting tests remain valid for nonmigrated callers.
