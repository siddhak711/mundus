"""Error type shared by services and the HTTP layer."""
from __future__ import annotations

from typing import Any

HTTP_STATUS = {"invalid_argument": 400, "unauthorized": 401, "not_found": 404, "not_ingested": 409,
               "sql_rejected": 400, "upstream_unavailable": 503}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    @property
    def status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
