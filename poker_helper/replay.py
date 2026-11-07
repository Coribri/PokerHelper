"""JSON observation replay. `python -m poker_helper.replay examples/hand_replay.json`."""
from dataclasses import asdict
import json
import sys
from pathlib import Path
from .config import DEFAULTS
from .vision import Reading, money
from .state import PokerStreetTracker
from .analysis import analyze

def replay(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    settings={**DEFAULTS,**data.get('settings',{})}
    now=[0.0]; tracker=PokerStreetTracker(log=False,clock=lambda:now[0]); results=[]
    for index,frame in enumerate(data['frames']):
        now[0]=float(frame.get('time',index))
        settings.update(frame.get('settings',{}))
        readings={name:Reading(tuple(frame.get(name,[]))) for name in ('hero','board')}
        readings['pot']=Reading(money(str(frame['pot']))) if frame.get('pot') is not None else Reading(error='底池未知')
        for kind in ('stack','bet'):
            for seat,value in frame.get(kind+'s',{}).items():
                readings[f'{kind}_{seat}']=Reading(money(str(value))) if value is not None else Reading(error='识别失败')
        state=tracker.update(readings,frame.get('dealer',settings.get('dealer_seat')),settings)
        report=analyze(state,settings)
        results.append({'frame':index,'time':now[0],'state':asdict(state),'report':asdict(report)})
    return results

def main():
    if len(sys.argv)<2: raise SystemExit('用法：python -m poker_helper.replay 输入.json [输出.json]')
    result=replay(sys.argv[1]); text=json.dumps(result,ensure_ascii=False,indent=2)
    if len(sys.argv)>2: Path(sys.argv[2]).write_text(text,encoding='utf-8')
    else: print(text)

if __name__=='__main__': main()
