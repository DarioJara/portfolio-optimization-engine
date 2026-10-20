"""P-05: códec JSON del diario (ida y vuelta exacta de todos los resultados y rechazo seguro)."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pytest

from portfolio_engine.models.enums import SolverStatus
from portfolio_engine.parallel.codec import CodecError, decode, encode
from portfolio_engine.parallel.executor import SequentialExecutor
from portfolio_engine.parallel.task import ExecutionStatus
from tests.fixtures.parallel import Comparison, reference_requests
from tests.fixtures.problems import base_config

pytestmark = pytest.mark.unit

CONFIG = base_config()


def _through_json(value: object) -> Any:
    """Ida y vuelta por texto JSON (lo que hace el diario en disco)."""
    return decode(json.loads(json.dumps(encode(value), allow_nan=False)))


def test_all_workload_classes_round_trip_exactly() -> None:
    """Cada resultado de cada clase W0-W5 se reconstruye idéntico (0 floats distintos).

    Es la prueba de que el códec cubre todos los tipos que producen los motores: el comparador
    genérico falla con «tipo no comparable» ante cualquier tipo que no sepa recorrer.
    """
    snapshots, by_universe = reference_requests(CONFIG, 1)
    checked = 0
    for key, requests in by_universe.items():
        run = SequentialExecutor(CONFIG, snapshots[key]).run(requests)
        for result in run.results:
            assert result.execution_status is ExecutionStatus.COMPLETED, result.portfolio_id
            restored = _through_json(result)
            comparison = Comparison(tolerance=0.0)
            comparison.compare(result, restored)
            assert comparison.differences == [], (result.portfolio_id, comparison.differences[:3])
            assert comparison.inexact_floats == 0
            assert comparison.float_comparisons > 0
            checked += 1
    assert checked == sum(len(v) for v in by_universe.values())


def test_solver_states_survive_the_round_trip() -> None:
    state = _through_json(SolverStatus.OPTIMAL_INACCURATE)
    assert state is SolverStatus.OPTIMAL_INACCURATE


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        7,
        -3,
        2**70,
        0.1,
        -0.0,
        1e-300,
        "texto ñ",
        (1, (2.5, "a")),
        [1, 2],
        {"a": 1, 2: (3,), (4, 5): None},
        frozenset({1, 2}),
        {3, 4},
        b"\x00\xff",
    ],
)
def test_plain_values_round_trip(value: object) -> None:
    restored = _through_json(value)
    assert restored == value and type(restored) is type(value)
    if isinstance(value, float):
        assert math.copysign(1.0, restored) == math.copysign(1.0, value)


@pytest.mark.parametrize("number", [math.nan, math.inf, -math.inf])
def test_non_finite_floats_round_trip(number: float) -> None:
    restored = _through_json(number)
    assert (math.isnan(restored) and math.isnan(number)) or restored == number


def test_arrays_round_trip_bit_for_bit_and_scalars_become_python_numbers() -> None:
    array = np.array([[0.1, math.nan], [math.inf, -0.0]])
    restored = _through_json(array)
    assert restored.dtype == array.dtype and restored.shape == array.shape
    assert restored.tobytes() == array.tobytes()
    for dtype in (np.int64, np.bool_, np.float32):
        sample = np.arange(4).astype(dtype)
        assert _through_json(sample).tobytes() == sample.tobytes()
    assert _through_json(np.float64(0.25)) == 0.25
    assert isinstance(_through_json(np.int64(3)), int)
    assert _through_json(np.array([], dtype=np.float64)).shape == (0,)


def test_unsupported_values_are_rejected_when_encoding() -> None:
    with pytest.raises(CodecError, match="no admitido"):
        encode(np.array([object()], dtype=object))
    with pytest.raises(CodecError, match="no serializable"):
        encode(object())
    with pytest.raises(CodecError, match="no serializable"):
        encode(complex(1, 2))


@pytest.mark.parametrize(
    "document",
    [
        {"$dc": ["os:system", {}]},  # fuera de portfolio_engine
        {"$dc": ["subprocess:Popen", {}]},
        {"$dc": ["portfolio_engine.parallel.task:run_portfolio", {}]},  # no es dataclass
        {"$dc": ["portfolio_engine.nope:Missing", {}]},
        {"$dc": ["portfolio_engine:__builtins__", {}]},
        {"$dc": "mal-formada"},
        {"$e": ["portfolio_engine.parallel.task:TaskResult", "X"]},  # no es enum
        {"$e": ["portfolio_engine.models.enums:SolverStatus", "NO_EXISTE"]},
        {"$a": ["|O", [1], "AAAA"]},  # dtype object
        {"$a": ["<f8", [1], "no-base64!!"]},
        {"$a": ["<f8"]},
        {"$f": "huge"},
        {"$unknown": 1},
        {"a": 1, "b": 2},  # más de una clave
        {"$t": "no-lista"},
    ],
)
def test_decoding_rejects_hostile_or_malformed_documents(document: object) -> None:
    with pytest.raises((CodecError, ValueError)):
        decode(document)


def test_a_dataclass_with_different_fields_is_rejected() -> None:
    snapshots, by_universe = reference_requests(CONFIG, 1)
    result = SequentialExecutor(CONFIG, snapshots["p8"]).run(by_universe["p8"][:1]).results[0]
    document = encode(result)
    assert isinstance(document, dict)
    fields = document["$dc"][1]
    del fields["worker_pid"]
    with pytest.raises(CodecError, match="no coinciden"):
        decode(document)
