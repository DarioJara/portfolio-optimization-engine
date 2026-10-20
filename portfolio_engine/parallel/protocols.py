"""Contratos desacoplados del ejecutor y sus implementaciones locales (Bloque 5.4; P-07, D-10).

El ejecutor no conoce bases de datos, red ni agentes: recibe datos, solicitudes y control a través
de estas interfaces. Las integraciones reales (SQL Server, orquestador, agente) son del Bloque 6 y
se escribirán contra estos contratos. Aquí solo hay implementaciones **locales y en memoria**.

* :class:`MarketDataProvider` — entrega el :class:`MarketSnapshot` de la ejecución.
* :class:`PortfolioRequestSource` — entrega las solicitudes de cartera.
* :class:`ResultSink` — recibe cada resultado final **exactamente una vez** (también los
  restaurados del diario).
* :class:`RunControl` — permite pedir la cancelación de una ejecución en curso.
* :class:`ProgressReporter` — recibe eventos de progreso y de recuperación (sin datos de carteras).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from portfolio_engine.parallel.task import MarketSnapshot, PortfolioRequest, TaskResult


class ProgressKind(StrEnum):
    """Clase de evento de progreso."""

    STARTED = "STARTED"
    RESUMED = "RESUMED"
    RESULTS = "RESULTS"
    RECOVERY = "RECOVERY"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"
    FINISHED = "FINISHED"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Evento de progreso: contadores y un detalle acotado, nunca datos de carteras.

    Attributes:
        kind: clase del evento.
        completed: tareas con resultado final en este momento.
        total: tareas de la ejecución.
        detail: texto corto y acotado (p. ej. la causa de una reconstrucción).
    """

    kind: ProgressKind
    completed: int
    total: int
    detail: str = ""


@runtime_checkable
class MarketDataProvider(Protocol):
    """Origen de los datos de mercado inmutables de una ejecución."""

    def load_snapshot(self) -> MarketSnapshot:
        """Devuelve el snapshot de mercado (``MuSigmaVersion`` incluida)."""


@runtime_checkable
class PortfolioRequestSource(Protocol):
    """Origen de las solicitudes de optimización."""

    def requests(self) -> Sequence[PortfolioRequest]:
        """Devuelve las solicitudes (``PortfolioID`` únicos)."""


@runtime_checkable
class ResultSink(Protocol):
    """Destino de los resultados finales."""

    def accept(self, results: Sequence[TaskResult]) -> None:
        """Recibe resultados finales; cada ``TaskID`` llega exactamente una vez por ejecución."""


@runtime_checkable
class RunControl(Protocol):
    """Control externo de una ejecución."""

    def cancel_requested(self) -> bool:
        """``True`` si se pidió cancelar: no se envía más trabajo y se conserva lo completado."""


@runtime_checkable
class ProgressReporter(Protocol):
    """Receptor de eventos de progreso."""

    def report(self, event: ProgressEvent) -> None:
        """Recibe un evento; no debe lanzar (un fallo del receptor no debe abortar el cálculo)."""


# ------------------------------------------------------------------ implementaciones locales


@dataclass(frozen=True, eq=False, slots=True)
class InMemoryMarketData:
    """:class:`MarketDataProvider` sobre un snapshot ya construido."""

    snapshot: MarketSnapshot

    def load_snapshot(self) -> MarketSnapshot:
        """Devuelve el snapshot recibido."""
        return self.snapshot


@dataclass(frozen=True, eq=False, slots=True)
class SequenceRequestSource:
    """:class:`PortfolioRequestSource` sobre una secuencia en memoria."""

    items: Sequence[PortfolioRequest]

    def requests(self) -> Sequence[PortfolioRequest]:
        """Devuelve las solicitudes recibidas."""
        return self.items


@dataclass(eq=False, slots=True)
class CollectingResultSink:
    """:class:`ResultSink` que acumula en memoria los resultados recibidos."""

    received: list[TaskResult] = field(default_factory=list)

    def accept(self, results: Sequence[TaskResult]) -> None:
        """Acumula ``results`` en el orden de llegada."""
        self.received.extend(results)


class CancellationToken:
    """:class:`RunControl` local: ``cancel()`` desde cualquier hilo pide la cancelación."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Pide la cancelación de la ejecución que usa este control."""
        self._event.set()

    def cancel_requested(self) -> bool:
        """``True`` si ya se llamó a :meth:`cancel`."""
        return self._event.is_set()


class NullProgressReporter:
    """:class:`ProgressReporter` que descarta los eventos."""

    def report(self, event: ProgressEvent) -> None:
        """No hace nada."""
        del event


@dataclass(eq=False, slots=True)
class RecordingProgressReporter:
    """:class:`ProgressReporter` que guarda los eventos (diagnóstico y pruebas)."""

    events: list[ProgressEvent] = field(default_factory=list)

    def report(self, event: ProgressEvent) -> None:
        """Guarda ``event``."""
        self.events.append(event)
