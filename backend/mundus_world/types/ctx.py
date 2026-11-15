"""Per-request context shared by the API layer and the services."""
from __future__ import annotations

import contextvars

# Claim scope. Empty string: the shared memory every caller sees. A run id: a private memory for that run, so many
# evaluation runs can execute at once, each starting from an empty store, without touching the shared one.
CLAIM_SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar("claim_scope", default="")
