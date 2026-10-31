"""Experimental procedural evidence API, separate from the original CueTrail API.

No network, model, authentication or tool execution is provided by this module.
Callers supply canonical sources, namespace identity and model output drafts.
"""
from .evidence import Procedure, compile_schema, selection_schema, validate_draft
from .ledger import Ledger, SourceMutation
from .trigger import TriggerPlan, select, materialize
from . import prompts

__all__ = ['Procedure', 'Ledger', 'SourceMutation', 'TriggerPlan', 'compile_schema',
           'selection_schema', 'validate_draft', 'select', 'materialize', 'prompts']
EXPERIMENTAL_VERSION = 'procedure-ledger-preview1'
