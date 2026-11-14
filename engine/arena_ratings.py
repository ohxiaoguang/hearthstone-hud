"""Local, versioned factual score snapshot. No runtime rating network requests."""
import json
import math
from pathlib import Path

class ArenaRatings:
    def __init__(self, path=None, data=None):
        self.error=''
        try:
            self.data=data if data is not None else json.loads((path or Path(__file__).with_name('arena_ratings.json')).read_text())
            if not isinstance(self.data,dict):raise ValueError('评分格式错误')
            if self.data.get('schema')!=1 or not isinstance(self.data.get('classes'),dict):raise ValueError('评分格式错误')
            for table in self.data['classes'].values():
                if not isinstance(table,dict):raise ValueError('职业评分格式错误')
                for entry in table.values():
                    if not isinstance(entry,dict):raise ValueError('卡牌评分格式错误')
                    score=entry['score']
                    if type(score) not in (int,float) or not math.isfinite(score) or not isinstance(entry['tier'],str):raise ValueError('评分值无效')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.error=str(exc);self.data=dict(classes={},source='不可用',captured_at='')

    def get(self, cls, cid):
        for key in (cls,'NEUTRAL'):
            table=self.data['classes'].get(key,{})
            for candidate in (cid,cid.removeprefix('CORE_')):
                if candidate in table:return dict(table[candidate],rating_class=key)
        return None

    def metadata(self):
        return {k:self.data.get(k,'') for k in ('source','url','captured_at','source_sha256')} | dict(entries=sum(len(v) for v in self.data['classes'].values()),error=self.error)
