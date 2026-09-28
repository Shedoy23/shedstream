# Pet animations — 26 September 2026

Both collections have six-frame signature scenes (72 new poses total). Eleven walking pets now use the original contact A and a generated opposite contact B; the ghost keeps its existing floating motion. Frames other than B remain identical pixel for pixel in the new base atlases. Side-by-side visual inspection checks the leg alternation separately from automated checks.

## Delivery state

Published and browser-checked:
- https://shedoy23.ru/pet-assets/companions-v1/preview.html
- https://shedoy23.ru/pet-assets/fantasy-v1/preview.html

Both previews provide scenes, individual steps and 4x slow motion. SHA-256 matched for 37 scene/walk/preview files. The combined package published 84 static assets and two previews.

**Live OBS activation and the second collection catalogue remain pending.** Fresh Helix returned shedoy23 live on 26 September. CLAUDE.md section 7 requires feature deployments after the stream. No service restart or production backend/OBS patch was applied. Health and DB are ok; the catalogue still contains eight items. Server frozen frontend and backend/OBS patch hashes remain unchanged.

## Behaviour and art

Each scene lasts 4.2 seconds, using six poses at 0.7 seconds each. In OBS it occurs during a stationary interval on alternate walking cycles (roughly every 3–5 minutes), offset by viewer identity. Initial greetings suppress scenes; reduced motion shows idle; unavailable scene images retain base animation.

| Collection | Scenes |
| --- | --- |
| Companions | Wayfarer map/mug; knight salute/visor; engineer repair; mage sleepy spell; rogue coin trick; fisher boot catch |
| Fantasy | Cat skeletal mouse; mimic coin sneeze; grandpa growing mushroom; dragon burnt bread; ghost tea/blanket; frog meditation/fly |

Built-in image generation created the art. Sharp only crops, scales and packs sprites. All12 remain rare at 500000 each.

- Scene outputs: Расширение/frontend/pet-assets/v2/<id>/scene-v1.png
- Walk outputs: same directories, animation-v2.png and walk-opposite-v2.png (11 pets).
- Original atlases retained for rollback.
- Scene prompts: [PET_SCENES_PROMPTS_2026-09-26.md](PET_SCENES_PROMPTS_2026-09-26.md).
- Walking prompts: [PET_WALK_PROMPTS_2026-09-26.md](PET_WALK_PROMPTS_2026-09-26.md).
- Generated originals copied to dist/pet-scenes-20260926/{sources,walk-sources}/.
- Packaging specs/scripts: scripts/pet-scenes-spec.json, scripts/pet-walk-fix-spec.json, scripts/package-pet-scenes.cjs, scripts/package-pet-walk-fix.cjs.

## Verification

Both browser suites passed scene frames 0–5 in preview and mock OBS, steps 1/2, reduced motion, mobile width, skin replacement and legacy fallback. Every non-target base frame is pixel-identical; each replacement contact differs. Public browser checks loaded both steps and scene atlases and exercised slow motion. These checks do not constitute live OBS or viewer purchase proof.

Server preparation passed both collection purchase tests and idempotent migration against a production-schema SQLite copy, preserving existing inventory and catalogue rows. Frozen candidate verification passed:
6f8e07f56b7d6a0b4f628a2731d81686a47b77dd8b7cfcc912dd1f8af3f90672.

## Continue after the stream

**Use the combined bundle below, superseding pets-fantasy-20260926 and pet-scenes-20260926.** Earlier bundles have stale preview baselines and must not be applied.

Server: /root/shedlink-deploy-backups/pet-walk-fix-20260926/
Local: dist/pet-scenes-20260926/walk-bundle.tar.gz
Backup: server bundle backup/ (source and SQLite snapshot).

After fresh offline verification:
```sh
/root/twitch-extension/venv/bin/python /root/shedlink-deploy-backups/pet-walk-fix-20260926/install.py apply
```

The installer checks Helix again, guards seven source patches and all staged files, activates M130 and the OBS script, and verifies health, fourteen catalogue entries, six new prices and frozen hashes. It refuses drift. On failure it restores touched source and deprecates new catalogue entries rather than replacing the live DB. Refresh the OBS source afterward and verify a real viewer pet. No automatic later run has been scheduled.
