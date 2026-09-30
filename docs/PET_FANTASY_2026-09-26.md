# Fantasy pets — prepared, catalogue rollout pending

**Superseded delivery instructions:** use [PET_ANIMATIONS_2026-09-26.md](PET_ANIMATIONS_2026-09-26.md)
and the combined pet-walk-fix-20260926 bundle. Signature scenes and corrected walking
are now public in both previews; live catalogue/OBS activation still waits for the stream to end.
The earlier bundle described below has stale preview guards and must not be applied.

Owner approved six fantasy pets, all rare and 500000 crustics each, matching the first collection.

| Variant | Name |
| --- | --- |
| necro_cat | Кот-некромант |
| chest_mimic | Сундук-мимик |
| mushroom_grandpa | Грибной дедушка |
| baker_dragon | Дракончик-пекарь |
| blanket_ghost | Призрак в пледе |
| frog_samurai | Лягушка-самурай |

## Current delivery state

Public preview: https://shedoy23.ru/pet-assets/fantasy-v1/preview.html

**Only the 50 new static preview/asset files are published.** Backend, production catalogue,
OBS integration script and service process are unchanged. Helix reported shedoy23 live;
CLAUDE.md section 7 requires feature deployments after the stream. Do not restart during this stream.
Public health is ok/db ok; catalogue remains the original eight items. No new purchase is available yet.

Source implementation is complete: six generated atlases, six poses per pet (idle, two movement
frames, greeting, sleep, joy), west frame mirrored from east, shared OBS support for both collections,
fixed 500000 price, M130 catalogue migration. This is a six-pose animation, not eight hand-drawn directions.

## Saved art and prompts

Built-in imagegen was used, with the approved concept sheet as identity/style reference and actual alpha.
No CLI fallback. Mechanical crop/scale/packing uses sharp and preserves generated alpha.

- Deliverable frames: `Расширение/frontend/pet-assets/v2/<variant>/{south,east,walk-2,wave,sleep,cheer,west,animation}.png`.
- Public preview source/manifest: `Расширение/frontend/pet-assets/fantasy-v1/`.
- Full prompt set: [PET_FANTASY_PROMPTS_2026-09-26.md](PET_FANTASY_PROMPTS_2026-09-26.md).
- Original copied atlases: `dist/pets-fantasy-20260926/sources/` (local ignored build output).
- Repack specification: `scripts/pet-fantasy-spec.json`.

## Validation

- Red regression test committed before implementation: missing FANTASY_COMPANIONS.
- Real database purchase method tested for every new pet: price, funds, auto-equip, duplicates,
  channel balance isolation, old kimono price and purchase audit.
- Migration is idempotent; first collection rows remain byte-for-byte equal.
- Both collection browser tests passed: walking, turns, sleep, cheer, skin swap and legacy fallback.
- Transparent edges inspected on light background; desktop/mobile preview passed.
- Frozen-client harness and verify-candidate passed. Candidate SHA-256 remains
  `6f8e07f56b7d6a0b4f628a2731d81686a47b77dd8b7cfcc912dd1f8af3f90672`.
- Server staging passed real production-schema migration and purchase tests on a SQLite backup copy.
- SHA-256 of all 50 public static files matched local output; production frozen-file hashes unchanged.
- Public browser preview and frozen pets.js with staged 14-item catalogue data checked separately.
  The latter is a compatibility simulation, not live catalogue activation or a real purchase.

## Finish after the stream

Prepared server bundle: `/root/shedlink-deploy-backups/pets-fantasy-20260926/`.
Backup: its `backup/` directory, including SQLite snapshot and original touched source files.

After verifying the stream is offline, run:

```sh
/root/twitch-extension/venv/bin/python /root/shedlink-deploy-backups/pets-fantasy-20260926/install.py apply
```

The installer checks Helix again, verifies all five source patches still match the staged baseline,
accepts only matching already-published preview assets, installs backend/migration and OBS support,
restarts twitchbot, verifies health, six prices and frozen hashes. It refuses source drift;
if another deployment intervenes, rebuild/rebase the five surgical patches and stage in a fresh directory.
Never replace the full production backend or frontend: unrelated server fixes must be preserved.

After activation: verify public catalogue has all 14 items and all six new prices are 500000,
run both animation browser tests and public hashes, refresh the OBS browser source, then check
a real equipped pet and a user-authorized purchase. Live OBS/purchase remain unverified.

Rollback restores changed source and deprecates only new IDs; it never restores the whole live DB.
`scripts/verify-pet-fantasy-preview.py` deliberately checks the **pre-activation** state and will fail
once catalogue activation happens; use catalogue verification instead after apply.
