"""Synthetic, dependency-free source/confirmation/trigger demonstration."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from cuetrail_governance import confirmation as h

p = h.p
text = '每当我询问「恢复检查」时，请遵守以下步骤：\n1. 先核对备份来源。\n2. 不要删除副本，除非恢复验证全部通过。'
advice = p.Source('advice', 'demo', 'user', 's1', 'assistant', text, 1)
approval = p.Source('approval', 'demo', 'user', 's2', 'user', h.PREFIX + text, 2)
sources = {v.id: v for v in (advice, approval)}
native = set(sources)
program, _ = p.compile_source(advice)
request = p.parse_request('请按既定程序处理「恢复检查」。', namespace='demo', subject_id='user', request_id='r1')
without, before = h.select([program], [], request, sources.__getitem__, native)
assert before['accepted'] is False
habit, reason = h.compile_confirmation(program, approval, sources.__getitem__, native)
assert reason == 'valid'
stored = h.serialize_habits([habit], sources.__getitem__, native)
reopened = h.deserialize_habits(stored, sources.__getitem__, native)
receipt, decision = h.select([program], reopened, request, sources.__getitem__, native)
assert decision['accepted'] and receipt.selected == (('confirmed_habit', habit.id),)
rendered, result = h.render(receipt, [program], reopened, request, sources.__getitem__, native)
assert result['accepted']
print(json.dumps(dict(unconfirmed_advice_applies=before['accepted'], confirmed_program_applies=decision['accepted'],
    proposal_role=habit.proposal.source.role, confirmation_role=habit.confirmation_source.role,
    complete_actions=[asdict(action) for action in habit.proposal.actions],
    behavior_independently_observed=habit.behavior_independently_observed,
    executes_steps=receipt.executes_steps, adopts_long_term_rule=receipt.adopts_long_term_rule,
    new_model_calls=0), ensure_ascii=False, indent=2))
