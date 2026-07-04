"""Anonymous reference generation (Feature 03)."""

import secrets
import string

_ALPHABET = string.ascii_uppercase + string.digits


def generate_anon_ref(prefix: str = "ANON") -> str:
    """Generate an anonymous reference like 'ANON-7X3K'."""
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(4))
    return f"{prefix}-{suffix}"
