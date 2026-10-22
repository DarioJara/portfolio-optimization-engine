"""Barrido H-1: perturbacion determinista de b,q (eps relativo o +-1 ulp) y registro de cada reintento.

uso: python h1_sweep.py <arbol> <salida.json> [n_semillas]
"""
from __future__ import annotations

import dataclasses
import json
import sys

tree, out = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 30
sys.path.insert(0, tree)

import numpy as np  # noqa: E402

from portfolio_engine.models.enums import CostTreatment  # noqa: E402
from portfolio_engine.optimizers import clarabel_backend as cb  # noqa: E402
from portfolio_engine.scenarios import MultiScenarioOptimizer  # noqa: E402
from portfolio_engine.config import ConstraintOverrides, GroupLimit  # noqa: E402
from portfolio_engine.models.enums import GroupDimension  # noqa: E402
from tests.fixtures.block4 import four_asset_problem, scenario_definitions, with_overrides  # noqa: E402
from tests.unit.scenarios.test_multi_scenario import _scenarios  # noqa: E402
from tests.unit.scenarios.test_multi_scenario import CONFIG, LAMBDA  # noqa: E402

import portfolio_engine  # noqa: E402

assert portfolio_engine.__file__.startswith(tree.replace("/", "\\")) or tree in portfolio_engine.__file__.replace("\\", "/"), portfolio_engine.__file__

LOG: list[dict] = []
orig_solve = cb.ClarabelBackend.solve
orig_retry = cb.ClarabelBackend.cold_retry
orig_ctor = cb.clarabel.DefaultSolver
SETTINGS: list[dict] = []


def rec(res):
    return {
        "status": res.status.value,
        "native": res.native_status if hasattr(res, "native_status") else None,
        "iters": int(res.iterations),
        "obj": None if res.objective_value is None else float(res.objective_value),
        "x": None if res.x is None else [float(v) for v in res.x],
    }


def solve(self):
    r = orig_solve(self)
    LOG.append({"k": "first", **rec(r)})
    return r


def retry(self):
    r = orig_retry(self)
    LOG.append({"k": "retry", **rec(r)})
    return r


def spy(*a):
    s = a[-1]
    SETTINGS.append({n: getattr(s, n) for n in ("tol_gap_abs", "tol_gap_rel", "tol_feas", "tol_infeas_abs", "tol_infeas_rel", "max_iter", "equilibrate_enable", "static_regularization_enable", "presolve_enable")})
    return orig_ctor(*a)


cb.ClarabelBackend.solve = solve
cb.ClarabelBackend.cold_retry = retry
cb.clarabel.DefaultSolver = spy
orig_form = cb.to_conic_form


def make_perturb(mode, eps, seed):
    rng = np.random.default_rng(seed)

    def perturbed(problem, q, lower, upper):
        form = orig_form(problem, q, lower, upper)
        if mode == "rel":
            b = form.b * (1 + eps * rng.standard_normal(form.b.shape))
            qq = form.q * (1 + eps * rng.standard_normal(form.q.shape))
        else:  # +-1 ulp determinista
            sb = np.where(rng.random(form.b.shape) < 0.5, -np.inf, np.inf)
            sq = np.where(rng.random(form.q.shape) < 0.5, -np.inf, np.inf)
            b = np.nextafter(form.b, sb)
            qq = np.nextafter(form.q, sq)
        return dataclasses.replace(form, b=b, q=qq)

    return perturbed


problem = four_asset_problem(CONFIG, current=[0.25] * 4)
definitions = list(scenario_definitions())
definitions[1] = with_overrides(definitions[1], ConstraintOverrides(0.05, None, 0.4, ()))
definitions[2] = with_overrides(definitions[2], ConstraintOverrides(None, None, None, (GroupLimit(GroupDimension.SECTOR, "Tech", None, 0.45),)))
scenarios = _scenarios(problem, tuple(definitions))
opt = MultiScenarioOptimizer(CONFIG)
rows = []
cells = [("rel", 0.0)] + [("rel", e) for e in (1e-16, 1e-14, 1e-12, 1e-10)] + [("ulp", 1.0)]
for mode, eps in cells:
    for seed in range(N):
        LOG.clear()
        SETTINGS.clear()
        if eps:
            cb.to_conic_form = make_perturb(mode, eps, seed)
        else:
            cb.to_conic_form = orig_form
        sol = opt.solve_worst_case(problem, scenarios, CostTreatment.GROSS, LAMBDA).single_solution
        rows.append(
            {
                "mode": mode, "eps": eps, "seed": seed,
                "valid": bool(sol.is_valid_solution),
                "status": sol.status.value, "source": sol.status_source.value,
                "violations": None if sol.validation is None else len(sol.validation.violations),
                "w": None if sol.weights is None else [float(v) for v in sol.weights],
                "gap": None if sol.weights is None else abs(sol.extra("solver_t") - sol.extra("worst_case_utility")),
                "log": [dict(e) for e in LOG],
                "settings": [dict(s) for s in SETTINGS],
            }
        )
json.dump(rows, open(out, "w"))
print("done", len(rows))
