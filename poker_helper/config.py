import json
import sys
from pathlib import Path

ROOT = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
ASSETS = Path(getattr(sys, '_MEIPASS', ROOT))
SEATS = ['BOTTOM_LEFT', 'MID_LEFT', 'TOP_LEFT', 'TOP_MID_L', 'TOP_MID_R',
         'TOP_RIGHT', 'MID_RIGHT', 'BOTTOM_RIGHT', 'BOTTOM_MID']
NAMES = ['左下', '正左', '左上', '顶部左', '顶部右', '右上', '正右', '右下', '正下']
DEFAULT_BOARD = [dict(left=x,top=y,width=w,height=h) for x,y,w,h in
                 ((855,448,50,73),(910,450,51,70),(965,449,52,71),(1020,449,52,73),(1075,449,53,74))]
DEFAULTS = dict(hero_seat=8, bb_cents=10, pot_mode='unknown', monitor=1,
                reference_width=1920, reference_height=1080, offset_x=0, offset_y=0,
                stable_frames=3, iterations=1200, rake_pct=0.0, rake_cap_cents=0,
                dealer_seat=None, statuses=['unknown']*9)

def read_json(name, fallback):
    for base in (ROOT, ASSETS):
        path = base / name
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    return fallback

def load_settings():
    return {**DEFAULTS, **read_json('helper_settings.json', {})}

def load_coords():
    coords = read_json('table_coords.json', {})
    coords.setdefault('COMMUNITY_BOXES', DEFAULT_BOARD)
    return coords

def save_json(name, data):
    path = ROOT / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
