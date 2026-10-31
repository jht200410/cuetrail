"""Bind a model-chosen condition to adjacent,locally governed original actions.

CPU prototype. Full original evidence remains intact. This is a conservative
syntactic witness,not semantic entailment,habit confirmation or advice adoption.
"""
import hashlib,importlib.util
from pathlib import Path
import re,sys

from . import regions as backend
REGIONS=Path(backend.__file__)
PIN='131a622374c7331ef156333a2095de7775f5a64fe2c447d8f756bea6b8e3999a'
assert hashlib.sha256(REGIONS.read_bytes()).hexdigest()==PIN
g=backend.evidence
FIRST=re.compile(r'\bfirst\b|^\s*(?:1[.)]|[-*])\s',re.I)
STEP=re.compile(r'^\s*(?:then\b|next\b|finally\b|\d+[.)]\s|[-*]\s)',re.I)
LIMITER=re.compile(r'^\s*(?:only\b|except\b|unless\b|provided\b|otherwise\b|however\b|but\b|not\b|never\b|仅|只有|只在|除非|不过|但是|但)',re.I)
REPORTED=re.compile(r'\b(?:says|said|told|according to|was advised|asked me to)\b|(?:他说|她说|老师说|据说)',re.I)
MIXED=re.compile(r'\b(?:assistant|chatbot|agent|bot)\s*:|助手[：:]|助理[：:]',re.I)


def materialize(pointer,source):
    # Keep the complete-unit,polarity,exception,source identity and offset checks.
    original=backend.materialize(pointer,source);v=backend.view(source)
    condition=original['condition'];actions=original['actions']
    if not backend.LEADING_CONTEXT.match(condition['quote']):
        raise backend.PointerError('condition_not_explicit_leading_context')
    if not condition['quote'].rstrip().endswith((',', '，')):
        raise backend.PointerError('condition_not_bounded_context_clause')
    if pointer['scope_unit']!=pointer['condition_unit']:
        raise backend.PointerError('scope_not_bound_to_context_unit')
    indexes={unit.id:index for index,unit in enumerate(v.units)}
    ci=indexes[pointer['condition_unit']];ai=[indexes[sid] for sid in pointer['action_units']]
    if ai!=list(range(ci+1,ci+1+len(ai))):
        raise backend.PointerError('actions_not_adjacent_after_context')
    if ai[-1]+1<len(v.units) and LIMITER.match(v.units[ai[-1]+1].text):
        raise backend.PointerError('following_governing_qualifier_unresolved')
    if source['role']=='user' and (g.REPORTED.search(v.text) or REPORTED.search(v.text) or MIXED.search(v.text)):
        raise backend.PointerError('whole_window_attribution_unresolved')
    # Markers elsewhere in the full window cannot authorize an unrelated action.
    action_text=v.text[v.units[ai[0]].start:v.units[ai[-1]].end]
    kind=pointer['kind']
    if kind=='conditional_constraint':
        marker=g.CONSTRAINT.search(action_text)
        if marker is None:raise backend.PointerError('constraint_not_governing_local_actions')
    elif kind=='habit':
        marker=g.SELF_HABIT.search(action_text)
        if marker is None:raise backend.PointerError('habit_not_reported_in_local_action')
    else:
        if len(ai)<2 or not FIRST.search(actions[0]['quote']) or not all(STEP.match(a['quote']) for a in actions[1:]):
            raise backend.PointerError('ordered_steps_not_locally_explicit')
        marker=g.SELF_HABIT.search(action_text) or g.PERSONAL.search(action_text) or g.REQUEST.search(action_text)
        if source['role']=='user' and marker is None:
            raise backend.PointerError('ordered_actions_not_personal_or_requested')
    start=condition['start'];end=actions[-1]['end']
    local=source['content'][start:end]
    draft=dict(original['draft'],connecting_quote=local)
    procedure,reason=g.validate_draft(draft,source)
    if procedure is None:raise backend.PointerError(reason)
    action_start=actions[0]['start']
    return dict(representation='local-governor-witness-v1',pointer=pointer,draft=draft,
        procedure_id=procedure.id,source_id=source['id'],source_role=source['role'],
        source_sha256=hashlib.sha256(source['content'].encode()).hexdigest(),
        local_relation=dict(start=start,end=end,quote=local),condition=condition,actions=actions,
        authority_witness=None if marker is None else dict(start=action_start+marker.start(),end=action_start+marker.end(),quote=marker.group()),
        original_window=original['original_window'],canonical_binding=v.canonical_binding,
        authority=procedure.authority,lifetime=procedure.lifetime,source_basis=procedure.source_basis,
        full_original_retained=True,automatic_adoption=False,backend_sha256=PIN,
        validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def revalidate(record,source):
    if not isinstance(record,dict) or 'pointer' not in record:raise backend.PointerError('relation_record_schema')
    rebuilt=materialize(record['pointer'],source)
    if rebuilt!=record:raise backend.PointerError('local_relation_or_source_changed')
    return rebuilt['draft']
