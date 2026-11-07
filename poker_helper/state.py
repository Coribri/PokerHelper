"""Confirmed observations and an auditable, deliberately partial action ledger."""
from dataclasses import dataclass, field, asdict
import json
import time
from .config import ROOT

STREETS={0:'preflop',3:'flop',4:'turn',5:'river'}
POSITIONS={9:['BTN','SB','BB','UTG','UTG+1','UTG+2','MP','HJ','CO'],
           8:['BTN','SB','BB','UTG','UTG+1','MP','HJ','CO'],
           7:['BTN','SB','BB','UTG','MP','HJ','CO'],
           6:['BTN','SB','BB','UTG','MP','CO'],5:['BTN','SB','BB','MP','CO'],
           4:['BTN','SB','BB','CO'],3:['BTN','SB','BB'],2:['BTN/SB','BB']}

@dataclass
class Action:
    street: str
    seat: int
    kind: str
    increment: int
    total: int
    pot_before: int
    board: tuple
    ordered: bool=True
    timestamp: float=field(default_factory=time.time)

@dataclass
class State:
    hand_id: int=0
    hero: tuple=()
    board: tuple=()
    street: str='preflop'
    dealer: object=None
    positions: dict=field(default_factory=dict)
    stacks: dict=field(default_factory=dict)
    bets: dict=field(default_factory=dict)
    committed: dict=field(default_factory=dict)
    statuses: dict=field(default_factory=dict)
    total_pot: int=0
    call: int=0
    highest: int=0
    last_full_raise: int=0
    actions: list=field(default_factory=list)
    issues: list=field(default_factory=list)
    notes: list=field(default_factory=list)
    complete_history: bool=False
    sequence: int=0

    def signature(self):
        return (self.hand_id,self.hero,self.board,self.dealer,tuple(self.stacks.items()),
                tuple(self.bets.items()),tuple(self.statuses.items()),self.total_pot,len(self.actions),tuple(self.issues))

class StableField:
    def __init__(self):
        self.candidate=object(); self.count=0; self.value=None
    def update(self,reading,n):
        if reading.value is None:
            self.count=0; return False
        if self.candidate==reading.value: self.count+=1
        else: self.candidate=reading.value; self.count=1
        if self.count>=n: self.value=reading.value; return True
        return False

class PokerStreetTracker:
    def __init__(self,log=True,clock=time.monotonic):
        self.state=State(); self.fields={}; self.log=log
        self.clock=clock
        self.freeze_until=0.0; self.last_dealer=None
        self.last_pot=None; self.last_statuses={}
        self.initialized=False
        self.confirmed_stacks={}

    def reset(self):
        hand_id=self.state.hand_id+1
        self.state=State(hand_id=hand_id); self.fields={}
        self.last_pot=None; self.last_statuses={}; self.freeze_until=0
        self.initialized=False
        self.confirmed_stacks={}

    def append(self,action):
        self.state.actions.append(action)
        if self.log:
            path=ROOT/'logs'; path.mkdir(exist_ok=True)
            with (path/'actions.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'hand_id':self.state.hand_id,**asdict(action)},ensure_ascii=False)+'\n')

    def update(self,readings,dealer,settings):
        n=settings['stable_frames']; ok={}
        for key,reading in readings.items():
            ok[key]=self.fields.setdefault(key,StableField()).update(reading,n)
        from .vision import Reading
        dealer_ok=self.fields.setdefault('dealer',StableField()).update(Reading(dealer),n)
        dealer=self.fields['dealer'].value if dealer_ok else None
        s=self.state; s.sequence+=1; s.issues=[]; s.notes=[]
        if not ok.get('hero') or not ok.get('board'):
            s.issues.append('手牌/公共牌尚未连续确认'); return s
        hero=self.fields['hero'].value; board=self.fields['board'].value
        if set(hero)&set(board):
            s.issues.append('手牌与公共牌重复'); return s
        new_hand=(s.hero and hero!=s.hero) or (s.board and not board) or (
            s.hero and not board and dealer is not None and s.dealer is not None and dealer!=s.dealer)
        if new_hand:
            old_id=s.hand_id
            self.reset(); self.state.hand_id=max(1,old_id+1)
            s=self.state; s.issues=['检测到新手牌，重新确认金额']; return s
        if s.hero and len(board)<len(s.board):
            s.issues.append('公共牌短暂减少，等待动画结束'); return s
        if s.board and tuple(board[:len(s.board)])!=s.board:
            s.issues.append('公共牌发生不合法变化'); return s
        street_changed=board!=s.board
        if street_changed:
            s.bets={}; self.last_pot=None
            s.last_full_raise=settings['bb_cents']
            self.freeze_until=self.clock()+0.8
            # Force post-animation reconfirmation of amounts.
            for key in self.fields:
                if key.startswith(('bet_','stack_')) or key=='pot': self.fields[key].count=0
        s.hero=hero; s.board=board; s.street=STREETS[len(board)]
        s.dealer=dealer; s.statuses={i:v for i,v in enumerate(settings['statuses'])}
        s.statuses[settings['hero_seat']]='active'
        if dealer is None: s.issues.append('庄位尚未确认，可手动选择庄位')
        occupied=[i for i in range(9) if s.statuses[i]!='empty']
        if dealer in occupied and len(occupied)>=2:
            j=occupied.index(dealer); rotation=occupied[j:]+occupied[:j]
            s.positions=dict(zip(rotation,POSITIONS[len(occupied)]))
        else: s.positions={}
        if any(v=='unknown' for v in s.statuses.values()):
            s.issues.append('请确认各座位仍在局内、已弃牌或空座；筹码亮暗不代表弃牌')
        if settings['pot_mode']=='unknown': s.issues.append('请确认中央底池是否包含当轮下注')
        if self.clock()<self.freeze_until:
            s.issues.append('换街动画，暂停决策'); return s
        previous_stacks=dict(self.confirmed_stacks)
        for i in occupied:
            if s.statuses[i]=='allin':
                # An explicitly confirmed all-in seat may display text instead of a balance.
                s.stacks[i]=0
            elif ok.get(f'stack_{i}') and self.fields[f'stack_{i}'].count>=n:
                s.stacks[i]=self.fields[f'stack_{i}'].value
            elif s.statuses[i] in ('active','allin'):
                s.issues.append(f'座位 {i+1} 筹码未确认')
        bets={}
        for i in occupied:
            if ok.get(f'bet_{i}') and self.fields[f'bet_{i}'].count>=n:
                bets[i]=self.fields[f'bet_{i}'].value
            else: s.issues.append(f'座位 {i+1} 下注未确认')
        if not ok.get('pot') or self.fields['pot'].count<n:
            s.issues.append('底池金额未确认')
        # Unknown or transient observations never overwrite the confirmed ledger.
        if len(bets)!=len(occupied) or not ok.get('pot') or self.fields['pot'].count<n:
            return s
        visible_bet_sum=sum(bets.values())
        # Folded players may have their displayed wager collected early; retain their
        # historical street contribution without adding it twice to the visible pot.
        for i in bets:
            if s.statuses[i]=='folded' and bets[i]==0 and s.bets.get(i,0)>0:
                bets[i]=s.bets[i]
        if any(bets[i]<s.bets.get(i,0) for i in bets):
            s.issues.append('当轮下注减少但未换街，等待确认或重置新一手'); return s
        pot=self.fields['pot'].value
        total=pot+visible_bet_sum if settings['pot_mode']=='collected' else pot
        if settings['pot_mode']!='unknown' and total<sum(bets.values()):
            s.issues.append('底池小于桌面下注，金额或底池含义不一致'); return s
        if self.last_pot is not None and total<self.last_pot:
            s.issues.append('同一轮底池减少，可能误读或新手牌未识别'); return s
        changes=[i for i,b in bets.items() if b>s.bets.get(i,0)]
        increments=sum(bets[i]-s.bets.get(i,0) for i in changes)
        if any('筹码未确认' in issue for issue in s.issues): return s
        if self.initialized and not street_changed:
            mismatches=[i for i in changes if i in previous_stacks and
                        abs((previous_stacks[i]-s.stacks[i])-(bets[i]-s.bets.get(i,0)))>2]
            if mismatches:
                # Keep previous confirmed stacks so the next snapshot can reconcile the delta.
                s.stacks=previous_stacks
                s.issues.append('下注增量与筹码减少不一致，等待同步快照'); return s
        if self.last_pot is not None and abs((total-self.last_pot)-increments)>2:
            s.issues.append('底池变化与下注增量不一致，等待一致快照'); return s
        first=not self.initialized
        if first:
            s.complete_history=(not board and max(bets.values(),default=0)<=settings['bb_cents'] and
                                abs(total-round(settings['bb_cents']*1.5))<=1)
            for i,b in bets.items(): s.committed[i]=s.committed.get(i,0)+b
            if not s.complete_history:
                s.notes.append('从中途快照开始：前序行动和投入未知')
                for i,b in bets.items():
                    if b>0: self.append(Action(s.street,i,'snapshot',b,b,max(0,total-sum(bets.values())),s.board,False))
            s.last_full_raise=settings['bb_cents']
            self.initialized=True
        else:
            highest=max(s.bets.values(),default=0)
            ordered=len(changes)==1
            for i in changes:
                old=s.bets.get(i,0); amount=bets[i]; delta=amount-old
                kind='raise' if highest>0 and amount>highest else 'bet' if highest==0 else 'call'
                if s.street=='preflop' and amount<=settings['bb_cents'] and not s.actions: kind='blind'
                if not ordered: kind='unknown'
                if ordered and amount>highest and amount-highest>=s.last_full_raise:
                    s.last_full_raise=amount-highest
                self.append(Action(s.street,i,kind,delta,amount,max(0,total-increments),s.board,ordered))
                s.committed[i]=s.committed.get(i,0)+delta
            if not ordered and changes: s.notes.append('同一快照有多名玩家下注变化：行动先后未知')
        for i,status in s.statuses.items():
            if self.last_statuses.get(i) in ('active','allin') and status=='folded':
                self.append(Action(s.street,i,'fold',0,bets.get(i,0),total,s.board))
        self.last_statuses=dict(s.statuses)
        s.bets=bets; s.total_pot=total; self.last_pot=total
        self.confirmed_stacks=dict(s.stacks)
        s.highest=max(bets.values(),default=0)
        hero_i=settings['hero_seat']; hero_stack=s.stacks.get(hero_i,0)
        s.call=min(hero_stack,max(0,s.highest-bets.get(hero_i,0)))
        for i in occupied:
            if s.statuses[i]=='active' and s.stacks.get(i)==0: s.statuses[i]='allin'
        if not s.complete_history: s.notes.append('历史不完整：范围分析使用默认先验')
        if any(a.kind=='unknown' for a in s.actions): s.notes.append('部分行动顺序未知，不能可靠重建加注树')
        return s

def side_pots(contributions, eligible):
    """Each layer includes folded money; only non-folded contributors can win."""
    levels=sorted(set(v for v in contributions.values() if v>0)); previous=0; pots=[]
    for level in levels:
        payers=[i for i,v in contributions.items() if v>=level]
        amount=(level-previous)*len(payers)
        pots.append((amount,tuple(i for i in payers if i in eligible)))
        previous=level
    return pots
