"""Opt-in Procedure sidecar around the unmodified official 0.32 source."""
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

from . import procedural


def memory_store_class(base):
    class ProceduralStore(base):
        def __init__(self, *args, procedure_path=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.procedure_index = procedural.ProcedureIndex(procedure_path)
            self.procedure_trace = {}
            self._document_prior = False
            self._procedures = {}

        def ranked(self, *args, **kwargs):
            result = super().ranked(*args, **kwargs)
            if kwargs.get('return_document_prior'):
                self._document_prior = bool(result[1])
            return result

        def search(self, *, user_id, query, top_k=100, options=None, mode='hybrid_window'):
            self._document_prior = False
            hits = super().search(user_id=user_id, query=query, top_k=top_k,
                                  options=options, mode=mode)
            self.procedure_trace = {'applied': False, 'reason': 'protected_path'}
            if mode != 'query_document_evidence' or self._document_prior or top_k != 100:
                return hits
            with closing(self.connect()) as db:
                sources = [dict(row) for row in db.execute(
                    'SELECT * FROM sources WHERE user_id=? ORDER BY rowid', (user_id,))]
            identity = procedural.digest([(s['id'], s['content'], s['role']) for s in sources])
            cache_key = user_id, identity
            if cache_key not in self._procedures:
                # Cache size is bounded to the native user's memory-cache size.
                self._procedures.clear()
                self._procedures[cache_key] = self.procedure_index.compile(sources)
            procedures = self._procedures[cache_key]
            self.procedure_index.persist(user_id, procedures)
            selected, trace = self.procedure_index.select(procedures, query)
            output, injection = procedural.inject(hits, selected, self.render, self.config.context_chars)
            self.procedure_trace = {**trace, **injection, 'source_identity': identity,
                                    'compiled_authorities': {a: sum(p.authority == a for p in procedures)
                                        for a in ('user_constraint', 'confirmed_habit', 'assistant_suggestion')},
                                    'selected': [asdict(p) for p in selected]}
            return output
    return ProceduralStore
