from collections import Counter
from itertools import combinations

RANKS = '23456789TJQKA'
SUITS = 'shdc'
DECK = tuple(r+s for r in RANKS for s in SUITS)
VALUES = {r:i+2 for i,r in enumerate(RANKS)}
LABELS = ['高牌', '一对', '两对', '三条', '顺子', '同花', '葫芦', '四条', '同花顺']

def validate(cards):
    if any(c not in DECK for c in cards) or len(cards) != len(set(cards)):
        raise ValueError('牌面包含无效或重复牌')

def straight(values):
    values = set(values)
    if 14 in values:
        values.add(1)
    return next((h for h in range(14,4,-1) if set(range(h-4,h+1)) <= values), 0)

def evaluate(cards):
    """Comparable fixed-length tuples; direct 5–7 card evaluation."""
    values = [VALUES[c[0]] for c in cards]
    counts = Counter(values)
    groups = sorted(((n,r) for r,n in counts.items()), reverse=True)
    by_suit = {s: sorted((VALUES[c[0]] for c in cards if c[1]==s), reverse=True) for s in SUITS}
    flushes = [v for v in by_suit.values() if len(v)>=5]
    sf = max((straight(v) for v in flushes), default=0)
    if sf: result = (8,sf)
    elif groups[0][0]==4:
        q=groups[0][1]; result=(7,q,max(r for r in values if r!=q))
    elif groups[0][0]>=3 and len(groups)>1 and groups[1][0]>=2:
        result=(6,groups[0][1],groups[1][1])
    elif flushes: result=(5,*max(tuple(v[:5]) for v in flushes))
    elif straight(values): result=(4,straight(values))
    elif groups[0][0]==3:
        t=groups[0][1]; result=(3,t,*sorted((r for r in counts if r!=t),reverse=True)[:2])
    elif len(groups)>1 and groups[0][0]==groups[1][0]==2:
        a,b=sorted((groups[0][1],groups[1][1]),reverse=True)
        result=(2,a,b,max((r for r in counts if r not in (a,b)),default=0))
    elif groups[0][0]==2:
        p=groups[0][1]; result=(1,p,*sorted((r for r in counts if r!=p),reverse=True)[:3])
    else: result=(0,*sorted(counts,reverse=True)[:5])
    return result + (0,)*(6-len(result))

def shorthand(hand):
    a,b=sorted(hand,key=lambda c:VALUES[c[0]],reverse=True)
    return a[0]+b[0]+('' if a[0]==b[0] else 's' if a[1]==b[1] else 'o')

def warnings(hero, board):
    if len(board)<3: return ['翻前：先确认位置、盲注与行动历史。']
    validate(hero+board)
    out=[]
    suits=Counter(c[1] for c in board); ranks=Counter(c[0] for c in board)
    for suit,n in suits.items():
        if n>=3:
            out.append(f'公共牌有 {n} 张 {dict(s="♠",h="♥",d="♦",c="♣")[suit]}：'+
                       ('对手两张该花色可成同花。' if n==3 else '对手一张该花色即可成同花。' if n==4 else '公共牌已成同花，比较最高五张。'))
            held=[c for c in hero if c[1]==suit]
            if held: out.append('你的同花阻断牌：'+' '.join(held)+'；阻断不代表对手没有同花。')
    if max(ranks.values())>=2:
        out.append('公共牌配对：葫芦/四条可能成立；顺子、同花也可能落后。')
    remaining=[c for c in DECK if c not in hero+board]
    examples=[]
    for combo in combinations(remaining,2):
        if evaluate(board+list(combo))[0]==4:
            key=shorthand(combo)
            if key not in examples: examples.append(key)
        if len(examples)>=5: break
    if examples: out.append('可成顺子的对手组合示例：'+ '、'.join(examples)+'（不等于对手实际持有）。')
    if len(board)<5 and len(hero)==2:
        base=evaluate(hero+board)
        flush_outs=[]; straight_outs=[]
        for c in remaining:
            score=evaluate(hero+board+[c])
            if score>base and score[0] in (5,8) and base[0]<5: flush_outs.append(c)
            if score>base and score[0] in (4,8) and base[0]<4: straight_outs.append(c)
        if flush_outs: out.append(f'下一张可成同花的牌：{len(flush_outs)} 张。')
        if straight_outs: out.append(f'下一张可成顺子的牌：{len(straight_outs)} 张。')
        if flush_outs or straight_outs: out.append('以上为成牌张数，不保证获胜；须扣除对手更强成牌和反超风险。')
    if len(hero)==2:
        own=evaluate(hero+board)
        out.insert(0, '当前最佳牌型：'+LABELS[own[0]])
        if len(board)==5 and own==evaluate(board): out.append('你在使用公共牌最佳五张，牌型名称不代表独有优势。')
    return out or ['未发现明显同花、配对或已成顺子结构，仍需结合对手范围。']
