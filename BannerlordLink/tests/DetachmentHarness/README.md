# Viewer battle-order regression harness

Run from the repository root:

```powershell
dotnet run --project BannerlordLink/tests/DetachmentHarness
```

The harness compiles the **actual** `HeroDetachmentBehavior.cs` and `DetachmentHandlers.cs`, with deterministic in-memory substitutes for engine calls. It checks command acceptance and feedback, state preservation after native failures, siege target classification, and infantry charge selection/contact/pursuit across mission ticks. Additional checks cover arrival and blocked statuses, target loss and reacquisition, path changes, and player-control rejection. Search-budget checks also verify empty-search backoff and eventual discovery beyond many unreachable candidates.

Optional before/after regression run against a directory containing the two unchanged source files:

```powershell
dotnet run --project BannerlordLink/tests/DetachmentHarness -p:BaselineSourceDir=D:/shedlink-build/battle-orders-local/baseline
```

The original implementation fails 34 of 43 checks. Nine checks establish preserved behavior, including native contact handoff, dead-target replacement, mounted charge selection, successful attach/hold feedback, and ordinary movement flags.

These are policy and API-boundary tests. Stubs can return unreachable paths and throw native-call exceptions; they do not simulate native navigation, animation, combat, actual ladders, or game performance. Passing this harness does not establish live battle behavior. No build output is installed in the game.
