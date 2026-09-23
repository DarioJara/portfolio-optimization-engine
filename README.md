# portfolio-engine

Motor profesional de optimización cuantitativa de carteras multi-escenario.

- Contrato técnico, matemático y funcional: [`MASTER_SPEC.md`](MASTER_SPEC.md).
- Diseño: [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Estado de cada requisito: [`TRACEABILITY.md`](TRACEABILITY.md).
- Plan por bloques: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
- Historial: [`CHANGELOG.md`](CHANGELOG.md).

Estado actual: **Bloque 1 (Foundation)** — configuración, datos, validación, retornos, expected returns, covarianza (Empirical, Ledoit-Wolf), diagnóstico y reparación PSD, modelo de costes de transacción y estado actual de cartera. Todavía **no** hay optimización (Bloque 2 en adelante).

## Requisitos

- Python ≥ 3.11.
- Dependencias de runtime: `numpy`, `scipy`, `pandas`, `pyarrow` (ver `pyproject.toml`).
- Dependencias de desarrollo (grupo `dev`): `pytest`, `hypothesis`, `mypy`, `ruff`, `scikit-learn` (solo como referencia en tests).

## Instalación (entorno local, nunca global)

```bash
python -m venv .venv
```

Windows (Git Bash / PowerShell):

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

Linux / macOS:

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

Versiones exactas con las que se validó el último bloque: `requirements-lock.txt`
(`.venv/Scripts/python -m pip install -r requirements-lock.txt` para reproducirlas).

## Ejecutar tests y controles de calidad

```bash
.venv/Scripts/python -m pytest
```

```bash
.venv/Scripts/python -m mypy
```

```bash
.venv/Scripts/python -m ruff check portfolio_engine tests
```

## Configuración

Toda decisión financiera, matemática u operativa procede de configuración (MASTER_SPEC §4).
El fichero de ejemplo es [`config/default_engine.toml`](config/default_engine.toml) y se carga con:

```python
from portfolio_engine.config import load_engine_config

config = load_engine_config("config/default_engine.toml")
```

Los dataclasses de configuración no tienen valores por defecto para parámetros de negocio:
cada valor debe declararse explícitamente en la configuración.
