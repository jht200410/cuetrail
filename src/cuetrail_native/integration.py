"""Native canonical-source projection and current-intent Procedure evidence cards."""
from contextlib import closing
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import re
import threading
import time

from cuetrail_governance import confirmation as h, guarded as g, withdrawal as w
from cuetrail_scope import programs as e

p=h.p
NAMESPACE='cuetrail-native-v77'
MAX_CARDS_CHARS=6000
EXECUTE=re.compile(r'^\s*(?:please\s+)?(?:help\b|write\b|draft\b|create\b|prepare\b|plan\b|provide\b|give\b|recommend\b|suggest\b|show\b|list\b|explain\b|how\s+(?:should|can|do)\s+I\b|what\s+(?:should\s+I|steps|procedure|approach)\b)',re.I)
HISTORICAL=re.compile(r'^\s*(?:recall\b|remember\b|what\s+(?:did\s+I\s+(?:ask|instruct|say)|were\s+my)\b)',re.I)


def project(rows,user_id):
    sources,raw={},{}
    for row in rows:
        if row['user_id']!=user_id or row['id'] in sources:
            raise ValueError('Canonical native partition mismatch')
        source=p.Source(row['id'],NAMESPACE,user_id,row['session_id'],row['role'],row['content'],row['timestamp'])
        sources[source.id]=source
        raw[source.id]=dict(row)
    native=set(sources)
    ordered=sorted(sources.values(),key=lambda s:(s.timestamp is None,s.timestamp or 0,s.id))
    ordinary,english,guarded,proposals=[],[],[],{}
    for source in ordered:
        ordinary_program,_=p.compile_source(source)
        if ordinary_program is not None:
            ordinary.append(ordinary_program)
            if ordinary_program.authority=='assistant_suggestion':
                proposals.setdefault(ordinary_program.evidence.quote,[]).append(ordinary_program)
        english_program,_=e.compile_view(raw[source.id])
        if english_program is not None:
            english.append(english_program)
        guarded_program,_=g.compile_source(source)
        if guarded_program is not None:
            guarded.append(guarded_program)
    habits=[]
    for source in ordered:
        if source.content.startswith(h.PREFIX):
            for proposal in proposals.get(source.content[len(h.PREFIX):],[]):
                habit,_=h.compile_confirmation(proposal,source,sources.__getitem__,native)
                if habit is not None:
                    habits.append(habit)
    # The native snapshot, not any caller-selected subset or cached card, is
    # authoritative. Whole raw-source bindings also cover uncompiled sources.
    projection=p.digest([asdict(sources[identity]) for identity in sorted(sources)])
    return dict(sources=sources,raw=raw,native=native,ordinary=ordinary,english=english,
                guarded=guarded,habits=habits,projection=projection)


def withdrawal_proofs(snapshot,kind,target):
    if kind=='confirmed_habit':
        program,authority=target.proposal,target.confirmation_source
        text,identity,version=program.evidence.quote,target.id,target.content_version
    elif kind=='english':
        authority=snapshot['sources'][target.source_id]
        text,identity,version=target.evidence.quote,target.id,str(target.version)
    else:
        authority=target.source
        text,identity,version=target.evidence.quote,target.id,target.content_version
    proofs=[]
    for source in snapshot['sources'].values():
        if source.role!='user' or source.content!=w.PREFIX+text or source.id==authority.id:
            continue
        known=type(source.timestamp) is int and type(authority.timestamp) is int
        if known and source.timestamp<=authority.timestamp:
            continue
        proof=dict(schema_version='cuetrail-native-bound-withdrawal-v1',target_kind=kind,target_id=identity,
            content_version=version,target_binding=p.digest(asdict(target)),source=asdict(source),
            source_binding=p.digest(asdict(source)),source_sha256=p.text_sha(source.content),
            explicit_intent=asdict(p.Span(0,len(w.PREFIX)-1,w.PREFIX[:-1])),
            quoted_program=asdict(p.Span(len(w.PREFIX),len(source.content),text)),
            effect='explicit_bound_withdrawal' if known else 'abstain_unknown_withdrawal_order',creates_replacement=False)
        # Existing proven ordinary/confirmed withdrawals keep their original
        # schema/evidence as an additional proof, without rewriting authorship.
        if known and kind in ('ordinary','confirmed_habit'):
            original,reason=w.compile_withdrawal(target,source,snapshot['sources'].__getitem__,snapshot['native'])
            if original is None:
                raise ValueError('Current withdrawal library rejected native authority: '+reason)
            proof['original_withdrawal']=asdict(original)
        proofs.append(proof)
    return proofs


def program_cards(snapshot,query,user_id,*,observed_ms):
    source_loader=snapshot['sources'].__getitem__
    ordinary_raw=snapshot['ordinary']
    english_raw=snapshot['english']
    guarded_raw=snapshot['guarded']
    habits=snapshot['habits']
    # Audit the full original projection before applying explicit withdrawal.
    p.audit(p.govern_versions(ordinary_raw),source_loader,snapshot['native'])
    h.audit_habits(habits,source_loader,snapshot['native'])
    e.audit(e.govern_versions(english_raw),snapshot['raw'].__getitem__,snapshot['native'])
    g.audit(guarded_raw,source_loader,snapshot['native'])
    proofs={}
    for kind,values in [('ordinary',ordinary_raw),('confirmed_habit',habits),('english',english_raw),('guarded',guarded_raw)]:
        for target in values:
            # Suggestions are never authorities that a withdrawal could confirm.
            authority=target.authority
            lifetime=target.lifetime
            if authority not in ('user_constraint','user_confirmed_habit') or lifetime!='recurring':
                continue
            proofs[kind,target.id]=withdrawal_proofs(snapshot,kind,target)
    current_id='current-search-input:'+p.digest([user_id,query,observed_ms])
    cards=[]
    request_binding=p.digest([NAMESPACE,user_id,query,observed_ms,snapshot['projection']])

    def add_card(kind,program,trigger,mode):
        withdrawal=proofs.get((kind,program.id),[])
        if mode=='execute' and withdrawal:
            raise ValueError('Withdrawn authority reached current execution evidence')
        cards.append(dict(schema_version='cuetrail-native-procedure-card-v1',kind=kind,program=asdict(program),
            withdrawals=withdrawal,applicability=('withdrawn_or_order_unproven' if withdrawal else 'source_authority_unchanged'),
            native_source_projection_sha256=snapshot['projection'],current_input_sha256=p.text_sha(query),
            current_request_binding=request_binding,trigger=trigger,display_mode=('applicable_user_authority' if mode=='execute' else 'historical_attribution_only'),
            external_state_verified=False,executes_steps=False,adopts_long_term_rule=False))

    ordinary_request=p.parse_request(query,namespace=NAMESPACE,subject_id=user_id,request_id=current_id)
    if ordinary_request is not None:
        mode=ordinary_request.mode
        ordinary=p.govern_versions([v for v in ordinary_raw if mode=='historical' or not proofs.get(('ordinary',v.id))])
        selected_habits=[v for v in habits if mode=='historical' or not proofs.get(('confirmed_habit',v.id))]
        receipt,decision=h.select(ordinary,selected_habits,ordinary_request,source_loader,snapshot['native'])
        if receipt is not None and decision['accepted']:
            materialized,accepted=h.render(receipt,ordinary,selected_habits,ordinary_request,source_loader,snapshot['native'],max_chars=64000)
            if not accepted['accepted']:
                raise ValueError('Current library could not revalidate ordinary source cards')
            lookup={('procedure',v.id):v for v in ordinary}
            lookup.update({('confirmed_habit',v.id):v for v in selected_habits})
            for kind,identity in receipt.selected:
                actual='ordinary' if kind=='procedure' else kind
                add_card(actual,lookup[kind,identity],dict(current_input_kind='native_search_query',
                    current_input_scope=asdict(ordinary_request.scope),selection_receipt=asdict(receipt)),mode)

    english_mode='execute' if EXECUTE.match(query) else 'historical_procedure' if HISTORICAL.match(query) else None
    if english_mode is not None:
        english=e.govern_versions([v for v in english_raw if english_mode!='execute' or not proofs.get(('english',v.id))])
        receipt,decision=e.select(english,query=query,mode=english_mode,request_id=current_id,
            source_loader=snapshot['raw'].__getitem__,native_ids=snapshot['native'])
        if receipt is not None and decision['accepted']:
            selected,accepted=e.materialize(receipt,english,query=query,mode=english_mode,request_id=current_id,
                source_loader=snapshot['raw'].__getitem__,native_ids=snapshot['native'])
            if not accepted['accepted']:
                raise ValueError('English source/current intent changed')
            witnesses={v['procedure_id']:v['query_scope'] for v in receipt['selected']}
            for program in selected:
                add_card('english',program,dict(current_input_kind='native_search_query',query_scope=witnesses[program.id],
                    selection_receipt=receipt),'execute' if english_mode=='execute' else 'historical')

    # Search is separately identified current native input, never an historical
    # Add citation. Its timestamp is actual observed server time; original
    # program timestamps are preserved and unknown chronology still abstains.
    current=p.Source(current_id,NAMESPACE,user_id,'current-search-input','user',query,observed_ms)
    guarded_request=g.parse_request(current)
    if guarded_request is not None:
        mode=guarded_request.mode
        guarded=[v for v in guarded_raw if mode=='historical' or not proofs.get(('guarded',v.id))]
        inputs=dict(snapshot['sources'],**{current_id:current})
        input_ids=snapshot['native']|{current_id}
        receipt,decision=g.select(guarded,guarded_request,inputs.__getitem__,input_ids)
        if receipt is not None and decision['accepted']:
            rendered,accepted=g.render(receipt,guarded,guarded_request,inputs.__getitem__,input_ids,max_chars=64000)
            if not accepted['accepted']:
                raise ValueError('Current guarded source witnesses changed')
            lookup={v.id:v for v in guarded}
            for identity in receipt.selected:
                add_card('guarded',lookup[identity],dict(current_input_kind='native_search_query',
                    current_assertions=asdict(guarded_request),selection_receipt=asdict(receipt),
                    evidence_basis='current_user_assertion_only'),mode)

    # Deterministic channel dispatch and source-derived programs; no learned
    # source reordering, graph, model call or benchmark identity is used.
    cards=cards[:2]
    encoded=[json.dumps(v,ensure_ascii=False,sort_keys=True) for v in cards]
    if sum(map(len,encoded))>MAX_CARDS_CHARS:
        return [],dict(accepted=False,reason='whole_procedure_budget_fallback')
    counts=dict(ordinary=len(ordinary_raw),english=len(english_raw),guarded=len(guarded_raw),confirmed=len(habits))
    return cards,dict(accepted=bool(cards),reason='current_source_bound_programs' if cards else 'no_applicable_program',
        compiled_programs=counts,withdrawn_or_uncertain_authorities=sum(bool(v) for v in proofs.values()),
        source_projection_sha256=snapshot['projection'],current_input_sha256=p.text_sha(query),
        selected_ids=[v['program']['id'] for v in cards],executes_steps=False,adopts_long_term_rule=False)


def inject(hits,cards,*,top_k,context_chars):
    if not cards or not hits or top_k<2:
        return hits,dict(applied=False,reason='no_card_or_protected_first_hit')
    additions=[dict(id='cuetrail-procedure:'+v['program']['id'],
                    content='[CueTrail Procedure] '+json.dumps(v,ensure_ascii=False,sort_keys=True),score=0.5/(n+1)) for n,v in enumerate(cards)]
    required=[hits[0],*additions]
    if len(required)>top_k or len('\n\n'.join(v['content'] for v in required))>context_chars:
        return hits,dict(applied=False,reason='whole_card_or_first_hit_budget_fallback')
    output=list(required)
    for hit in hits[1:]:
        if len(output)>=top_k:
            break
        if len('\n\n'.join(v['content'] for v in [*output,hit]))<=context_chars:
            output.append(hit)
    return output,dict(applied=True,inserted_cards=len(additions),native_first_hit_unchanged=output[0]==hits[0],
        native_hits_removed=len(hits)-sum(not v['id'].startswith('cuetrail-procedure:') for v in output),
        packed_chars=len('\n\n'.join(v['content'] for v in output)))


def memory_store_class(base):
    if getattr(base,'_cuetrail_native',None)=='v77':
        return base
    class CurrentProcedureStore(base):
        _cuetrail_native='v77'
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self._procedure_state=threading.local()
            self.procedural_searches=0
            self.procedural_injections=0
            self.procedural_audit_failures=0
            self._procedure_audit_lock=threading.Lock()

        @property
        def procedure_trace(self):
            return getattr(self._procedure_state,'trace',{})

        def ranked(self,*args,**kwargs):
            result=super().ranked(*args,**kwargs)
            if kwargs.get('return_document_prior'):
                self._procedure_state.document_prior=bool(result[1])
            return result

        def search(self,*,user_id,query,top_k=100,options=None,mode='hybrid_window'):
            self._procedure_state.document_prior=False
            eligible=mode=='query_document_evidence' and top_k==100
            revision_before=None
            if eligible:
                with closing(self.connect()) as db:
                    row=db.execute('select revision from scopes where user_id=?',(user_id,)).fetchone()
                    revision_before=None if row is None else row[0]
            hits=super().search(user_id=user_id,query=query,top_k=top_k,options=options,mode=mode)
            trace=dict(applied=False,reason='protected_native_path',current_input_sha256=p.text_sha(query))
            output=hits
            if eligible and not self._procedure_state.document_prior:
                try:
                    with closing(self.connect()) as db:
                        db.execute('begin')
                        row=db.execute('select revision from scopes where user_id=?',(user_id,)).fetchone()
                        revision_after=None if row is None else row[0]
                        if revision_after!=revision_before:
                            raise ValueError('Native source revision changed during retrieval')
                        rows=[dict(row) for row in db.execute('select * from sources where user_id=? order by id',(user_id,))]
                        snapshot=project(rows,user_id)
                        cards,selection=program_cards(snapshot,query,user_id,observed_ms=int(time.time()*1000))
                        output,injection=inject(hits,cards,top_k=top_k,context_chars=self.config.context_chars)
                        trace=dict(selection,**injection)
                except (ValueError,KeyError,TypeError,AttributeError,OverflowError) as error:
                    trace=dict(applied=False,reason='source_or_trigger_integrity_fallback',error_type=type(error).__name__)
                    output=hits
            self._procedure_state.trace=trace
            with self.cache_lock:
                self.procedural_searches+=1
                self.procedural_injections+=bool(trace.get('applied'))
            audit=os.getenv('CUETRAIL_PROCEDURE_AUDIT')
            if audit:
                safe=dict(at_ms=int(time.time()*1000),user_sha256=p.text_sha(user_id),**trace)
                try:
                    with self._procedure_audit_lock:
                        with Path(audit).open('a',encoding='utf8') as stream:
                            stream.write(json.dumps(safe,ensure_ascii=False,sort_keys=True)+'\n')
                except OSError:
                    with self.cache_lock:
                        self.procedural_audit_failures+=1
            return output
    return CurrentProcedureStore
