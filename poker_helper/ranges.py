"""Explicit heuristic priors and action likelihoods, not solver/GTO outputs."""
from bisect import bisect_left
from dataclasses import dataclass
from itertools import combinations
import math
import random
from .cards import DECK, VALUES, evaluate, shorthand, straight

@dataclass
class Range:
    combos: list
    weights: list
    cumulative: list
    def sample(self,rng,used):
        for _ in range(150):
            idx=bisect_left(self.cumulative,rng.random()*self.cumulative[-1])
            combo=self.combos[min(idx,len(self.combos)-1)]
            if not set(combo)&used: return combo
        available=[(c,w) for c,w in zip(self.combos,self.weights) if not set(c)&used]
        if not available: raise ValueError('对手范围无合法组合')
        return rng.choices([c for c,w in available],[w for c,w in available])[0]
    def summary(self):
        groups={}
        for c,w in zip(self.combos,self.weights):
            key=shorthand(c); groups[key]=groups.get(key,0)+w
        top=sorted(groups.items(),key=lambda x:x[1],reverse=True)[:8]
        total=sum(self.weights)
        return '、'.join(f'{key} {weight/total:.0%}' for key,weight in top)

def preflop_strength(combo):
    a,b=sorted((VALUES[c[0]] for c in combo),reverse=True)
    pair=a==b; suited=combo[0][1]==combo[1][1]
    if pair: return 0.40+0.045*a
    return min(0.98,(a+b)/32 + (0.055 if suited else 0) + (0.035 if a-b<=2 else 0) - (0.055 if a-b>=5 else 0))

def make_range(hero,board,position,actions,bb):
    available=[c for c in DECK if c not in hero+board]
    combos=list(combinations(available,2)); weights=[]
    early=position in ('UTG','UTG+1','UTG+2','MP')
    for combo in combos:
        strength=preflop_strength(combo)
        weight=1.0
        for action in actions:
            snapshot=action.kind=='snapshot'
            if (not action.ordered and not snapshot) or action.kind in ('unknown','blind','fold'): continue
            if action.street=='preflop':
                if action.kind in ('raise','bet','snapshot'):
                    # More expensive observed raises favor strong combinations; a soft floor retains bluffs.
                    threshold=(0.70 if early else 0.60)+min(0.17,max(0,action.total/max(1,bb)-3)*0.013)
                    likelihood=0.06+0.94/(1+math.exp(-18*(strength-threshold)))
                    weight*=0.5+0.5*likelihood if snapshot else likelihood
                elif action.kind=='call': weight*=0.18+0.82/(1+math.exp(-11*(strength-0.56)))
            else:
                cards=list(combo)+list(action.board)
                if len(cards)<5: continue
                score=evaluate(cards); category=score[0]
                if len(action.board)>=5:
                    board_score=evaluate(action.board)
                    # Playing the board is not a strong private made hand.
                    if score==board_score: category=0
                suits=[c[1] for c in cards]
                draw=len(action.board)<5 and any(suits.count(s)==4 for s in 'shdc')
                # Include straight draws as well as flush draws in semi-bluff likelihood.
                if len(action.board)<5 and category<4:
                    values={VALUES[c[0]] for c in cards}
                    draw=draw or any(straight(values|{v}) for v in range(2,15) if v not in values)
                size=action.increment/max(1,action.pot_before)
                if action.kind in ('bet','raise','snapshot'):
                    value=[0.12,0.35,0.65,0.80,0.95,1,1,1,1][category]
                    if size>=0.75 and category<=1: value*=0.55
                    if draw: value=max(value,0.45)
                    weight*=0.5+0.5*value if snapshot else value
                elif action.kind=='call': weight*=[0.12,0.65,0.85,0.90,0.95,1,1,1,1][category] if not draw else 0.70
        weights.append(max(weight,1e-6))
    cumulative=[]; total=0.0
    for w in weights: total+=w; cumulative.append(total)
    return Range(combos,weights,cumulative)

@dataclass
class Equity:
    equity: float
    stderr: float
    iterations: int
    showdown_share: float

def simulate(hero,board,ranges,iterations=1200,seed=17,pots=None,hero_seat=None):
    """Sequential range samples conditional on card removal; includes exact split shares.

    This inexpensive sequential sampler is an approximation to a joint range distribution.
    Its sampling interval excludes range-model uncertainty.
    """
    rng=random.Random(seed); known=set(hero+board)
    total=0.0; squares=0.0; share_total=0.0
    seats=list(ranges)
    if len(seats)>8: raise ValueError('最多支持八名对手')
    for _ in range(iterations):
        used=set(known); hands={}
        # Rotate sampling order to limit systematic seat-order bias.
        order=list(seats); rng.shuffle(order)
        for seat in order:
            combo=ranges[seat].sample(rng,used); used.update(combo); hands[seat]=list(combo)
        rest=[c for c in DECK if c not in used]
        runout=list(board)+rng.sample(rest,5-len(board))
        hero_score=evaluate(list(hero)+runout)
        scores={seat:evaluate(hand+runout) for seat,hand in hands.items()}
        best=max([hero_score,*scores.values()])
        share=(1/(1+sum(v==best for v in scores.values()))) if hero_score==best else 0.0
        share_total+=share
        if pots is None: result=share
        else:
            result=0.0
            all_scores={hero_seat:hero_score,**scores}
            for amount,eligible in pots:
                if hero_seat not in eligible: continue
                best_score=max(all_scores[s] for s in eligible)
                winners=[s for s in eligible if all_scores[s]==best_score]
                if hero_seat in winners: result+=amount/len(winners)
        total+=result; squares+=result*result
    avg=total/iterations; variance=max(0,squares/iterations-avg*avg)
    return Equity(avg,math.sqrt(variance/iterations),iterations,share_total/iterations)
