"""Monte-Carlo симуляция слотов для верификации RTP.
Копирует логику _calc_spin из backend/routes/casino.py.
"""
import random
from collections import Counter

SLOT_SYMBOLS = [
    {"id": "wood",   "mult": 0, "weight": 55},
    {"id": "stone",  "mult": 1, "weight": 25},
    {"id": "amulet", "mult": 2, "weight": 15},
    {"id": "crown",  "mult": 5, "weight": 5},
]
JACKPOT_START = 10_000
JACKPOT_CONTRIBUTION = 0.02

def _pick():
    total = sum(s["weight"] for s in SLOT_SYMBOLS)
    r = random.randint(1, total)
    cum = 0
    for s in SLOT_SYMBOLS:
        cum += s["weight"]
        if r <= cum:
            return s
    return SLOT_SYMBOLS[0]

def _calc_spin(bet: int, jackpot: int) -> dict:
    r1, r2, r3 = _pick(), _pick(), _pick()
    ids = [r1["id"], r2["id"], r3["id"]]
    jackpot_won = False
    near_miss_amt = 0
    mult = 0
    win_amount = 0
    if ids[0] == ids[1] == ids[2]:
        if ids[0] == "crown":
            win_amount = jackpot
            jackpot_won = True
        else:
            mult = {"amulet": 75, "stone": 25, "wood": 0}.get(ids[0], 0)
            win_amount = int(bet * mult)
    else:
        if   ids[0] == ids[1]: pair = ids[0]
        elif ids[1] == ids[2]: pair = ids[1]
        elif ids[0] == ids[2]: pair = ids[0]
        else:                  pair = None
        if pair == "crown":
            mult, win_amount = 4, bet * 4
        elif pair == "amulet":
            mult, win_amount = 3, bet * 3
        elif pair == "stone":
            near_miss_amt = int(bet * 0.1)
        elif pair == "wood":
            near_miss_amt = int(bet * 0.1)
    return {
        "ids": ids,
        "win_amount": win_amount,
        "mult": mult,
        "jackpot_won": jackpot_won,
        "near_miss_amt": near_miss_amt,
    }

def simulate(n_spins=1_000_000, bet=100, seed=42):
    random.seed(seed)
    jackpot = JACKPOT_START
    total_bet = 0
    total_payout = 0
    events = Counter()
    for _ in range(n_spins):
        total_bet += bet
        jackpot += int(bet * JACKPOT_CONTRIBUTION)
        res = _calc_spin(bet, jackpot)
        payout = res["win_amount"] + res["near_miss_amt"]
        total_payout += payout
        if res["jackpot_won"]:
            jackpot = JACKPOT_START
            events["jackpot"] += 1
        elif res["ids"][0] == res["ids"][1] == res["ids"][2]:
            events[f"triple_{res['ids'][0]}"] += 1
        elif res["mult"] > 0:
            events[f"pair_win_x{res['mult']}"] += 1
        elif res["near_miss_amt"] > 0:
            events["near_miss"] += 1
        else:
            events["loss"] += 1
    rtp = total_payout / total_bet
    print(f"Spins: {n_spins:,}  Bet: {bet}")
    print(f"Total bet:    {total_bet:,}")
    print(f"Total payout: {total_payout:,}")
    print(f"RTP (эмпирическое): {rtp*100:.2f}%")
    print()
    print("Частоты событий:")
    for k, v in events.most_common():
        print(f"  {k:20s} {v:8d}  {v/n_spins*100:6.3f}%")

if __name__ == "__main__":
    simulate(1_000_000, 100)
