"""Bounded source-exact Chinese conditional programs. Standard library only."""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Callable

SCHEMA = 'cuetrail.zh-explicit.1'
TOPIC = r'(?P<scope>[^「」\r\n]{1,80})'
RECURRING = re.compile(r'(?P<condition>每当我询问「' + TOPIC + r'」时)，请始终(?P<action>[^\r\n。]+)。')
TASK = re.compile(r'(?P<condition>这次我询问「' + TOPIC + r'」时)，请(?P<action>[^\r\n。]+)。')
STEPS = re.compile(r'(?P<condition>每当我询问「' + TOPIC + r'」时)，请遵守以下步骤：\r?\n(?P<steps>[\s\S]+)')
STEP = re.compile(r'(?P<number>[1-6])\. (?P<action>[^\r\n]+)')
EXECUTE = re.compile(r'请按既定程序处理「' + TOPIC + r'」。')
HISTORY = re.compile(r'回顾我关于「' + TOPIC + r'」的程序。')
ACTION = re.compile(r'(?:不要|不得|避免|先|首先|检查|核对|列出|保留|返回|使用|提供|引用|确认|保存|执行|验证|写|说明|按|记录|报告|比较|总结|不允许)')


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8')).hexdigest()


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf8')).hexdigest()


@dataclass(frozen=True)
class Source:
    id: str
    namespace: str
    subject_id: str
    session_id: str
    role: str
    content: str
    timestamp: int | None = None


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class Procedure:
    id: str
    schema_version: str
    content_version: str
    condition: Span
    scope: Span
    actions: tuple[Span, ...]
    evidence: Span
    source: Source
    source_sha256: str
    source_binding: str
    authority: str
    lifetime: str
    status: str
    source_basis: str


@dataclass(frozen=True)
class Request:
    id: str
    namespace: str
    subject_id: str
    query: str
    mode: str
    scope: Span


@dataclass(frozen=True)
class Receipt:
    schema_version: str
    request_binding: str
    projection_sha256: str
    native_ids_sha256: str
    selected: tuple[str, ...]
    mode: str
    executes_steps: bool = False
    adopts_long_term_rule: bool = False


def span(text: str, bounds: tuple[int, int]) -> Span:
    start, end = bounds
    return Span(start, end, text[start:end])


def compile_source(source: Source) -> tuple[Procedure | None, str]:
    if not isinstance(source, Source) or source.role not in ('user', 'assistant'):
        return None, 'unsupported_source_role'
    if not all(type(v) is str and v for v in (source.id, source.namespace, source.subject_id, source.session_id, source.content)):
        return None, 'missing_canonical_source_identity'
    if source.timestamp is not None and type(source.timestamp) is not int:
        return None, 'invalid_source_timestamp'
    text = source.content
    if len(text) > 1200:
        return None, 'whole_short_direct_turn_required'
    match = RECURRING.fullmatch(text) or TASK.fullmatch(text) or STEPS.fullmatch(text)
    if match is None:
        return None, 'unsupported_whole_directive'
    if match['scope'] != match['scope'].strip() or not match['scope'].strip():
        return None, 'noncanonical_scope'
    lifetime = 'task_bound' if match.re is TASK else 'recurring'
    actions = []
    if match.re is STEPS:
        lines = list(re.finditer(r'[^\r\n]+', match['steps']))
        # Joining proves no unparsed blank, dangling or embedded extra line exists.
        if not 2 <= len(lines) <= 6 or '\n'.join(line.group() for line in lines) != match['steps'].replace('\r\n', '\n'):
            return None, 'complete_consecutive_steps_required'
        for index, line in enumerate(lines, 1):
            item = STEP.fullmatch(line.group())
            if item is None or int(item['number']) != index or not ACTION.match(item['action']):
                return None, 'unsupported_or_nonconsecutive_step'
            start = match.start('steps') + line.start()
            actions.append(span(text, (start, start + len(line.group()))))
    else:
        if not ACTION.match(match['action']):
            return None, 'unsupported_imperative_action'
        actions.append(span(text, match.span('action')))
    binding = digest(asdict(source))
    version = digest([SCHEMA, asdict(span(text, match.span('scope'))), [asdict(a) for a in actions]])
    authority = 'user_constraint' if source.role == 'user' else 'assistant_suggestion'
    if source.role == 'assistant':
        lifetime = 'proposal'
    value = Procedure(digest([SCHEMA, binding]), SCHEMA, version,
        span(text, match.span('condition')), span(text, match.span('scope')), tuple(actions),
        Span(0, len(text), text), source, text_sha(text), binding, authority, lifetime,
        'source_grounded' if source.role == 'user' else 'unconfirmed',
        'explicit_user_directive' if source.role == 'user' else 'unconfirmed_assistant_advice')
    return value, 'valid'


def govern_versions(programs: list[Procedure]) -> list[Procedure]:
    signatures: dict[tuple, set] = {}
    for program in programs:
        key = (program.source.namespace, program.source.subject_id, program.authority, program.lifetime, program.scope.quote)
        signatures.setdefault(key, set()).add(tuple(action.quote for action in program.actions))
    return [replace(p, status='conflicting') if p.authority == 'user_constraint' and len(signatures[
        (p.source.namespace, p.source.subject_id, p.authority, p.lifetime, p.scope.quote)]) > 1 else p for p in programs]


def audit(programs: list[Procedure], source_loader: Callable[[str], Source], native_ids: set[str]) -> str:
    seen, rebuilt = set(), []
    for program in programs:
        if program.id in seen or program.source.id not in native_ids:
            raise ValueError('Duplicate or nonnative program')
        seen.add(program.id)
        fresh, reason = compile_source(source_loader(program.source.id))
        if fresh is None:
            raise ValueError('Source does not support program: ' + reason)
        rebuilt.append(fresh)
    if govern_versions(rebuilt) != programs:
        raise ValueError('Source, offsets, authority or content version changed')
    return digest([asdict(program) for program in programs])


def serialize(programs: list[Procedure], source_loader: Callable[[str], Source], native_ids: set[str]) -> str:
    projection = audit(programs, source_loader, native_ids)
    return json.dumps(dict(schema_version=SCHEMA, projection_sha256=projection,
        programs=[asdict(program) for program in programs]), ensure_ascii=False, sort_keys=True)


def deserialize(text: str, source_loader: Callable[[str], Source], native_ids: set[str]) -> list[Procedure]:
    """A stored JSON projection is never itself the authoritative source."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate stored JSON field')
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=unique_pairs)
    if set(value) != {'schema_version', 'projection_sha256', 'programs'} or value['schema_version'] != SCHEMA:
        raise ValueError('Unsupported stored projection schema')
    programs = []
    for item in value['programs']:
        fields = dict(item)
        fields['source'] = Source(**fields['source'])
        for name in ('condition', 'scope', 'evidence'):
            fields[name] = Span(**fields[name])
        fields['actions'] = tuple(Span(**action) for action in fields['actions'])
        programs.append(Procedure(**fields))
    if audit(programs, source_loader, native_ids) != value['projection_sha256']:
        raise ValueError('Stored projection hash mismatch')
    return programs


def parse_request(query: str, *, namespace: str, subject_id: str, request_id: str) -> Request | None:
    if not all(type(value) is str and value for value in (query, namespace, subject_id, request_id)) or len(query) > 1200:
        return None
    match = EXECUTE.fullmatch(query) or HISTORY.fullmatch(query)
    if match is None or match['scope'] != match['scope'].strip() or not match['scope'].strip():
        return None
    return Request(request_id, namespace, subject_id, query, 'execute' if match.re is EXECUTE else 'historical',
        span(query, match.span('scope')))


def select(programs: list[Procedure], request: Request, source_loader: Callable[[str], Source], native_ids: set[str]) -> tuple[Receipt | None, dict]:
    if not isinstance(request, Request) or parse_request(request.query, namespace=request.namespace,
        subject_id=request.subject_id, request_id=request.id) != request:
        return None, dict(accepted=False, reason='invalid_current_request')
    try:
        projection = audit(programs, source_loader, native_ids)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, dict(accepted=False, reason='source_or_version_changed')
    selected, rejected, signatures = [], [], set()
    for program in programs:
        reason = None
        if (program.source.namespace, program.source.subject_id) != (request.namespace, request.subject_id):
            reason = 'different_user_or_namespace'
        elif program.scope.quote != request.scope.quote:
            reason = 'no_exact_current_scope'
        elif request.mode == 'execute' and (program.authority != 'user_constraint' or program.lifetime != 'recurring' or program.status != 'source_grounded'):
            reason = 'authority_lifetime_or_conflict'
        signature = (program.authority, tuple(a.quote for a in program.actions))
        if reason is None and signature in signatures:
            reason = 'duplicate_action_signature'
        if reason is None and len(selected) >= 2:
            reason = 'at_most_two'
        if reason:
            rejected.append(dict(id=program.id, reason=reason))
        else:
            selected.append(program.id)
            signatures.add(signature)
    receipt = Receipt(SCHEMA, digest(asdict(request)), projection, digest(sorted(native_ids)), tuple(selected), request.mode)
    return receipt, dict(accepted=bool(selected), reason='source_exact_scoped_recall' if selected else 'no_applicable_program', rejected=rejected)


def render(receipt: Receipt, programs: list[Procedure], request: Request, source_loader: Callable[[str], Source], native_ids: set[str], *, max_chars: int = 6000) -> tuple[str, dict]:
    fresh, result = select(programs, request, source_loader, native_ids)
    if receipt != fresh or not result['accepted']:
        return '', dict(accepted=False, reason='stale_or_unaccepted_receipt')
    lookup = {p.id: p for p in programs}
    cards = [dict(procedure=asdict(lookup[key]), display_mode='applicable_user_instruction' if request.mode == 'execute' else 'historical_attribution_only',
                  executes_steps=False, adopts_long_term_rule=False) for key in receipt.selected]
    text = json.dumps(cards, ensure_ascii=False, sort_keys=True)
    if type(max_chars) is not int or max_chars < 1 or len(text) > max_chars:
        return '', dict(accepted=False, reason='whole_card_budget_fallback')
    return text, dict(accepted=True, cards=len(cards), executes_steps=False, adopts_long_term_rule=False)
