"""Synthetic, standard-library explicit-withdrawal and source-history example."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cuetrail_governance import withdrawal as w

p = w.p
text = '每当我询问「恢复检查」时，请遵守以下步骤：\n1. 先核对备份来源。\n2. 不要删除副本，除非恢复验证全部通过。'
original = p.Source('original', 'demo', 'user', 's1', 'user', text, 1)
withdrawal_source = p.Source('withdrawal', 'demo', 'user', 's2', 'user', w.PREFIX+text, 2)
sources = {v.id:v for v in (original, withdrawal_source)}
native = set(sources)
program = p.compile_source(original)[0]
request = p.parse_request('请按既定程序处理「恢复检查」。', namespace='demo', subject_id='user', request_id='r1')
old, before = w.select([program], [], [], request, sources.__getitem__, native)
assert before['accepted']
event, reason = w.compile_withdrawal(program, withdrawal_source, sources.__getitem__, native)
assert reason == 'valid'
snapshot = w.serialize([program], [], [event], sources.__getitem__, native)
reopened = w.deserialize(snapshot, sources.__getitem__, native)
receipt, after = w.select(*reopened, request, sources.__getitem__, native)
assert not after['accepted'] and receipt.selected == ()
stale, _ = w.render(old, *reopened, request, sources.__getitem__, native)
assert stale == ''
history = p.parse_request('回顾我关于「恢复检查」的程序。', namespace='demo', subject_id='user', request_id='r2')
historical_receipt, _ = w.select(*reopened, history, sources.__getitem__, native)
rendered, decision = w.render(historical_receipt, *reopened, history, sources.__getitem__, native)
assert decision['accepted']
card = json.loads(rendered)[0]
print(json.dumps(dict(before_withdrawal_applies=before['accepted'], after_withdrawal_applies=after['accepted'],
    stale_receipt_rejected=stale=='', historical_status=card['applicability'],
    original_source=card['evidence']['source']['id'], withdrawal_source=card['withdrawals'][0]['source']['id'],
    creates_replacement=event.creates_replacement, executes_steps=receipt.executes_steps, model_calls=0), ensure_ascii=False, indent=2))
