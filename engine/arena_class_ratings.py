"""Static Firestone class aggregates, queried offline; no runtime network I/O.
Aggregation/ranking follows justfaked/hs-decktracker-linux classstats.py (MIT).
"""
import json
from fractions import Fraction
from pathlib import Path
from .arena import CLASS_NAMES


def aggregate(data):
    if not isinstance(data,dict) or not isinstance(data.get('stats'),list) or len(data['stats'])>10000:raise ValueError('职业统计结构无效')
    out={}
    for entry in data['stats']:
        cls=entry['playerClass'].upper().replace('-','').replace('_','').replace(' ','')
        games,wins=entry['totalGames'],entry['totalsWins']
        if cls not in CLASS_NAMES or type(games) is not int or type(wins) is not int or not 0<=wins<=games<=10**12:raise ValueError('职业统计数值无效')
        row=out.setdefault(cls,dict(totalGames=0,totalsWins=0))
        row['totalGames']+=games;row['totalsWins']+=wins
    if not out:raise ValueError('职业统计为空')
    return out


class ClassRatings:
    def __init__(self,path=None,data=None):
        self.error='';self.mode_errors={}
        try:
            raw=data if data is not None else json.loads((path or Path(__file__).with_name('arena_class_ratings.json')).read_text())
            if raw['schema']!=1 or not isinstance(raw.get('modes'),dict):raise ValueError('职业评分版本无效')
            self.data=dict(raw,modes={})
            for mode in ('arena','arena-underground'):
                try:
                    value=raw['modes'][mode];classes=value['classes']
                    aggregate(dict(stats=[dict(playerClass=cls,**row) for cls,row in classes.items()]))
                    self.data['modes'][mode]=value
                except (ValueError,KeyError,TypeError,AttributeError) as exc:self.mode_errors[mode]=str(exc)
            self.error='; '.join(k+': '+v for k,v in self.mode_errors.items())
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            self.error=str(exc);self.data=dict(modes={})

    def get(self,underground,cls):
        classes=self.data['modes'].get('arena-underground' if underground else 'arena',{}).get('classes',{})
        rows={c:r for c,r in classes.items() if r['totalGames']>0}
        if cls not in rows:return None
        rates={c:Fraction(r['totalsWins'],r['totalGames']) for c,r in rows.items()};rate=rates[cls]
        return dict(winrate=float(rate),games=rows[cls]['totalGames'],wins=rows[cls]['totalsWins'],rank=1+sum(v>rate for v in rates.values()),of=len(rows))

    def metadata(self):
        return dict(source=self.data.get('source','Firestone (unavailable)'),captured_at=self.data.get('captured_at',''),
                    modes={m:{k:v for k,v in r.items() if k!='classes'} for m,r in self.data['modes'].items()},error=self.error,mode_errors=dict(self.mode_errors))
