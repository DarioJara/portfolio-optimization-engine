"""Perfilado del ``CandidateEngine`` por etapas (remediación del Bloque 3, M-1).

Ejecuta ``CandidateEngine.search`` con ``cProfile`` y agrega el tiempo **acumulado** de las
funciones de entrada de cada etapa (screening, listas cortas, generación de vecinos, deduplicación,
hashing, preparación de restricciones, evaluación y selección de finalistas), junto con los
contadores deterministas del ``CandidateDiagnostics`` (evaluaciones por perfil y fase, duplicados,
aciertos de la memoria de evaluaciones) y el número de llamadas a funciones, que **no** depende de
la carga de la máquina. Los tiempos absolutos sí dependen de ella (en este equipo se observó una
diferencia de 5× entre ejecuciones idénticas), por lo que se informa también el mínimo de ``N``
repeticiones de tiempo de CPU.

Uso::

    .venv/Scripts/python benchmarks/scripts/candidate_profile.py --universe 50 --held 20 --reps 5
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.candidates import CandidateEngine  # noqa: E402
from tests.fixtures.candidates import context_of, universe_problem  # noqa: E402
from tests.fixtures.problems import base_config  # noqa: E402

#: Etapa -> (sufijo del fichero, nombre de la función) cuyo tiempo acumulado se atribuye a la etapa.
STAGES: dict[str, list[tuple[str, str]]] = {
    "screening (señales + score)": [("candidates/screening.py", "screen")],
    "listas cortas (selección/exploración)": [("candidates/exploration.py", "select")],
    "generación de vecinos": [("candidates/swap_generator.py", "neighbors")],
    "deduplicación (CompositionHash de vecinos)": [("candidates/prepared.py", "digest")],
    "preparación (restricciones B2 + factibilidad)": [("candidates/prepared.py", "prepare")],
    "evaluación de composiciones (PROJECTED_WEIGHTS)": [("candidates/evaluation.py", "evaluate")],
    "selección de finalistas": [("candidates/beam_search.py", "select_survivors")],
    "hash de composición (incluido en lo anterior)": [
        ("models/portfolio.py", "composition_hash"),
    ],
}


def _cumulative(stats: pstats.Stats, suffix: str, name: str) -> float:
    """Mayor tiempo acumulado entre las funciones ``name`` del fichero (evita doble cuenta)."""
    found = [
        float(values[3])
        for (filename, _, function), values in stats.stats.items()  # type: ignore[attr-defined]
        if filename.replace("\\", "/").endswith(suffix) and function == name
    ]
    return max(found, default=0.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=int, default=50)
    parser.add_argument("--held", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--reps", type=int, default=5)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    config = base_config()
    problem = universe_problem(args.universe, args.held, args.seed, config)
    engine = CandidateEngine(config)
    context = context_of(problem)
    composition = problem.state.composition()
    engine.search(composition, context)  # calentamiento
    cpu: list[float] = []
    for _ in range(args.reps):
        started = time.process_time()
        result = engine.search(composition, context)
        cpu.append(time.process_time() - started)
    profiler = cProfile.Profile()
    profiler.enable()
    result = engine.search(composition, context)
    profiler.disable()
    stats = pstats.Stats(profiler)
    total = float(stats.total_tt)  # type: ignore[attr-defined]
    diagnostics = result.diagnostics
    print(f"universo={args.universe} cartera={args.held} composiciones={len(result.compositions)}")
    print(
        f"CPU min de {args.reps} = {min(cpu):.3f} s ; mediana = {sorted(cpu)[len(cpu) // 2]:.3f} s"
    )
    print(f"llamadas a funciones (deterministas) = {stats.total_calls}")  # type: ignore[attr-defined]
    print(f"tiempo con cProfile = {total:.3f} s (sobrecarga del perfilador incluida)")
    for stage, functions in STAGES.items():
        seconds = sum(_cumulative(stats, suffix, name) for suffix, name in functions)
        print(f"  {stage:<52} {seconds:7.3f} s  {100 * seconds / total:5.1f} %")
    per_phase: Counter[tuple[float, str]] = Counter()
    for stage in diagnostics.stages:
        per_phase[(stage.risk_aversion, stage.algorithm.value)] += stage.evaluated
    print("evaluaciones por (perfil lambda, fase):")
    for (lam, phase), count in sorted(per_phase.items()):
        print(f"  lambda={lam:>5} {phase:<13} {count}")
    print(
        f"total_evaluated={diagnostics.total_evaluated}"
        f" total_generated={diagnostics.total_generated}"
        f" duplicados={sum(s.duplicates_skipped for s in diagnostics.stages)}"
        f" aciertos_memoria={diagnostics.evaluation_cache_hits}"
    )
    print(
        f"max_evaluations={config.candidates.max_evaluations} perfiles="
        f"{len(config.candidates.utility_risk_aversions)} -> tope = perfiles x 2 fases x max"
    )


if __name__ == "__main__":
    main()
