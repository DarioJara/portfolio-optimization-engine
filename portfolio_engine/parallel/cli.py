"""CLI JSON local para inspeccionar diarios de ejecución (Bloque 5.4; P-07).

Un único subcomando, ``journal-info <directorio>``, que escribe **un objeto JSON estable** (claves
ordenadas) con el manifiesto y el estado de integridad del diario y no lo modifica::

    python -m portfolio_engine.parallel.cli journal-info <directorio>

Códigos de salida: ``0`` diario legible; ``2`` diario ilegible o inexistente (el JSON de error es
``{"error": "..."}``). Es local: no abre conexiones ni lee datos de mercado. Ejecutar una
optimización desde la línea de comandos exige un cargador de datos y de solicitudes, que pertenece
al Bloque 6 (``MarketDataProvider``/``PortfolioRequestSource`` reales); aquí solo existen sus
contratos (``parallel.protocols``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from portfolio_engine.parallel.journal import JournalError, inspect_journal

EXIT_OK = 0
EXIT_UNREADABLE = 2


def build_parser() -> argparse.ArgumentParser:
    """Parser de argumentos de la CLI."""
    parser = argparse.ArgumentParser(prog="portfolio_engine.parallel.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    info = commands.add_parser("journal-info", help="resumen verificable de un diario local")
    info.add_argument("directory", help="directorio del diario")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada; devuelve el código de salida."""
    args = build_parser().parse_args(argv)
    try:
        document = inspect_journal(args.directory)
    except JournalError as error:
        sys.stdout.write(json.dumps({"error": str(error)}, sort_keys=True) + "\n")
        return EXIT_UNREADABLE
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
