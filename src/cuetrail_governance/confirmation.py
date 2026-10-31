"""Source-bound explicit confirmations; no model calls or implicit adoption."""
from dataclasses import asdict, dataclass
import json
from typing import Callable
from . import procedure_zh as p

SCHEMA = 'cuetrail.full-source-confirmation.1'
PREFIX = '我确认把以下程序作为今后的固定习惯：\n'


@dataclass(frozen=True)
class ConfirmedHabit:
    id: str
    schema_version: str
    content_version: str
    proposal: p.Procedure
    confirmation_source: p.Source
    confirmation_sha256: str
    confirmation_binding: str
    explicit_intent: p.Span
    quoted_program: p.Span
    authority: str = 'user_confirmed_habit'
    lifetime: str = 'recurring'
    status: str = 'source_grounded'
    source_basis: str = 'explicit_user_confirmation_of_complete_assistant_program'
    behavior_independently_observed: bool = False


@dataclass(frozen=True)
class Receipt:
    schema_version: str
    request_binding: str
    projection_sha256: str
    native_ids_sha256: str
    selected: tuple[tuple[str, str], ...]
    mode: str
    executes_steps: bool = False
    adopts_long_term_rule: bool = False


def compile_confirmation(proposal: p.Procedure, confirmation: p.Source,
                         source_loader: Callable[[str], p.Source], native_ids: set[str]) -> tuple[ConfirmedHabit | None, str]:
    if not isinstance(proposal, p.Procedure) or not isinstance(confirmation, p.Source):
        return None, 'typed_proposal_and_confirmation_required'
    if proposal.source.id == confirmation.id or not {proposal.source.id, confirmation.id} <= native_ids:
        return None, 'two_distinct_native_sources_required'
    try:
        canonical_proposal = source_loader(proposal.source.id)
        canonical_confirmation = source_loader(confirmation.id)
        fresh, _ = p.compile_source(canonical_proposal)
    except (KeyError, TypeError, AttributeError):
        return None, 'canonical_source_unavailable'
    if fresh != proposal or canonical_confirmation != confirmation:
        return None, 'canonical_source_or_version_changed'
    if proposal.source.role != 'assistant' or proposal.authority != 'assistant_suggestion' or confirmation.role != 'user':
        return None, 'assistant_proposal_and_user_confirmation_required'
    if (proposal.source.namespace, proposal.source.subject_id) != (confirmation.namespace, confirmation.subject_id):
        return None, 'different_user_or_namespace'
    if not all(type(value) is str and value for value in (confirmation.id, confirmation.namespace, confirmation.subject_id, confirmation.session_id)):
        return None, 'missing_confirmation_identity'
    if type(proposal.source.timestamp) is not int or type(confirmation.timestamp) is not int or confirmation.timestamp <= proposal.source.timestamp:
        return None, 'confirmation_chronology_unproven'
    if p.TASK.fullmatch(proposal.source.content):
        return None, 'one_time_proposal_not_recurring'
    if confirmation.content != PREFIX + proposal.evidence.quote:
        return None, 'complete_explicit_future_confirmation_required'
    proof = p.digest(asdict(confirmation))
    value = ConfirmedHabit(p.digest([SCHEMA, proposal.id, proof]), SCHEMA, proposal.content_version,
        proposal, confirmation, p.text_sha(confirmation.content), proof,
        p.Span(0, len(PREFIX)-1, PREFIX[:-1]),
        p.Span(len(PREFIX), len(confirmation.content), proposal.evidence.quote))
    return value, 'valid'


def audit_habits(habits: list[ConfirmedHabit], source_loader: Callable[[str], p.Source], native_ids: set[str]) -> str:
    seen = set()
    for habit in habits:
        if habit.id in seen:
            raise ValueError('Duplicate confirmed program')
        seen.add(habit.id)
        rebuilt, reason = compile_confirmation(habit.proposal, habit.confirmation_source, source_loader, native_ids)
        if rebuilt != habit:
            raise ValueError('Confirmation no longer proven: ' + reason)
    return p.digest([asdict(habit) for habit in habits])


def serialize_habits(habits: list[ConfirmedHabit], source_loader: Callable[[str], p.Source], native_ids: set[str]) -> str:
    projection = audit_habits(habits, source_loader, native_ids)
    return json.dumps(dict(schema_version=SCHEMA, projection_sha256=projection, habits=[asdict(h) for h in habits]), ensure_ascii=False, sort_keys=True)


def deserialize_habits(text: str, source_loader: Callable[[str], p.Source], native_ids: set[str]) -> list[ConfirmedHabit]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON confirmation field')
            result[key] = value
        return result
    stored = json.loads(text, object_pairs_hook=unique)
    if set(stored) != {'schema_version', 'projection_sha256', 'habits'} or stored['schema_version'] != SCHEMA:
        raise ValueError('Unsupported confirmation snapshot')
    habits = []
    for item in stored['habits']:
        proposal, _ = p.compile_source(source_loader(item['proposal']['source']['id']))
        confirmation = source_loader(item['confirmation_source']['id'])
        habit, reason = compile_confirmation(proposal, confirmation, source_loader, native_ids)
        # JSON arrays represent the original tuple of action spans; compare the
        # complete canonical JSON binding rather than Python tuple/list types.
        if habit is None or p.digest(asdict(habit)) != p.digest(item):
            raise ValueError('Stored habit differs from canonical confirmation: ' + reason)
        habits.append(habit)
    if audit_habits(habits, source_loader, native_ids) != stored['projection_sha256']:
        raise ValueError('Stored confirmation projection hash differs')
    return habits


def select(programs: list[p.Procedure], habits: list[ConfirmedHabit], request: p.Request,
           source_loader: Callable[[str], p.Source], native_ids: set[str]) -> tuple[Receipt | None, dict]:
    if not isinstance(request, p.Request) or p.parse_request(request.query, namespace=request.namespace,
        subject_id=request.subject_id, request_id=request.id) != request:
        return None, dict(accepted=False, reason='invalid_current_request')
    try:
        projection = p.digest([p.audit(programs, source_loader, native_ids), audit_habits(habits, source_loader, native_ids)])
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, dict(accepted=False, reason='canonical_procedure_or_confirmation_changed')
    entries = [('procedure', v.id, v, v.authority, v.lifetime, v.status) for v in programs]
    entries += [('confirmed_habit', h.id, h.proposal, h.authority, h.lifetime, h.status) for h in habits]
    variants = {}
    for _, _, program, authority, lifetime, _ in entries:
        if authority in ('user_constraint', 'user_confirmed_habit') and lifetime == 'recurring':
            key = program.source.namespace, program.source.subject_id, program.scope.quote
            variants.setdefault(key, set()).add(tuple(a.quote for a in program.actions))
    selected, rejections, used = [], [], set()
    for kind, identity, program, authority, lifetime, status in entries:
        key = program.source.namespace, program.source.subject_id, program.scope.quote
        signature = tuple(a.quote for a in program.actions)
        reason = None
        if key[:2] != (request.namespace, request.subject_id):
            reason = 'different_user_or_namespace'
        elif program.scope.quote != request.scope.quote:
            reason = 'no_exact_current_scope'
        elif request.mode == 'execute' and (authority not in ('user_constraint', 'user_confirmed_habit') or lifetime != 'recurring' or status != 'source_grounded'):
            reason = 'authority_lifetime_or_existing_conflict'
        elif request.mode == 'execute' and len(variants.get(key, set())) > 1:
            reason = 'conflict_across_user_constraints_and_confirmed_habits'
        dedup = (authority, signature) if request.mode == 'historical' else signature
        if reason is None and dedup in used:
            reason = 'duplicate_action_signature'
        if reason is None and len(selected) >= 2:
            reason = 'at_most_two'
        if reason:
            rejections.append(dict(kind=kind, id=identity, reason=reason))
        else:
            selected.append((kind, identity))
            used.add(dedup)
    receipt = Receipt(SCHEMA, p.digest(asdict(request)), projection, p.digest(sorted(native_ids)), tuple(selected), request.mode)
    return receipt, dict(accepted=bool(selected), rejected=rejections, executes_steps=False, adopts_long_term_rule=False)


def render(receipt: Receipt, programs: list[p.Procedure], habits: list[ConfirmedHabit], request: p.Request,
           source_loader: Callable[[str], p.Source], native_ids: set[str], *, max_chars: int = 12000) -> tuple[str, dict]:
    fresh, decision = select(programs, habits, request, source_loader, native_ids)
    if receipt != fresh or not decision['accepted']:
        return '', dict(accepted=False, reason='stale_or_unproven_receipt')
    lookup = {('procedure', v.id): v for v in programs}
    lookup.update({('confirmed_habit', v.id): v for v in habits})
    cards = [dict(kind=kind, evidence=asdict(lookup[kind, identity]),
        display_mode='applicable_user_authority' if request.mode == 'execute' else 'historical_attribution_only',
        executes_steps=False, adopts_long_term_rule=False) for kind, identity in receipt.selected]
    text = json.dumps(cards, ensure_ascii=False, sort_keys=True)
    if type(max_chars) is not int or max_chars < 1 or len(text) > max_chars:
        return '', dict(accepted=False, reason='whole_card_budget_fallback')
    return text, dict(accepted=True, cards=len(cards), executes_steps=False, adopts_long_term_rule=False)
