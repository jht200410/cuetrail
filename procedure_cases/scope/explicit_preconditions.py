"""Synthetic missing/satisfied literal prerequisites; no external state checks."""
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from cuetrail_governance import guarded as g

p=g.p
text='每当我询问「恢复检查」且「环境=隔离；备份=已验证」时，请遵守以下步骤：\n1. 先核对备份来源。\n2. 不要删除副本，除非恢复验证全部通过。'
original=p.Source('program','demo','user','s1','user',text,10)
missing=p.Source('missing','demo','user','s2','user','在「环境=隔离」条件下，请按既定程序处理「恢复检查」。',20)
satisfied=replace(missing,id='satisfied',content='在「备份=已验证；环境=隔离」条件下，请按既定程序处理「恢复检查」。')
sources={v.id:v for v in (original,missing,satisfied)}
native=set(sources)
program,reason=g.compile_source(original)
assert reason=='valid'
missing_request=g.parse_request(missing)
_,before=g.select([program],missing_request,sources.__getitem__,native)
assert not before['accepted']
request=g.parse_request(satisfied)
receipt,after=g.select([program],request,sources.__getitem__,native)
assert after['accepted']
text,result=g.render(receipt,[program],request,sources.__getitem__,native)
assert result['accepted']
card=json.loads(text)[0]
print(json.dumps(dict(missing_condition_applies=before['accepted'],literal_conditions_apply=after['accepted'],
    evidence_basis=card['current_request']['evidence_basis'],external_state_verified=card['external_state_verified'],
    complete_steps=[v['quote'] for v in card['program']['actions']],executes_steps=card['executes_steps'],
    adopts_long_term_rule=card['adopts_long_term_rule'],model_calls=0),ensure_ascii=False,indent=2))
