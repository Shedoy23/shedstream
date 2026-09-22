# Days-based wage reserve, owner request 16 September

Owner replaced fixed 2000 gold minimum with seven days of upkeep, including
new recruits. Default MinGoldReserve is now zero; seven-day wage reserve remains.
Food was already purchased using the native food-buying model's days target
(town/village targets can exceed the seven-day expedition minimum).

Recruitment evaluates PartyWageModel.GetTotalWage on a detached copied roster
with proposed recruits. The remaining gold after recruitment must cover seven
days of that wage, with no speculative future income counted. Planning and
the actual recruitment loop both check the reserve. No temporary changes to the
live roster are made to predict wages. Existing pass spending/count caps remain.

This is party wage coverage, not a forecast of every clan expense or future food
market prices. It does not change food buying targets or the village waiting flow.
An existing save already waiting outside a village may still require re-entry
for another service pass; this change removes the budget blocker at that pass.

Regression 2ac8db8 failed (354 pass, 1 fail) before implementation. A 1000-gold
scenario with 100 recruitment cost and 50 daily wage per recruit now hires two
and rejects the third: 800 remaining covers 700 wages, whereas 700 would not
cover 1050. Current suite 356/356, BattleMission 22/22, native contract 422/422,
build no warnings/errors. Real new-campaign replay remains unverified.
