"""GOV-006, GOV-008, CFG-015, SOL-010 y controles de alcance (análisis estático del paquete).

El Bloque 2 amplía las reglas del Bloque 1: nuevos paquetes en el grafo de capas, OSQP confinado
en su backend y ausencia de módulos de los Bloques 3-6.
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
    "costs": {"exceptions", "utils", "models", "config"},
    "metrics": {"exceptions", "utils", "models", "config", "costs"},
    "constraints": {"exceptions", "utils", "models", "config", "costs"},
    "optimizers": {"exceptions", "utils", "models", "config", "constraints", "costs"},
    "validation": {"exceptions", "utils", "models", "config", "costs", "constraints", "metrics"},
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
    },
    "outputs": {"exceptions", "utils", "models", "config", "costs", "metrics"},
    "benchmark": {"exceptions", "utils", "models", "config", "frontiers", "optimizers"},
}

#: Paquetes/módulos de bloques posteriores (3-6) que no deben existir en el Bloque 2.
LATER_BLOCK_PACKAGES = (
    "candidates",
    "scenarios",
    "parallel",
    "staging",
    "persistence",
    "cache",
    "engine.py",
    "frontiers/global_frontier.py",
    "constraints/conic.py",
    "constraints/integer.py",
    "metrics/cvar_metric.py",
    "optimizers/clarabel_backend.py",
    "optimizers/mixed_integer_backend.py",
    "optimizers/nonconvex_backend.py",
    "optimizers/formulations/sharpe.py",
    "optimizers/formulations/volatility.py",
    "optimizers/formulations/cvar.py",
    "optimizers/formulations/robust.py",
    "optimizers/formulations/multi_scenario.py",
    "optimizers/formulations/miqp.py",
)

#: ``osqp`` solo puede importarse en su backend (test aparte); el resto sigue prohibido.
FORBIDDEN_IMPORTS = (
    "clarabel",
    "cvxpy",
    "pyscipopt",
    "gurobipy",
    "multiprocessing",
    "concurrent",
    "pyodbc",
    "duckdb",
    "sklearn",
)

#: Literales numéricos neutros (estructurales: índices, mitades, dobles, unidad presupuestaria).
NEUTRAL_LITERALS = {0, 1, 2, -1, 0.5}
#: Constantes con nombre permitidas: conversiones de unidades y constantes matemáticas.
ALLOWED_NAMED_CONSTANTS = {
    ("models/costs.py", "BPS_PER_UNIT"),
    ("data/validation/market_data_validator.py", "MAD_TO_STD_NORMAL"),
    ("data/validation/report.py", "SUMMARY_ISSUES"),
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
    """Ningún módulo de los Bloques 3-6 existe (no se ha implementado más allá del Bloque 2)."""
    present = [name for name in LATER_BLOCK_PACKAGES if (PACKAGE_ROOT / name).exists()]
    assert not present, f"Módulos de bloques posteriores presentes: {present}"


def test_no_forbidden_imports() -> None:
    offenders = [
        f"{_relative(path)}: {imported}"
        for path in _python_files()
        for imported in _imports(path)
        if imported.split(".")[0] in FORBIDDEN_IMPORTS
    ]
    assert not offenders, offenders


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
