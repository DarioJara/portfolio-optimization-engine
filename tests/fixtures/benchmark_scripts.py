"""Acceso de las pruebas a los módulos auxiliares de ``benchmarks/scripts`` (B5.5).

``benchmarks/scripts`` no es un paquete instalable: sus módulos se importan por nombre añadiendo su
carpeta a ``sys.path``, igual que hacen los propios scripts.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "scripts"


def load_script(name: str) -> ModuleType:
    """Importa ``benchmarks/scripts/<name>.py`` como módulo."""
    directory = str(SCRIPTS_DIR)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return importlib.import_module(name)
