# New campaign inspection, 23:11:54–23:13:19

Read-only code/DLL inspection requested by owner. Installed DLL MD5 matches
9c21b58: CF46A2E2933CD31A0D85CF1D80AE1C05.

New campaign starts with one troop, 1000 gold, no wars/fiefs, zero daily wage.
At 23:11:57 reaches Kanor; service reserves 2000 gold and refuses recruitment
because no gold exceeds reserve. Food is sufficient. Native AI repeatedly scores
staying in Kanor at 9.248, above patrol options around 1.5–1.8. In the inspected
snapshot 74 stay decisions appear. At 23:12:23 the long-stay warning reports
5.1 campaign days without departure. Later summaries still show one troop and
1000 gold. Time advances: this is a recruitment/economic deadlock, not paused time
or an exception. Growing an initial party needs a startup reserve policy; merely
forcing departure does not provide recruitment funds or a viable party.

Earlier old-campaign run with this DLL:
- 23:04:27: raid result Continue executed, time resumed and a new target followed.
- 23:06:58–23:07:01: attack after lord dialogue, battle behavior attached and hero
  plus eight formations controlled. No final battle result before next campaign.
- Remaining gap: 23:06:48/55 lord intro and option 546 still selected through
  random dialogue. Previous combat-dialogue fix has not covered every live state.
- 23:04:08: enable rejected after loading into an existing battle; event type
  unavailable in log, so do not claim all resumed battles fixed.

No implementation/DLL changes in this inspection. New-campaign startup economy,
remaining lord-dialogue path and resumed-battle classification require follow-up.
