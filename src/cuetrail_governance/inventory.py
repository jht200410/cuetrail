"""Optional raw-source SQLite inventory for bounded Procedure grammars only."""
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from . import withdrawal as w
p, h = w.p, w.h
SCHEMA = 'cuetrail-procedure-source-inventory-v1'


class SourceConflict(ValueError):
    """An immutable source identity was reused with different evidence."""


class SourceIntegrityError(ValueError):
    """The canonical raw-source store is inconsistent or unsupported."""


@dataclass(frozen=True)
class Receipt:
    schema_version: str
    store_id: str
    partition_sha256: str
    procedure_receipt: w.Receipt


def validate_source(source):
    if not isinstance(source, p.Source):
        raise SourceIntegrityError('Expected a typed canonical Source')
    if not all(type(v) is str and v for v in (source.id,source.namespace,source.subject_id,source.session_id,source.content)):
        raise SourceIntegrityError('Empty or untyped source identity/content')
    if source.role not in ('user','assistant','tool','system') or type(source.role) is not str:
        raise SourceIntegrityError('Unsupported canonical role')
    if source.timestamp is not None and type(source.timestamp) is not int:
        raise SourceIntegrityError('Timestamp must be known integer or None')
    if len(source.content) > 64000:
        raise SourceIntegrityError('Source exceeds this bounded store limit')


class Inventory:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.parent.is_dir():
            raise ValueError('Inventory parent directory must already exist')
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('begin immediate')
            tables = {v[0] for v in db.execute("select name from sqlite_master where type='table' and name not glob 'sqlite_*'")}
            if tables and tables != {'procedure_meta','procedure_sources'}:
                raise SourceIntegrityError('Not a dedicated Procedure source store')
            if not tables:
                db.execute('create table procedure_meta (key text primary key, value text not null)')
                db.execute('create table procedure_sources (namespace text not null, subject text not null, id text not null, body text not null, binding text not null, primary key(namespace,subject,id))')
                db.executemany('insert into procedure_meta values (?,?)', [('schema',SCHEMA),('store_id',uuid4().hex)])
            self.store_id = self._metadata(db)

    @staticmethod
    def _metadata(db):
        values = dict(db.execute('select key,value from procedure_meta'))
        if set(values) != {'schema','store_id'} or values['schema'] != SCHEMA or not values['store_id']:
            raise SourceIntegrityError('Unsupported inventory metadata')
        return values['store_id']

    def add(self, source: p.Source) -> dict:
        validate_source(source)
        body, binding = json.dumps(asdict(source),ensure_ascii=False,sort_keys=True), p.digest(asdict(source))
        key = source.namespace,source.subject_id,source.id
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('begin immediate')
            if self._metadata(db) != self.store_id:
                raise SourceIntegrityError('Store identity changed')
            old = db.execute('select body,binding from procedure_sources where namespace=? and subject=? and id=?',key).fetchone()
            if old is not None:
                if old != (body,binding):
                    raise SourceConflict('Immutable source identity already contains different evidence')
                return dict(added=False,idempotent=True)
            db.execute('insert into procedure_sources values (?,?,?,?,?)',(*key,body,binding))
            return dict(added=True,idempotent=False)

    @contextmanager
    def _snapshot(self, namespace: str, subject_id: str):
        if not all(type(v) is str and v for v in (namespace,subject_id)):
            raise SourceIntegrityError('Partition identity required')
        db = sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=10)
        try:
            db.execute('begin')
            if self._metadata(db) != self.store_id:
                raise SourceIntegrityError('Store identity changed')
            rows = db.execute('select id,body,binding from procedure_sources where namespace=? and subject=? order by id',
                              (namespace,subject_id)).fetchall()
            sources, bindings = {}, []
            for identity,body,binding in rows:
                try:
                    source = p.Source(**json.loads(body))
                    validate_source(source)
                except (ValueError,TypeError) as error:
                    raise SourceIntegrityError('Canonical source schema changed') from error
                if (source.namespace,source.subject_id,source.id) != (namespace,subject_id,identity) or p.digest(asdict(source)) != binding or body != json.dumps(asdict(source),ensure_ascii=False,sort_keys=True):
                    raise SourceIntegrityError('Canonical source projection/hash changed')
                sources[identity] = source
                bindings.append((identity,binding))
            native = set(sources)
            ordered = sorted(sources.values(), key=lambda v:(v.timestamp is None, v.timestamp or 0, v.id))
            programs, proposals, compiled = [], {}, set()
            for source in ordered:
                program, _ = p.compile_source(source)
                if program is not None:
                    programs.append(program)
                    compiled.add(source.id)
                    if program.authority == 'assistant_suggestion':
                        proposals.setdefault(program.evidence.quote,[]).append(program)
            programs = p.govern_versions(programs)
            habits = []
            for source in ordered:
                if source.content.startswith(h.PREFIX):
                    for proposal in proposals.get(source.content[len(h.PREFIX):],[]):
                        habit, _ = h.compile_confirmation(proposal,source,sources.__getitem__,native)
                        if habit is not None:
                            habits.append(habit)
                            compiled.add(source.id)
            targets = {}
            for program in programs:
                if program.authority == 'user_constraint' and program.lifetime == 'recurring':
                    targets.setdefault(program.evidence.quote,[]).append(program)
            for habit in habits:
                targets.setdefault(habit.proposal.evidence.quote,[]).append(habit)
            withdrawals = []
            for source in ordered:
                if source.content.startswith(w.PREFIX):
                    for target in targets.get(source.content[len(w.PREFIX):],[]):
                        event, _ = w.compile_withdrawal(target,source,sources.__getitem__,native)
                        if event is not None:
                            withdrawals.append(event)
                            compiled.add(source.id)
            w.audit_ledger(programs,habits,withdrawals,sources.__getitem__,native)
            projection = p.digest([SCHEMA,self.store_id,namespace,subject_id,bindings])
            info = dict(canonical_sources=len(sources),programs=len(programs),confirmed_programs=len(habits),
                withdrawals=len(withdrawals),uncompiled_source_ids=sorted(set(sources)-compiled),
                complete_within_stored_partition=True,external_corpus_completeness_proven=False)
            yield projection,programs,habits,withdrawals,sources,native,info
        finally:
            db.rollback()
            db.close()

    def select(self, query: str, *, namespace: str, subject_id: str, request_id: str):
        request = p.parse_request(query,namespace=namespace,subject_id=subject_id,request_id=request_id)
        if request is None:
            return None,dict(accepted=False,reason='unsupported_current_request')
        try:
            with self._snapshot(namespace,subject_id) as (projection,programs,habits,withdrawals,sources,native,info):
                base,decision = w.select(programs,habits,withdrawals,request,sources.__getitem__,native)
                if base is None:
                    return None,dict(accepted=False,reason='unproven_derived_inventory')
                return Receipt(SCHEMA,self.store_id,projection,base),dict(decision,inventory=info)
        except (SourceIntegrityError,ValueError,KeyError,TypeError,sqlite3.DatabaseError):
            return None,dict(accepted=False,reason='canonical_inventory_integrity_failure')

    def render(self, receipt: Receipt, query: str, *, namespace: str, subject_id: str, request_id: str, max_chars: int = 16000):
        request = p.parse_request(query,namespace=namespace,subject_id=subject_id,request_id=request_id)
        if request is None or not isinstance(receipt,Receipt):
            return '',dict(accepted=False,reason='invalid_request_or_inventory_receipt')
        try:
            with self._snapshot(namespace,subject_id) as (projection,programs,habits,withdrawals,sources,native,info):
                base,decision = w.select(programs,habits,withdrawals,request,sources.__getitem__,native)
                current = Receipt(SCHEMA,self.store_id,projection,base) if base is not None else None
                if current != receipt or not decision['accepted']:
                    return '',dict(accepted=False,reason='stale_or_unaccepted_inventory_receipt')
                text,result = w.render(base,programs,habits,withdrawals,request,sources.__getitem__,native,max_chars=max_chars)
                return text,dict(result,inventory=info)
        except (SourceIntegrityError,ValueError,KeyError,TypeError,sqlite3.DatabaseError):
            return '',dict(accepted=False,reason='canonical_inventory_integrity_failure')
