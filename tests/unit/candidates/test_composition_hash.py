"""CAN-015: ``CompositionHash`` determinista (orden, unicidad, estabilidad entre procesos)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from portfolio_engine.candidates import composition_hash_of
from portfolio_engine.exceptions import CandidateError
from portfolio_engine.models.portfolio import composition_hash

pytestmark = pytest.mark.unit


def _expected(ids: list[str]) -> str:
    """SHA-256 del JSON canónico de los AssetID ordenados, calculado sin usar el código."""
    payload = json.dumps(
        {"Composition": sorted(ids)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_hash_matches_the_canonical_serialization_of_sorted_ids() -> None:
    assert composition_hash_of(["A002", "A000", "A001"]) == _expected(["A000", "A001", "A002"])


def test_same_composition_with_another_order_has_the_same_hash() -> None:
    first = composition_hash_of(["A003", "A001", "A007"])
    assert first == composition_hash_of(["A007", "A003", "A001"])
    assert first == composition_hash_of(("A001", "A007", "A003"))
    assert first == composition_hash(frozenset({"A007", "A001", "A003"}))


def test_different_compositions_have_different_hashes() -> None:
    hashes = {
        composition_hash_of(ids)
        for ids in (["A000", "A001"], ["A000", "A002"], ["A000", "A001", "A002"], ["A001"], ["A00"])
    }
    assert len(hashes) == 5


def test_repeated_calls_give_the_same_hash() -> None:
    ids = ["B", "A", "C"]
    assert len({composition_hash_of(ids) for _ in range(20)}) == 1


def test_hash_is_stable_across_processes_with_different_python_hash_seeds() -> None:
    """No se usa ``hash()`` nativo (aleatorizado por proceso)."""
    code = (
        "from portfolio_engine.candidates import composition_hash_of;"
        "print(composition_hash_of(['A001', 'A000', 'A002']))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            check=True,
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PYTHONPATH": "."},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert outputs == {_expected(["A000", "A001", "A002"])}


def test_duplicates_and_empty_compositions_are_errors() -> None:
    with pytest.raises(CandidateError, match="repetidos"):
        composition_hash_of(["A000", "A000"])
    with pytest.raises(CandidateError, match="vacía"):
        composition_hash_of([])


@pytest.mark.parametrize(
    "ids",
    [
        ["A000"],
        ["B", "A", "C"],
        ["Ñandú", "azúcar", "Z"],
        ['com"illa', r"back\slash", "tab\tchar", "\u2603"],
        [f"A{i:03d}" for i in reversed(range(40))],
    ],
)
def test_the_direct_serialization_equals_the_generic_canonical_json(ids: list[str]) -> None:
    """Optimización de rendimiento (B3): mismos bytes que ``canonical_json`` genérico."""
    from portfolio_engine.utils.hashing import canonical_json, sha256_hex

    generic = sha256_hex(canonical_json({"Composition": sorted(ids)}))
    assert composition_hash(frozenset(ids)) == generic == _expected(ids)
