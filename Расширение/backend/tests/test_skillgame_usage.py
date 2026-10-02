"""New minigame counters are bounded semantic labels, never move payloads."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ui_usage import validate_batch

class SkillgameUsageTests(unittest.TestCase):
    def batch(self, event):
        return {'batch_id':'01234567-89ab-4cde-8123-456789abcdef','surface':'mobile','events':[event]}

    def test_game_opens_and_actions(self):
        for game,actions in {'battleship':['queue','place','autoplace','ready','fire','quit'],
                             'minesweeper':['start','open','flag','unflag','quit','restart']}.items():
            validate_batch(self.batch({'kind':'section_open','feature':'core:game.'+game,'count':1}))
            for action in actions:
                validate_batch(self.batch({'kind':'action_attempt','feature':'core:'+game+'.'+action,'count':1}))

    def test_move_content_never_accepted(self):
        for extra in ({'cell':15},{'ships':[[0,1]]},{'seed':'secret'},{'mines':[8,9]}):
            event={'kind':'action_attempt','feature':'core:minesweeper.open','count':1,**extra}
            with self.assertRaises(ValueError): validate_batch(self.batch(event))
        for feature in ['core:minesweeper.cell15','core:battleship.fire.23','core:minesweeper.seed']:
            with self.assertRaises(ValueError):
                validate_batch(self.batch({'kind':'action_attempt','feature':feature,'count':1}))

if __name__ == '__main__': unittest.main()
