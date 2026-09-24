"""Turnover convencional (MASTER_SPEC §24): ``Turnover = 0.5 · Σ|w_new − w_current|``.

Se calcula sobre la unión current ∪ nueva composición, de modo que las posiciones liquidadas por
completo cuentan. Con presupuesto 1 el resultado está en ``[0, 1]``. Sin cartera actual el turnover
no está disponible y no debe inventarse (no es 0,5 ni 1).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt


def turnover(new_weights: npt.ArrayLike, current_weights: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Turnover de cada fila de ``new_weights`` (``K×M`` o ``M``) respecto a ``current_weights``.

    Ambos argumentos deben estar alineados sobre la misma unión de activos.
    """
    new = np.asarray(new_weights, dtype=np.float64)
    current = np.asarray(current_weights, dtype=np.float64)
    return np.asarray(0.5 * np.abs(new - current).sum(axis=-1), dtype=np.float64)
