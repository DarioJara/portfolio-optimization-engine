"""Los 316 ``RequirementID`` oficiales se conservan al añadir requisitos propuestos.

``TRACEABILITY.md`` es el contrato de gobierno (CLAUDE.md): el total oficial es de 316
requisitos con los estados del resumen (criterio de aceptación 13). Los requisitos propuestos
``HC-*`` (restricciones obligatorias de carteras finales) viven en una sección aparte,
**fuera** de ese total, hasta su aprobación. Esta prueba
lee la matriz tal cual (sin importar nada del motor) y falla si algún cambio altera el recuento
oficial, si un identificador se duplica o si un estado no es uno de los cuatro permitidos.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

TRACEABILITY = Path(__file__).resolve().parents[2] / "TRACEABILITY.md"
ROW = re.compile(r"^\| ([A-Z]{2,4}-\d{3}) \|(.*)$", flags=re.MULTILINE)
STATE = re.compile(r"^(NOT_IMPLEMENTED|PARTIAL|IMPLEMENTED|VALIDATED)\b")
PROPOSED_HEADING = "## HC — "
TOTAL_ROW = re.compile(
    r"^\| \*\*Total\*\* \| \| \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| \*\*(\d+)\*\* \| "
    r"\*\*(\d+)\*\* \| \*\*(\d+)\*\* \|$",
    flags=re.MULTILINE,
)


def _split() -> tuple[str, str]:
    text = TRACEABILITY.read_text(encoding="utf-8")
    head, marker, tail = text.partition(PROPOSED_HEADING)
    return head, marker + tail


def _states(section: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for _, rest in ROW.findall(section):
        cells = [cell.strip() for cell in rest.split("|") if cell.strip()]
        match = STATE.match(cells[-1])
        assert match, f"estado no permitido: {cells[-1][:40]!r}"
        counts[match.group(1)] += 1
    return counts


def test_the_official_contract_keeps_316_unique_requirements_with_the_summary_totals() -> None:
    official, _ = _split()
    ids = [rid for rid, _ in ROW.findall(official)]
    assert len(ids) == len(set(ids)) == 316
    total = TOTAL_ROW.search(official)
    assert total is not None
    count, not_implemented, partial, implemented, validated = (int(g) for g in total.groups())
    assert count == 316
    states = _states(official)
    assert (states["NOT_IMPLEMENTED"], states["PARTIAL"]) == (not_implemented, partial)
    assert (states["IMPLEMENTED"], states["VALIDATED"]) == (implemented, validated)
    assert sum(states.values()) == 316


def test_proposed_hard_constraint_requirements_are_outside_the_official_count() -> None:
    official, proposed = _split()
    assert proposed, "falta la sección de requisitos propuestos HC-*"
    official_ids = {rid for rid, _ in ROW.findall(official)}
    proposed_ids = [rid for rid, _ in ROW.findall(proposed)]
    assert proposed_ids and all(rid.startswith("HC-") for rid in proposed_ids)
    assert len(proposed_ids) == len(set(proposed_ids))
    assert not official_ids & set(proposed_ids)
    assert not any(rid.startswith("HC-") for rid in official_ids)
    assert set(_states(proposed)) <= {"PARTIAL", "VALIDATED", "NOT_IMPLEMENTED", "IMPLEMENTED"}
