"""Structured JSON logging for the risk-engine service."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from .correlation import get_correlation_id

SERVICE_NAME = "risk-engine"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE_NAME,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Include any extra structured fields the caller attached.
        for key, value in getattr(record, "__dict__", {}).items():
            if key == "extra_fields" and isinstance(value, dict):
                payload.update(value)
        return json.dumps(payload)


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Align uvicorn loggers with our JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
        lg.setLevel(level)
