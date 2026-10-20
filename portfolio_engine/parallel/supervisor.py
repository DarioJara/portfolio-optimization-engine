"""Supervisor de lotes: recuperación de caídas, reintentos, plazos y cancelación (Bloque 5.4).

``ProcessPoolExecutor`` rompe **todo** el pool cuando muere un worker, no dice qué tarea lo mató y
no permite terminar una tarea concreta. El supervisor añade, sin tocar ningún motor matemático:

**Caídas (P-03, P-06).** Al romperse el pool se recogen los lotes que sí terminaron; de los demás,
solo la tarea que cada worker declaraba estar ejecutando (``parallel.markers``) es *sospechosa*; el
resto de carteras de esos lotes se reenvía intacto (son idempotentes: mismas entradas, mismos
resultados). Las sospechosas se ejecutan **una a una** en el pool reconstruido: si una tarea sola
mata su proceso ``max_task_attempts`` veces queda ``WORKER_CRASHED`` (venenosa confirmada); si
termina, su resultado es el de una ejecución sin fallos. Una cartera sana nunca queda
``WORKER_CRASHED`` por compartir lote o pool con otra. Si no hay marca (el proceso murió antes de
empezar una tarea, p. ej. en su *initializer*), nadie es sospechoso y solo avanza el contador de
reconstrucciones sin progreso.

**Cotas (sin bucles infinitos).** ``max_rebuilds_without_progress`` limita (a) las caídas
consecutivas que no se pueden atribuir a ninguna tarea (el proceso murió antes de empezar una:
*initializer* roto) y (b) las tareas venenosas confirmadas consecutivas sin que ninguna otra
produzca un resultado en medio (todas matan su proceso: el entorno es sospechoso). Las caídas
atribuidas a una sospechosa no cuentan en (a): están acotadas por ``max_task_attempts`` y por
``max_total_rebuilds``, la cota absoluta por ejecución. Al agotarlas, todo lo pendiente queda
``ABORTED`` (o ``WORKER_INIT_FAILED`` si el entorno no arranca). Las tareas abortadas pueden
reintentarse en otra ejecución (p. ej. reanudando el diario).

**Detección tardía (D-DET).** El pool puede tardar en notar la muerte de un worker creado bajo
demanda. Cada sondeo, el supervisor comprueba que los PID registrados siguen vivos y trata
«registrado, sin salida limpia y sin proceso» como una caída, sin esperar al pool.

**Plazos.** ``task_timeout_seconds``: una cartera que supera el plazo desde que su worker la empieza
queda ``TIMED_OUT``. ``batch_timeout_seconds``: un lote de varias carteras que lo supera se
descompone en lotes unitarios (nadie falla por compartir lote lento); un lote unitario que lo
supera queda ``TIMED_OUT``. Como ``ProcessPoolExecutor`` no puede terminar una tarea, se termina el
**proceso** del worker (su PID consta en las marcas): eso rompe el pool, de modo que los lotes de
los demás workers se **recalculan** (daño colateral = trabajo repetido, nunca resultados perdidos
ni carteras falladas). El tiempo se mide desde que el coordinador *observa* el inicio (resolución
= ``supervision_poll_seconds``); una tarea que termina justo en el límite puede constar
``TIMED_OUT``. Los plazos del solver (``TIME_LIMIT`` de los backends) son otra capa: producen un
``SolverStatus`` dentro de una tarea ``COMPLETED`` y no los toca el supervisor.

**Cancelación.** Al pedirse (``RunControl``) no se envía más trabajo; las tareas sin concluir
quedan ``CANCELLED``; los lotes en vuelo disponen de ``cancel_grace_seconds`` para terminar (sus
resultados se conservan) y luego se termina a sus workers.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path

from portfolio_engine.config.parallel_config import RecoveryConfig
from portfolio_engine.parallel import markers
from portfolio_engine.parallel.batching import PortfolioBatch, SequencedRequest
from portfolio_engine.parallel.protocols import RunControl
from portfolio_engine.parallel.task import ExecutionStatus, PortfolioRequest, TaskError, TaskResult
from portfolio_engine.parallel.worker import ResultBatch, WorkerInitializationError, crashed_result

TASK_SCOPE = "TASK"
BATCH_SCOPE = "BATCH"


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Qué hizo el supervisor en una ejecución (diagnóstico; no forma parte del cálculo).

    Attributes:
        pool_rebuilds: pools descartados y reconstruidos.
        crashes: caídas de proceso atribuidas a un fallo (no a un plazo ni a una cancelación).
        isolated_retries: ejecuciones aisladas de tareas sospechosas.
        poisoned_tasks: tareas confirmadas como venenosas (``WORKER_CRASHED``).
        timeouts: tareas con ``TIMED_OUT``.
        batches_split: lotes de varias carteras descompuestos por plazo de lote.
        init_failures: lotes que recibieron un fallo del *initializer*.
        cancelled: la ejecución se canceló.
        aborted: el supervisor agotó sus cotas.
        recovery_seconds: tiempo total entre detectar una caída y recibir el siguiente resultado.
        events: ``(clase, detalle acotado)`` en orden cronológico.
    """

    pool_rebuilds: int = 0
    crashes: int = 0
    isolated_retries: int = 0
    poisoned_tasks: int = 0
    timeouts: int = 0
    batches_split: int = 0
    init_failures: int = 0
    cancelled: bool = False
    aborted: bool = False
    recovery_seconds: float = 0.0
    events: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SupervisorHooks:
    """Funciones que el ejecutor entrega al supervisor.

    Attributes:
        new_pool: crea un pool nuevo (con su *initializer*).
        submit: envía un lote a un pool y devuelve su futuro.
        task_id: ``TaskID`` de una solicitud.
        on_batch: recibe el :class:`ResultBatch` de un lote terminado.
        on_final: recibe resultados finales sintéticos (caída, plazo, cancelación, aborto).
        report: notifica un evento ``(clase, detalle)``.
    """

    new_pool: Callable[[], ProcessPoolExecutor]
    submit: Callable[[ProcessPoolExecutor, PortfolioBatch], Future[ResultBatch]]
    task_id: Callable[[PortfolioRequest], str]
    on_batch: Callable[[ResultBatch], None]
    on_final: Callable[[Sequence[TaskResult]], None]
    report: Callable[[str, str], None]


class _Seen:
    """Primera vez que el coordinador observó cada tarea y lote en curso (reloj propio)."""

    __slots__ = ("batch_first", "position", "task_first")

    def __init__(self, position: int, now: float) -> None:
        self.position = position
        self.task_first = now
        self.batch_first = now


class BatchSupervisor:
    """Ejecuta ``batches`` en pools sucesivos aplicando las políticas de :class:`RecoveryConfig`."""

    def __init__(
        self,
        hooks: SupervisorHooks,
        policy: RecoveryConfig,
        max_in_flight: int,
        progress_dir: Path,
        control: RunControl | None = None,
    ) -> None:
        self._hooks = hooks
        self._policy = policy
        self._max_in_flight = max_in_flight
        self._dir = progress_dir
        self._control = control
        self._pending: deque[PortfolioBatch] = deque()
        self._suspects: deque[SequencedRequest] = deque()
        self._in_flight: dict[Future[ResultBatch], PortfolioBatch] = {}
        self._isolated: set[int] = set()
        self._affected: list[tuple[PortfolioBatch, bool]] = []
        self._attempts: dict[int, int] = {}
        self._seen: dict[int, _Seen] = {}
        self._next_batch_id = 0
        self._consecutive = 0
        self._poison_streak = 0
        self._init_error: str | None = None
        self._broken = False
        self._intentional = False
        self._break_started: float | None = None
        self._events: list[tuple[str, str]] = []
        self._rebuilds = 0
        self._crashes = 0
        self._retries = 0
        self._poisoned = 0
        self._timeouts = 0
        self._splits = 0
        self._init_failures = 0
        self._recovery_seconds = 0.0
        self._cancelled = False
        self._aborted = False

    # ----------------------------------------------------------------------------- entrada

    def run(self, batches: Sequence[PortfolioBatch]) -> RecoveryReport:
        """Ejecuta todos los lotes; cada tarea acaba en un resultado final exactamente una vez."""
        self._pending = deque(batches)
        self._next_batch_id = max((batch.batch_id for batch in batches), default=-1) + 1
        pool: ProcessPoolExecutor | None = None
        try:
            while self._pending or self._suspects or self._in_flight:
                if self._cancel_requested():
                    self._cancel(pool)
                    break
                if self._aborted:
                    break
                if pool is None:
                    pool = self._hooks.new_pool()
                self._submit_ready(pool)
                if not self._broken:
                    self._poll()
                if self._broken:
                    self._recover(pool)
                    pool = None
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
        return self._report()

    # --------------------------------------------------------------------------- utilidades

    def _report(self) -> RecoveryReport:
        return RecoveryReport(
            pool_rebuilds=self._rebuilds,
            crashes=self._crashes,
            isolated_retries=self._retries,
            poisoned_tasks=self._poisoned,
            timeouts=self._timeouts,
            batches_split=self._splits,
            init_failures=self._init_failures,
            cancelled=self._cancelled,
            aborted=self._aborted,
            recovery_seconds=self._recovery_seconds,
            events=tuple(self._events),
        )

    def _event(self, kind: str, detail: str = "") -> None:
        bounded = detail[: self._policy.max_message_chars]
        self._events.append((kind, bounded))
        self._hooks.report(kind, bounded)

    def _new_batch(self, items: Sequence[SequencedRequest]) -> PortfolioBatch:
        batch = PortfolioBatch(self._next_batch_id, tuple(items))
        self._next_batch_id += 1
        return batch

    def _cancel_requested(self) -> bool:
        return self._control is not None and self._control.cancel_requested()

    def _synthetic(
        self, items: Sequence[SequencedRequest], status: ExecutionStatus, kind: str, message: str
    ) -> None:
        error = TaskError(
            error_type=kind,
            message=message[: self._policy.max_message_chars],
            operation_index=None,
            traceback="",
        )
        self._hooks.on_final(
            [
                crashed_result(
                    self._hooks.task_id(item.request),
                    item.request.portfolio_id,
                    item.request.workload.workload_hash,
                    item.sequence_id,
                    status,
                    error,
                )
                for item in items
            ]
        )

    def _progress_made(self, *, success: bool = True) -> None:
        """Avance: reinicia el contador de caídas sin explicación; ``success`` también el resto."""
        self._consecutive = 0
        if not success:
            return
        self._poison_streak = 0
        self._init_error = None
        if self._break_started is not None:
            self._recovery_seconds += time.monotonic() - self._break_started
            self._break_started = None

    # ------------------------------------------------------------------------------ envío

    def _submit_one(self, pool: ProcessPoolExecutor, batch: PortfolioBatch) -> None:
        self._in_flight[self._hooks.submit(pool, batch)] = batch

    def _submit_ready(self, pool: ProcessPoolExecutor) -> None:
        """Envía trabajo: sospechosas de una en una; si no, lotes hasta la cota en vuelo."""
        try:
            if self._suspects:
                if not self._in_flight:
                    self._submit_suspect(pool)
                return
            while self._pending and len(self._in_flight) < self._max_in_flight:
                batch = self._pending.popleft()
                try:
                    self._submit_one(pool, batch)
                except BrokenProcessPool:
                    self._pending.appendleft(batch)  # no llegó a enviarse: inocente
                    raise
        except BrokenProcessPool:
            self._broken = True
            self._event("submit_broken", "el pool estaba roto al enviar un lote")

    def _submit_suspect(self, pool: ProcessPoolExecutor) -> None:
        item = self._suspects.popleft()
        batch = self._new_batch((item,))
        try:
            self._submit_one(pool, batch)
        except BrokenProcessPool:
            self._suspects.appendleft(item)
            raise
        self._isolated.add(batch.batch_id)
        self._retries += 1

    # ----------------------------------------------------------------------------- sondeo

    def _poll(self) -> None:
        if not self._in_flight:
            return
        done, _ = wait(
            list(self._in_flight),
            timeout=self._policy.supervision_poll_seconds,
            return_when=FIRST_COMPLETED,
        )
        for future in done:
            self._collect(future)
        if self._broken:
            return
        self._check_deadlines(time.monotonic())
        if not self._broken:
            self._check_workers()

    def _collect(self, future: Future[ResultBatch]) -> None:
        """Procesa un futuro terminado; marca el pool como roto si procede."""
        batch = self._in_flight.pop(future)
        isolated = batch.batch_id in self._isolated
        self._isolated.discard(batch.batch_id)
        self._seen.pop(batch.batch_id, None)
        try:
            outcome = future.result()
        except BrokenProcessPool:
            self._affected.append((batch, isolated))
            self._broken = True
        except WorkerInitializationError as error:
            self._init_failures += 1
            self._init_error = str(error)
            self._affected.append((batch, isolated))  # inocente: el entorno no arrancó
            self._broken = True
            self._event("initializer_failed", str(error))
        except Exception as error:  # fallo del lote (p. ej. resultado no serializable)
            self._synthetic(
                batch.items,
                ExecutionStatus.FAILED_EXCEPTION,
                type(error).__name__,
                f"El lote {batch.batch_id} no devolvió resultado: {error}",
            )
            self._progress_made()
        else:
            self._hooks.on_batch(outcome)
            self._progress_made()

    # ------------------------------------------------------------------------------ plazos

    def _check_deadlines(self, now: float) -> None:
        task_limit = self._policy.task_timeout_seconds
        batch_limit = self._policy.batch_timeout_seconds
        if task_limit is None and batch_limit is None:
            return
        snapshot = markers.scan(self._dir)
        for future, batch in list(self._in_flight.items()):
            marker = snapshot.tasks.get(batch.batch_id)
            if marker is None or future.done():
                continue
            seen = self._seen.get(batch.batch_id)
            if seen is None:
                self._seen[batch.batch_id] = _Seen(marker.position, now)
                continue
            if seen.position != marker.position:
                seen.position = marker.position
                seen.task_first = now
            if task_limit is not None and now - seen.task_first > task_limit:
                self._deadline_kill(future, batch, marker, TASK_SCOPE, now - seen.task_first)
                return
            if batch_limit is not None and now - seen.batch_first > batch_limit:
                self._deadline_kill(future, batch, marker, BATCH_SCOPE, now - seen.batch_first)
                return

    def _deadline_kill(
        self,
        future: Future[ResultBatch],
        batch: PortfolioBatch,
        marker: markers.TaskMarker,
        scope: str,
        elapsed: float,
    ) -> None:
        """Aplica un plazo vencido: finaliza o descompone y pide terminar los workers."""
        del self._in_flight[future]
        self._isolated.discard(batch.batch_id)
        self._seen.pop(batch.batch_id, None)
        offender = batch.items[marker.position]
        if scope == TASK_SCOPE or len(batch.items) == 1:
            limit = (
                self._policy.task_timeout_seconds
                if scope == TASK_SCOPE
                else self._policy.batch_timeout_seconds
            )
            self._timeouts += 1
            self._synthetic(
                (offender,),
                ExecutionStatus.TIMED_OUT,
                "TaskTimeout" if scope == TASK_SCOPE else "BatchTimeout",
                f"Plazo de {scope} superado: {elapsed:.1f} s observados (límite {limit} s).",
            )
            self._event("timeout", f"{scope} seq={offender.sequence_id} tras {elapsed:.1f}s")
            others = [item for item in batch.items if item is not offender]
            if others:
                self._pending.appendleft(self._new_batch(others))
            self._progress_made(success=False)
        else:
            self._splits += 1
            self._event("batch_split", f"lote de {len(batch.items)} carteras tras {elapsed:.1f}s")
            for item in reversed(batch.items):
                self._pending.appendleft(self._new_batch((item,)))
        self._intentional = True
        self._broken = True

    # ------------------------------------------------------------------------- vigilancia

    def _check_workers(self) -> None:
        """D-DET: un worker registrado, sin salida limpia y sin proceso es una caída."""
        for pid in markers.scan(self._dir).workers:
            if markers.process_is_gone(pid):
                self._event("worker_vanished", f"pid {pid} desapareció sin salir limpiamente")
                self._broken = True
                return

    # ---------------------------------------------------------------------- recuperación

    def _terminate_pool(self, pool: ProcessPoolExecutor, snapshot: markers.MarkerSnapshot) -> None:
        """Termina los workers registrados y cierra el pool (todos sus futuros quedan resueltos)."""
        for pid in set(snapshot.workers) | {marker.pid for marker in snapshot.tasks.values()}:
            markers.terminate_process(pid)
        pool.shutdown(wait=True, cancel_futures=True)

    def _recover(self, pool: ProcessPoolExecutor) -> None:
        """Recoge lo terminado, reparte los lotes afectados, descarta el pool y aplica cotas."""
        detected = time.monotonic()
        intentional = self._intentional
        snapshot = markers.scan(self._dir)
        for future in [f for f in self._in_flight if f.done()]:
            self._collect(future)
        self._terminate_pool(pool, snapshot)
        for future in list(self._in_flight):
            batch = self._in_flight.pop(future)
            self._affected.append((batch, batch.batch_id in self._isolated))
            self._isolated.discard(batch.batch_id)
        affected, self._affected = self._affected, []
        blamed = self._distribute(affected, snapshot, intentional)
        markers.clear(self._dir)
        self._seen.clear()
        self._broken = False
        self._intentional = False
        self._rebuilds += 1
        if not intentional:
            self._crashes += 1
            if self._break_started is None:
                self._break_started = detected
            if not blamed:
                self._consecutive += 1  # caída que no se pudo atribuir a ninguna tarea
            self._event(
                "pool_rebuilt",
                f"reconstrucción {self._rebuilds}; sin atribuir consecutivas={self._consecutive}",
            )
        self._apply_limits()

    def _distribute(
        self,
        affected: Sequence[tuple[PortfolioBatch, bool]],
        snapshot: markers.MarkerSnapshot,
        intentional: bool,
    ) -> bool:
        """Reparte los lotes afectados; devuelve ``True`` si alguna tarea fue señalada."""
        blamed = False
        requeue: list[PortfolioBatch] = []
        for batch, isolated in sorted(affected, key=lambda entry: entry[0].batch_id):
            marker = snapshot.tasks.get(batch.batch_id)
            if intentional or marker is None or marker.position >= len(batch.items):
                # Inocente: nunca empezó, o fue el supervisor quien terminó su worker.
                if isolated:
                    self._suspects.appendleft(batch.items[0])
                else:
                    requeue.append(batch)
                continue
            suspect = batch.items[marker.position]
            others = [item for item in batch.items if item is not suspect]
            if others:
                requeue.append(self._new_batch(others))
            self._blame(suspect, isolated=isolated)
            blamed = True
        for batch in reversed(requeue):
            self._pending.appendleft(batch)
        return blamed

    def _blame(self, suspect: SequencedRequest, *, isolated: bool) -> None:
        """Registra una sospechosa; tras ``max_task_attempts`` intentos aislados es venenosa."""
        if isolated:
            attempts = self._attempts.get(suspect.sequence_id, 0) + 1
            self._attempts[suspect.sequence_id] = attempts
            if attempts >= self._policy.max_task_attempts:
                self._poisoned += 1
                self._poison_streak += 1
                self._synthetic(
                    (suspect,),
                    ExecutionStatus.WORKER_CRASHED,
                    "WorkerCrashed",
                    f"La tarea mató a su worker en {attempts} intento(s) aislado(s).",
                )
                self._event("poisoned", f"seq={suspect.sequence_id} tras {attempts} intento(s)")
                return
        self._suspects.append(suspect)
        self._event("quarantined", f"seq={suspect.sequence_id}")

    def _apply_limits(self) -> None:
        limit = self._policy.max_rebuilds_without_progress
        over_streak = self._consecutive >= limit or self._poison_streak >= limit
        over_total = self._rebuilds >= self._policy.max_total_rebuilds and bool(
            self._pending or self._suspects
        )
        if over_streak or over_total:
            self._abort("sin progreso" if over_streak else "máximo de reconstrucciones")

    def _abort(self, reason: str) -> None:
        """Cierra lo pendiente: ``ABORTED``, o ``WORKER_INIT_FAILED`` si el entorno no arranca."""
        remaining = self._drain_unfinished()
        self._aborted = True
        if self._init_error is not None:
            status, kind = ExecutionStatus.WORKER_INIT_FAILED, "WorkerInitializationError"
            message = (
                f"El initializer de los workers falla de forma consistente: {self._init_error}"
            )
        else:
            status, kind = ExecutionStatus.ABORTED, "SupervisorAborted"
            message = f"El supervisor abortó la ejecución ({reason}); la tarea puede reintentarse."
        self._event("aborted", f"{reason}; {len(remaining)} tarea(s) sin concluir")
        if remaining:
            self._synthetic(remaining, status, kind, message)

    def _drain_unfinished(self) -> list[SequencedRequest]:
        items = [item for batch in self._pending for item in batch.items]
        items.extend(self._suspects)
        self._pending.clear()
        self._suspects.clear()
        return sorted(items, key=lambda item: item.sequence_id)

    # ----------------------------------------------------------------------- cancelación

    def _collateral(self) -> list[SequencedRequest]:
        """Tareas que una caída o un fallo del entorno dejó sin concluir durante la cancelación."""
        items = [item for batch, _ in self._affected for item in batch.items]
        self._affected = []
        self._broken = False
        return items + self._drain_unfinished()

    def _cancel(self, pool: ProcessPoolExecutor | None) -> None:
        """No se envía más; se espera la gracia a lo en vuelo y se termina el resto."""
        self._cancelled = True
        leftovers = self._drain_unfinished()
        self._event("cancel_requested", f"{len(leftovers)} tarea(s) sin enviar")
        deadline = time.monotonic() + self._policy.cancel_grace_seconds
        while self._in_flight and time.monotonic() < deadline:
            wait_for = min(self._policy.supervision_poll_seconds, deadline - time.monotonic())
            done, _ = wait(
                list(self._in_flight), timeout=max(wait_for, 0.0), return_when=FIRST_COMPLETED
            )
            for future in done:
                self._collect(future)
            leftovers += self._collateral()
        if self._in_flight and pool is not None:
            self._terminate_pool(pool, markers.scan(self._dir))
            for future in [f for f in self._in_flight if f.done()]:
                self._collect(future)
            leftovers += self._collateral()
        for batch in self._in_flight.values():
            leftovers.extend(batch.items)
        self._in_flight.clear()
        leftovers.sort(key=lambda item: item.sequence_id)
        if leftovers:
            self._synthetic(
                leftovers,
                ExecutionStatus.CANCELLED,
                "RunCancelled",
                "La ejecución se canceló antes de que la tarea concluyera.",
            )
