from hashlib import blake2b
from typing import Any

import rfc8785
from pydantic_core import to_jsonable_python


def canonical_bytes(value: Any) -> bytes:
    normalized = to_jsonable_python(value, serialize_unknown=True)
    return rfc8785.dumps(normalized)


def content_digest(value: Any) -> str:
    return blake2b(canonical_bytes(value), digest_size=32).hexdigest()
