from dataclasses import dataclass, field
from .cards import warnings, evaluate, LABELS, shorthand
from .ranges import make_range, simulate
from .state import side_pots

@dataclass
class Report:
    action: str='等待可靠信息'
    reasons: list=field(default_factory=list)
    warnings: list=field(default_factory=list)
    ranges: dict=field(default_factory=dict)
    equity: object=None
    interval: object=None
    required: object=None
    ev: object=None
    spr: dict=field(default_factory=dict)
    confidence: str='低'
    samples: int=0

def analyze(state,settings):
    hero=list(state.hero); board=list(state.board)
    report=Report(warnings=warnings(hero,board) if hero else ['等待手牌'])
    if state.issues:
        report.reasons=list(state.issues); return report
    hero_i=settings['hero_seat']
    opponents=[s for s,v in state.statuses.items() if s!=hero_i and v in ('active','allin')]
    if not opponents:
        report.action='牌局已无对手'; report.reasons=['等待下一手。']; return report
    if state.stacks.get(hero_i,0)==0:
        report.action='你已全下，等待摊牌'; return report
    ranges={}
    for seat in opponents:
        actions=[a for a in state.actions if a.seat==seat]
        ranges[seat]=make_range(hero,board,state.positions.get(seat,'unknown'),actions,settings['bb_cents'])
        report.ranges[seat]=ranges[seat].summary()
        report.spr[seat]=min(state.stacks[hero_i],state.stacks.get(seat,0))/max(1,state.total_pot)
    equity=simulate(hero,board,ranges,settings['iterations'])
    report.equity=equity.equity
    report.interval=(max(0,equity.equity-1.96*equity.stderr),min(1,equity.equity+1.96*equity.stderr))
    report.samples=equity.iterations
    report.reasons=list(dict.fromkeys(state.notes))
    report.reasons.append('范围来自可解释的启发式先验和已观察行动，尚未接入 GTO 求解器。')
    call=state.call; pot=state.total_pot
    if call:
        final=pot+call
        rake=min(round(final*settings['rake_pct']),settings['rake_cap_cents']) if settings['rake_cap_cents'] else round(final*settings['rake_pct'])
        report.required=call/max(1,final-rake)
        # An incomplete ledger cannot establish eligibility for uneven all-in pots.
        short=state.highest-state.bets.get(hero_i,0)>state.stacks[hero_i]
        unequal_allin=any(state.statuses[i]=='allin' and state.bets.get(i,0)!=state.highest for i in opponents)
        layered=short or unequal_allin
        if layered:
            if not state.complete_history:
                report.action='边池投入不完整，暂停建议'
                report.reasons.append('请从发牌前开始记录；中途快照无法还原各玩家的底池资格。')
                report.required=None; return report
            contributions=dict(state.committed); contributions[hero_i]=contributions.get(hero_i,0)+call
            pots=side_pots(contributions,[hero_i,*opponents])
            if sum(p for p,_ in pots)!=final:
                report.action='边池与底池不一致，暂停建议'; report.required=None; return report
            # Refund singleton layers before applying rake; hero cannot win another player's uncalled excess.
            # Uncalled singleton layers never alter the hero's eligibility. Rake is allocated
            # proportionally across all layers here; platform-specific policies need config.
            contest=pots
            gross=sum(a for a,_ in contest)
            adjusted=[(a*(1-rake/max(1,gross)),eligible) for a,eligible in contest]
            payout=simulate(hero,board,ranges,settings['iterations'],pots=adjusted,hero_seat=hero_i)
            ev=payout.equity-call
            report.required=None
            report.reasons.append('已按整手投入分层计算主池/边池权益；假设其余玩家不再追加。')
        else: ev=equity.equity*(final-rake)-call
        report.ev=ev/100
        interval_low,interval_high=report.interval
        if len(board)==5 or state.stacks[hero_i]==call:
            if ev>0: report.action=f'条件下倾向跟注 {call/100:.2f}'
            else: report.action='条件下倾向弃牌'
            report.reasons.append('EV 假设此后没有加注；仍有玩家可行动时需重新评估。')
        else:
            marginal=abs(ev)<=1.96*payout.stderr if layered else interval_low<=report.required<=interval_high
            report.action='边缘决策，需评估下一轮' if marginal else (
                f'倾向跟注 {call/100:.2f}，保留后续评估' if ev>0 else '倾向弃牌')
            report.reasons.append('这里的 EV 是直接摊牌基准：翻牌/转牌继续下注会改变实际价值。')
        threshold='分层底池按各层资格计算，没有统一权益门槛' if layered else f'含抽水所需权益 {report.required:.1%}'
        report.reasons.append(f'需跟注 {call/100:.2f}；当前底池 {pot/100:.2f}；{threshold}。')
        report.reasons.append('未计算加注收益，不能据此断定跟注优于加注。')
    else:
        if not board:
            # Use the existing explicit position priors only for clearly unopened scenarios.
            from .priors import PREFLOP_RFI_9MAX
            position=state.positions.get(hero_i,'unknown').replace('BTN/SB','BTN')
            freq=PREFLOP_RFI_9MAX.get(position,{}).get(shorthand(hero),0)
            raises=[a for a in state.actions if a.street=='preflop' and a.kind in ('raise','bet','unknown')]
            if state.complete_history and not raises and state.highest<=settings['bb_cents']:
                report.action='考虑开池加注' if freq>0 else '可过牌，手牌不在默认开池范围'
                report.reasons.append(f'默认 {position} 开池先验频率 {freq:.0%}；这是人工范围表，不是求解结果。')
            else: report.action='可过牌；翻前行动不足以确定加注策略'
        else:
            score=evaluate(hero+board)
            report.action='可过牌；评估价值下注' if equity.equity>0.70 and score[0]>=1 else '可过牌；保留摊牌或听牌价值'
            report.reasons.append('价值下注取决于会跟注的更差手牌；当前权益不等于下注收益。')
        report.reasons.append('未观察到下注不代表所有对手已经过牌；请确认轮到你行动。')
    report.confidence='中低（范围假设）' if state.complete_history else '低（历史不完整）'
    if not board and state.complete_history and state.highest<=settings['bb_cents'] and not any(
        a.kind in ('raise','bet','unknown','snapshot') for a in state.actions):
        from .priors import PREFLOP_RFI_9MAX
        position=state.positions.get(hero_i,'unknown').replace('BTN/SB','BTN')
        if position!='BB':
            frequency=PREFLOP_RFI_9MAX.get(position,{}).get(shorthand(hero),0)
            report.action='考虑开池加注' if frequency>0 else '默认开池范围外，倾向弃牌'
            report.reasons.append(f'未开池场景：默认 {position} 开池先验频率 {frequency:.0%}，不应只凭对随机手牌权益选择平跟。')
    report.reasons.append('对手筹码与逐人 SPR：'+ '；'.join(f'{i+1}号剩余 {state.stacks[i]/100:.2f} / SPR {report.spr[i]:.2f}' for i in opponents))
    return report
