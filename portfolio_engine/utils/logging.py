"""Logging estructurado (JSON) del motor (MASTER_SPEC §3).

La librería no configura handlers al importarse: solo emite eventos. La aplicación que la usa
decide dónde se escriben llamando a :func:`configure_json_logging`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import IO

ROOT_LOGGER_NAME = "portfolio_engine"
_CONTEXT_ATTRIBUTE = "context"


class JsonFormatter(logging.Formatter):
    """Formatea cada registro como un objeto JSON de una línea con su contexto estructurado."""

    def format(self, record: logging.LogRecord) -> str:
        """Devuelve el registro serializado con ``timestamp``, ``level``, ``logger``, ``event``."""
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        context = getattr(record, _CONTEXT_ATTRIBUTE, None)
        if isinstance(context, dict):
            payload["context"] = context
        return json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """Devuelve el logger ``portfolio_engine.<name>``."""
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def log_event(logger: logging.Logger, level: int, event: str, **context: object) -> None:
    """Emite ``event`` con un diccionario de contexto estructurado."""
    logger.log(level, event, extra={_CONTEXT_ATTRIBUTE: context})


def configure_json_logging(stream: IO[str], level: int) -> logging.Handler:
    """Adjunta al logger raíz del motor un handler JSON sobre ``stream`` y lo devuelve."""
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.addHandler(handler)
    root.setLevel(level)
    return handler
