from pathlib import Path
s=(Path(__file__).resolve().parents[1]/"BannerlordLink/src/Behaviors/KillRewardBehavior.cs").read_text(encoding="utf-8")
message_pos = s.find('@{s.Username}: за бой +')
paid_pos = s.find('s.PayoutPaid = true;', s.find('if (goldDelta != 0)'))
checks={
"payout journal follows successful payment": message_pos > paid_pos > 0,
"payout journal includes all parts": message_pos >= 0 and all(x in s[message_pos:message_pos+450] for x in ('s.ParticipationGold', 's.PersonalGold', 's.RetinueGold')),

"no immediate kill gold": "GiveGoldAction.ApplyBetweenCharacters(null, killer, gold, true)" not in s,
"no immediate milestone gold": "GiveGoldAction.ApplyBetweenCharacters(null, s.Hero, gold, true)" not in s,
"new payout calculator wired": "BattlePayoutPolicy.Calculate" in s,
"retinue hits tracked": "override void OnAgentHit" in s and "RetinuePoints" in s,
"settlement consumed before mutation": "s.PayoutSettled = true;" in s,
}
for name,ok in checks.items(): print(("PASS " if ok else "FAIL ")+name)
raise SystemExit(0 if all(checks.values()) else 1)
