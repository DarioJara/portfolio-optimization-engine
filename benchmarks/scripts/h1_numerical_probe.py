"""Investigación de H-1 (fragilidad numérica de B4 dependiente del hardware; AUDIT_BLOCK_5_3 H-1).

H-1: en algunos runners de CI (p. ej. AMD EPYC 7763) fallan de forma intermitente dos tests de B4,
``test_single_solutions_satisfy_the_constraints_of_every_scenario`` y
``test_worst_case_maximizes_the_minimum_scenario_utility``, sin que el código haya cambiado.

Este script **no modifica ningún algoritmo, tolerancia ni test**: solo mide. No se dispone de la CPU
que falla, así que reproduce el MECANISMO con perturbaciones deterministas a nivel de redondeo
(del orden de 1 ulp) de los datos que se entregan a Clarabel, algo que equivale a lo que cambia
entre CPU (orden de sumas, FMA, vectorización):

* Parte A (motor): para el problema del primer test, resuelve ``solve_worst_case`` ``n`` veces por
  perturbación ``eps`` y cuenta los estados finales (``Solved`` ⇒ ``OPTIMAL``; ``AlmostSolved`` ⇒
  ``OPTIMAL_INACCURATE``, que ``accept_inaccurate_solutions = false`` rechaza). Repite con
  tolerancias cónicas distintas de la configurada (SOLO EN ESTE EXPERIMENTO) para ver si el estado
  depende de que ``tol = 1e-9`` esté en el borde de lo alcanzable.
* Parte B (oráculo): el segundo test compara con un oráculo SLSQP con ``ftol = 1e-15``, que exige
  más precisión que la de doble precisión; se mide con qué frecuencia SLSQP declara ``success =
  False`` («Positive directional derivative for linesearch») partiendo de puntos iniciales
  perturbados en 1 ulp, y si aun así devuelve el mismo óptimo.

Salida: ``benchmarks/results/h1_numerical_probe_<timestamp>.json``.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402
from scipy.optimize import minimize  # noqa: E402

from portfolio_engine.config.scenario_definitions import (  # noqa: E402
    ConstraintOverrides,
    GroupLimit,
)
from portfolio_engine.models.enums import CostTreatment, GroupDimension  # noqa: E402
from portfolio_engine.optimizers import clarabel_backend  # noqa: E402
from portfolio_engine.scenarios.multi_scenario import MultiScenarioOptimizer  # noqa: E402
from tests.fixtures.block4 import (  # noqa: E402
    four_asset_problem,
    scenario_definitions,
    with_overrides,
)
from tests.unit.scenarios import test_multi_scenario as b4_tests  # noqa: E402

LAMBDA = b4_tests.LAMBDA


def _first_test_inputs(config: Any) -> tuple[Any, Any]:
    """Problema y escenarios exactamente como en el primer test fallido."""
    problem = four_asset_problem(config, current=[0.25] * 4)
    definitions = list(scenario_definitions())
    definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, 0.4, ()))
    definitions[2] = with_overrides(
        definitions[2],
        ConstraintOverrides(
            None, None, None, (GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.45),)
        ),
    )
    return problem, b4_tests._scenarios(problem, tuple(definitions), config)


def _with_conic_tolerance(config: Any, tolerance: float) -> Any:
    conic = dataclasses.replace(
        config.conic,
        tol_gap_abs=tolerance,
        tol_gap_rel=tolerance,
        tol_feas=tolerance,
        tol_infeas_abs=tolerance,
        tol_infeas_rel=tolerance,
    )
    return dataclasses.replace(config, conic=conic)


def _engine_cell(config: Any, eps: float, repetitions: int, seed: int) -> dict[str, Any]:
    problem, scenarios = _first_test_inputs(config)
    optimizer = MultiScenarioOptimizer(config)
    rng = np.random.default_rng(seed)
    original = clarabel_backend.to_conic_form

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
    iterations: list[int] = []
    valid = 0
    gaps: list[float] = []
    clarabel_backend.to_conic_form = perturbed
    try:
        for _ in range(repetitions):
            solution = optimizer.solve_worst_case(
                problem, scenarios, CostTreatment.GROSS, LAMBDA
            ).single_solution
            assert solution is not None
            states[f"{solution.status.value}/{solution.status_source.value}"] += 1
            valid += bool(solution.is_valid_solution)
            if solution.solve is not None:
                iterations.append(sum(n for _, n in solution.solve.iterations_by_solver))
            extras = dict(solution.extras)
            if "worst_case_utility" in extras and "solver_t" in extras:
                gaps.append(abs(extras["worst_case_utility"] - extras["solver_t"]))
    finally:
        clarabel_backend.to_conic_form = original
    return {
        "relative_perturbation": eps,
        "repetitions": repetitions,
        "valid_solutions": valid,
        "valid_fraction": valid / repetitions,
        "states": dict(sorted(states.items())),
        "clarabel_iterations": sorted(set(iterations)),
        "max_abs_gap_worst_case_utility_vs_solver_t": max(gaps, default=None),
    }


def _oracle_cell(
    config: Any, ftol: float, eps: float, repetitions: int, seed: int
) -> dict[str, Any]:
    """Réplica del oráculo SLSQP del segundo test con punto inicial perturbado."""
    problem = four_asset_problem(config, max_weight=0.6)
    scenarios = b4_tests._scenarios(problem)
    data = b4_tests._arrays(scenarios)
    rng = np.random.default_rng(seed)
    successes, messages, objectives = 0, collections.Counter(), []
    for _ in range(repetitions):
        start = np.concatenate([np.full(4, 0.25), [-1.0]])
        start = start * (1 + eps * rng.standard_normal(start.shape))
        result = minimize(
            lambda x: -x[4],
            start,
            bounds=[(0.0, 0.6)] * 4 + [(None, None)],
            constraints=[{"type": "eq", "fun": lambda x: float(np.sum(x[:4]) - 1.0)}]
            + [
                {"type": "ineq", "fun": lambda x, m=mu, c=s: b4_tests._utility(x[:4], m, c) - x[4]}
                for _, _, mu, s in data
            ],
            method="SLSQP",
            options={"ftol": ftol, "maxiter": 2000},
        )
        successes += bool(result.success)
        messages[str(result.message)] += 1
        objectives.append(float(-result.fun))
    return {
        "ftol": ftol,
        "start_point_relative_perturbation": eps,
        "repetitions": repetitions,
        "success_true": successes,
        "success_fraction": successes / repetitions,
        "messages": dict(messages),
        "optimum_spread_over_runs": float(max(objectives) - min(objectives)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results")
    args = parser.parse_args()
    config = b4_tests.CONFIG
    perturbations = (0.0, 1e-16, 1e-15, 1e-14, 1e-12, 1e-10)
    engine = {
        f"conic_tol_{tolerance:g}": [
            _engine_cell(_with_conic_tolerance(config, tolerance), eps, args.repetitions, args.seed)
            for eps in perturbations
        ]
        for tolerance in (config.conic.tol_feas, 3e-9, 1e-8)
    }
    oracle = [
        _oracle_cell(config, ftol, eps, args.repetitions, args.seed)
        for ftol in (1e-15, 1e-12, 1e-10)
        for eps in (0.0, 1e-16, 1e-12)
    ]
    meta = _common.metadata(
        "h1_numerical_probe",
        ["H-1 (AUDIT_BLOCK_5_3)"],
        configured_conic_tolerance=config.conic.tol_feas,
        accept_inaccurate_solutions=config.solver.accept_inaccurate_solutions,
        ambiguous_status_policy=config.solver.ambiguous_status_policy.value,
        random_seed=args.seed,
        repetitions=args.repetitions,
        engine_changes="NINGUNA: solo se perturban los datos en el experimento y se mide",
    )
    document = {"metadata": meta, "part_a_engine": engine, "part_b_slsqp_oracle": oracle}
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"h1_numerical_probe_{meta['execution_timestamp_utc']}.json"
    path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
    for label, cells in engine.items():
        print(label, [(c["relative_perturbation"], c["valid_fraction"]) for c in cells])
    for cell in oracle:
        print(
            "SLSQP",
            cell["ftol"],
            cell["start_point_relative_perturbation"],
            cell["success_fraction"],
        )
    print(f"resultado: {path}")


if __name__ == "__main__":
    main()
