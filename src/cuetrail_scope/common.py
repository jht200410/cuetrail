"""Standard-library source helpers; no runtime or workspace dependencies."""
import hashlib
from pathlib import Path

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_json(value, spec):
    kind = spec['type']
    types = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str)}
    if not types[kind]:
        raise ValueError('Memory JSON type mismatch')
    if 'enum' in spec and value not in spec['enum']:
        raise ValueError('Memory JSON enum mismatch')
    if kind == 'object':
        if set(value) != set(spec['required']):
            raise ValueError('Memory JSON keys mismatch')
        for key, sub in spec['properties'].items():
            validate_json(value[key], sub)
    if kind in ('array', 'string'):
        if not spec.get('minItems', spec.get('minLength', 0)) <= len(value) <= spec.get('maxItems', spec.get('maxLength', 10**9)):
            raise ValueError('Memory JSON length mismatch')
    if kind == 'array':
        for item in value:
            validate_json(item, spec['items'])
