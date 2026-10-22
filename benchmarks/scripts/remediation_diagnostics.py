"""Diagnóstico de H-1 (B4) y F-B55-1 (B3) por CPU (REMEDIATION_H1_FB551.md).

Mide, sin cambiar ningún algoritmo ni tolerancia, qué hace cada CPU con los dos defectos y qué
efecto tiene la remediación:

* ``env``: modelo de CPU, flags relevantes, versiones y despacho de BLAS/NumPy (para atribuir una
  divergencia a una CPU concreta y no a «una plataforma»).
* ``h1``: la instancia degenerada de H-1 sin perturbar y con perturbaciones de 1 ulp, **antes**
  (``retry_equilibrate = equilibrate``: el reintento repite la misma numérica) y **después** de la
  remediación (``retry_equilibrate`` configurado), y las últimas iteraciones de Clarabel.
* ``fb551``: búsqueda de candidatos sobre un universo con activos clonados (empates exactos) con y
  sin ruido de 1 ulp, **antes** (desempate por ``-mejora`` exacta) y **después** (``rank_nodes``).

Cada subcomando imprime una línea JSON por celda y, con ``--annotate``, la repite como anotación de
GitHub Actions (``::notice``) para que la evidencia sea consultable públicamente.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FLAG_PATTERN = re.compile(r"\b(avx|avx2|fma|avx512[a-z_0-9]*|sse4_2|bmi2)\b")


def dispatch_context() -> dict[str, Any]:
    """Qué núcleo de OpenBLAS está activo y si se forzó (para no confundir pasos de CI)."""
    context: dict[str, Any] = {"forced_coretype": os.environ.get("OPENBLAS_CORETYPE", "")}
    try:
        from threadpoolctl import threadpool_info

        context["blas_arch"] = [e.get("architecture") for e in threadpool_info()]
    except ImportError:
        pass
    return context


def emit(label: str, payload: dict[str, Any], annotate: bool) -> None:
    payload = {**payload, "ctx": dispatch_context()}
    line = json.dumps(payload, sort_keys=True, default=str)
    print(f"{label}: {line}", flush=True)
    if annotate:
        print(f"::notice title=diag-{label}::{line[:3800]}", flush=True)


def cpu_description() -> dict[str, Any]:
    model, flags = platform.processor(), ""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
        model_match = re.search(r"model name\s*:\s*(.*)", text)
        flags_match = re.search(r"flags\s*:\s*(.*)", text)
        model = model_match.group(1).strip() if model_match else model
        flags = flags_match.group(1) if flags_match else ""
    except OSError:
        pass
    return {"model": model, "flags": sorted(set(FLAG_PATTERN.findall(flags)))}


def cmd_env(annotate: bool) -> None:
    import clarabel
    import osqp
    import scipy

    info: dict[str, Any] = {
        "cpu": cpu_description(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "clarabel": clarabel.__version__,
        "osqp": osqp.__version__,
        "env": {k: v for k, v in os.environ.items() if k.startswith(("OPENBLAS", "NPY_", "OMP_"))},
    }
    try:
        from numpy._core._multiarray_umath import __cpu_features__ as features

        info["numpy_cpu_features_enabled"] = sorted(k for k, v in features.items() if v)
    except ImportError:
        pass
    try:
        from threadpoolctl import threadpool_info

        info["blas"] = [
            {k: v for k, v in entry.items() if k in ("internal_api", "version", "architecture")}
            for entry in threadpool_info()
        ]
    except ImportError:
        pass
    emit("env", info, annotate)


# ---------------------------------------------------------------------------------------- H-1


@contextmanager
def captured_stdout_fd() -> Iterator[Callable[[], str]]:
    """Captura lo que Clarabel (Rust) escribe en el descriptor 1, que ``contextlib`` no ve."""
    sys.stdout.flush()
    saved = os.dup(1)
    with tempfile.TemporaryFile(mode="w+b") as handle:
        os.dup2(handle.fileno(), 1)
        try:

            def read() -> str:
                handle.flush()
                handle.seek(0)
                return handle.read().decode("utf-8", errors="replace")

            yield read
        finally:
            os.dup2(saved, 1)
            os.close(saved)


def h1_problem() -> tuple[Any, Any, Any]:
    from portfolio_engine.config import ConstraintOverrides, GroupLimit
    from portfolio_engine.models.enums import GroupDimension
    from tests.fixtures.block4 import four_asset_problem, scenario_definitions, with_overrides
    from tests.unit.scenarios.test_multi_scenario import CONFIG, _scenarios

    problem = four_asset_problem(CONFIG, current=[0.25] * 4)
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, 0.4, ()))
    definitions[2] = with_overrides(
        definitions[2],
        ConstraintOverrides(
            None, None, None, (GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.45),)
        ),
    )
    return CONFIG, problem, _scenarios(problem, tuple(definitions))


def h1_cell(
    config: Any, problem: Any, scenarios: Any, eps: float, repetitions: int
) -> dict[str, Any]:
    from portfolio_engine.models.enums import CostTreatment
    from portfolio_engine.optimizers import clarabel_backend
    from portfolio_engine.scenarios import MultiScenarioOptimizer
    from tests.unit.scenarios.test_multi_scenario import LAMBDA

    original = clarabel_backend.to_conic_form
    rng = np.random.default_rng(0)

    def perturbed(problem_: Any, q: Any, lower: Any, upper: Any) -> Any:
        form = original(problem_, q, lower, upper)
        if eps == 0.0:
            return form
        return dataclasses.replace(
            form,
            b=form.b * (1 + eps * rng.standard_normal(form.b.shape)),
            q=form.q * (1 + eps * rng.standard_normal(form.q.shape)),
        )

    states: collections.Counter[str] = collections.Counter()
    iterations: set[int] = set()
    valid = 0
    clarabel_backend.to_conic_form = perturbed
    try:
        for _ in range(repetitions):
            solution = (
                MultiScenarioOptimizer(config)
                .solve_worst_case(problem, scenarios, CostTreatment.GROSS, LAMBDA)
                .single_solution
            )
            assert solution is not None
            states[f"{solution.status.value}/{solution.status_source.value}"] += 1
            valid += bool(solution.is_valid_solution)
            if solution.solve is not None:
                iterations.add(sum(n for _, n in solution.solve.iterations_by_solver))
    finally:
        clarabel_backend.to_conic_form = original
    return {
        "eps": eps,
        "n": repetitions,
        "valid": valid,
        "states": dict(sorted(states.items())),
        "iterations": sorted(iterations),
    }


def clarabel_tail(config: Any, problem: Any, scenarios: Any) -> list[str]:
    """Últimas filas de la tabla de iteraciones de Clarabel (primer intento, sin perturbar)."""
    import clarabel

    from portfolio_engine.models.enums import CostTreatment
    from portfolio_engine.optimizers import clarabel_backend
    from portfolio_engine.scenarios import MultiScenarioOptimizer

    original = clarabel_backend.ClarabelBackend._new_solver

    def verbose(self: Any, form: Any, max_iterations: int, equilibrate: bool) -> Any:
        s = clarabel.DefaultSettings()
        s.verbose = True
        s.max_iter = max_iterations
        c = self._conic
        s.tol_gap_abs, s.tol_gap_rel, s.tol_feas = c.tol_gap_abs, c.tol_gap_rel, c.tol_feas
        s.tol_infeas_abs, s.tol_infeas_rel = c.tol_infeas_abs, c.tol_infeas_rel
        s.equilibrate_enable = equilibrate
        return clarabel.DefaultSolver(form.P, form.q, form.A, form.b, list(form.cones), s)

    clarabel_backend.ClarabelBackend._new_solver = verbose  # type: ignore[method-assign]
    try:
        with captured_stdout_fd() as read:
            outcome = (
                MultiScenarioOptimizer(config)
                .solve_worst_case(problem, scenarios, CostTreatment.GROSS, LAMBDA_OF_H1)
                .single_solution
            )
            text = read()
    finally:
        clarabel_backend.ClarabelBackend._new_solver = original  # type: ignore[method-assign]
    rows = [line.strip() for line in text.splitlines() if re.match(r"^\s*\d+\s+[+-]", line)]
    status = [line.strip() for line in text.splitlines() if "Terminated with status" in line]
    final = "none" if outcome is None else f"{outcome.status.value}/{outcome.status_source.value}"
    return [f"engine status: {final}", *rows[:1], *rows[-4:], *status[:2]]


LAMBDA_OF_H1 = 3.0


def cmd_h1(annotate: bool, repetitions: int) -> None:
    config, problem, scenarios = h1_problem()
    conic = config.conic
    emit(
        "h1-config",
        {
            "equilibrate": conic.equilibrate,
            "retry_equilibrate": conic.retry_equilibrate,
            "tol_feas": conic.tol_feas,
        },
        annotate,
    )
    emit("h1-clarabel-tail", {"rows": clarabel_tail(config, problem, scenarios)}, annotate)
    before = dataclasses.replace(
        config, conic=dataclasses.replace(conic, retry_equilibrate=conic.equilibrate)
    )
    for label, cfg in (("before", before), ("after", config)):
        for eps in (0.0, 1e-16, 1e-14, 1e-12):
            payload = h1_cell(cfg, problem, scenarios, eps, repetitions if eps else 3)
            emit(f"h1-{label}", payload, annotate)


# ------------------------------------------------------------------------------------ F-B55-1


def clone_problem(config: Any) -> Any:
    from tests.fixtures.candidates import random_problem
    from tests.fixtures.problems import make_problem

    base = random_problem(8, [0, 1, 2, 3], 7, config)
    mu = base.risk_model.expected_returns.values
    sigma = base.risk_model.covariance.matrix
    source = [0, 1, 2, 3, 4, 5, 6, 7, 4, 5]
    current = [0.25, 0.25, 0.25, 0.25] + [0.0] * 6
    return make_problem(
        mu[source],
        sigma[np.ix_(source, source)].copy(),
        current,
        config,
        universe_overrides={"MaxWeight": [0.6] * 10},
    )


def perturb(problem: Any, seed: int, eps: float) -> Any:
    rng = np.random.default_rng(seed)
    risk = problem.risk_model
    n = risk.covariance.matrix.shape[0]
    noise = rng.standard_normal((n, n))
    noise = (noise + noise.T) / 2
    covariance = dataclasses.replace(
        risk.covariance, matrix=risk.covariance.matrix * (1 + eps * noise)
    )
    expected = dataclasses.replace(
        risk.expected_returns,
        values=risk.expected_returns.values
        * (1 + eps * rng.standard_normal(risk.expected_returns.values.shape)),
    )
    return dataclasses.replace(
        problem,
        risk_model=dataclasses.replace(risk, covariance=covariance, expected_returns=expected),
    )


def cmd_fb551(annotate: bool, repetitions: int) -> None:
    from portfolio_engine.candidates import beam_search, expansion, local_search
    from tests.fixtures.candidates import search, with_candidates
    from tests.fixtures.problems import base_config

    config = with_candidates(
        base_config(),
        beam_width=3,
        max_levels=2,
        swap_orders=(1,),
        local_search_starts=1,
        utility_risk_aversions=(1.0, 4.0, 16.0),
        max_candidates=12,
        shortlist_in=10,
        shortlist_out=4,
        max_evaluations=300,
    )
    problem = clone_problem(config)
    real = expansion.rank_nodes

    def exact(nodes: Any, tolerance: float) -> Any:
        return real(nodes, 0.0)

    for label, function in (("before", exact), ("after", real)):
        beam_search.rank_nodes = function
        local_search.rank_nodes = function
        reference = {c.composition_id for c in search(config, problem).compositions}
        for eps in (1e-16, 1e-14, 1e-12):
            sets = collections.Counter(
                len(
                    {
                        c.composition_id
                        for c in search(config, perturb(problem, seed, eps)).compositions
                    }
                    ^ reference
                )
                == 0
                for seed in range(repetitions)
            )
            emit(
                f"fb551-{label}",
                {
                    "eps": eps,
                    "n": repetitions,
                    "same_candidates": sets[True],
                    "different": sets[False],
                    "reference_size": len(reference),
                },
                annotate,
            )
    beam_search.rank_nodes = real
    local_search.rank_nodes = real


def run_checked(command: list[str]) -> str:
    return subprocess.run(command, check=False, capture_output=True, text=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("env", "h1", "fb551"))
    parser.add_argument("--annotate", action="store_true")
    parser.add_argument("--repetitions", type=int, default=30)
    args = parser.parse_args()
    if args.command == "env":
        cmd_env(args.annotate)
    elif args.command == "h1":
        cmd_h1(args.annotate, args.repetitions)
    else:
        cmd_fb551(args.annotate, args.repetitions)


if __name__ == "__main__":
    main()
