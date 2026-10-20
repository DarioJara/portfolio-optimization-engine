"""GOV-006, GOV-008, CFG-015, SOL-010 y controles de alcance (análisis estático del paquete).

El Bloque 2 amplía las reglas del Bloque 1: nuevos paquetes en el grafo de capas, OSQP confinado
en su backend y ausencia de módulos de los Bloques 3-6. El Bloque 3 añade los paquetes
``candidates`` y ``parallel`` (solo determinismo) al grafo y retira de la lista de módulos
futuros los que implementa; los de los Bloques 4-6 siguen prohibidos.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from collections.abc import Iterator
from pathlib import Path

import pytest

import portfolio_engine

pytestmark = pytest.mark.architecture

PACKAGE_ROOT = Path(portfolio_engine.__file__).resolve().parent

#: Dependencias permitidas entre paquetes (ARCHITECTURE §4.1). La clave depende de los valores.
ALLOWED_DEPENDENCIES: dict[str, set[str]] = {
    "exceptions": set(),
    "utils": {"exceptions"},
    "models": {"exceptions", "utils"},
    "config": {"exceptions", "utils", "models"},
    "data": {"exceptions", "utils", "models", "config"},
    "returns": {"exceptions", "utils", "models", "config"},
    "risk": {"exceptions", "utils", "models", "config", "returns"},
    # Bloque 2 (ARCHITECTURE §4.1). ``validation`` NO depende de ``optimizers`` (independencia §44).
    # Bloque 5.2: la orquestación (``task``, ``executor``, ``worker``) compone los motores B1-B4;
    # los paquetes de capas inferiores solo pueden importar ``parallel.determinism`` (véase
    # ``test_lower_layers_only_import_parallel_determinism``), de modo que el grafo de módulos
    # sigue siendo acíclico.
    "parallel": {
        "exceptions",
        "utils",
        "models",
        "config",
        "costs",
        "constraints",
        "metrics",
        "optimizers",
        "validation",
        "candidates",
        "frontiers",
        "scenarios",
        "risk",
        "cache",
    },
    # Bloque 5.3: la caché de resultados es de bajo nivel (claves canónicas y almacén acotado).
    "cache": {"exceptions", "utils"},
    "costs": {"exceptions", "utils", "models", "config"},
    "metrics": {"exceptions", "utils", "models", "config", "costs"},
    "constraints": {"exceptions", "utils", "models", "config", "costs"},
    "optimizers": {"exceptions", "utils", "models", "config", "constraints", "costs"},
    "validation": {"exceptions", "utils", "models", "config", "costs", "constraints", "metrics"},
    # Bloque 3: ``candidates`` usa constraints/validation/parallel (sin optimizers ni frontiers);
    # ``frontiers`` (frontera global) consume ``candidates`` y ``parallel`` (orden estable).
    "candidates": {
        "exceptions",
        "utils",
        "models",
        "config",
        "costs",
        "constraints",
        "validation",
        "parallel",
    },
    "frontiers": {
        "exceptions",
        "utils",
        "models",
        "config",
        "costs",
        "constraints",
        "metrics",
        "optimizers",
        "validation",
        "candidates",
        "parallel",
    },
    "outputs": {"exceptions", "utils", "models", "config", "costs", "metrics"},
    # Bloque 4: ``scenarios`` orquesta escenarios y optimización multiescenario sobre los motores de
    # fronteras y optimizadores; nadie por debajo depende de ``scenarios``.
    "scenarios": {
        "exceptions",
        "utils",
        "models",
        "config",
        "costs",
        "constraints",
        "metrics",
        "optimizers",
        "validation",
        "candidates",
        "frontiers",
        "risk",
    },
    "benchmark": {
        "exceptions",
        "utils",
        "models",
        "config",
        "frontiers",
        "optimizers",
        "candidates",
        "scenarios",
        "validation",
        "constraints",
        "costs",
        "metrics",
    },
}

#: Paquetes/módulos de los Bloques 4-6 que no deben existir en el Bloque 3 (los del Bloque 3 —
#: ``candidates``, ``frontiers/global_frontier.py``, ``constraints/integer.py`` y
#: ``parallel/determinism.py``— se han implementado y ya no figuran aquí).
LATER_BLOCK_PACKAGES = (
    # B5.4 entregó ``parallel/journal.py`` (diario local de recuperación): ya no es «posterior».
    # La persistencia SQL/empresarial sigue siendo del Bloque 6 (``staging``/``persistence``).
    "staging",
    "persistence",
    "engine.py",
)

#: Módulos del Bloque 4 que deben existir (ScenarioEngine, backends cónico y mixto, formulaciones).
BLOCK_4_MODULES = (
    "scenarios/scenario_engine.py",
    "scenarios/multi_scenario.py",
    "metrics/cvar_metric.py",
    "optimizers/clarabel_backend.py",
    "optimizers/mixed_integer_backend.py",
    "optimizers/scip_backend.py",
    "optimizers/nonconvex_backend.py",
    "optimizers/formulations/sharpe.py",
    "optimizers/formulations/volatility.py",
    "optimizers/formulations/cvar.py",
    "optimizers/formulations/robust.py",
    "optimizers/formulations/multi_scenario.py",
    "optimizers/formulations/miqp.py",
    "frontiers/strategy_optimizer.py",
    "frontiers/exact_mip_validation.py",
    "validation/advanced_validator.py",
)

#: ``osqp`` solo puede importarse en su backend (test aparte); el resto sigue prohibido.
#: Solo ``parallel/`` puede usar procesos (Bloque 5.2); ningún otro paquete importa estos módulos.
PROCESS_IMPORTS = ("multiprocessing", "concurrent")
FORBIDDEN_IMPORTS = (
    "cvxpy",
    "gurobipy",
    "pyodbc",
    "duckdb",
    "sklearn",
)

#: Literales numéricos neutros (estructurales: índices, mitades, dobles, unidad presupuestaria).
NEUTRAL_LITERALS = {0, 1, 2, -1, 0.5}
#: Constantes con nombre permitidas: conversiones de unidades y constantes matemáticas.
ALLOWED_NAMED_CONSTANTS = {
    ("models/costs.py", "BPS_PER_UNIT"),
    # Bloque 5.5: conversión de unidades (segundos por hora) de la proyección de capacidad.
    ("benchmark/scaling.py", "SECONDS_PER_HOUR"),
    ("data/validation/market_data_validator.py", "MAD_TO_STD_NORMAL"),
    ("data/validation/report.py", "SUMMARY_ISSUES"),
    # Bloque 5.3: constantes de formato/plataforma de los datos compartidos (no son parámetros
    # de negocio): alineación de buffers, protocolo pickle 5 (PEP 574), tamaño del sufijo de nombre
    # de segmento y constantes de la API de procesos de Windows.
    ("parallel/shared_data.py", "ALIGNMENT"),
    ("parallel/shared_data.py", "PICKLE_OUT_OF_BAND_PROTOCOL"),
    ("parallel/shared_data.py", "SHM_TOKEN_BYTES"),
    ("parallel/shared_data.py", "SHM_NAME_PARTS"),
    ("parallel/shared_data.py", "WIN_PROCESS_QUERY_LIMITED_INFORMATION"),
    ("parallel/shared_data.py", "WIN_STILL_ACTIVE"),
    ("parallel/shared_data.py", "WIN_ERROR_ACCESS_DENIED"),
    ("parallel/shared_data.py", "REMOVE_RETRIES"),
    ("parallel/shared_data.py", "REMOVE_DELAY_SECONDS"),
    ("parallel/worker.py", "MAX_BACKING_DEPTH"),
    # Bloque 5.4: constantes de formato del diario y de las marcas de progreso (no son parámetros
    # de negocio): número de partes de un array/par del códec JSON, anchuras de nombres de fichero,
    # longitud del sufijo aleatorio, permisos privados POSIX y campos del nombre de una marca.
    ("parallel/codec.py", "ARRAY_PARTS"),
    ("parallel/codec.py", "PAIR_PARTS"),
    ("parallel/codec.py", "MAX_DEPTH"),
    ("parallel/markers.py", "LINUX_STARTTIME_INDEX"),
    ("parallel/markers.py", "WIN_PROCESS_QUERY_LIMITED_INFORMATION"),
    ("parallel/markers.py", "FILETIME_HIGH_SHIFT"),
    ("parallel/markers.py", "FILETIME_COUNT"),
    ("parallel/supervisor.py", "DEADLINE_REBUILDS_PER_TASK"),
    ("parallel/journal.py", "SEQUENCE_DIGITS"),
    ("parallel/journal.py", "SHA_PREFIX_CHARS"),
    ("parallel/journal.py", "TOKEN_BYTES"),
    ("parallel/journal.py", "PRIVATE_DIRECTORY_MODE"),
    ("parallel/journal.py", "PRIVATE_FILE_MODE"),
    ("parallel/markers.py", "TASK_FIELDS"),
}


def _python_files() -> Iterator[Path]:
    yield from sorted(PACKAGE_ROOT.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE_ROOT).as_posix()


def _top_package(module: str) -> str | None:
    parts = module.split(".")
    if parts[0] != "portfolio_engine" or len(parts) < 2:
        return None
    return parts[1]


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_layered_dependencies() -> None:
    violations = []
    for path in _python_files():
        own = _top_package(_module_name(path)) or "portfolio_engine"
        own = own.removesuffix(".py")
        for imported in _imports(path):
            target = _top_package(imported)
            if target is None or target == own or own == "portfolio_engine":
                continue
            if target not in ALLOWED_DEPENDENCIES.get(own, set()):
                violations.append(f"{_relative(path)} → {imported}")
    assert not violations, violations


def test_import_graph_is_acyclic() -> None:
    graph: dict[str, set[str]] = {}
    for path in _python_files():
        module = _module_name(path)
        graph[module] = {
            imported for imported in _imports(path) if imported.startswith("portfolio_engine.")
        }
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        if node in done:
            return
        assert node not in visiting, f"Ciclo de imports: {' → '.join([*trail, node])}"
        visiting.add(node)
        for child in graph.get(node, ()):
            if child in graph:
                visit(child, [*trail, node])
        visiting.discard(node)
        done.add(node)

    for module in sorted(graph):
        visit(module, [])


def test_no_later_block_packages_exist() -> None:
    """Ningún módulo de los Bloques 5-6 existe (no se ha implementado más allá del Bloque 4)."""
    present = [name for name in LATER_BLOCK_PACKAGES if (PACKAGE_ROOT / name).exists()]
    assert not present, f"Módulos de bloques posteriores presentes: {present}"


def test_block_4_modules_exist() -> None:
    """Los módulos del Bloque 4 existen (ScenarioEngine, Clarabel, MIP, formulaciones)."""
    missing = [name for name in BLOCK_4_MODULES if not (PACKAGE_ROOT / name).exists()]
    assert not missing, f"Módulos del Bloque 4 ausentes: {missing}"


def test_clarabel_and_scip_are_confined_to_their_backends() -> None:
    """SOL-005, MIP-007: Clarabel y PySCIPOpt solo se importan en su propio backend."""
    allowed = {
        "clarabel": "optimizers/clarabel_backend.py",
        "pyscipopt": "optimizers/scip_backend.py",
    }
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        for imported in _imports(path)
        if imported.split(".")[0] in allowed and _relative(path) != allowed[imported.split(".")[0]]
    ]
    assert not offenders, offenders


def test_exact_mip_never_reaches_the_production_inner_loop() -> None:
    """MIP-005: el bucle interno de producción (candidatos, sesión de frontera, motor continuo y
    frontera global) no importa el solver mixto, su formulación ni la validación EXACT_MIP."""
    inner_loop = (
        "candidates/",
        "frontiers/session.py",
        "frontiers/continuous_frontier.py",
        "frontiers/global_frontier.py",
        "frontiers/numerical_recovery.py",
        "frontiers/candidate_evaluator.py",
    )
    forbidden = (
        "portfolio_engine.optimizers.scip_backend",
        "portfolio_engine.optimizers.mixed_integer_backend",
        "portfolio_engine.optimizers.formulations.miqp",
        "portfolio_engine.frontiers.exact_mip_validation",
        "pyscipopt",
    )
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        if _relative(path).startswith(inner_loop)
        for imported in _imports(path)
        if imported.startswith(forbidden)
    ]
    assert not offenders, offenders


def test_scenario_and_advanced_validation_do_not_bypass_the_validator() -> None:
    """Las estrategias y el modo multiescenario validan siempre con el validador independiente:
    ``StrategyOptimizer.assemble`` es el único constructor de ``StrategyResult`` con pesos y usa
    ``AdvancedSolutionValidator``; ``scenarios`` no importa ningún backend (usa el optimizador)."""
    forbidden = (
        "portfolio_engine.optimizers.clarabel_backend",
        "portfolio_engine.optimizers.osqp_backend",
        "portfolio_engine.optimizers.highs_backend",
        "portfolio_engine.optimizers.scip_backend",
        "clarabel",
        "osqp",
    )
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        if _relative(path).startswith("scenarios/")
        for imported in _imports(path)
        if imported.startswith(forbidden)
    ]
    assert not offenders, offenders
    optimizer = (PACKAGE_ROOT / "frontiers/strategy_optimizer.py").read_text(encoding="utf-8")
    assert "AdvancedSolutionValidator" in optimizer and "self._validator.validate(" in optimizer


def test_no_forbidden_imports() -> None:
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        for imported in _imports(path)
        if imported.split(".")[0] in FORBIDDEN_IMPORTS
    ]
    assert not offenders, offenders


def test_process_libraries_are_confined_to_the_parallel_package() -> None:
    """PAR-001/013: ``multiprocessing``/``concurrent`` solo se importan desde ``parallel/``."""
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        if _relative(path).split("/")[0] != "parallel"
        for imported in _imports(path)
        if imported.split(".")[0] in PROCESS_IMPORTS
    ]
    assert not offenders, offenders


def test_lower_layers_only_import_parallel_determinism() -> None:
    """Los paquetes que usa la orquestación solo importan ``parallel.determinism`` (sin ciclos)."""
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        if _relative(path).split("/")[0] != "parallel"
        for imported in _imports(path)
        if imported.startswith("portfolio_engine.parallel")
        and imported != "portfolio_engine.parallel.determinism"
    ]
    assert not offenders, offenders


def test_parallel_package_never_uses_implicit_cpu_count_or_external_systems() -> None:
    """PAR-012, D-10: ni ``cpu_count`` implícito ni acceso a bases de datos/red en ``parallel/``."""
    forbidden_calls = ("os.cpu_count", "multiprocessing.cpu_count", "os.sched_getaffinity")
    forbidden_modules = ("pyodbc", "sqlalchemy", "duckdb", "requests", "urllib", "http", "socket")
    offenders = []
    for path in _python_files():
        if _relative(path).split("/")[0] != "parallel":
            continue
        offenders.extend(
            f"{_relative(path)}: import {imported}"
            for imported in _imports(path)
            if imported.split(".")[0] in forbidden_modules
        )
        offenders.extend(
            f"{_relative(path)}:{call.lineno} {ast.unparse(call.func)}"
            for call in _calls(path)
            if ast.unparse(call.func) in forbidden_calls
        )
    assert not offenders, offenders


#: Módulos que pueden usar ``pickle.load(s)``: leen únicamente bytes que el propio proceso
#: coordinador creó (caché en memoria) o un fichero propio verificado por SHA-256 antes de
#: deserializar (arranque de los workers).
PICKLE_LOAD_ALLOWED = {"cache/result_cache.py", "parallel/shared_data.py"}


def test_pickle_is_never_loaded_from_external_sources() -> None:
    """C-25 / P-05: ningún ``pickle.load(s)`` de ficheros externos; el diario es JSON.

    ``pickle`` solo se deserializa en los módulos de ``PICKLE_LOAD_ALLOWED`` (bytes propios o
    ficheros propios con hash verificado). Ningún otro módulo —en particular el diario, el códec,
    el supervisor, el ejecutor y la CLI— puede importar ``pickle``, ``marshal`` ni ``shelve``.
    """
    offenders = []
    for path in _python_files():
        relative = _relative(path)
        if relative in PICKLE_LOAD_ALLOWED:
            continue
        offenders.extend(
            f"{relative}: import {imported}"
            for imported in _imports(path)
            if imported.split(".")[0] in {"pickle", "marshal", "shelve", "dill", "cloudpickle"}
        )
        offenders.extend(
            f"{relative}:{call.lineno} {ast.unparse(call.func)}"
            for call in _calls(path)
            if ast.unparse(call.func).split(".")[-1] in {"loads", "load"}
            and ast.unparse(call.func).split(".")[0] in {"pickle", "marshal", "shelve"}
        )
    assert not offenders, offenders


def test_the_journal_decodes_only_through_the_allow_listed_codec() -> None:
    """El diario no usa ``eval``/``exec``/``compile`` ni ``importlib`` fuera del códec."""
    for module in ("parallel/journal.py", "parallel/codec.py", "parallel/cli.py"):
        names = {ast.unparse(call.func) for call in _calls(PACKAGE_ROOT / module)}
        assert not names & {"eval", "exec", "compile", "__import__"}, module
    importers = [
        _relative(path)
        for path in _python_files()
        if _relative(path).startswith("parallel/")
        and any(imported == "importlib" for imported in _imports(path))
    ]
    assert "parallel/journal.py" not in importers and "parallel/cli.py" not in importers


def test_no_module_level_mutable_state() -> None:
    mutable_calls = {"list", "dict", "set", "defaultdict", "OrderedDict", "Counter", "deque"}
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if value is None:
                continue
            is_literal = isinstance(
                value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp)
            )
            is_call = (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in mutable_calls
            )
            if is_literal or is_call:
                offenders.append(f"{_relative(path)}:{node.lineno}")
    assert not offenders, offenders


def test_no_business_numeric_literals() -> None:
    """CFG-015: los números de negocio proceden de configuración, no del código."""
    offenders = []
    for path in _python_files():
        relative = _relative(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed_nodes: set[int] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if (
                    isinstance(target, ast.Name)
                    and (relative, target.id) in ALLOWED_NAMED_CONSTANTS
                ):
                    allowed_nodes.update(id(child) for child in ast.walk(node.value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, (int, float))
                and not isinstance(node.value, bool)
                and node.value not in NEUTRAL_LITERALS
                and id(node) not in allowed_nodes
            ):
                offenders.append(f"{relative}:{node.lineno} → {node.value!r}")
    assert not offenders, offenders


def test_no_disguised_stubs() -> None:
    """Sin ``NotImplementedError``, ``TODO`` ni cuerpos vacíos fuera de Protocol/abstractos."""
    offenders = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        if "NotImplementedError" in source or "TODO" in source or "FIXME" in source:
            offenders.append(_relative(path))
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                is_protocol = any(
                    isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases
                )
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and _is_empty(item):
                        abstract = any(
                            isinstance(d, ast.Name) and d.id == "abstractmethod"
                            for d in item.decorator_list
                        )
                        if not (is_protocol or abstract):
                            offenders.append(f"{_relative(path)}:{item.lineno}")
    assert not offenders, offenders


def _is_empty(function: ast.FunctionDef) -> bool:
    body = [
        statement
        for statement in function.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]
    return not body or all(isinstance(statement, ast.Pass) for statement in body)


def test_public_api_is_documented_and_typed() -> None:
    missing = []
    for module_info in pkgutil.walk_packages(portfolio_engine.__path__, "portfolio_engine."):
        module = importlib.import_module(module_info.name)
        if not module.__doc__:
            missing.append(f"{module.__name__} (módulo)")
        for name, member in vars(module).items():
            if name.startswith("_") or getattr(member, "__module__", None) != module.__name__:
                continue
            if inspect.isclass(member) or inspect.isfunction(member):
                if not inspect.getdoc(member):
                    missing.append(f"{module.__name__}.{name}")
                if inspect.isfunction(member) and "return" not in member.__annotations__:
                    missing.append(f"{module.__name__}.{name} (sin anotación de retorno)")
    assert not missing, missing


def test_osqp_confined_to_its_backend() -> None:
    """SOL-010: OSQP solo en ``optimizers/osqp_backend.py`` (API nativa, sin capas adicionales)."""
    offenders = [
        _relative(path)
        for path in _python_files()
        if any(imported.split(".")[0] == "osqp" for imported in _imports(path))
        and _relative(path) != "optimizers/osqp_backend.py"
    ]
    assert not offenders, offenders


def test_no_cvxpy_in_fast_path() -> None:
    """SOL-010: sin canonicalización CVXPY en el camino de producción."""
    hot_path = ("optimizers", "frontiers", "validation", "constraints", "metrics", "costs")
    offenders = [
        _relative(path)
        for path in _python_files()
        if _relative(path).split("/")[0] in hot_path
        and any(imported.split(".")[0] == "cvxpy" for imported in _imports(path))
    ]
    assert not offenders, offenders


def test_validator_is_independent_of_solvers() -> None:
    """VAL-001: el validador no importa backends, formulaciones ni frontiers (§44)."""
    forbidden = ("portfolio_engine.optimizers", "portfolio_engine.frontiers", "osqp")
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        if _relative(path).startswith("validation/")
        for imported in _imports(path)
        if imported.startswith(forbidden)
    ]
    assert not offenders, offenders


def test_policy_not_referenced_in_backends_or_frontiers() -> None:
    """CON-022: la política solo se traduce en constraints/ y se verifica en validation/."""
    packages = ("optimizers/", "frontiers/", "costs/", "metrics/")
    offenders = [
        _relative(path)
        for path in _python_files()
        if _relative(path).startswith(packages)
        and "RestrictedExistingPositionPolicy" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_scipy_optimize_confined_to_the_lp_backend() -> None:
    """R2-01: ``scipy.optimize`` (HiGHS) solo en ``optimizers/highs_backend.py``; el resto del
    paquete no resuelve problemas por su cuenta."""
    offenders = [
        _relative(path)
        for path in _python_files()
        if any(imported.startswith("scipy.optimize") for imported in _imports(path))
        and _relative(path) != "optimizers/highs_backend.py"
    ]
    assert not offenders, offenders


def test_max_return_tolerance_has_a_single_source() -> None:
    """La holgura de la etapa 2 de MaximumReturn solo se define en ``SolverConfig`` y solo la
    consume la sesión de frontera (sin copias hardcodeadas ni parámetros paralelos)."""
    users = sorted(
        _relative(path)
        for path in _python_files()
        if "max_return_tie" in path.read_text(encoding="utf-8")
    )
    assert users == [
        "config/solver_config.py",
        "frontiers/session.py",
    ], users


def _calls(path: Path) -> Iterator[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    yield from (node for node in ast.walk(tree) if isinstance(node, ast.Call))


def test_candidate_pipeline_never_uses_python_hash_or_global_random_state() -> None:
    """REP-003, CAN-015: sin ``hash()`` nativo ni estado aleatorio global en candidatos ni
    fronteras; la única aleatoriedad es ``np.random.default_rng`` con semilla derivada."""
    offenders = []
    for path in _python_files():
        if _relative(path).split("/")[0] not in ("candidates", "frontiers", "parallel"):
            continue
        source = path.read_text(encoding="utf-8")
        if "import random" in source or "from random" in source:
            offenders.append(f"{_relative(path)}: módulo random")
        for call in _calls(path):
            target = ast.unparse(call.func)
            if target == "hash":
                offenders.append(f"{_relative(path)}:{call.lineno} hash()")
            if target.startswith("np.random.") and target != "np.random.default_rng":
                offenders.append(f"{_relative(path)}:{call.lineno} {target}")
    assert not offenders, offenders


def test_candidate_engine_is_independent_of_solvers_and_frontiers() -> None:
    """La generación de composiciones solo usa un evaluador inyectado: ni ``optimizers`` ni
    ``frontiers`` ni SciPy/OSQP se importan desde ``candidates``."""
    forbidden = ("portfolio_engine.optimizers", "portfolio_engine.frontiers", "osqp", "scipy")
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        if _relative(path).startswith("candidates/")
        for imported in _imports(path)
        if imported.startswith(forbidden)
    ]
    assert not offenders, offenders
