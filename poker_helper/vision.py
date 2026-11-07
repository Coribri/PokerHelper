"""Field-specific glyph matching. No inferred decimal points or suit fallbacks."""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import cv2
import numpy as np
from .config import ASSETS, SEATS, load_coords
from .cards import validate

@dataclass(frozen=True)
class Reading:
    value: object = None
    raw: str = ''
    confidence: float = 0.0
    error: str = ''

def money(text):
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', text):
        raise ValueError('金额格式不完整')
    return int(Decimal(text)*100)

def white_mask(img, dim=False):
    if img is None or not img.size: return np.zeros((1,1),np.uint8)
    low=70 if dim else 105
    lo=img.min(axis=2); hi=img.max(axis=2)
    return ((lo>=low)&((hi.astype(int)-lo.astype(int))<80)).astype(np.uint8)*255

def tight(mask):
    points=cv2.findNonZero(mask)
    if points is None: return None
    x,y,w,h=cv2.boundingRect(points)
    return mask[y:y+h,x:x+w]

def glyph_similarity(a,b):
    if a is None or b is None: return 0.0
    # Preserve aspect: a small dot must never match a large numeral.
    ar=a.shape[1]/a.shape[0]; br=b.shape[1]/b.shape[0]
    if abs(np.log(ar/br))>0.65: return 0.0
    a=cv2.resize(a,(24,32),interpolation=cv2.INTER_AREA)/255.0
    b=cv2.resize(b,(24,32),interpolation=cv2.INTER_AREA)/255.0
    return float(2*np.minimum(a,b).sum()/max(1,(a.sum()+b.sum())))

class ScreenParser:
    def __init__(self):
        self.coords=load_coords()
        self.templates={}
        for group in ('digits','bets_digits','dim_digits','hero','board'):
            self.templates[group]={}
            for path in (ASSETS/'templates'/group).glob('*.png'):
                img=cv2.imread(str(path))
                if img is None: continue
                key='.' if path.stem=='dot' else path.stem
                if group in ('hero','board'):
                    self.templates[group][key]=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
                else:
                    mask=white_mask(img,group=='dim_digits')
                    if key=='.':
                        n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
                        if n>1:
                            best=1+int(np.argmax(stats[1:,4])); mask=(labels==best).astype(np.uint8)*255
                    self.templates[group][key]=tight(mask)
        self.dealer=cv2.imread(str(ASSETS/'templates/dealer.png'),cv2.IMREAD_GRAYSCALE)

    def crop(self,screen,box,settings):
        if not box: return None
        h,w=screen.shape[:2]
        sx=w/settings['reference_width']; sy=h/settings['reference_height']
        x=int(box['left']*sx+settings['offset_x']); y=int(box['top']*sy+settings['offset_y'])
        bw=round(box['width']*sx); bh=round(box['height']*sy)
        if x<0 or y<0 or x+bw>w or y+bh>h: return None
        region=screen[y:y+bh,x:x+bw]
        if not region.size: return None
        return cv2.resize(region,(box['width'],box['height']),interpolation=cv2.INTER_AREA)

    def amount(self,crop,group='bets_digits',allow_blank=False,decimal_required=True):
        if crop is None: return Reading(error='缺少坐标或区域超出屏幕')
        mask=white_mask(crop,group=='dim_digits')
        # Currency symbols are green; detect and remove the symbol only when present.
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        green=cv2.inRange(hsv,np.array([30,65,60]),np.array([100,255,255]))
        n,labels,stats,_=cv2.connectedComponentsWithStats(green)
        coins=[s for s in stats[1:] if s[4]>=12 and s[0]<crop.shape[1]*0.7 and 5<=s[2]<=28 and 5<=s[3]<=28 and 0.65<s[2]/s[3]<1.6]
        if coins:
            coin=max(coins,key=lambda s:s[4]); mask[:,:coin[0]+coin[2]+1]=0
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask)
        parts=[(tuple(s), (labels==i).astype(np.uint8)*255) for i,s in enumerate(stats[1:],1) if s[4]>=2]
        if not parts:
            return Reading(0,'',1.0) if allow_blank else Reading(error='未识别到金额')
        main=[s for s,_ in parts if s[3]>=6 and s[4]>=8]
        if not main: return Reading(error='数字不完整')
        baseline=int(np.median([s[1]+s[3] for s in main]))
        typical=float(np.median([s[3] for s in main]))
        tokens=[]; scores=[]
        for (x,y,w,h,area),part in sorted(parts,key=lambda p:p[0][0]):
            glyph=part[y:y+h,x:x+w]
            if h>=6 and (x+w>=crop.shape[1] or y+h>=crop.shape[0]):
                return Reading(raw=''.join(tokens),error='数字贴近裁剪边界，可能被截断')
            # Tiny dots accepted only at the text baseline, never at the top of icons.
            if h<=max(5,typical*0.35) and w<=6:
                if tokens and y+h>=baseline-3 and y+h<=baseline+4:
                    score=glyph_similarity(glyph,self.templates[group].get('.'))
                    if score<0.60: return Reading(raw=''.join(tokens),error='小数点模板匹配不明确')
                    tokens.append('.'); scores.append(score)
                elif tokens: return Reading(raw=''.join(tokens),error='存在未解释的小字符')
                continue
            ranked=sorted(((glyph_similarity(glyph,t),c) for c,t in self.templates[group].items() if c!='.'),reverse=True)
            if not ranked: return Reading(error=f'缺少 {group} 模板')
            best,ch=ranked[0]; margin=best-ranked[1][0] if len(ranked)>1 else best
            if best<0.70 or margin<0.015:
                if not tokens and best<0.55: continue  # leading non-numeric label/currency only
                return Reading(raw=''.join(tokens)+'?',confidence=best,error='数字匹配不明确')
            tokens.append(ch); scores.append(best)
        raw=''.join(tokens)
        # Existing table format uses decimal currency, so a missing dot is unknown.
        if decimal_required and '.' not in raw:
            return Reading(raw=raw,confidence=min(scores,default=0),error='缺少小数点；不猜金额')
        try: cents=money(raw)
        except (ValueError,InvalidOperation): return Reading(raw=raw,error='金额格式不完整')
        return Reading(cents,raw,min(scores,default=0))

    def card_match(self,gray,group,kind):
        keys='23456789TJQKA' if kind=='rank' else 'shdc'
        hits=[]
        for key in keys:
            template=self.templates[group].get(key)
            if template is None or any(a<b for a,b in zip(gray.shape,template.shape)): continue
            result=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
            _,score,_,loc=cv2.minMaxLoc(result)
            hits.append((score,key,loc,template.shape))
        hits.sort(reverse=True)
        if len(hits)<2 or hits[0][0]<0.78 or hits[0][0]-hits[1][0]<0.04:
            return None
        return hits[0]

    def hero(self,screen,settings):
        crop=self.crop(screen,self.coords.get('HERO_HAND'),settings)
        if crop is None: return Reading(error='手牌坐标无效')
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        # The existing persistent hand box has two cards side by side.
        result=[]; scores=[]
        for sub in (gray[:,:gray.shape[1]//2],gray[:,gray.shape[1]//2:]):
            rank=self.card_match(sub,'hero','rank'); suit=self.card_match(sub,'hero','suit')
            if not rank or not suit: return Reading(error='手牌点数或花色不明确')
            result.append(rank[1]+suit[1]); scores.extend((rank[0],suit[0]))
        if len(set(result))<2: return Reading(error='识别到重复手牌')
        return Reading(tuple(result),' '.join(result),min(scores))

    def board(self,screen,settings):
        result=[]; scores=[]; blank=False
        for box in self.coords['COMMUNITY_BOXES']:
            crop=self.crop(screen,box,settings)
            if crop is None: return Reading(error='公共牌坐标无效')
            gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
            rank=self.card_match(gray,'board','rank'); suit=self.card_match(gray,'board','suit')
            # White card background distinguishes unoccupied slots from uncertain cards.
            present=float(np.mean((crop.min(axis=2)>175)))>0.20
            if not rank or not suit:
                if present: return Reading(error='公共牌存在但识别不明确')
                blank=True; continue
            if blank: return Reading(error='公共牌识别存在空隙')
            result.append(rank[1]+suit[1]); scores.extend((rank[0],suit[0]))
        if len(result) not in (0,3,4,5) or len(set(result))!=len(result):
            return Reading(error='公共牌数量或唯一性校验失败')
        return Reading(tuple(result),' '.join(result),min(scores,default=1.0))

    def parse(self,screen,settings):
        readings={'hero':self.hero(screen,settings),'board':self.board(screen,settings)}
        # Prefer calibrated numeric-only POT; POT_BOX is the legacy wider label region.
        readings['pot']=self.amount(self.crop(screen,self.coords.get('POT') or self.coords.get('POT_BOX'),settings),'digits')
        for i,seat in enumerate(SEATS):
            crop=self.crop(screen,self.coords.get('STACK_'+seat),settings)
            stack=self.amount(crop,'bets_digits')
            if stack.value is None and self.templates['dim_digits']:
                stack=self.amount(crop,'dim_digits')
            readings[f'stack_{i}']=stack
            readings[f'bet_{i}']=self.amount(self.crop(screen,self.coords.get('BET_'+seat),settings),'bets_digits',allow_blank=True)
        dealer=settings.get('dealer_seat')
        if dealer is None and self.dealer is not None:
            gray=cv2.cvtColor(screen,cv2.COLOR_BGR2GRAY)
            sx=screen.shape[1]/settings['reference_width']; sy=screen.shape[0]/settings['reference_height']
            tmpl=cv2.resize(self.dealer,None,fx=sx,fy=sy)
            res=cv2.matchTemplate(gray,tmpl,cv2.TM_CCOEFF_NORMED)
            _,score,_,loc=cv2.minMaxLoc(res)
            if score>=0.85:
                centers=[]
                for i,seat in enumerate(SEATS):
                    box=self.coords.get('STACK_'+seat)
                    if box: centers.append(((box['left']+box['width']/2)*sx+settings['offset_x'],(box['top']+box['height']/2)*sy+settings['offset_y'],i))
                if centers:
                    cx=loc[0]+tmpl.shape[1]/2; cy=loc[1]+tmpl.shape[0]/2
                    nearest=min(centers,key=lambda p:(p[0]-cx)**2+(p[1]-cy)**2)
                    if (nearest[0]-cx)**2+(nearest[1]-cy)**2<(160*max(sx,sy))**2: dealer=nearest[2]
        return readings,dealer

    def diagnostics(self,screen,settings,path):
        path=Path(path); path.mkdir(parents=True,exist_ok=True)
        import json
        readings,dealer=self.parse(screen,settings)
        cv2.imwrite(str(path/'screen.png'),screen)
        for key,box in self.coords.items():
            if isinstance(box,dict) and 'left' in box:
                crop=self.crop(screen,box,settings)
                if crop is not None: cv2.imwrite(str(path/(key+'.png')),crop)
        (path/'readings.json').write_text(json.dumps({'dealer':dealer,'fields':{k:asdict(v) for k,v in readings.items()}},ensure_ascii=False,indent=2),encoding='utf-8')
