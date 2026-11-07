import copy
from itertools import combinations
from pathlib import Path
import random
import unittest
import cv2
import numpy as np
from poker_helper.cards import evaluate, warnings, validate
from poker_helper.config import DEFAULTS, ROOT
from poker_helper.vision import ScreenParser, Reading, money
from poker_helper.state import PokerStreetTracker, State, Action, side_pots
from poker_helper.ranges import Range, make_range, simulate
from poker_helper.analysis import analyze

def settings():
    return {**copy.deepcopy(DEFAULTS),'stable_frames':1,'hero_seat':0,'dealer_seat':0,
            'pot_mode':'total','statuses':['active','active']+['empty']*7,'iterations':120}

def observed(pot=15,bets=(5,10),stacks=(995,990),board=(),hero=('As','Kd')):
    readings={'hero':Reading(hero),'board':Reading(board),'pot':Reading(pot)}
    for i in range(2): readings[f'bet_{i}']=Reading(bets[i]); readings[f'stack_{i}']=Reading(stacks[i])
    return readings

class CardsTests(unittest.TestCase):
    def test_double_trips_full_house(self):
        self.assertEqual(evaluate('As Ah Ad Ks Kh Kd 2c'.split())[:3],(6,14,13))
    def test_wheel_and_straight_flush(self):
        self.assertEqual(evaluate('As 2h 3d 4c 5s 9h Tc'.split())[:2],(4,5))
        self.assertEqual(evaluate('As 2s 3s 4s 5s 9h Tc'.split())[:2],(8,5))
    def test_seven_equals_best_five(self):
        from engine import evaluate_5card
        # Compare ordering against an independently implemented legacy five-card evaluator.
        from poker_helper.cards import DECK
        rng=random.Random(18)
        for _ in range(100):
            cards=rng.sample(DECK,7)
            best=max(combinations(cards,5),key=evaluate_5card)
            self.assertEqual(evaluate(cards),evaluate(best))
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError): validate(['As','As'])
    def test_warnings(self):
        text=' '.join(warnings(['As','Kh'],['Qs','Js','Ts','Qd','2h']))
        self.assertIn('葫芦',text); self.assertIn('同花',text); self.assertIn('顺子',text)

class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.parser=ScreenParser()
    def test_real_pot_crop(self):
        if not (ROOT/'pot_crop_test.png').exists(): self.skipTest('Private pot screenshot is intentionally not published')
        crop=cv2.imread(str(ROOT/'pot_crop_test.png'))
        self.assertEqual(self.parser.amount(crop[:,100:173],'digits').value,193)
    def test_real_bet_crop(self):
        if not (ROOT/'debug_crops/bet_bottom_right_test.png').exists(): self.skipTest('Private wager screenshot is intentionally not published')
        crop=cv2.imread(str(ROOT/'debug_crops/bet_bottom_right_test.png'))
        self.assertEqual(self.parser.amount(crop,'bets_digits').value,120)
    def test_template_groups_distinct(self):
        self.assertIsNot(self.parser.templates['digits'],self.parser.templates['bets_digits'])
    def test_blank_vs_unknown(self):
        blank=np.zeros((24,70,3),np.uint8)
        self.assertEqual(self.parser.amount(blank,allow_blank=True).value,0)
        self.assertIsNone(self.parser.amount(None,allow_blank=True).value)
        self.assertIsNone(self.parser.amount(blank).value)
    def test_no_guessed_decimal(self):
        if not (ROOT/'templates/bets_digits/2.png').exists(): self.skipTest('Local recognition templates are intentionally not published')
        glyph=cv2.imread(str(ROOT/'templates/bets_digits/2.png'))
        canvas=np.zeros((30,glyph.shape[1]+10,3),np.uint8)
        canvas[3:3+glyph.shape[0],3:3+glyph.shape[1]]=glyph
        self.assertIsNone(self.parser.amount(canvas).value)
        self.assertEqual(money('20'),2000); self.assertEqual(money('0.20'),20)

class StateTests(unittest.TestCase):
    def test_pot_conservation_and_raise(self):
        tracker=PokerStreetTracker(log=False); cfg=settings()
        s=tracker.update(observed(),0,cfg); self.assertFalse(s.issues); self.assertTrue(s.complete_history)
        s=tracker.update(observed(40,(30,10),(970,990)),0,cfg)
        self.assertFalse(s.issues); self.assertEqual(s.actions[-1].kind,'raise'); self.assertEqual(s.last_full_raise,20)
        s=tracker.update(observed(60,(30,30),(970,970)),0,cfg)
        self.assertEqual(s.actions[-1].kind,'call'); self.assertEqual(s.committed,{0:30,1:30})
    def test_unknown_does_not_zero_bet(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        frame=observed(); frame['bet_1']=Reading(error='uncertain'); s=tracker.update(frame,0,cfg)
        self.assertEqual(s.bets[1],10); self.assertTrue(s.issues)
    def test_stability(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); cfg['stable_frames']=3
        for _ in range(2): self.assertTrue(tracker.update(observed(),0,cfg).issues)
        self.assertFalse(tracker.update(observed(),0,cfg).issues)
    def test_total_vs_collected(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); cfg['pot_mode']='collected'
        self.assertEqual(tracker.update(observed(pot=0),0,cfg).total_pot,15)
    def test_invalid_stack_delta(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        s=tracker.update(observed(40,(30,10),(995,990)),0,cfg)
        self.assertTrue(s.issues); self.assertEqual(s.bets[0],5)
    def test_street_ledger_not_double_counted(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        tracker.update(observed(20,(10,10),(990,990)),0,cfg)
        frame=observed(20,(0,0),(990,990),('2c','7h','Jd'))
        tracker.update(frame,0,cfg); tracker.freeze_until=0
        s=tracker.update(frame,0,cfg)
        self.assertEqual(s.committed,{0:10,1:10}); self.assertEqual(s.street,'flop')
    def test_new_hand_resets(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        s=tracker.update(observed(hero=('Qs','Qh')),0,cfg)
        self.assertEqual(s.committed,{}); self.assertTrue(s.issues)
    def test_dealer_rotation_resets_identical_cards(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        s=tracker.update(observed(),1,cfg)
        self.assertTrue(s.issues); self.assertEqual(s.committed,{})
    def test_delayed_bet_and_stack_confirm_together(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        frame=observed(40,(30,10),(970,990)); frame['bet_0']=Reading(error='animating')
        tracker.update(frame,0,cfg)
        s=tracker.update(observed(40,(30,10),(970,990)),0,cfg)
        self.assertFalse(s.issues); self.assertEqual(s.committed,{0:30,1:10})
    def test_simultaneous_actions_are_not_ordered(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        s=tracker.update(observed(60,(30,30),(970,970)),0,cfg)
        self.assertTrue(all(a.kind=='unknown' and not a.ordered for a in s.actions))
    def test_folded_money_remains_committed(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); tracker.update(observed(),0,cfg)
        cfg['statuses'][1]='folded'
        s=tracker.update(observed(15,(5,0),(995,990)),0,cfg)
        self.assertFalse(s.issues); self.assertEqual(s.committed[1],10)
        self.assertEqual(s.actions[-1].kind,'fold')
    def test_mid_hand_snapshot_is_not_a_known_raise(self):
        tracker=PokerStreetTracker(log=False); cfg=settings()
        s=tracker.update(observed(110,(10,100),(990,900)),0,cfg)
        self.assertFalse(s.complete_history)
        self.assertTrue(all(a.kind=='snapshot' for a in s.actions))
    def test_sidepot_layers(self):
        self.assertEqual(side_pots({0:100,1:200,2:200},[0,1,2]),[(300,(0,1,2)),(200,(1,2))])
        self.assertEqual(side_pots({0:100,1:200,2:200},[0,1]),[(300,(0,1)),(200,(1,))])
    def test_manual_allin_without_numeric_stack(self):
        tracker=PokerStreetTracker(log=False); cfg=settings(); cfg['statuses'][1]='allin'
        frame=observed(); frame['stack_1']=Reading(error='ALL IN')
        s=tracker.update(frame,0,cfg)
        self.assertFalse(s.issues); self.assertEqual(s.stacks[1],0)

class RangeTests(unittest.TestCase):
    def test_board_split_nine_players(self):
        board='As Ks Qs Js Ts'.split(); hero=['2h','3h']; ranges={}
        cards='4h 5h 6h 7h 8h 9h Th Jh Qh Kh Ah 2d 3d 4d 5d 6d'.split()
        for i in range(8): ranges[i]=Range([tuple(cards[2*i:2*i+2])],[1],[1])
        eq=simulate(hero,board,ranges,100)
        self.assertAlmostEqual(eq.equity,1/9); self.assertAlmostEqual(eq.stderr,0,places=7)
    def test_raise_updates_range(self):
        hero=['2c','3d']; baseline=make_range(hero,[],'UTG',[],10)
        action=Action('preflop',1,'raise',100,100,15,())
        raised=make_range(hero,[],'UTG',[action],10)
        weights=dict(zip(raised.combos,raised.weights))
        self.assertGreater(weights[('As','Ah')],weights[('2h','7s')])
        self.assertNotEqual(baseline.weights,raised.weights)
    def test_payout_excludes_sidepot(self):
        hero=['As','Ah']; board='2c 3d 7h 9s Tc'.split()
        ranges={1:Range([('Ks','Kh')],[1],[1]),2:Range([('Qs','Qh')],[1],[1])}
        eq=simulate(hero,board,ranges,100,pots=[(300,(0,1,2)),(200,(1,2))],hero_seat=0)
        self.assertEqual(eq.equity,300)
    def test_input_issues_block_recommendation(self):
        report=analyze(State(hero=('As','Kd'),issues=['unconfirmed']),settings())
        self.assertIsNone(report.equity); self.assertEqual(report.action,'等待可靠信息')
    def test_half_stack_example(self):
        cfg=settings(); state=State(hero=('As','Ah'),board=('2c','3d','7h','9s','Tc'),street='river',
            stacks={0:2000,1:1000},bets={0:0,1:1000},statuses={0:'active',1:'active'},total_pot=2000,call=1000)
        report=analyze(state,cfg); self.assertAlmostEqual(report.required,1/3)
        self.assertAlmostEqual(report.spr[1],0.5)
        state.total_pot=5000; report=analyze(state,cfg); self.assertAlmostEqual(report.required,1/6)
    def test_incomplete_sidepot_suspends_advice(self):
        state=State(hero=('As','Ah'),board=('2c','3d','7h','9s','Tc'),street='river',
            stacks={0:100,1:0,2:500},bets={0:0,1:500,2:500},
            statuses={0:'active',1:'allin',2:'active'},total_pot=1000,highest=500,call=100)
        self.assertIn('暂停',analyze(state,settings()).action)

class ReplayTests(unittest.TestCase):
    def test_full_hand_replay(self):
        from poker_helper.replay import replay
        result=replay(ROOT/'examples/hand_replay.json')
        last=result[-1]
        self.assertEqual(last['state']['committed'],{0:30,1:60})
        self.assertEqual(last['state']['issues'],[])
        self.assertEqual(last['report']['required'],0.25)

if __name__=='__main__': unittest.main()
