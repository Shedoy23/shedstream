"""Standalone Battleship invariants. Run with python tests/test_battleship_engine.py."""
import copy
import json
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skillgames import battleship as b

FLEET = [[0, 1, 2], [12, 13], [16, 17], [30]]
OTHER = [[0, 6, 12], [3, 9], [24, 25], [29]]

class BattleshipTests(unittest.TestCase):
    def ready_game(self):
        state = b.new_game(['alice', 'bob'], now=10)
        state = b.apply_action(state, 'alice', 'place', ships=FLEET, now=11)
        state = b.apply_action(state, 'bob', 'place', ships=OTHER, now=11)
        state = b.apply_action(state, 'alice', 'ready', now=12)
        return b.apply_action(state, 'bob', 'ready', now=13)

    def test_manual_placement_and_ready(self):
        state = self.ready_game()
        self.assertEqual(state['phase'], 'active')
        self.assertEqual(state['status'], 'active')
        self.assertIn(state['turn'], ['alice', 'bob'])
        self.assertEqual(state['turn_started_at'], 13)
        with self.assertRaises(b.InvalidAction):
            b.apply_action(state, 'alice', 'place', ships=FLEET)

    def test_illegal_fleets_are_rejected(self):
        state = b.new_game(['alice', 'bob'])
        bad = [[], FLEET[:-1], [[0, 1, 6], [12, 13], [16, 17], [30]],
               [[4, 5, 6], [12, 13], [16, 17], [30]],
               [[0, 1, 2], [8, 9], [16, 17], [30]],
               [[0, 1, 2], [12, 13], [16, 17], [True]],
               [[0, 1, 2], [12, 13], [16, 17], [36]],
               [[0, 0, 1], [12, 13], [16, 17], [30]]]
        for ships in bad:
            with self.subTest(ships=ships), self.assertRaises(b.InvalidAction):
                b.apply_action(state, 'alice', 'place', ships=ships)

    def test_auto_placements_many_seeds(self):
        for seed in range(200):
            fleet = b.generate_fleet(random.Random(seed))
            b.validate_fleet(fleet)
            self.assertEqual(sorted(map(len, fleet)), [1, 2, 2, 3])

    def test_projection_never_exposes_opponent_fleet(self):
        state = self.ready_game()
        a, z = b.public_projection(state, 'alice'), b.public_projection(state, 'bob')
        self.assertEqual(a['own_ships'], FLEET)
        self.assertEqual(z['own_ships'], OTHER)
        self.assertNotIn('fleets', a)
        self.assertNotIn('opponent_ships', a)
        self.assertEqual(a['shots'], [])
        with self.assertRaises(b.InvalidAction):
            b.public_projection(state, 'eve')
        changed = copy.deepcopy(state)
        changed['fleets']['bob'] = FLEET
        self.assertEqual(a, b.public_projection(changed, 'alice'))
        a['own_ships'][0][0] = 35
        self.assertEqual(state['fleets']['alice'], FLEET)

    def test_turn_replay_input_and_player_guards(self):
        state = self.ready_game()
        player = state['turn']
        other = next(p for p in state['players'] if p != player)
        before = copy.deepcopy(state)
        for badplayer in [other, 'eve']:
            with self.assertRaises(b.InvalidAction):
                b.apply_action(state, badplayer, 'fire', cell=0)
        for cell in [True, -1, 36, '0', 0.5, None]:
            with self.assertRaises(b.InvalidAction):
                b.apply_action(state, player, 'fire', cell=cell)
        state = b.apply_action(state, player, 'fire', cell=0, now=20)
        self.assertEqual(state['turn'], other, 'hit must also alternate')
        self.assertEqual(before['shots'][player], [])
        state = b.apply_action(state, other, 'fire', cell=35, now=21)
        with self.assertRaises(b.InvalidAction):
            b.apply_action(state, player, 'fire', cell=0)

    def test_winner_is_computed_from_hits_and_terminal_rejects(self):
        state = self.ready_game()
        attacker = state['turn']
        defender = next(p for p in state['players'] if p != attacker)
        targets = [cell for ship in state['fleets'][defender] for cell in ship]
        empty = [cell for cell in range(36) if all(cell not in ship for ship in state['fleets'][attacker])]
        for i, cell in enumerate(targets):
            state = b.apply_action(state, attacker, 'fire', cell=cell, now=30+i*2)
            if i < len(targets)-1:
                state = b.apply_action(state, defender, 'fire', cell=empty[i], now=31+i*2)
        self.assertEqual((state['status'], state['phase'], state['winner']), ('won', 'finished', attacker))
        with self.assertRaises(b.InvalidAction):
            b.apply_action(state, defender, 'fire', cell=empty[-1])
        self.assertNotIn('opponent_ships', b.public_projection(state, attacker))
        json.dumps(state)

    def test_ready_requires_fleet_and_cannot_change_ready_fleet(self):
        state = b.new_game(['alice', 'bob'])
        with self.assertRaises(b.InvalidAction):
            b.apply_action(state, 'alice', 'ready')
        state = b.apply_action(state, 'alice', 'autoplace')
        state = b.apply_action(state, 'alice', 'ready')
        for action in ['ready', 'autoplace', 'fire']:
            with self.assertRaises(b.InvalidAction):
                b.apply_action(state, 'alice', action, cell=0)
        with self.assertRaises(b.InvalidAction):
            b.new_game(['alice', 'alice'])

if __name__ == '__main__':
    unittest.main()
