"""Literal preconditions and current-user witnesses, never verified world state."""
from dataclasses import asdict, dataclass
import json
import re

from . import procedure_zh as p
SCHEMA='cuetrail-explicit-preconditions-v1'
TOPIC=r'(?P<scope>[^「」\r\n]{1,80})'
FACTS=r'(?P<facts>[^「」\r\n]{1,300})'
PROGRAM=re.compile(r'(?P<condition>每当我询问「'+TOPIC+r'」且「'+FACTS+r'」时)，请遵守以下步骤：\r?\n(?P<steps>[\s\S]+)')
CURRENT=re.compile(r'在「'+FACTS+r'」条件下，请按既定程序处理「'+TOPIC+r'」。')
HISTORY=re.compile(r'回顾我关于「'+TOPIC+r'」的条件程序。')
FIELD=re.compile(r'[\w\u4e00-\u9fff-]{1,24}')
UNSUPPORTED=re.compile(r'或|且|除非|也许|可能|如果|是否|未知|未确认|[?？]')


@dataclass(frozen=True)
class Predicate:
    field: p.Span
    value: p.Span
    evidence: p.Span


@dataclass(frozen=True)
class Procedure:
    id: str
    schema_version: str
    content_version: str
    scope: p.Span
    condition: p.Span
    prerequisites: tuple[Predicate,...]
    actions: tuple[p.Span,...]
    evidence: p.Span
    source: p.Source
    source_binding: str
    source_sha256: str
    authority: str
    lifetime: str
    status: str


@dataclass(frozen=True)
class Request:
    source: p.Source
    source_binding: str
    scope: p.Span
    assertions: tuple[Predicate,...]
    mode: str
    evidence_basis: str = 'current_user_assertion_only'
    external_state_verified: bool = False


@dataclass(frozen=True)
class Receipt:
    schema_version: str
    request_binding: str
    projection_sha256: str
    native_ids_sha256: str
    selected: tuple[str,...]
    mode: str
    executes_steps: bool = False
    adopts_long_term_rule: bool = False


def source_valid(source):
    return isinstance(source,p.Source) and all(type(v) is str and v for v in
        (source.id,source.namespace,source.subject_id,source.session_id,source.content)) and \
        source.role in ('user','assistant') and (source.timestamp is None or type(source.timestamp) is int) and len(source.content)<=1200


def predicates(text,bounds):
    start,end=bounds
    raw=text[start:end]
    pieces=list(re.finditer(r'[^；]+',raw))
    if not 1<=len(pieces)<=4 or '；'.join(v.group() for v in pieces)!=raw:
        return None
    values,seen=[],set()
    for piece in pieces:
        item=piece.group()
        if item.count('=')!=1:
            return None
        field,value=item.split('=')
        if not FIELD.fullmatch(field) or not value or len(value)>48 or value!=value.strip() or UNSUPPORTED.search(value) or field in seen:
            return None
        seen.add(field)
        offset=start+piece.start()
        values.append(Predicate(p.Span(offset,offset+len(field),field),
            p.Span(offset+len(field)+1,offset+len(item),value),p.Span(offset,offset+len(item),item)))
    return tuple(values)


def compile_source(source):
    if not source_valid(source):
        return None,'invalid_source'
    match=PROGRAM.fullmatch(source.content)
    if match is None or match['scope']!=match['scope'].strip():
        return None,'unsupported_guarded_program'
    guards=predicates(source.content,match.span('facts'))
    if not guards:
        return None,'unsupported_prerequisites'
    lines=list(re.finditer(r'[^\r\n]+',match['steps']))
    if not 2<=len(lines)<=6 or '\n'.join(v.group() for v in lines)!=match['steps'].replace('\r\n','\n'):
        return None,'complete_consecutive_steps_required'
    actions=[]
    for number,line in enumerate(lines,1):
        step=p.STEP.fullmatch(line.group())
        if step is None or int(step['number'])!=number or not p.ACTION.match(step['action']):
            return None,'unsupported_step'
        start=match.start('steps')+line.start()
        actions.append(p.Span(start,start+len(line.group()),line.group()))
    binding=p.digest(asdict(source))
    version=p.digest([SCHEMA,match['scope'],[(v.field.quote,v.value.quote) for v in guards],[v.quote for v in actions]])
    user=source.role=='user'
    return Procedure(p.digest([SCHEMA,binding]),SCHEMA,version,p.span(source.content,match.span('scope')),
        p.span(source.content,match.span('condition')),guards,tuple(actions),p.Span(0,len(source.content),source.content),
        source,binding,p.text_sha(source.content),'user_constraint' if user else 'assistant_suggestion',
        'recurring' if user else 'proposal','source_grounded' if user else 'unconfirmed'),'valid'


def parse_request(source):
    if not source_valid(source) or source.role!='user' or type(source.timestamp) is not int:
        return None
    match=CURRENT.fullmatch(source.content) or HISTORY.fullmatch(source.content)
    if match is None or match['scope']!=match['scope'].strip():
        return None
    assertions=predicates(source.content,match.span('facts')) if match.re is CURRENT else ()
    if match.re is CURRENT and not assertions:
        return None
    return Request(source,p.digest(asdict(source)),p.span(source.content,match.span('scope')),assertions,
                   'execute' if match.re is CURRENT else 'historical')


def audit(programs,source_loader,native_ids):
    seen=set()
    for program in programs:
        if not isinstance(program,Procedure) or program.id in seen or program.source.id not in native_ids:
            raise ValueError('Duplicate or nonnative program')
        seen.add(program.id)
        fresh,_=compile_source(source_loader(program.source.id))
        if fresh!=program:
            raise ValueError('Canonical guarded program changed')
    return p.digest([asdict(v) for v in programs])


def select(programs,request,source_loader,native_ids):
    try:
        if not isinstance(request,Request) or request.source.id not in native_ids or \
            source_loader(request.source.id)!=request.source or parse_request(request.source)!=request:
            return None,dict(accepted=False,reason='canonical_current_assertions_not_proven')
        projection=audit(programs,source_loader,native_ids)
        current={v.field.quote:v.value.quote for v in request.assertions}
        eligible,rejected=[],[]
        for program in programs:
            reason=None
            if (program.source.namespace,program.source.subject_id)!=(request.source.namespace,request.source.subject_id):
                reason='different_user_or_namespace'
            elif program.scope.quote!=request.scope.quote:
                reason='different_scope'
            elif type(program.source.timestamp) is not int or program.source.timestamp>=request.source.timestamp:
                reason='chronology_not_proven'
            elif request.mode=='execute' and program.authority!='user_constraint':
                reason='unconfirmed_assistant_proposal'
            elif request.mode=='execute' and any(current.get(v.field.quote)!=v.value.quote for v in program.prerequisites):
                reason='missing_or_different_prerequisite_witness'
            if reason:
                rejected.append(dict(id=program.id,reason=reason))
            else:
                eligible.append(program)
        conflicting=request.mode=='execute' and len({tuple(v.quote for v in program.actions) for program in eligible})>1
        selected,seen=[],set()
        for program in ([] if conflicting else eligible):
            signature=(program.authority,tuple(v.quote for v in program.actions))
            if signature not in seen and len(selected)<2:
                selected.append(program.id)
                seen.add(signature)
        receipt=Receipt(SCHEMA,p.digest(asdict(request)),projection,p.digest(sorted(native_ids)),tuple(selected),request.mode)
        return receipt,dict(accepted=bool(selected),reason='conflicting_applicable_actions' if conflicting else 'literal_witness_selection',
            rejected=rejected,conflicting_program_ids=[v.id for v in eligible] if conflicting else [],
            evidence_basis='current_user_assertion_only',external_state_verified=False,
            executes_steps=False,adopts_long_term_rule=False)
    except (ValueError,KeyError,TypeError,AttributeError):
        return None,dict(accepted=False,reason='canonical_program_or_request_changed')


def render(receipt,programs,request,source_loader,native_ids,*,max_chars=16000):
    fresh,decision=select(programs,request,source_loader,native_ids)
    if fresh!=receipt or not decision['accepted']:
        return '',dict(accepted=False,reason='stale_or_unproven_guard_receipt')
    lookup={v.id:v for v in programs}
    cards=[dict(program=asdict(lookup[identity]),current_request=asdict(request),
        display_mode='applicable_user_asserted_conditions' if request.mode=='execute' else 'historical_attribution_only',
        preconditions_witnessed_in_request=request.mode=='execute',external_state_verified=False,
        executes_steps=False,adopts_long_term_rule=False) for identity in receipt.selected]
    text=json.dumps(cards,ensure_ascii=False,sort_keys=True)
    if type(max_chars) is not int or max_chars<1 or len(text)>max_chars:
        return '',dict(accepted=False,reason='whole_card_budget_fallback')
    return text,dict(accepted=True,cards=len(cards),external_state_verified=False,executes_steps=False)


def serialize(programs,source_loader,native_ids):
    projection=audit(programs,source_loader,native_ids)
    return json.dumps(dict(schema_version=SCHEMA,projection_sha256=projection,programs=[asdict(v) for v in programs]),
                      ensure_ascii=False,sort_keys=True)


def deserialize(text,source_loader,native_ids):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError('Duplicate stored field')
            result[key]=value
        return result
    stored=json.loads(text,object_pairs_hook=unique)
    if set(stored)!={'schema_version','projection_sha256','programs'} or stored['schema_version']!=SCHEMA:
        raise ValueError('Unsupported guarded snapshot')
    programs=[]
    for item in stored['programs']:
        program,_=compile_source(source_loader(item['source']['id']))
        if program is None or p.digest(asdict(program))!=p.digest(item):
            raise ValueError('Stored prerequisites differ from canonical source')
        programs.append(program)
    if audit(programs,source_loader,native_ids)!=stored['projection_sha256']:
        raise ValueError('Stored projection changed')
    return programs
