from pathlib import Path
s=(Path(__file__).resolve().parents[1]/"BannerlordLink/src/Behaviors/KillRewardBehavior.cs").read_text(encoding="utf-8")
checks={
"no immediate kill gold": "GiveGoldAction.ApplyBetweenCharacters(null, killer, gold, true)" not in s,
"no immediate milestone gold": "GiveGoldAction.ApplyBetweenCharacters(null, s.Hero, gold, true)" not in s,
"new payout calculator wired": "BattlePayoutPolicy.Calculate" in s,
"retinue hits tracked": "override void OnAgentHit" in s and "RetinuePoints" in s,
"settlement consumed before mutation": "s.PayoutSettled = true;" in s,
}
for name,ok in checks.items(): print(("PASS " if ok else "FAIL ")+name)
raise SystemExit(0 if all(checks.values()) else 1)
