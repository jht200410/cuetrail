"""Source-bound explicit withdrawals of individual recurring Procedure versions."""
from dataclasses import asdict, dataclass, replace
import json
from typing import Callable

from . import confirmation as h
p = h.p

SCHEMA = 'cuetrail-explicit-withdrawal-v1'
PREFIX = '我撤回以下长期程序：\n'
Target = p.Procedure | h.ConfirmedHabit


@dataclass(frozen=True)
class Withdrawal:
    id: str
    schema_version: str
    target_kind: str
    target_id: str
    content_version: str
    target_binding: str
    source: p.Source
    source_sha256: str
    source_binding: str
    explicit_intent: p.Span
    quoted_program: p.Span
    effect: str = 'withdraw_bound_authority_only'
    creates_replacement: bool = False


@dataclass(frozen=True)
class Receipt:
    schema_version: str
    request_binding: str
    ledger_sha256: str
    native_ids_sha256: str
    selected: tuple[tuple[str, str], ...]
    mode: str
    executes_steps: bool = False
    adopts_long_term_rule: bool = False


def canonical_target(target: Target, source_loader: Callable[[str], p.Source], native_ids: set[str]) -> tuple[str, Target, p.Source, p.Procedure]:
    if isinstance(target, p.Procedure):
        if target.status not in ('source_grounded', 'conflicting') or target.source.id not in native_ids:
            raise ValueError('Unproven direct authority')
        fresh, _ = p.compile_source(source_loader(target.source.id))
        if fresh is None or fresh != replace(target, status='source_grounded'):
            raise ValueError('Direct authority changed')
        if fresh.authority != 'user_constraint' or fresh.lifetime != 'recurring':
            raise ValueError('Only recurring USER authority may be withdrawn')
        return 'procedure', fresh, fresh.source, fresh
    if isinstance(target, h.ConfirmedHabit):
        fresh, reason = h.compile_confirmation(target.proposal, target.confirmation_source, source_loader, native_ids)
        if fresh != target:
            raise ValueError('Unproven confirmed authority: ' + reason)
        return 'confirmed_habit', fresh, fresh.confirmation_source, fresh.proposal
    raise ValueError('Unsupported authority type')


def compile_withdrawal(target: Target, source: p.Source, source_loader: Callable[[str], p.Source],
                       native_ids: set[str]) -> tuple[Withdrawal | None, str]:
    try:
        kind, fresh, authority, program = canonical_target(target, source_loader, native_ids)
        if not isinstance(source, p.Source) or source.id not in native_ids or source_loader(source.id) != source:
            return None, 'withdrawal_source_not_canonical_native'
        if source.role != 'user':
            return None, 'withdrawal_requires_user_authority'
        if not all(type(v) is str and v for v in (source.id, source.namespace, source.subject_id, source.session_id)):
            return None, 'missing_withdrawal_identity'
        if (source.namespace, source.subject_id) != (authority.namespace, authority.subject_id):
            return None, 'different_user_or_namespace'
        if source.id in (authority.id, program.source.id):
            return None, 'independent_withdrawal_source_required'
        if type(source.timestamp) is not int or type(authority.timestamp) is not int or source.timestamp <= authority.timestamp:
            return None, 'withdrawal_must_follow_user_authority'
        if source.content != PREFIX + program.evidence.quote:
            return None, 'complete_literal_program_required'
        source_binding, target_binding = p.digest(asdict(source)), p.digest(asdict(fresh))
        value = Withdrawal(p.digest([SCHEMA, kind, fresh.id, target_binding, source_binding]), SCHEMA, kind,
            fresh.id, fresh.content_version, target_binding, source, p.text_sha(source.content), source_binding,
            p.Span(0, len(PREFIX)-1, PREFIX[:-1]), p.Span(len(PREFIX), len(source.content), program.evidence.quote))
        return value, 'valid'
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, 'target_authority_not_proven'


def audit_ledger(programs: list[p.Procedure], habits: list[h.ConfirmedHabit], withdrawals: list[Withdrawal],
                 source_loader: Callable[[str], p.Source], native_ids: set[str]) -> str:
    programs_hash = p.audit(programs, source_loader, native_ids)
    habits_hash = h.audit_habits(habits, source_loader, native_ids)
    targets = {('procedure', v.id): v for v in programs}
    targets.update({('confirmed_habit', v.id): v for v in habits})
    seen = set()
    for value in withdrawals:
        if not isinstance(value, Withdrawal) or value.id in seen:
            raise ValueError('Duplicate or unsupported withdrawal')
        seen.add(value.id)
        target = targets.get((value.target_kind, value.target_id))
        fresh, reason = compile_withdrawal(target, value.source, source_loader, native_ids)
        if fresh != value:
            raise ValueError('Withdrawal no longer supported: ' + reason)
    return p.digest([SCHEMA, programs_hash, habits_hash, [asdict(v) for v in withdrawals]])


def effective_inventory(programs: list[p.Procedure], habits: list[h.ConfirmedHabit], withdrawals: list[Withdrawal], mode: str):
    if mode == 'historical':
        return programs, habits
    withdrawn = {(w.target_kind, w.target_id) for w in withdrawals}
    # Conflict flags are a projection of the current inventory, never authority.
    remaining = [replace(v, status='source_grounded' if v.source.role == 'user' else 'unconfirmed')
                 for v in programs if ('procedure', v.id) not in withdrawn]
    return p.govern_versions(remaining), [v for v in habits if ('confirmed_habit', v.id) not in withdrawn]


def select(programs: list[p.Procedure], habits: list[h.ConfirmedHabit], withdrawals: list[Withdrawal], request: p.Request,
           source_loader: Callable[[str], p.Source], native_ids: set[str]) -> tuple[Receipt | None, dict]:
    if not isinstance(request, p.Request) or p.parse_request(request.query, namespace=request.namespace,
        subject_id=request.subject_id, request_id=request.id) != request:
        return None, dict(accepted=False, reason='invalid_current_request')
    try:
        ledger_hash = audit_ledger(programs, habits, withdrawals, source_loader, native_ids)
        active_programs, active_habits = effective_inventory(programs, habits, withdrawals, request.mode)
        base, decision = h.select(active_programs, active_habits, request, source_loader, native_ids)
        if base is None:
            return None, dict(accepted=False, reason='effective_inventory_not_proven')
        receipt = Receipt(SCHEMA, p.digest(asdict(request)), ledger_hash, p.digest(sorted(native_ids)), base.selected, request.mode)
        return receipt, dict(accepted=decision['accepted'], rejected=decision.get('rejected', []),
            withdrawn_authorities=sorted({(v.target_kind, v.target_id) for v in withdrawals}),
            executes_steps=False, adopts_long_term_rule=False)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, dict(accepted=False, reason='canonical_ledger_or_withdrawal_changed')


def render(receipt: Receipt, programs: list[p.Procedure], habits: list[h.ConfirmedHabit], withdrawals: list[Withdrawal],
           request: p.Request, source_loader: Callable[[str], p.Source], native_ids: set[str], *, max_chars: int = 16000) -> tuple[str, dict]:
    fresh, decision = select(programs, habits, withdrawals, request, source_loader, native_ids)
    if fresh != receipt or not decision['accepted']:
        return '', dict(accepted=False, reason='stale_or_unproven_ledger_receipt')
    effective_programs, effective_habits = effective_inventory(programs, habits, withdrawals, request.mode)
    lookup = {('procedure', v.id): v for v in effective_programs}
    lookup.update({('confirmed_habit', v.id): v for v in effective_habits})
    cards = []
    for key in receipt.selected:
        evidence = [asdict(v) for v in withdrawals if (v.target_kind, v.target_id) == key]
        cards.append(dict(kind=key[0], evidence=asdict(lookup[key]), withdrawals=evidence,
            applicability='withdrawn' if evidence else 'source_authority_unchanged',
            display_mode='applicable_user_authority' if request.mode == 'execute' else 'historical_attribution_only',
            executes_steps=False, adopts_long_term_rule=False))
    text = json.dumps(cards, ensure_ascii=False, sort_keys=True)
    if type(max_chars) is not int or max_chars < 1 or len(text) > max_chars:
        return '', dict(accepted=False, reason='whole_card_budget_fallback')
    return text, dict(accepted=True, cards=len(cards), executes_steps=False, adopts_long_term_rule=False)


def serialize(programs: list[p.Procedure], habits: list[h.ConfirmedHabit], withdrawals: list[Withdrawal],
              source_loader: Callable[[str], p.Source], native_ids: set[str]) -> str:
    projection = audit_ledger(programs, habits, withdrawals, source_loader, native_ids)
    return json.dumps(dict(schema_version=SCHEMA, ledger_sha256=projection, native_ids_sha256=p.digest(sorted(native_ids)),
        programs=json.loads(p.serialize(programs, source_loader, native_ids)),
        habits=json.loads(h.serialize_habits(habits, source_loader, native_ids)),
        withdrawals=[asdict(v) for v in withdrawals]), ensure_ascii=False, sort_keys=True)


def deserialize(text: str, source_loader: Callable[[str], p.Source], native_ids: set[str]):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate stored ledger field')
            result[key] = value
        return result
    stored = json.loads(text, object_pairs_hook=unique)
    if set(stored) != {'schema_version', 'ledger_sha256', 'native_ids_sha256', 'programs', 'habits', 'withdrawals'} or stored['schema_version'] != SCHEMA:
        raise ValueError('Unsupported stored ledger')
    if stored['native_ids_sha256'] != p.digest(sorted(native_ids)):
        raise ValueError('Native inventory changed')
    programs = p.deserialize(json.dumps(stored['programs'], ensure_ascii=False), source_loader, native_ids)
    habits = h.deserialize_habits(json.dumps(stored['habits'], ensure_ascii=False), source_loader, native_ids)
    targets = {('procedure', v.id): v for v in programs}
    targets.update({('confirmed_habit', v.id): v for v in habits})
    withdrawals = []
    for item in stored['withdrawals']:
        target = targets.get((item['target_kind'], item['target_id']))
        value, reason = compile_withdrawal(target, source_loader(item['source']['id']), source_loader, native_ids)
        if value is None or p.digest(asdict(value)) != p.digest(item):
            raise ValueError('Stored withdrawal differs from canonical sources: ' + reason)
        withdrawals.append(value)
    if audit_ledger(programs, habits, withdrawals, source_loader, native_ids) != stored['ledger_sha256']:
        raise ValueError('Stored ledger projection changed')
    return programs, habits, withdrawals
