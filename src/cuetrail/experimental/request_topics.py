"""Literal request-topic programs and request-bound,source-revalidated receipts."""
from dataclasses import asdict,dataclass,replace
import hashlib,json,re

SCHEMA_VERSION=1
FULL=re.compile(r'^\s*(?P<action>(?:Always|Never)\s+[^.!?\n]+?)\s+(?P<condition>when\s+I\s+ask\s+about\s+(?P<scope>[^.!?\n]{2,180}))[.]\s*(?P<trailer>[\W\d_]*)$',re.I)
VERBS={'provide','include','report','use','show','keep','exclude','avoid','check','verify','return','follow','cite','write','answer','give','compare','summarize','first','ask','format','list','explain','save','confirm'}
AMBIGUOUS=re.compile(r'\b(?:if|unless|except|only if|provided|otherwise|instead|rather than|according to|said|says|told|suppose|hypothetical|for example)\b',re.I)
TASK=re.compile(r'\b(?:today|tomorrow|next week|next time|just once|one[ -]time|for this (?:task|request|response|session|project))\b|这次|今天|明天',re.I)
TOKENS=re.compile(r'[A-Za-z0-9]+')
NEGATED=re.compile(r'\b(?:not|never|no|without|rather than|instead of)\b',re.I)


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def text_sha(value):return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Span:
    start:int
    end:int
    quote:str


@dataclass(frozen=True)
class Procedure:
    id:str
    schema_version:int
    version:int
    trigger_type:str
    condition:Span
    scope:Span
    actions:tuple[Span,...]
    source_id:str
    source_role:str
    session_id:str
    timestamp:int|None
    source_sha256:str
    evidence:Span
    source_binding:str
    authority:str
    lifetime:str
    status:str
    source_basis:str


def binding(source):
    return digest([source['id'],source['role'],source['session_id'],source.get('timestamp'),text_sha(source['content'])])


def compile_view(source):
    role=source['role']
    if role not in ('user','assistant'):return None,'unsupported_source_role'
    text=source['content'];offset=source.get('window_start',0);window=source.get('window_content',text)
    if not isinstance(offset,int) or not 0<=offset<=len(text) or text[offset:offset+len(window)]!=window:return None,'noncanonical_window'
    if not window or len(window)>1200:return None,'complete_short_window_required'
    match=FULL.fullmatch(window)
    if match is None:return None,'not_explicit_request_topic_directive'
    action=match['action'];parts=action.split()
    if len(parts)<2 or parts[1].casefold() not in VERBS:return None,'not_supported_imperative_action'
    if AMBIGUOUS.search(action+' '+match['scope']):return None,'unresolved_condition_or_attribution'
    if re.search(r'\bwhen\b',match['scope'],re.I):return None,'multiple_request_conditions'
    scope=match['scope'].strip()
    if not TOKENS.findall(scope):return None,'nonliteral_topic'
    def span(name):
        left,right=match.span(name)
        return Span(offset+left,offset+right,window[left:right])
    condition,scope_span,action_span=span('condition'),span('scope'),span('action')
    # Keep the period and every nonlinguistic source citation in original evidence.
    evidence=Span(offset,offset+len(window),window);source_binding=binding(source)
    authority='user_constraint' if role=='user' else 'assistant_suggestion'
    lifetime='task_bound' if TASK.search(window) else 'recurring' if role=='user' else 'proposal'
    status='source_grounded' if role=='user' else 'unconfirmed'
    ident=digest([SCHEMA_VERSION,source_binding,asdict(evidence),asdict(condition),asdict(scope_span),asdict(action_span)])
    return Procedure(ident,SCHEMA_VERSION,1,'request_about_topic',condition,scope_span,(action_span,),str(source['id']),role,
        str(source['session_id']),source.get('timestamp'),text_sha(text),evidence,source_binding,authority,lifetime,status,
        'explicit_user_scoped_directive' if role=='user' else 'unconfirmed_assistant_scoped_advice'),'valid'


def scope_key(procedure):
    return tuple(token.group().casefold() for token in TOKENS.finditer(procedure.scope.quote))


def govern_versions(procedures):
    groups={};variants={}
    for p in procedures:
        key=p.authority,scope_key(p),p.lifetime
        groups.setdefault(key,[]).append(p)
        versions=variants.setdefault(key,{})
        actions=tuple(span.quote for span in p.actions)
        versions.setdefault(actions,len(versions)+1)
    result=[]
    for p in procedures:
        key=p.authority,scope_key(p),p.lifetime;versions=variants[key]
        result.append(replace(p,version=versions[tuple(span.quote for span in p.actions)],
            status='conflicting' if len(versions)>1 and p.authority=='user_constraint' else p.status))
    return result


def audit(programs,source_loader,native_ids):
    originals=[];seen=set()
    for p in programs:
        if p.id in seen or p.source_id not in native_ids:raise ValueError('Duplicate or nonnative program')
        seen.add(p.id);source=source_loader(p.source_id)
        view=dict(source,window_start=p.evidence.start,window_content=p.evidence.quote)
        fresh,reason=compile_view(view)
        if fresh is None:raise ValueError('Source no longer supports program:'+reason)
        originals.append(fresh)
    fresh=govern_versions(originals)
    if fresh!=programs:raise ValueError('Source,authority,version or program changed')
    return digest([asdict(p) for p in fresh])


def witness(procedure,query):
    expected=scope_key(procedure);matches=list(TOKENS.finditer(query));tokens=[item.group().casefold() for item in matches]
    for index in range(len(tokens)-len(expected)+1):
        if tuple(tokens[index:index+len(expected)])!=expected:continue
        start,end=matches[index].start(),matches[index+len(expected)-1].end()
        if NEGATED.search(query[max(0,start-60):start]):continue
        return Span(start,end,query[start:end])
    return None


def select(programs,*,query,mode,request_id,source_loader,native_ids):
    if mode not in ('execute','historical_procedure') or not isinstance(query,str) or not query or not isinstance(request_id,str) or not request_id:return None,dict(accepted=False,reason='request_or_intent')
    try:projection=audit(programs,source_loader,native_ids)
    except (ValueError,KeyError,TypeError):return None,dict(accepted=False,reason='source_or_version_changed')
    chosen=[];rejections=[];dedup=set()
    for p in programs:
        if mode=='execute' and (p.authority!='user_constraint' or p.lifetime!='recurring' or p.status!='source_grounded'):
            rejections.append(dict(id=p.id,reason='authority_lifetime_or_version'));continue
        proof=witness(p,query)
        if proof is None:rejections.append(dict(id=p.id,reason='no_current_topic_witness'));continue
        key=scope_key(p),tuple(span.quote for span in p.actions),p.authority
        if key in dedup:continue
        if len(chosen)>=2:rejections.append(dict(id=p.id,reason='at_most_two'));continue
        dedup.add(key);chosen.append(dict(procedure_id=p.id,query_scope=asdict(proof),decision='apply' if mode=='execute' else 'historical_only'))
    receipt=dict(schema_version=SCHEMA_VERSION,request_id=request_id,query_sha256=text_sha(query),mode=mode,
        projection_sha256=projection,selected=chosen,native_ids_sha256=digest(sorted(native_ids)),executes_steps=False,adopts_long_term_rule=False)
    return receipt,dict(accepted=bool(chosen),reason='literal_request_topic_trigger' if chosen else 'no_eligible_request_topic',rejections=rejections)


def materialize(receipt,programs,**request):
    fresh,audit_result=select(programs,**request)
    if fresh!=receipt or not audit_result['accepted']:return [],dict(accepted=False,reason='request_source_or_version_changed')
    lookup={p.id:p for p in programs}
    return [lookup[item['procedure_id']] for item in receipt['selected']],dict(accepted=True,executes_steps=False,adopts_long_term_rule=False)
