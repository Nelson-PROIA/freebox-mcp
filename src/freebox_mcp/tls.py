"""TLS verification against the bundled Freebox root CAs."""

from __future__ import annotations

import ssl
from functools import lru_cache


@lru_cache(maxsize=4)
def freebox_ssl_context(cafile: str) -> ssl.SSLContext:
    """An SSL context that trusts the Freebox root CAs (and only the system +
    those). Used for verified HTTPS to the box."""
    context = ssl.create_default_context(cafile=cafile)
    # CPython 3.13+ turns on VERIFY_X509_STRICT by default, and the Freebox
    # intermediate CA carries no Authority Key Identifier: every box handshake
    # then fails with "Missing Authority Key Identifier".
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context
