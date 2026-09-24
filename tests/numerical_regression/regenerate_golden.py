"""Regenera ``golden/frontiers.json``. Ejecutar solo tras un cambio numérico deliberado y revisado.

Uso: ``.venv/Scripts/python -m tests.numerical_regression.regenerate_golden``
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.numerical_regression.snapshot import snapshot

GOLDEN = Path(__file__).parent / "golden" / "frontiers.json"

if __name__ == "__main__":
    GOLDEN.write_text(json.dumps(snapshot(), indent=1), encoding="utf-8")
    print(f"Escrito {GOLDEN}")
