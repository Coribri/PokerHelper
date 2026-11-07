"""Offscreen GUI verification with example observations; never starts capture."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PyQt5 import QtWidgets, QtGui
from poker_helper.config import ROOT, DEFAULTS
from poker_helper.vision import Reading
from poker_helper.ui import StakeQuantHUD
from poker_helper.state import State, Action
from poker_helper.analysis import Report
from poker_helper.replay import replay

app=QtWidgets.QApplication([])
for font in ('C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/arial.ttf'):
    if Path(font).exists(): QtGui.QFontDatabase.addApplicationFont(font)
app.setFont(QtGui.QFont('Microsoft YaHei',10))
window=StakeQuantHUD(start_worker=False)
result=replay(ROOT/'examples/hand_replay.json')[-1]
settings={**DEFAULTS,**__import__('json').loads((ROOT/'examples/hand_replay.json').read_text())['settings']}
window.hero.setCurrentIndex(settings['hero_seat']); window.dealer.setCurrentIndex(window.dealer.findData(settings['dealer_seat']))
window.pot_mode.setCurrentIndex(window.pot_mode.findData(settings['pot_mode']))
for i,box in enumerate(window.status_boxes): box.setCurrentIndex(box.findData(settings['statuses'][i]))
data=result['state']; data['actions']=[Action(**a) for a in data['actions']]
readings={f'{key}_{i}':Reading(v) for key,values in (('stack',data['stacks']),('bet',data['bets'])) for i,v in values.items()}
window.render(State(**data),Report(**result['report']),readings)
window.show(); app.processEvents()
path=ROOT/'diagnostics/ui_preview.png'; path.parent.mkdir(exist_ok=True)
window.grab().save(str(path)); print(path)
window.close()
