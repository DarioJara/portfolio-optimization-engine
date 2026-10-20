"""P-07, D-10: contratos desacoplados e implementaciones locales (sin conexiones externas)."""

from __future__ import annotations

import threading

import pytest

from portfolio_engine.parallel import protocols
from portfolio_engine.parallel.protocols import (
    CancellationToken,
    CollectingResultSink,
    InMemoryMarketData,
    MarketDataProvider,
    NullProgressReporter,
    PortfolioRequestSource,
    ProgressEvent,
    ProgressKind,
    ProgressReporter,
    RecordingProgressReporter,
    ResultSink,
    RunControl,
    SequenceRequestSource,
)

pytestmark = pytest.mark.unit


def test_local_implementations_satisfy_their_contracts() -> None:
    assert isinstance(InMemoryMarketData(object()), MarketDataProvider)  # type: ignore[arg-type]
    assert isinstance(SequenceRequestSource(()), PortfolioRequestSource)
    assert isinstance(CollectingResultSink(), ResultSink)
    assert isinstance(CancellationToken(), RunControl)
    assert isinstance(NullProgressReporter(), ProgressReporter)
    assert isinstance(RecordingProgressReporter(), ProgressReporter)


def test_the_providers_return_what_they_were_given() -> None:
    snapshot = object()
    assert InMemoryMarketData(snapshot).load_snapshot() is snapshot  # type: ignore[arg-type]
    items = ()
    assert SequenceRequestSource(items).requests() is items


def test_the_sink_accumulates_in_arrival_order_and_the_reporter_records() -> None:
    sink = CollectingResultSink()
    sink.accept(("a", "b"))  # type: ignore[arg-type]
    sink.accept(("c",))  # type: ignore[arg-type]
    assert sink.received == ["a", "b", "c"]
    reporter = RecordingProgressReporter()
    event = ProgressEvent(ProgressKind.RESULTS, 1, 2, "detalle")
    reporter.report(event)
    NullProgressReporter().report(event)
    assert reporter.events == [event]


def test_cancellation_is_visible_across_threads_and_idempotent() -> None:
    token = CancellationToken()
    assert not token.cancel_requested()
    thread = threading.Thread(target=token.cancel)
    thread.start()
    thread.join()
    token.cancel()
    assert token.cancel_requested()


def test_the_protocol_module_has_no_external_system_dependencies() -> None:
    """Las integraciones con SQL, red o agentes son del Bloque 6 (contra estos contratos)."""
    forbidden = {"pyodbc", "sqlalchemy", "duckdb", "requests", "urllib", "http", "socket"}
    loaded = {name.split(".")[0] for name in vars(protocols) if isinstance(name, str)}
    assert not loaded & forbidden
