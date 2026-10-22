"""Restricciones obligatorias de las carteras finales (cardinalidad, cambios, volatilidad, pesos).

Módulos (importar desde cada submódulo; el paquete no reexporta para evitar ciclos con ``config``):

* :mod:`~portfolio_engine.hard_constraints.resolver`: precedencia global < perfil < cartera,
  mandato efectivo y ``effective_hash``;
* :mod:`~portfolio_engine.hard_constraints.preflight`: factibilidad previa determinista;
* :mod:`~portfolio_engine.hard_constraints.validator`: validación final desde los pesos;
* :mod:`~portfolio_engine.hard_constraints.counts`: recuento de altas, bajas y sustituciones.

Diseño y límites matemáticos: ``HARD_CONSTRAINTS_DESIGN.md``.
"""
