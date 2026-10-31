"""Choose original context/action regions;preserve comma lists and dependent clauses."""
from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import re
import sys

from . import source_view as span
SPAN_FILE=Path(span.__file__)
SPAN_SHA256='559b6e7931932794ff8306c9ea9b6e4fa4337c217da3bbb39d2f052f28b74204'
assert hashlib.sha256(SPAN_FILE.read_bytes()).hexdigest()==SPAN_SHA256
evidence = span.evidence
EVIDENCE = span.EVIDENCE
EVIDENCE_SHA256 = span.EVIDENCE_SHA256
PointerError = span.PointerError
SCHEMA_VERSION = 1
MAX_UNITS = 64
PUNCTUATION = re.compile(r'[;；。！？!?\n]+|(?<!\d)\.(?=\s|$)')
STEP = re.compile(r'\bthen\b', re.I)

COMMA = re.compile(r'[,，]')
LEADING_CONTEXT = re.compile(r"^\s*(?:(?:[A-Z][a-z]+(?:[ '-][A-Z][a-z]+){0,2}|[\u4e00-\u9fff]{2,8}):\s*)?(?:when\b|whenever\b|before\b|after\b|during\b|for\b|if\b|unless\b|while\b|given\b|because\b|due to\b|当|如果|由于|因为|每当|为了)", re.I)
ACTION_START = re.compile(r'^\s*(?:I\b|we\b|please\b|first\b|then\b|我)', re.I)
DEPENDENT = re.compile(r'^\s*(?:and\b|or\b|nor\b|except\b|excluding\b|without\b|but not\b|only if\b|unless\b|以及|或者|但是|但|除了|除外|和)', re.I)


def region_boundaries(text):
    # Commas inside lists/exceptions stay inside one action region. Split a
    # leading context only at a comma followed by explicit personal/step syntax.
    major=sorted({0,len(text),*[m.end() for m in PUNCTUATION.finditer(text)]})
    boundaries=set(major)
    for start,end in zip(major,major[1:]):
        chunk=text[start:end]
        if LEADING_CONTEXT.match(chunk):
            for comma in COMMA.finditer(chunk):
                if ACTION_START.match(chunk[comma.end():]):
                    boundaries.add(start+comma.end());break
    boundaries.update(m.start() for m in STEP.finditer(text))
    return sorted(boundaries)



@dataclass(frozen=True)
class Unit:
    id: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class View:
    id: str
    text: str
    window_start: int
    units: tuple[Unit, ...]
    canonical_binding: str


def view(source):
    original = span.view(source)
    boundaries = region_boundaries(original.text)
    units = []
    for start, end in zip(boundaries, boundaries[1:]):
        # Whitespace trimming preserves all non-whitespace original characters;
        # punctuation belongs to the preceding unit and step markers to the next.
        while start < end and original.text[start].isspace():
            start += 1
        while end > start and original.text[end - 1].isspace():
            end -= 1
        if start < end:
            if units and DEPENDENT.match(original.text[start:end]):
                # A conjunction/exception fragment depends on the preceding
                # region;retain the complete contiguous original including its
                # punctuation and whitespace instead of inventing missing text.
                prior=units.pop()
                start=prior.start
            units.append(Unit('c' + str(len(units)), start, end, original.text[start:end]))
    if not units or len(units) > MAX_UNITS:
        raise PointerError('complete_unit_budget')
    nonspace = ''.join(char for unit in units for char in unit.text if not char.isspace())
    if nonspace != ''.join(char for char in original.text if not char.isspace()):
        raise PointerError('unit_partition_lost_original_text')
    identity = span.digest(['governed-region-v1', original.id,
        [(u.id, u.start, u.end, u.text) for u in units]])
    return View(identity, original.text, original.window_start, tuple(units), original.canonical_binding)


def source_payload(source):
    v = view(source)
    return dict(HISTORICAL_SOURCE=dict(source_id=source['id'], role=source['role'],
        view_id=v.id, original_text=v.text, source_regions={u.id:u.text for u in v.units}))


def schema(source):
    v = view(source)
    ref = dict(type='string', enum=[u.id for u in v.units])
    fields = dict(view_id=dict(type='string', enum=[v.id]), condition_unit=ref, scope_unit=ref,
        action_units=dict(type='array', items=ref, minItems=1, maxItems=6),
        kind=dict(type='string', enum=['conditional_constraint', 'habit', 'ordered_procedure']))
    return dict(type='object', properties=dict(procedures=dict(type='array', minItems=0, maxItems=2,
        items=dict(type='object', properties=fields, required=list(fields), additionalProperties=False))),
        required=['procedures'], additionalProperties=False)


def resolve(unit_id, v):
    by_id = {u.id:u for u in v.units}
    if not isinstance(unit_id, str) or unit_id not in by_id:
        raise PointerError('unknown_complete_unit')
    unit = by_id[unit_id]
    return dict(unit_id=unit.id, quote=unit.text,
        start=v.window_start+unit.start, end=v.window_start+unit.end)


def materialize(pointer, source):
    v = view(source)
    if not isinstance(pointer, dict) or set(pointer) != {'view_id', 'condition_unit', 'scope_unit', 'action_units', 'kind'}:
        raise PointerError('complete_unit_pointer_schema')
    if pointer['view_id'] != v.id:
        raise PointerError('stale_or_foreign_view')
    if not isinstance(pointer['action_units'], list) or not 1 <= len(pointer['action_units']) <= 6:
        raise PointerError('action_count')
    condition, scope = resolve(pointer['condition_unit'], v), resolve(pointer['scope_unit'], v)
    actions = [resolve(unit_id, v) for unit_id in pointer['action_units']]
    if not (evidence.LINK.search(condition['quote']) or evidence.CONTINGENT.match(condition['quote'])):
        raise PointerError('condition_unit_not_contextual')
    if any(DEPENDENT.match(a['quote']) for a in actions):
        raise PointerError('orphaned_dependent_action_region')
    if any(v.text.find(a['quote']) != a['start']-v.window_start for a in actions):
        raise PointerError('backend_action_occurrence_mismatch')
    draft = dict(source_id=source['id'], condition_quote=condition['quote'], scope_quote=scope['quote'],
        action_quotes=[a['quote'] for a in actions], connecting_quote=v.text, kind=pointer['kind'])
    procedure, reason = evidence.validate_draft(draft, source)
    if procedure is None:
        raise PointerError(reason)
    return dict(representation='governed-region-v1', pointer_schema=SCHEMA_VERSION,
        pointer=pointer, draft=draft, procedure_id=procedure.id,
        canonical_binding=v.canonical_binding, view_id=v.id,
        condition=condition, scope=scope, actions=actions,
        original_window=dict(start=v.window_start, end=v.window_start+len(v.text),
            sha256=hashlib.sha256(v.text.encode()).hexdigest()),
        evidence_contract_sha256=EVIDENCE_SHA256,
        binding_contract_sha256=SPAN_SHA256,
        pointer_contract_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def revalidate(record, fresh_source):
    if not isinstance(record, dict) or 'pointer' not in record:
        raise PointerError('record_schema')
    rebuilt = materialize(record['pointer'], fresh_source)
    if rebuilt != record:
        raise PointerError('pointer_record_changed')
    return rebuilt['draft']


def encode_fixture(draft, source):
    """CPU fixture oracle; models choose whole IDs without this helper."""
    v = view(source)
    if draft['connecting_quote'] != v.text or draft['source_id'] != source['id']:
        raise PointerError('fixture_not_full_current_window')
    def unit_for(quote):
        units = [u.id for u in v.units if quote in u.text]
        if len(units) != 1:
            raise PointerError('fixture_not_in_unique_complete_unit')
        return units[0]
    return dict(view_id=v.id, condition_unit=unit_for(draft['condition_quote']),
        scope_unit=unit_for(draft['scope_quote']),
        action_units=list(dict.fromkeys(unit_for(q) for q in draft['action_quotes'])), kind=draft['kind'])
