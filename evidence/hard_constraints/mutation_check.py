"""Mutación manual de las restricciones obligatorias: cada defecto plausible debe ser detectado.

Uso (desde la raíz, entorno ``.venv``; tarda unos minutos)::

    .venv/Scripts/python.exe evidence/hard_constraints/mutation_check.py

Para cada mutante: aplica el cambio de texto, ejecuta las pruebas indicadas, restaura el fichero y
registra si alguna prueba falló (``KILLED``) o no (``SURVIVED``). Termina con código 1 si alguno
sobrevive. No modifica nada de forma permanente.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
UNIT = [
    "tests/unit/hard_constraints",
    "tests/unit/frontiers/test_volatility_band.py",
    "tests/unit/frontiers/test_hard_constraint_gate.py",
]
PIPELINE = ["tests/integration/test_hard_constraints_pipeline.py"]
GATE = ["tests/unit/frontiers/test_hard_constraint_gate.py"]

#: (nombre, fichero, texto original, texto mutado, pruebas a ejecutar)
MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    (
        "validator: suelo de retorno ignorado",
        "portfolio_engine/hard_constraints/validator.py",
        "        recorder.lower(CHECK_MIN_RETURN, value, max(floors), tolerance)",
        "        pass",
        UNIT,
    ),
    (
        "validator: volatilidad minima sin comprobar",
        "portfolio_engine/hard_constraints/validator.py",
        "        recorder.lower(CHECK_MIN_VOLATILITY, volatility, effective.min_volatility, v_tol)",
        "        pass",
        UNIT,
    ),
    (
        "validator: tolerancia de volatilidad sin tope de banda",
        "portfolio_engine/hard_constraints/validator.py",
        "        tolerance = min(tolerance, BAND_TOLERANCE_FRACTION * (high - low))",
        "        pass",
        UNIT,
    ),
    (
        "validator: estado del solver siempre admisible",
        "portfolio_engine/hard_constraints/validator.py",
        "        acceptable = status is SolverStatus.OPTIMAL or (",
        "        acceptable = True or (",
        GATE,
    ),
    (
        "counts: sustituciones = max(a, r)",
        "portfolio_engine/hard_constraints/counts.py",
        "    paired = min(added, removed)",
        "    paired = max(added, removed)",
        UNIT,
    ),
    (
        "counts: posicion con w >= umbral",
        "portfolio_engine/hard_constraints/counts.py",
        "if weight > threshold)",
        "if weight >= threshold)",
        UNIT,
    ),
    (
        "resolver: relajar un maximo sin autorizacion",
        "portfolio_engine/hard_constraints/resolver.py",
        '    if sense == "MAX":\n        return float(new) > float(old)  # type: ignore[arg-type]\n',  # noqa: E501
        '    if sense == "MAX":\n        return False\n',
        UNIT,
    ),
    (
        "integer: limite de sustituciones ignorado",
        "portfolio_engine/constraints/integer.py",
        "        (limits.max_replacements, paired, MAX_REPLACEMENTS),",
        "        (None, paired, MAX_REPLACEMENTS),",
        [*UNIT, *PIPELINE],
    ),
    (
        "preflight: presupuesto de cambios ignorado",
        "portfolio_engine/hard_constraints/preflight.py",
        "        if limit is not None and required > limit:",
        "        if False:",
        [*UNIT, *PIPELINE],
    ),
    (
        "band: se acepta la relajacion sin comprobar el minimo",
        "portfolio_engine/frontiers/volatility_band.py",
        "        return floor is None or self._vol(weights) >= floor - self._vol_tolerance",
        "        return True",
        UNIT,
    ),
    (
        "band: corte tangente con signo cambiado",
        "portfolio_engine/frontiers/volatility_band.py",
        "            rhs = floor**2 + float(current @ self._sigma @ current)",
        "            rhs = floor**2 - float(current @ self._sigma @ current)",
        UNIT,
    ),
    (
        "config_hash: el mandato no entra en el hash",
        "portfolio_engine/config/hashing.py",
        "        if not (field.name in _OMITTED_WHEN_NONE and getattr(config, field.name) is None)",
        "        if field.name not in _OMITTED_WHEN_NONE",
        UNIT,
    ),
    (
        "gate: acepta puntos que el solver no valido",
        "portfolio_engine/frontiers/hard_constraint_gate.py",
        "        if not point.is_valid_solution:",
        "        if False:",
        GATE,
    ),
    (
        "gate: acepta puntos sin pesos",
        "portfolio_engine/frontiers/hard_constraint_gate.py",
        "        if weights is None:",
        "        if False:",
        GATE,
    ),
    (
        "gate: INFEASIBLE sin prueba determinista",
        "portfolio_engine/frontiers/hard_constraint_gate.py",
        "        elif candidate_count == 0 and causes:",
        "        elif candidate_count == 0:",
        GATE,
    ),
]


def run(paths: list[str]) -> int:
    """Código de salida de pytest sobre ``paths`` (``-x``: basta con una prueba que falle)."""
    command = [sys.executable, "-m", "pytest", *paths, "-q", "-x", "-p", "no:cacheprovider"]
    return subprocess.run(command, capture_output=True, text=True, check=False).returncode


def main() -> int:
    survivors: list[str] = []
    for name, file, old, new, paths in MUTANTS:
        path = ROOT / file
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"SKIP (patron no encontrado): {name}")
            survivors.append(f"{name} (patron no encontrado)")
            continue
        path.write_text(original.replace(old, new, 1), encoding="utf-8")
        try:
            code = run(paths)
        finally:
            path.write_text(original, encoding="utf-8")
        verdict = "KILLED" if code != 0 else "SURVIVED"
        print(f"{verdict}: {name}")
        if code == 0:
            survivors.append(name)
    print(f"supervivientes: {survivors}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
