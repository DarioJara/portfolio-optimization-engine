"""GOV-001, GOV-004, GOV-005: versión de Python, excepciones y logging estructurado."""

from __future__ import annotations

import io
import json
import logging
import sys
import tomllib

import pytest

from portfolio_engine import exceptions
from portfolio_engine.config import load_engine_config
from portfolio_engine.utils.logging import configure_json_logging, get_logger, log_event
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.unit


def test_python_version_matches_project_requirement() -> None:
    assert sys.version_info >= (3, 11)
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["requires-python"] == ">=3.11"
    assert "hypothesis" not in " ".join(project["dependencies"])  # solo desarrollo
    assert any(dep.startswith("hypothesis") for dep in project["optional-dependencies"]["dev"])


def test_exception_hierarchy() -> None:
    engine_errors = [
        exceptions.ConfigError,
        exceptions.DataValidationError,
        exceptions.AssetResolutionError,
        exceptions.InsufficientDataError,
        exceptions.TransactionCostInputError,
        exceptions.CovarianceEstimationError,
        exceptions.NotPositiveSemidefiniteError,
    ]
    for error in engine_errors:
        assert issubclass(error, exceptions.PortfolioEngineError)
    assert issubclass(exceptions.NotPositiveSemidefiniteError, exceptions.CovarianceEstimationError)
    issue = object()
    raised = exceptions.DataValidationError("mensaje", [issue])
    assert raised.issues == (issue,)


def test_errors_raised_by_engine_are_engine_errors() -> None:
    with pytest.raises(exceptions.PortfolioEngineError):
        load_engine_config({"engine": {}})


def test_structured_json_logging() -> None:
    stream = io.StringIO()
    handler = configure_json_logging(stream, logging.INFO)
    try:
        log_event(get_logger("test"), logging.WARNING, "covariance_repaired", portfolio_id="P1")
    finally:
        logging.getLogger("portfolio_engine").removeHandler(handler)
    record = json.loads(stream.getvalue().strip())
    assert record["event"] == "covariance_repaired"
    assert record["level"] == "WARNING"
    assert record["logger"] == "portfolio_engine.test"
    assert record["context"] == {"portfolio_id": "P1"}
    assert "timestamp" in record


def test_library_does_not_configure_handlers_on_import() -> None:
    assert logging.getLogger("portfolio_engine").handlers == []
