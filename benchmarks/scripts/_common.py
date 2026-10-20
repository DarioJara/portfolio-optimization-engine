"""Utilidades comunes de los benchmarks de B5.5: metadatos (BEN-006), memoria, auditoría de
restricciones y contadores de trabajo.

Los metadatos se recogen en el momento de la ejecución; nada se rellena a mano. Si un dato no está
disponible en la plataforma (p. ej. gobernador de frecuencia en Windows) se registra ``null`` y su
causa, no un valor inventado.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from portfolio_engine.config import EngineConfig  # noqa: E402
from portfolio_engine.models.frontier import (  # noqa: E402
    CompositionFrontierResult,
    GlobalFrontierResult,
)
from portfolio_engine.models.strategy import StrategyResult  # noqa: E402
from portfolio_engine.parallel.task import MarketSnapshot, TaskResult  # noqa: E402
from portfolio_engine.scenarios import MultiScenarioResult  # noqa: E402

TRACKED_LIBRARIES = ("numpy", "scipy", "osqp", "clarabel", "pyscipopt", "threadpoolctl", "psutil")


# ------------------------------------------------------------------------------------ metadatos


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


#: Carpetas cuyo contenido sin versionar altera lo que se mide (código, configuración, pruebas).
_CODE_DIRS = ("portfolio_engine/", "tests/", "benchmarks/scripts/", "config/", "pyproject.toml")


def git_state() -> dict[str, Any]:
    """Commit, rama y estado del árbol.

    ``dirty`` es verdadero si hay ficheros versionados modificados o ficheros sin versionar dentro
    del código, la configuración, las pruebas o los scripts (lo que cambia lo medido). Los ficheros
    sin versionar ajenos (documentos de auditoría, resultados) se listan aparte en
    ``untracked_outside_code``: no alteran la medición pero no se ocultan.
    """
    try:
        lines = _git("status", "--porcelain").splitlines()
        tracked = [line for line in lines if not line.startswith("??")]
        untracked = [line[3:] for line in lines if line.startswith("??")]
        in_code = [path for path in untracked if path.startswith(_CODE_DIRS)]
        return {
            "commit": _git("rev-parse", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(tracked or in_code),
            "modified_tracked_files": tracked[:20],
            "untracked_in_code": in_code[:20],
            "untracked_outside_code": [p for p in untracked if p not in in_code][:20],
        }
    except (OSError, subprocess.CalledProcessError) as error:
        return {"commit": None, "branch": None, "dirty": None, "error": repr(error)}


def library_versions() -> dict[str, str | None]:
    """Versiones instaladas de las librerías relevantes (``None`` si no están instaladas)."""
    from importlib import metadata

    versions: dict[str, str | None] = {}
    for name in TRACKED_LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def cpu_model() -> str | None:
    """Modelo de CPU legible (``/proc/cpuinfo`` en Linux, registro en Windows)."""
    try:
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, ImportError):
        pass
    return platform.processor() or None


def _governor() -> str | None:
    try:
        path = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None  # no disponible en esta plataforma (Windows, contenedores sin cpufreq)


def host_info() -> dict[str, Any]:
    """Descripción del host y carga previa (sin conectarse a ninguna base de datos)."""
    logical = psutil.cpu_count(logical=True)
    physical = psutil.cpu_count(logical=False)
    memory = psutil.virtual_memory()
    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_model(),
        "cpu_logical": logical,
        "cpu_physical": physical,
        # SMT activo si hay más hilos lógicos que núcleos físicos (None si no se puede saber).
        "smt_enabled": None if not (logical and physical) else logical > physical,
        "cpu_governor": _governor(),
        "ram_total_bytes": memory.total,
        "ram_available_bytes_at_start": memory.available,
        "swap_used_bytes_at_start": psutil.swap_memory().used,
        "system_cpu_percent_before": psutil.cpu_percent(interval=0.5),
        "load_note": "medido con psutil; no se consulta ningún servidor de base de datos",
    }


def host_fingerprint(info: dict[str, Any] | None = None) -> str:
    """Huella estable del host para asociar baselines (sin valores que varían por ejecución)."""
    info = info if info is not None else host_info()
    stable = {
        "os": info["os"],
        "machine": info["machine"],
        "cpu_model": info["cpu_model"],
        "cpu_logical": info["cpu_logical"],
        "cpu_physical": info["cpu_physical"],
        "python": platform.python_version(),
        "libs": library_versions(),
    }
    blob = json.dumps(stable, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def metadata(name: str, evidence_for: list[str], **extra: Any) -> dict[str, Any]:
    """Metadatos obligatorios de un resultado (BEN-006)."""
    info = host_info()
    return {
        "benchmark": name,
        "evidence_for": evidence_for,
        "execution_timestamp_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "git": git_state(),
        "python": platform.python_version(),
        "versions": library_versions(),
        "host": info,
        "host_fingerprint": host_fingerprint(info),
        "command": " ".join(sys.argv),
        "env_threads": {
            key: os.environ.get(key)
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
        **extra,
    }


# ----------------------------------------------------------------------------------- memoria


@dataclass
class MemoryReport:
    """Picos de memoria observados por el muestreador (bytes)."""

    coordinator_peak_rss: int = 0
    worker_peak_rss: dict[int, int] = field(default_factory=dict)
    worker_peak_uss: dict[int, int] = field(default_factory=dict)
    total_peak_rss: int = 0
    samples: int = 0

    def to_json(self) -> dict[str, Any]:
        peaks = list(self.worker_peak_rss.values())
        uss = list(self.worker_peak_uss.values())
        return {
            "coordinator_peak_rss_bytes": self.coordinator_peak_rss,
            "worker_processes_observed": len(peaks),
            "worker_peak_rss_bytes_max": max(peaks, default=0),
            "worker_peak_rss_bytes_mean": int(np.mean(peaks)) if peaks else 0,
            "worker_peak_uss_bytes_max": max(uss, default=0),
            "total_peak_rss_bytes": self.total_peak_rss,
            "samples": self.samples,
        }


class MemorySampler:
    """Muestrea RSS (y USS) del coordinador y de todos sus procesos hijos desde un hilo.

    La suma de RSS de varios procesos cuenta varias veces las páginas compartidas (cota superior de
    la memoria física); el USS (memoria exclusiva) es la parte privada de cada proceso. Se informan
    ambos y se advierte de esa diferencia en el informe.
    """

    def __init__(self, interval: float = 0.05) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._me = psutil.Process()
        self.report = MemoryReport()

    def __enter__(self) -> MemorySampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)

    def _loop(self) -> None:
        tick = 0
        while not self._stop.is_set():
            self._sample(with_uss=(tick % 5 == 0))
            tick += 1
            self._stop.wait(self._interval)

    def _sample(self, *, with_uss: bool) -> None:
        total = 0
        try:
            own = self._me.memory_info().rss
            self.report.coordinator_peak_rss = max(self.report.coordinator_peak_rss, own)
            total += own
            for child in self._me.children(recursive=True):
                try:
                    rss = child.memory_info().rss
                    total += rss
                    pid = child.pid
                    self.report.worker_peak_rss[pid] = max(
                        self.report.worker_peak_rss.get(pid, 0), rss
                    )
                    if with_uss:
                        uss = child.memory_full_info().uss
                        self.report.worker_peak_uss[pid] = max(
                            self.report.worker_peak_uss.get(pid, 0), uss
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        self.report.total_peak_rss = max(self.report.total_peak_rss, total)
        self.report.samples += 1


# ------------------------------------------------------------------ auditoría de restricciones


def _weight_vectors(
    value: object,
) -> list[tuple[tuple[str, ...], np.ndarray]]:  # type: ignore[type-arg]
    """Pares ``(asset_ids, pesos)`` de todos los resultados de una operación."""
    found: list[tuple[tuple[str, ...], np.ndarray]] = []  # type: ignore[type-arg]
    if isinstance(value, CompositionFrontierResult):
        found.extend((value.asset_ids, p.weights) for p in value.points if p.weights is not None)
    elif isinstance(value, StrategyResult):
        if value.weights is not None:
            found.append((value.asset_ids, value.weights))
    elif isinstance(value, GlobalFrontierResult):
        children: list[object] = list(value.composition_results)
        children.append(value.continuous)
        for child in children:
            found.extend(_weight_vectors(child))
    elif isinstance(value, MultiScenarioResult):
        children = [*value.frontiers, *value.strategies, value.single_solution]
        for child in children:
            found.extend(_weight_vectors(child))
    return found


@dataclass
class ConstraintAudit:
    """Resultado de la revalidación independiente de las soluciones de una ejecución."""

    solutions: int = 0
    budget_violations: int = 0
    bound_violations: int = 0
    max_budget_error: float = 0.0
    max_bound_excess: float = 0.0
    flag_inconsistencies: int = 0
    status_histogram: dict[str, int] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not (self.budget_violations or self.bound_violations or self.flag_inconsistencies)

    def to_json(self) -> dict[str, Any]:
        return {
            "solutions_checked": self.solutions,
            "budget_violations": self.budget_violations,
            "bound_violations": self.bound_violations,
            "flag_inconsistencies": self.flag_inconsistencies,
            "max_budget_error": self.max_budget_error,
            "max_bound_excess": self.max_bound_excess,
            "solver_status_histogram": dict(sorted(self.status_histogram.items())),
        }


def audit_constraints(
    results: tuple[TaskResult, ...], snapshot: MarketSnapshot, config: EngineConfig
) -> ConstraintAudit:
    """Revalida, sin reutilizar el código del motor, presupuesto, largo-solo y ``MaxWeight``.

    Para cada solución con pesos comprueba ``|Σw − 1| ≤ budget_tolerance``,
    ``w ≥ −bound_tolerance`` y ``w ≤ MaxWeight_i + bound_tolerance`` (tolerancias de
    ``config.solver``). Además comprueba que ninguna solución marcada válida tenga un informe de
    validación inválido. Complementa (no sustituye) al ``SolutionValidator`` que ya corre dentro del
    motor sobre el 100 % de las soluciones, con todas las restricciones del mandato.
    """
    audit = ConstraintAudit()
    budget_tol = config.solver.budget_tolerance
    bound_tol = config.solver.bound_tolerance
    caps = {a.asset_id: a.max_weight for a in snapshot.universe.assets}
    for result in results:
        for outcome in result.operations:
            value = outcome.result
            status = getattr(value, "status", None)
            if status is not None:
                key = getattr(status, "value", str(status))
                audit.status_histogram[key] = audit.status_histogram.get(key, 0) + 1
            for ids, weights in _weight_vectors(value):
                audit.solutions += 1
                budget_error = abs(float(weights.sum()) - 1.0)
                audit.max_budget_error = max(audit.max_budget_error, budget_error)
                if not np.isfinite(weights).all() or budget_error > budget_tol:
                    audit.budget_violations += 1
                upper = np.array([caps[a] if caps[a] is not None else np.inf for a in ids])
                excess = float(max((weights - upper).max(), (-weights).max()))
                audit.max_bound_excess = max(audit.max_bound_excess, excess)
                if excess > bound_tol:
                    audit.bound_violations += 1
            for wrapper in getattr(value, "points", ()):
                point = getattr(wrapper, "point", wrapper)  # GlobalFrontierPoint envuelve un punto
                point_status = getattr(point.status, "value", str(point.status))
                key = f"point:{point_status}"
                audit.status_histogram[key] = audit.status_histogram.get(key, 0) + 1
                validation = getattr(point, "validation", None)
                if point.is_valid_solution and validation is not None and not validation.is_valid:
                    audit.flag_inconsistencies += 1
            validation = getattr(value, "validation", None)
            if getattr(value, "is_valid_solution", False) and validation is not None:
                audit.flag_inconsistencies += 0 if validation.is_valid else 1
    return audit


# --------------------------------------------------------------------------- contadores de trabajo


def frontier_iterations(results: tuple[TaskResult, ...]) -> int:
    """Contador determinista de trabajo: iteraciones de solver de las fronteras."""
    total = 0
    for result in results:
        for outcome in result.operations:
            value = outcome.result
            if isinstance(value, CompositionFrontierResult):
                total += value.diagnostics.total_iterations
            elif isinstance(value, GlobalFrontierResult):
                total += sum(r.diagnostics.total_iterations for r in value.composition_results)
    return total


def status_counts(results: tuple[TaskResult, ...]) -> dict[str, int]:
    """Estados de ejecución (no de solver) de los resultados."""
    counts: dict[str, int] = {}
    for result in results:
        key = result.execution_status.value
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def timed(function: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """Ejecuta ``function`` y devuelve ``(resultado, segundos de pared)``."""
    started = time.perf_counter()
    value = function(*args, **kwargs)
    return value, time.perf_counter() - started
