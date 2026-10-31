"""Transactional Procedure-only ledger; native sources remain authoritative.

No model, benchmark, graph, full-history fact extraction or autonomous actions.
The retrieval API requires a bounded set of native source IDs from its caller.
"""
from dataclasses import asdict
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from . import evidence as g


def encode(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)


def restore(value):
    value=dict(value)
    value['action_quotes']=tuple(value['action_quotes'])
    value['supersedes_ids']=tuple(value.get('supersedes_ids',()))
    return g.Procedure(**value)


def govern_owned(values):
    groups=defaultdict(list)
    for p in values:groups[p.subject_quote.casefold()].append(p)
    return [p for group in groups.values() for p in g.govern_versions(group)]


class SourceMutation(ValueError):pass


class Ledger:
    def __init__(self,path):
        self.path=Path(path)
        self.code_path=Path(g.__file__)
        self.code_sha=hashlib.sha256(self.code_path.read_bytes()).hexdigest()
        self.ledger_path=Path(__file__)
        self.ledger_sha=hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        self.db=sqlite3.connect(self.path,timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(
              namespace TEXT NOT NULL,source_id TEXT NOT NULL,identity_json TEXT NOT NULL,
              PRIMARY KEY(namespace,source_id));
            CREATE TABLE IF NOT EXISTS derivations(
              namespace TEXT NOT NULL,id TEXT NOT NULL,source_id TEXT NOT NULL,
              original_json TEXT NOT NULL,draft_json TEXT NOT NULL,relation_start INTEGER NOT NULL,
              relation_end INTEGER NOT NULL,extraction_ref TEXT NOT NULL,
              PRIMARY KEY(namespace,id),FOREIGN KEY(namespace,source_id) REFERENCES sources(namespace,source_id));
            CREATE TABLE IF NOT EXISTS procedures(
              namespace TEXT NOT NULL,id TEXT NOT NULL,value_json TEXT NOT NULL,
              PRIMARY KEY(namespace,id),FOREIGN KEY(namespace,id) REFERENCES derivations(namespace,id));
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY,namespace TEXT NOT NULL,id TEXT NOT NULL,
              previous_json TEXT,new_json TEXT NOT NULL,cause_ref TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS derivation_source ON derivations(namespace,source_id);
        ''')
        expected=encode({'schema':g.SCHEMA_VERSION,'validator_sha256':self.code_sha,
                         'ledger_sha256':self.ledger_sha,'ledger_schema':1})
        row=self.db.execute('SELECT value FROM metadata WHERE key=?',('contract',)).fetchone()
        if row and row[0]!=expected:
            self.db.close();raise ValueError('Stored Procedure contract differs; explicit migration required')
        self.db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',('contract',expected));self.db.commit()

    def close(self):self.db.close()

    def _verify_contract(self):
        if hashlib.sha256(self.code_path.read_bytes()).hexdigest()!=self.code_sha:
            raise ValueError('Validator code changed while ledger open')
        if hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()!=self.ledger_sha:
            raise ValueError('Version-governance code changed while ledger open')
        expected=encode({'schema':g.SCHEMA_VERSION,'validator_sha256':self.code_sha,
                         'ledger_sha256':self.ledger_sha,'ledger_schema':1})
        row=self.db.execute('SELECT value FROM metadata WHERE key=?',('contract',)).fetchone()
        if not row or row[0]!=expected:raise SourceMutation('Open ledger contract changed')

    def record(self,namespace,items,*,extraction_ref):
        """Validate source/draft pairs before committing any state.

        Only bounded evidence and the original relation citation are persisted,
        together with source identity hashes. The complete historical source is
        not copied into the ledger. An unchanged reinsert is idempotent.
        """
        if not namespace or not isinstance(namespace,str):raise ValueError('Explicit user/task namespace required')
        if not extraction_ref or not isinstance(extraction_ref,str):raise ValueError('Extraction receipt reference required')
        self._verify_contract()
        validated=[]
        for item in items:
            draft,source=item['draft'],item['source']
            p,reason=g.validate_draft(draft,source)
            if p is None:raise ValueError('Invalid grounded Procedure: '+reason)
            identity=encode({k:source.get(k) for k in ('id','role','session_id','timestamp')}|{'sha256':p.source_sha256})
            relation=p.evidence_start+p.evidence_quote.find(draft['connecting_quote'])
            assert source['content'][relation:relation+len(draft['connecting_quote'])]==draft['connecting_quote']
            validated.append((p,draft,identity,relation))
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for p,draft,identity,relation in validated:
                old=self.db.execute('SELECT identity_json FROM sources WHERE namespace=? AND source_id=?',(namespace,p.source_id)).fetchone()
                if old and old[0]!=identity:raise SourceMutation('Immutable source identity changed')
                self.db.execute('INSERT OR IGNORE INTO sources VALUES(?,?,?)',(namespace,p.source_id,identity))
                immutable=encode(asdict(p));draft_json=encode(draft)
                old=self.db.execute('SELECT original_json,draft_json FROM derivations WHERE namespace=? AND id=?',(namespace,p.id)).fetchone()
                if old and old!=(immutable,draft_json):raise SourceMutation('Immutable derivation changed')
                self.db.execute('INSERT OR IGNORE INTO derivations VALUES(?,?,?,?,?,?,?,?)',
                    (namespace,p.id,p.source_id,immutable,draft_json,relation,relation+len(draft['connecting_quote']),extraction_ref))
            base=[restore(json.loads(row[0])) for row in self.db.execute('SELECT original_json FROM derivations WHERE namespace=? ORDER BY rowid',(namespace,))]
            governed=govern_owned(base)
            for p in governed:
                value=encode(asdict(p))
                prior=self.db.execute('SELECT value_json FROM procedures WHERE namespace=? AND id=?',(namespace,p.id)).fetchone()
                if not prior or prior[0]!=value:
                    self.db.execute('INSERT INTO events(namespace,id,previous_json,new_json,cause_ref) VALUES(?,?,?,?,?)',
                                    (namespace,p.id,prior[0] if prior else None,value,extraction_ref))
                    self.db.execute('INSERT OR REPLACE INTO procedures VALUES(?,?,?)',(namespace,p.id,value))
            self.db.commit()
        except BaseException:
            self.db.rollback();raise
        current={p.id:p for p in governed}
        return [current[p.id] for p,_,_,_ in validated]

    def visible(self,namespace,source_ids,*,historical=False):
        """No unbounded retrieval: use only the caller's current native IDs.

        Applicability to the actual query is still checked by the source-aware
        selector. Visibility does not execute or adopt a procedure.
        """
        self._verify_contract()
        ids=set(source_ids)
        if not ids:return []
        if len(ids)>32:raise ValueError('Visibility requires at most32 native source IDs')
        output=[]
        placeholders=','.join('?' for _ in ids)
        query=('SELECT p.value_json FROM procedures p JOIN derivations d ON p.namespace=d.namespace AND p.id=d.id '
               'WHERE p.namespace=? AND d.source_id IN ('+placeholders+') ORDER BY d.rowid')
        for row in self.db.execute(query,(namespace,*sorted(ids))):
            p=restore(json.loads(row[0]))
            if p.source_id not in ids:continue
            if historical or (p.status=='source_grounded' and p.authority!='assistant_suggestion' and p.lifetime!='task_bound'):
                output.append(p)
        return output

    def verified_visible(self,namespace,source_ids,source_loader,*,historical=False):
        """Return a consistent source-audited snapshot, never an execution grant.

        Revalidate original text only for current native IDs. Stored namespace
        version/event metadata is still replayed, so an earlier rule cannot
        evade a later conflict/replacement merely by retrieving its old source.
        The loader never needs unrelated canonical history for a query.
        """
        ids=tuple(source_ids)
        if len(set(ids))>32:raise ValueError('Visibility requires at most32 native source IDs')
        if not ids:return [],None
        self.db.execute('BEGIN')
        try:
            report=self.audit(namespace,source_loader,source_ids=ids)
            values=self.visible(namespace,ids,historical=historical)
            self.db.commit()
            return values,report
        except BaseException:
            self.db.rollback();raise

    def audit(self,namespace,source_loader,*,source_ids=None):
        """Audit all stored metadata; optionally bound canonical source reads.

        With no source_ids, this is the full offline source audit. Query-time
        snapshots supply current native IDs, and report their narrower scope.
        Unretrieved versions can suppress an obsolete rule, never supply steps.
        """
        self._verify_contract()
        ids=None if source_ids is None else set(source_ids)
        if ids is not None and len(ids)>32:raise ValueError('Canonical audit requires at most32 native source IDs')
        verified=0;originals=[];verified_ids=set()
        source_identities={sid:value for sid,value in self.db.execute(
            'SELECT source_id,identity_json FROM sources WHERE namespace=?',(namespace,))}
        for sid,original,draft_text,start,end,receipt in self.db.execute(
            'SELECT source_id,original_json,draft_json,relation_start,relation_end,extraction_ref FROM derivations WHERE namespace=? ORDER BY rowid',(namespace,)):
            draft=json.loads(draft_text);saved=restore(json.loads(original))
            try:stored=json.loads(source_identities[sid])
            except (KeyError,TypeError,ValueError) as error:
                raise SourceMutation('Stored source identity is malformed') from error
            if not isinstance(stored,dict) or set(stored)!={'id','role','session_id','timestamp','sha256'} or not isinstance(stored['role'],str):
                raise SourceMutation('Stored source identity is malformed')
            if (str(stored['id']),stored['role'].casefold(),str(stored['session_id']),stored['timestamp'],stored['sha256'])!=(
                    saved.source_id,saved.source_role,saved.session_id,saved.timestamp,saved.source_sha256):
                raise SourceMutation('Source identity differs from stored derivation')
            if not isinstance(receipt,str) or not receipt.strip():raise SourceMutation('Missing extraction receipt reference')
            if ids is None or sid in ids:
                source=source_loader(sid)
                identity=encode({k:source.get(k) for k in ('id','role','session_id','timestamp')}|
                                {'sha256':hashlib.sha256(source['content'].encode()).hexdigest()})
                if source_identities.get(sid)!=identity:raise SourceMutation('Stored source identity differs from canonical source')
                source={**source,'window_start':saved.evidence_start,
                        'window_content':source['content'][saved.evidence_start:saved.evidence_end]}
                fresh,reason=g.validate_draft(draft,source)
                if fresh!=saved or reason!='valid':raise SourceMutation('Canonical source or derivation no longer matches')
                if source['content'][start:end]!=draft['connecting_quote']:raise SourceMutation('Relation citation no longer matches')
                verified+=1;verified_ids.add(sid)
            originals.append(saved)
        if set(source_identities)!={p.source_id for p in originals}:
            raise SourceMutation('Source identities differ from immutable derivations')
        projection={pid:restore(json.loads(value)) for pid,value in self.db.execute(
            'SELECT id,value_json FROM procedures WHERE namespace=?',(namespace,))}
        expected={p.id:p for p in govern_owned(originals)}
        if projection!=expected:raise SourceMutation('Stored version projection differs from immutable derivations')
        replay={};events=0
        for pid,previous,new,cause in self.db.execute(
            'SELECT id,previous_json,new_json,cause_ref FROM events WHERE namespace=? ORDER BY seq',(namespace,)):
            before=restore(json.loads(previous)) if previous is not None else None
            after=restore(json.loads(new))
            if pid not in expected or after.id!=pid or (before is not None and before.id!=pid):
                raise SourceMutation('Version event references unknown Procedure')
            if replay.get(pid)!=before:raise SourceMutation('Version event history is disconnected')
            if before==after:raise SourceMutation('Redundant version event')
            if not isinstance(cause,str) or not cause.strip():raise SourceMutation('Missing version event cause')
            replay[pid]=after;events+=1
        if replay!=projection:raise SourceMutation('Version event replay differs from current projection')
        proposals=sum(json.loads(row[0])['authority']=='assistant_suggestion' for row in self.db.execute(
            'SELECT value_json FROM procedures WHERE namespace=?',(namespace,)))
        return dict(verified_derivations=verified,version_events=events,unconfirmed_proposals=proposals,
                    contract_sha256=self.code_sha,ledger_sha256=self.ledger_sha,
                    source_fidelity_verified=True,version_projection_verified=True,
                    event_replay_verified=True,source_identity_verified=True,
                    metadata_derivations_replayed=len(originals),canonical_source_ids_verified=sorted(verified_ids),
                    canonical_source_scope='all_stored_procedures' if ids is None else 'current_native_ids',
                    all_namespace_sources_verified=verified==len(originals))
