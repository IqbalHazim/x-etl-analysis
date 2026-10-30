"""Author anonymization.

A plain SHA-256 of a numeric X user ID can be reversed by hashing every possible ID, 
so we use a keyed hash (HMAC) with a secret salt instead. The same author always map to
the same hash, so per-author counts are still possible.
"""

import hashlib
import hmac

HASH_LENGTH = 16  # 64 bits: no realistic collisions at this dataset's size


def hash_author_id(author_id: str | int, salt: str) -> str:
    if not salt:
        raise ValueError("salt must not be empty")
    digest = hmac.new(salt.encode(), str(author_id).encode(), hashlib.sha256)
    return digest.hexdigest()[:HASH_LENGTH]
