"""BEN-006 (B5.5): todo resultado de benchmark versionado procede de una ejecución real y lleva sus
metadatos de reproducibilidad.

Recorre ``benchmarks/results`` y, para los resultados producidos por el harness de B5.5 (los que
tienen ``metadata.benchmark`` y ``metadata.host_fingerprint``), exige: commit completo, árbol sin
modificaciones (``dirty = false``), versiones de librerías, modelo de CPU y núcleos, comando, huella
del host y semilla (cuando procede). Los resultados históricos de bloques anteriores no se tocan.
"""

from __future__ import annotations

import json
import re

from tests.conftest import REPO_ROOT
from tests.fixtures.benchmark_scripts import load_script

RESULTS = REPO_ROOT / "benchmarks" / "results"
COMMIT = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_VERSIONS = ("numpy", "scipy", "clarabel", "osqp")
NEEDS_SEED = {"scaling", "recovery_bench", "h1_numerical_probe", "cross_platform_reference"}


def _b55_results() -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    found = []
    for path in sorted(RESULTS.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        meta = document.get("metadata", {}) if isinstance(document, dict) else {}
        if "host_fingerprint" in meta:
            found.append((str(path.relative_to(REPO_ROOT)), document))
    return found


def test_the_metadata_collector_reports_every_required_field() -> None:
    common = load_script("_common")
    meta = common.metadata("probe", ["BEN-006"], random_seed=1)
    assert COMMIT.match(meta["git"]["commit"]) and isinstance(meta["git"]["dirty"], bool)
    assert all(meta["versions"][name] for name in REQUIRED_VERSIONS)
    host = meta["host"]
    assert host["cpu_model"] and host["cpu_logical"] and host["cpu_physical"]
    assert host["smt_enabled"] in (True, False) and "ram_available_bytes_at_start" in host
    assert "system_cpu_percent_before" in host and "cpu_governor" in host  # None si no existe
    assert meta["host_fingerprint"] and meta["command"] and meta["python"]


def test_every_versioned_b55_result_carries_complete_reproducibility_metadata() -> None:
    results = _b55_results()
    assert results, "no hay resultados de B5.5 en benchmarks/results"
    for name, document in results:
        meta = document["metadata"]
        assert COMMIT.match(meta["git"]["commit"]), name
        assert meta["git"]["dirty"] is False, f"{name}: medido con el árbol modificado"
        for library in REQUIRED_VERSIONS:
            assert meta["versions"][library], (name, library)
        assert meta["host"]["cpu_model"] and meta["host"]["cpu_logical"], name
        assert meta["command"] and meta["python"] and meta["host_fingerprint"], name
        if meta["benchmark"] in NEEDS_SEED:
            assert "random_seed" in meta, name


def test_scaling_results_validate_every_measurement_and_keep_the_integrity_checks() -> None:
    scaling = [(n, d) for n, d in _b55_results() if d["metadata"]["benchmark"] == "scaling"]
    assert scaling, "no hay resultados de escalado"
    for name, document in scaling:
        for entry in document["results"]:
            assert entry["portfolios"] < 1000, f"{name}: carga masiva sin autorización"
            for cell in entry["cells"]:
                if not cell.get("available", True):
                    continue
                assert cell["valid_measurement"] is True, (name, entry["mix"], cell["mode"])
                if cell["mode"] != "sequential":
                    assert cell["t1_differences_vs_sequential"] == 0, name
                    assert cell["exactly_once_and_balanced"] is True, name
                    audit = cell["constraint_audit"]
                    assert audit["budget_violations"] == audit["bound_violations"] == 0, name


def test_no_result_is_pending_authorization() -> None:
    """D-12: ningún resultado de ≥ 1.000 carteras sin autorización registrada."""
    for name, document in _b55_results():
        meta = document["metadata"]
        if meta["benchmark"] == "scaling" and any(
            e["portfolios"] >= 1000 for e in document["results"]
        ):
            assert meta.get("authorized_by"), name
        if meta["benchmark"] == "capacity_estimate":
            assert meta["executed"] is False, name
