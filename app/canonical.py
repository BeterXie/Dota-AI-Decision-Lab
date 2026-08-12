from hashlib import blake2b
from typing import Any

import rfc8785
from pydantic_core import to_jsonable_python


def canonical_bytes(value: Any) -> bytes:
    normalized = _json_safe_integers(to_jsonable_python(value, serialize_unknown=True))
    return rfc8785.dumps(normalized)


def content_digest(value: Any) -> str:
    return blake2b(canonical_bytes(value), digest_size=32).hexdigest()


def _json_safe_integers(value: Any) -> Any:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value) if abs(value) > 9_007_199_254_740_991 else value
    if isinstance(value, list):
        return [_json_safe_integers(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe_integers(item) for key, item in value.items()}
    return value
