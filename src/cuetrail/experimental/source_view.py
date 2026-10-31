"""Bounded original-token pointers; canonical source and V9 guards stay decisive."""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

from . import evidence
EVIDENCE=Path(evidence.__file__)
EVIDENCE_SHA256='9afb80b62f3b309f42d8a8fc66d61a7ad6e17ecb1b998d5d10bd08d6f423e175'
assert hashlib.sha256(EVIDENCE.read_bytes()).hexdigest()==EVIDENCE_SHA256

SCHEMA_VERSION = 1
MAX_WINDOW_CHARS = 1200
MAX_TOKENS = 512
TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|[\u3400-\u9fff]|[^\W_]+|_+|[^\s]", re.UNICODE)


class PointerError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Token:
    id: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class View:
    id: str
    text: str
    window_start: int
    tokens: tuple[Token, ...]
    canonical_binding: str


def view(source):
    if not isinstance(source, dict) or not {'id', 'role', 'content', 'session_id'} <= set(source):
        raise PointerError('source_schema')
    if any(not isinstance(source[k], str) for k in ('id', 'role', 'content', 'session_id')):
        raise PointerError('source_types')
    text = source['content']
    start = source.get('window_start', 0)
    window = source.get('window_content', text)
    if type(start) is not int or start < 0 or not isinstance(window, str):
        raise PointerError('window_schema')
    if not window.strip() or len(window) > MAX_WINDOW_CHARS:
        raise PointerError('window_size')
    if text[start:start + len(window)] != window:
        raise PointerError('window_offsets')
    tokens = tuple(Token('t' + str(i), m.start(), m.end(), m.group())
                   for i, m in enumerate(TOKEN.finditer(window)))
    if not tokens or len(tokens) > MAX_TOKENS:
        raise PointerError('token_budget')
    # This check guarantees every omitted character is whitespace; original
    # separators remain in the canonical text and are restored without joining.
    cursor = 0
    for token in tokens:
        if window[cursor:token.start].strip():
            raise PointerError('tokenizer_skipped_content')
        cursor = token.end
    if window[cursor:].strip():
        raise PointerError('tokenizer_skipped_content')
    binding = digest(dict(source_id=source['id'], role=source['role'],
        session_id=source['session_id'], timestamp=source.get('timestamp'),
        source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        window_start=start, window=window))
    return View(digest([SCHEMA_VERSION, EVIDENCE_SHA256, binding]), window, start, tokens, binding)

