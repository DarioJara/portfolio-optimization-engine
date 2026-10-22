"""Bloqueo de ``pool.shutdown(wait=True)`` por un semáforo de cola huérfano (REMEDIATION §11).

Los workers ociosos de un ``ProcessPoolExecutor`` esperan trabajo dentro de ``call_queue.get()`` y
esa espera ocurre **con el semáforo de lectura de la cola tomado**: un worker lo sostiene y los
demás lo esperan. Si el supervisor termina solo a un worker (los registrados) y era el que lo
sostenía, el semáforo no se libera: los supervivientes no reciben el centinela de cierre y
``shutdown(wait=True)`` no termina jamás. Observado en CI (4 de 10 ejecuciones, tres modelos de
CPU) como cuelgue de la prueba de iniciadores que siempre fallan, en ``_terminate_pool``.

No se sabe qué worker sostiene el semáforo, así que cada prueba ejecuta el escenario con **cada
uno** de los dos workers como víctima: en una de las dos ejecuciones la víctima es quien lo
sostiene. Cada escenario corre en un proceso aparte con un vigilante: un cuelgue nunca bloquea la
suite.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.integration

SCENARIO = textwrap.dedent(
    """
    import os, sys, threading, time
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    from portfolio_engine.parallel.supervisor import kill_pool_workers


    if __name__ == "__main__":
        victim, mode, limit = int(sys.argv[1]), sys.argv[2], float(sys.argv[3])
        pool = ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn"))
        for future in [pool.submit(time.sleep, 0.5), pool.submit(time.sleep, 0.5)]:
            future.result(timeout=120)
        time.sleep(1.0)  # ambos workers ociosos dentro de call_queue.get()
        processes = sorted(pool._processes.values(), key=lambda p: p.pid)
        assert len(processes) == 2, len(processes)

        def give_up():  # vigilante: un cierre colgado mata a los workers y sale con el código 3
            for process in processes:
                process.kill()
            print("SHUTDOWN_HUNG", flush=True)
            os._exit(3)

        watchdog = threading.Timer(limit, give_up)
        watchdog.daemon = True
        watchdog.start()
        processes[victim].kill()  # lo que hace terminate_owned con un worker registrado
        processes[victim].join(timeout=30)
        if mode == "fixed":
            kill_pool_workers(pool)
        pool.shutdown(wait=True, cancel_futures=True)
        watchdog.cancel()
        print("SHUTDOWN_DONE")
    """
)


def _run(victim: int, mode: str, seconds: float) -> bool:
    """``True`` si el cierre terminó dentro de ``seconds``; ``False`` si se colgó (y se abortó)."""
    done = subprocess.run(
        [sys.executable, "-c", SCENARIO, str(victim), mode, str(seconds)],
        capture_output=True,
        text=True,
        timeout=seconds + 120.0,
        check=False,
    )
    if done.returncode == 3:
        return False
    assert done.returncode == 0, done.stderr[-2000:]
    return "SHUTDOWN_DONE" in done.stdout


@pytest.mark.parametrize("victim", [0, 1])
def test_shutdown_after_killing_one_worker_completes_with_kill_pool_workers(victim: int) -> None:
    """Con la corrección el cierre termina sea cual sea el worker terminado."""
    assert _run(victim, "fixed", 60.0)


def test_control_plain_shutdown_hangs_when_the_killed_worker_held_the_queue_lock() -> None:
    """Control: sin la corrección, en una de las dos ejecuciones el cierre se cuelga.

    Documenta el riesgo de CPython que justifica ``kill_pool_workers``. Si una versión futura de
    Python lo corrigiera, esta prueba fallará y indicará que la protección puede revisarse.
    """
    outcomes = [_run(victim, "plain", 15.0) for victim in (0, 1)]
    assert outcomes.count(False) >= 1, outcomes
