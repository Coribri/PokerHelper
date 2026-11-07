import copy
from datetime import datetime
import json
import threading
import time
import traceback
import cv2
import mss
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from .config import ROOT, NAMES, load_settings, save_json, load_coords
from .vision import ScreenParser
from .state import PokerStreetTracker
from .analysis import analyze, Report

STATUS=[('未确认','unknown'),('在局内','active'),('已弃牌','folded'),('全下','allin'),('空座','empty')]
STREET_NAMES={'preflop':'翻前','flop':'翻牌','turn':'转牌','river':'河牌'}

class Worker(QtCore.QThread):
    result=QtCore.pyqtSignal(object,object,object)
    failure=QtCore.pyqtSignal(str)
    diagnostic=QtCore.pyqtSignal(str)
    def __init__(self,settings):
        super().__init__(); self.lock=threading.Lock(); self.settings=settings
        self.reset_requested=False; self.diagnostic_requested=False; self.reload_requested=False
    def configure(self,settings):
        with self.lock: self.settings=copy.deepcopy(settings); self.reload_requested=True
    def request_reset(self):
        with self.lock: self.reset_requested=True
    def request_diagnostics(self):
        with self.lock: self.diagnostic_requested=True
    def run(self):
        parser=ScreenParser(); tracker=PokerStreetTracker(); signature=None; report=Report()
        try:
            with mss.MSS() as capture:
                while not self.isInterruptionRequested():
                    started=time.monotonic()
                    with self.lock:
                        settings=copy.deepcopy(self.settings)
                        reset=self.reset_requested; diagnostic=self.diagnostic_requested; reload=self.reload_requested
                        self.reset_requested=False; self.diagnostic_requested=False; self.reload_requested=False
                    if reset or reload:
                        tracker.reset(); parser.coords=load_coords(); signature=None
                    try:
                        monitor=min(max(1,settings['monitor']),len(capture.monitors)-1)
                        screen=cv2.cvtColor(np.array(capture.grab(capture.monitors[monitor])),cv2.COLOR_BGRA2BGR)
                        readings,dealer=parser.parse(screen,settings)
                        state=tracker.update(readings,dealer,settings)
                        current=state.signature()
                        if current!=signature:
                            report=analyze(copy.deepcopy(state),settings); signature=current
                        self.result.emit(copy.deepcopy(state),copy.deepcopy(report),readings)
                        if diagnostic:
                            path=ROOT/'diagnostics'/datetime.now().strftime('%Y%m%d_%H%M%S')
                            parser.diagnostics(screen,settings,path); self.diagnostic.emit(str(path))
                    except Exception as exc:
                        path=ROOT/'logs'; path.mkdir(exist_ok=True)
                        with (path/'errors.log').open('a',encoding='utf-8') as f: f.write(traceback.format_exc()+'\n')
                        self.failure.emit(str(exc))
                    self.msleep(max(10,round((0.65-(time.monotonic()-started))*1000)))
        except Exception as exc: self.failure.emit(str(exc))

class CoordinateEditor(QtWidgets.QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle('坐标校准（参考分辨率坐标）'); self.resize(700,680)
        layout=QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel('沿用原坐标。移动/缩放后可先调整参考分辨率和偏移。'))
        self.coords=load_coords(); self.keys=[]
        for key,value in self.coords.items():
            if isinstance(value,dict) and 'left' in value: self.keys.append((key,None))
        for i,box in enumerate(self.coords['COMMUNITY_BOXES']): self.keys.append(('COMMUNITY_BOXES',i))
        self.table=QtWidgets.QTableWidget(len(self.keys),5); self.table.setHorizontalHeaderLabels(['区域','X','Y','宽','高'])
        for row,(key,index) in enumerate(self.keys):
            box=self.coords[key] if index is None else self.coords[key][index]
            item=QtWidgets.QTableWidgetItem(key if index is None else f'公共牌 {index+1}')
            item.setFlags(item.flags()&~QtCore.Qt.ItemIsEditable); self.table.setItem(row,0,item)
            for col,field in enumerate(('left','top','width','height'),1): self.table.setItem(row,col,QtWidgets.QTableWidgetItem(str(box[field])))
        self.table.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.table)
        buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
    def save(self):
        try:
            for row,(key,index) in enumerate(self.keys):
                box=self.coords[key] if index is None else self.coords[key][index]
                for col,field in enumerate(('left','top','width','height'),1):
                    value=int(self.table.item(row,col).text())
                    if value<0 or (field in ('width','height') and value==0): raise ValueError('坐标必须非负，宽高必须大于零')
                    box[field]=value
            save_json('table_coords.json',self.coords); self.accept()
        except ValueError as exc: QtWidgets.QMessageBox.information(self,'坐标无效',str(exc))

class StakeQuantHUD(QtWidgets.QWidget):
    def __init__(self,start_worker=True):
        super().__init__(); self.settings=load_settings(); self.worker=None; self.readings={}; self.last_hand_id=None
        # Persist rules/geometry, never persist last session's fold/all-in decisions.
        self.settings['statuses']=['unknown']*9
        self.settings['statuses'][self.settings['hero_seat']]='active'
        self.setWindowTitle('PokerHelper v2 · 范围分析'); self.resize(1120,800)
        self.setWindowFlags(self.windowFlags()|QtCore.Qt.WindowStaysOnTopHint)
        self.setStyleSheet('''QWidget {background:#101a27;color:#dfebf6;font-family:"Microsoft YaHei";font-size:12px;}
            QPushButton,QComboBox,QSpinBox,QDoubleSpinBox{background:#223448;border:1px solid #435970;padding:5px;border-radius:4px;}
            QPushButton:hover{background:#34516c;} QTextBrowser,QTableWidget{background:#142232;border:1px solid #34485e;}
            QHeaderView::section{background:#223448;padding:5px;}''')
        main=QtWidgets.QVBoxLayout(self)
        title=QtWidgets.QLabel('PokerHelper v2  |  九人桌范围分析与牌面解释')
        title.setStyleSheet('font-size:19px;font-weight:bold;color:#82e4db;'); main.addWidget(title)
        main.addWidget(QtWidgets.QLabel('输入连续确认后才分析 · 策略为启发式范围模型 · 尚未接入 GTO 求解器'))
        controls=QtWidgets.QHBoxLayout()
        self.hero=QtWidgets.QComboBox(); self.dealer=QtWidgets.QComboBox(); self.dealer.addItem('自动识别庄位',None)
        for i,name in enumerate(NAMES): self.hero.addItem(f'{i+1} {name}',i); self.dealer.addItem(f'{i+1} {name}',i)
        self.hero.setCurrentIndex(self.settings['hero_seat']); self.dealer.setCurrentIndex(self.dealer.findData(self.settings['dealer_seat']))
        self.pot_mode=QtWidgets.QComboBox()
        for text,value in [('底池含义未确认','unknown'),('中央已含当轮下注','total'),('中央仅含已收筹码','collected')]: self.pot_mode.addItem(text,value)
        self.pot_mode.setCurrentIndex(self.pot_mode.findData(self.settings['pot_mode']))
        self.bb=QtWidgets.QDoubleSpinBox(); self.bb.setRange(0.01,100000); self.bb.setDecimals(2); self.bb.setValue(self.settings['bb_cents']/100)
        for label,widget in [('自己',self.hero),('庄位',self.dealer),('底池',self.pot_mode),('大盲',self.bb)]: controls.addWidget(QtWidgets.QLabel(label)); controls.addWidget(widget)
        main.addLayout(controls)
        horizontal=QtWidgets.QSplitter()
        left=QtWidgets.QWidget(); ll=QtWidgets.QVBoxLayout(left); ll.setContentsMargins(0,0,0,0)
        self.seats=QtWidgets.QTableWidget(9,5); self.seats.setHorizontalHeaderLabels(['座位','状态确认','剩余','当轮下注','位置']); self.status_boxes=[]
        for i,name in enumerate(NAMES):
            self.seats.setItem(i,0,QtWidgets.QTableWidgetItem(f'{i+1} {name}')); box=QtWidgets.QComboBox()
            for text,value in STATUS: box.addItem(text,value)
            box.setCurrentIndex(box.findData(self.settings['statuses'][i])); self.status_boxes.append(box); self.seats.setCellWidget(i,1,box)
        self.seats.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.seats.verticalHeader().hide(); self.seats.setMinimumHeight(320)
        for row in range(9): self.seats.setRowHeight(row,31)
        self.seats.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents); ll.addWidget(self.seats)
        button=QtWidgets.QPushButton('确认全桌在局内（随后标记弃牌/空座）'); button.clicked.connect(self.all_active); ll.addWidget(button)
        ll.addWidget(QtWidgets.QLabel('每手重新核对状态；不会从筹码亮暗猜测弃牌。'))
        self.ranges=QtWidgets.QTextBrowser(); ll.addWidget(self.ranges); horizontal.addWidget(left)
        right=QtWidgets.QWidget(); rl=QtWidgets.QVBoxLayout(right); rl.setContentsMargins(0,0,0,0)
        self.cards_label=QtWidgets.QLabel('手牌：等待 | 公共牌：等待'); self.cards_label.setWordWrap(True); rl.addWidget(self.cards_label)
        self.metrics=QtWidgets.QLabel('底池 / 跟注 / 权益：等待'); self.metrics.setWordWrap(True); rl.addWidget(self.metrics)
        self.action=QtWidgets.QLabel('等待可靠信息'); self.action.setWordWrap(True); self.action.setStyleSheet('font-size:20px;color:#ffd280;font-weight:bold;'); rl.addWidget(self.action)
        self.reason=QtWidgets.QTextBrowser(); rl.addWidget(self.reason,2)
        self.threat=QtWidgets.QTextBrowser(); rl.addWidget(self.threat,2)
        self.history=QtWidgets.QTextBrowser(); rl.addWidget(self.history,1)
        horizontal.addWidget(right); horizontal.setSizes([440,650]); main.addWidget(horizontal,1)
        advanced=QtWidgets.QHBoxLayout()
        self.ref_w=QtWidgets.QSpinBox(); self.ref_w.setRange(320,10000); self.ref_w.setValue(self.settings['reference_width'])
        self.ref_h=QtWidgets.QSpinBox(); self.ref_h.setRange(200,10000); self.ref_h.setValue(self.settings['reference_height'])
        self.off_x=QtWidgets.QSpinBox(); self.off_x.setRange(-10000,10000); self.off_x.setValue(self.settings['offset_x'])
        self.off_y=QtWidgets.QSpinBox(); self.off_y.setRange(-10000,10000); self.off_y.setValue(self.settings['offset_y'])
        self.rake=QtWidgets.QDoubleSpinBox(); self.rake.setRange(0,20); self.rake.setValue(self.settings['rake_pct']*100); self.rake.setSuffix('%')
        self.rake_cap=QtWidgets.QDoubleSpinBox(); self.rake_cap.setRange(0,100000); self.rake_cap.setValue(self.settings['rake_cap_cents']/100)
        self.monitor=QtWidgets.QSpinBox(); self.monitor.setRange(1,16); self.monitor.setValue(self.settings['monitor'])
        for label,widget in [('参考宽',self.ref_w),('高',self.ref_h),('偏移X',self.off_x),('Y',self.off_y),('屏幕',self.monitor),('抽水',self.rake),('封顶(0无)',self.rake_cap)]: advanced.addWidget(QtWidgets.QLabel(label)); advanced.addWidget(widget)
        main.addLayout(advanced); buttons=QtWidgets.QHBoxLayout()
        for text,handler in [('应用设置',self.apply_settings),('新一手 / 重置',self.reset_hand),('编辑坐标',self.edit_coords),('保存识别诊断',self.diagnostics),('识别详情',self.show_readings)]:
            button=QtWidgets.QPushButton(text); button.clicked.connect(handler); buttons.addWidget(button)
        self.pause=QtWidgets.QPushButton('暂停'); self.pause.setCheckable(True); self.pause.toggled.connect(self.pause_analysis); buttons.addWidget(self.pause); main.addLayout(buttons)
        self.status_label=QtWidgets.QLabel('首次使用：确认底池含义、大盲、庄位和各座位状态，然后应用设置。'); self.status_label.setWordWrap(True); main.addWidget(self.status_label)
        if start_worker: self.start_worker()
    def start_worker(self):
        self.worker=Worker(copy.deepcopy(self.settings)); self.worker.result.connect(self.render); self.worker.failure.connect(self.on_error)
        self.worker.diagnostic.connect(self.diagnostic_done); self.worker.start()
    def all_active(self):
        for box in self.status_boxes: box.setCurrentIndex(box.findData('active'))
        self.apply_settings()
    def collect_settings(self):
        return {**self.settings,'hero_seat':self.hero.currentData(),'dealer_seat':self.dealer.currentData(),
                'pot_mode':self.pot_mode.currentData(),'bb_cents':round(self.bb.value()*100),'statuses':[b.currentData() for b in self.status_boxes],
                'reference_width':self.ref_w.value(),'reference_height':self.ref_h.value(),'offset_x':self.off_x.value(),'offset_y':self.off_y.value(),
                'monitor':self.monitor.value(),'rake_pct':self.rake.value()/100,'rake_cap_cents':round(self.rake_cap.value()*100)}
    def apply_settings(self):
        settings=self.collect_settings()
        reset=any(settings[k]!=self.settings[k] for k in ('hero_seat','dealer_seat','pot_mode','bb_cents','reference_width','reference_height','offset_x','offset_y','monitor'))
        self.settings=settings; save_json('helper_settings.json',settings)
        if self.worker:
            with self.worker.lock:
                self.worker.settings=copy.deepcopy(settings)
                if reset: self.worker.reset_requested=True
        self.status_label.setText('设置已保存。等待连续确认。')
    def reset_hand(self):
        for i,box in enumerate(self.status_boxes): box.setCurrentIndex(box.findData('active' if i==self.hero.currentData() else 'unknown'))
        self.apply_settings()
        if self.worker: self.worker.request_reset()
    def edit_coords(self):
        if CoordinateEditor(self).exec_()==QtWidgets.QDialog.Accepted and self.worker: self.worker.configure(self.settings)
    def diagnostics(self):
        if self.worker: self.worker.request_diagnostics()
    def diagnostic_done(self,path):
        self.status_label.setText('诊断已保存：'+path); QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
    def show_readings(self):
        from dataclasses import asdict
        dialog=QtWidgets.QDialog(self); dialog.setWindowTitle('识别候选、置信度与失败原因'); dialog.resize(720,620)
        layout=QtWidgets.QVBoxLayout(dialog); text=QtWidgets.QPlainTextEdit(); text.setReadOnly(True)
        text.setPlainText(json.dumps({k:asdict(v) for k,v in self.readings.items()},ensure_ascii=False,indent=2)); layout.addWidget(text); dialog.exec_()
    def pause_analysis(self,paused):
        if paused and self.worker:
            self.worker.requestInterruption(); self.worker.wait(); self.worker=None; self.action.setText('已暂停'); self.pause.setText('继续')
        elif not paused: self.pause.setText('暂停'); self.start_worker()
    def on_error(self,message):
        self.action.setText('分析暂停：发生错误'); self.metrics.setText('当前指标无效'); self.reason.setPlainText(message); self.status_label.setText('详情已写入 logs/errors.log')
    def render(self,state,report,readings):
        self.readings=readings
        if self.last_hand_id is not None and state.hand_id!=self.last_hand_id and any('检测到新手牌' in i for i in state.issues):
            for i,box in enumerate(self.status_boxes): box.setCurrentIndex(box.findData('active' if i==self.settings['hero_seat'] else 'unknown'))
            self.apply_settings()
        self.last_hand_id=state.hand_id
        self.cards_label.setText(f'{STREET_NAMES[state.street]} | 手牌 {" ".join(state.hero) or "--"} | 公共牌 {" ".join(state.board) or "未发牌"}')
        eq='--' if report.equity is None else f'{report.equity:.1%}'
        interval='' if report.interval is None else f'（抽样区间 {report.interval[0]:.1%}–{report.interval[1]:.1%}）'
        required='--' if report.required is None else f'{report.required:.1%}'; ev='--' if report.ev is None else f'{report.ev:+.2f}'
        self.metrics.setText(f'底池 {state.total_pot/100:.2f} | 需跟注 {state.call/100:.2f}\n范围权益 {eq} {interval}\n所需权益 {required} | 条件跟注 EV {ev} | 模型置信度 {report.confidence}')
        self.action.setText(report.action); self.reason.setPlainText('\n\n'.join(report.reasons)); self.threat.setPlainText('牌面与手牌分析\n\n'+'\n\n'.join(report.warnings))
        self.ranges.setPlainText('对手范围（按组合权重汇总的前八类）\n\n'+'\n\n'.join(f'{seat+1} {NAMES[seat]}: {summary}' for seat,summary in report.ranges.items())+'\n\n抽样区间仅描述模拟误差，不包含范围假设误差。')
        kinds={'raise':'加注到','bet':'下注到','call':'跟注到','fold':'弃牌','unknown':'下注变化（顺序未知）','blind':'盲注','snapshot':'当前下注（前序未知）'}
        self.history.setPlainText('已确认行动（不会猜测过牌）\n'+'\n'.join(f'{STREET_NAMES[a.street]} {a.seat+1}号 {kinds[a.kind]} {a.total/100:.2f}' for a in state.actions[-12:]))
        for i in range(9):
            for col,key in ((2,f'stack_{i}'),(3,f'bet_{i}')):
                reading=readings.get(key); text='--' if reading is None or reading.value is None else f'{reading.value/100:.2f}'
                self.seats.setItem(i,col,QtWidgets.QTableWidgetItem(text))
            self.seats.setItem(i,4,QtWidgets.QTableWidgetItem(state.positions.get(i,'--')))
        self.status_label.setText(f'第 {state.hand_id} 手 | '+('输入未通过校验，建议已暂停。' if state.issues else f'{report.samples} 次范围模拟；请确认轮到你行动。'))
    def closeEvent(self,event):
        if self.worker: self.worker.requestInterruption(); self.worker.wait()
        event.accept()

def main():
    import sys
    if '--self-check' in sys.argv:
        import os
        os.environ['QT_QPA_PLATFORM']='offscreen'
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app=QtWidgets.QApplication(sys.argv)
    if '--self-check' in sys.argv:
        parser=ScreenParser(); window=StakeQuantHUD(start_worker=False)
        result={'templates':{k:len(v) for k,v in parser.templates.items()},
                'community_regions':len(parser.coords['COMMUNITY_BOXES']),
                'ui_rows':window.seats.rowCount(),'version':2}
        assert all(result['templates'][g]==11 for g in ('digits','bets_digits','dim_digits'))
        assert result['community_regions']==5 and result['ui_rows']==9
        save_json('self_check_result.json',result); window.close(); return 0
    window=StakeQuantHUD(); window.show(); return app.exec_()
