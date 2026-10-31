"""Action-head authority attachment over immutable local relationship proofs."""
import hashlib,importlib.util
from pathlib import Path
import re,sys

from . import relations as parent
PARENT=Path(parent.__file__)
PIN='b007cc750829dfff8a08c3de7f40ff2785a235553e984598d311d6b9d164b671'
assert hashlib.sha256(PARENT.read_bytes()).hexdigest()==PIN
backend=parent.backend;g=parent.g
DISCOURSE=re.compile(r'^\s*(?:(?:User|Human|用户)\s*[:：]\s*)?for\s+(?:instance|example|starters|one|that matter)\b',re.I)
# Anchor at the original action region's start,not an arbitrary later clause.
CONSTRAINT_HEAD=re.compile(r"^\s*(?:(?:I|we)\s+(?:must(?:n't)?|cannot|can't|have to|need you to|do not|don't)\b|(?:please|make sure|ensure)\b|我(?:必须|不能|不要|避免))",re.I)
HABIT_HEAD=re.compile(r'^\s*(?:(?:I|we)\s+(?:always|usually|typically|normally|routinely)\b|我(?:通常|总是|习惯))',re.I)
DISCOURSE_MODAL=re.compile(r"^\s*(?:I|we)\s+(?:must\s+(?:admit|say|confess|mention)\b|(?:cannot|can't)\s+(?:begin to express|help but|wait to)\b)",re.I)


def materialize(pointer,source):
    original=parent.materialize(pointer,source)
    if DISCOURSE.search(original['condition']['quote']):
        raise backend.PointerError('discourse_marker_not_applicability_scope')
    actions=original['actions'];heads=[]
    if pointer['kind']=='conditional_constraint':
        for action in actions:
            match=CONSTRAINT_HEAD.match(action['quote'])
            if match is None:raise backend.PointerError('constraint_not_at_action_head')
            if DISCOURSE_MODAL.match(action['quote']):raise backend.PointerError('discourse_modal_not_action_constraint')
            heads.append(dict(start=action['start']+match.start(),end=action['start']+match.end(),quote=match.group()))
    elif pointer['kind']=='habit':
        # Multiple independent action regions cannot borrow one routine marker.
        for action in actions:
            match=HABIT_HEAD.match(action['quote'])
            if match is None:raise backend.PointerError('habit_not_at_action_head')
            heads.append(dict(start=action['start']+match.start(),end=action['start']+match.end(),quote=match.group()))
    result=dict(original,representation='local-action-head-witness-v2',authority_heads=heads,
        parent_contract_sha256=PIN,validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return result


def revalidate(record,source):
    if not isinstance(record,dict) or 'pointer' not in record:raise backend.PointerError('action_head_record_schema')
    fresh=materialize(record['pointer'],source)
    if fresh!=record:raise backend.PointerError('action_head_record_or_source_changed')
    return fresh['draft']
