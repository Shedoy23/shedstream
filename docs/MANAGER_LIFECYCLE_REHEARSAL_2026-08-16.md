# Manager Update/Repair rehearsal — 2026-08-16

## Scope

The rehearsal verifies the production RimLink installation lifecycle without
writing to the real game installation, Manager state, configuration, credential
store, or saves.

The verifier:

1. copies the installed RimLink directory to a unique temporary game root;
2. fingerprints the original tree before the test;
3. removes a required health-probe file from the copy;
4. requires `RepairRequired`, downloads the immutable production archive over
   HTTPS, verifies its size, SHA-256 and RSA-PSS signature, then repairs the copy;
5. marks the separate copy as an older Manager-tracked version and adds a legacy
   marker, requires `UpdateAvailable`, then updates it from the same signed source;
6. requires the legacy marker and all transaction artifacts to be gone;
7. fingerprints the original installation again and requires an exact match;
8. removes the temporary rehearsal root only after success.

The older version is represented by Manager's `InstalledReleaseVersion` input
plus a legacy marker because no signed historical `0.1.0` distribution artifact
exists. The update path replaces the whole separate installation directory, so
this exercises the same production atomic swap used for a real old release.

## Command

```powershell
dotnet run --project ShedLink.Manager/tools/ShedLink.Manager.VerifyLifecycle -- `
  --manifest manifests/installation/rimworld-0.1.1.json `
  --public-key "$env:LOCALAPPDATA/ShedLink/release-keys/shedlink-release-2026.public.pem" `
  --seed-game-root "X:/SteamLibrary/steamapps/common/RimWorld" `
  --old-version 0.1.0
```

## Result

Passed on 2026-08-16 against the installed copy under
`X:/SteamLibrary/steamapps/common/RimWorld` and the production release at
`https://shedoy23.ru/releases/RimLink-0.1.1.zip`.

```text
LIFECYCLE VERIFIED rimworld 0.1.1
STATES=Healthy -> RepairRequired -> Healthy -> UpdateAvailable -> Healthy
SHA256=4e9656cb84b574691482938967928b0c50ad3cafd3cb7e41e79a12cb7ed42381
KEY_ID=shedlink-release-2026
SEED_FINGERPRINT_SHA256=1e9fa9664495d34a55366bb2387796be38e8595c4be477e9b5b8d4627b058d26
ORIGINAL_INSTALLATION=UNCHANGED
```

The successful verifier run removed its unique temporary root. No transaction
stage, backup, or journal remained in the separate installation root.

This check does not replace the clean Windows VM matrix. It closes the real
filesystem Update/Repair rehearsal while preserving that separate release gate.
