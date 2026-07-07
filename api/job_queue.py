"""
In-process simulation job queue with a bounded number of concurrent workers.

Every simulation (single-player match/tournament, multiplayer match/
tournament) used to get dispatched via one of two ad hoc "fire and forget
onto a thread" mechanisms — FastAPI's BackgroundTasks for single-player, a
direct loop.run_in_executor(...) call for multiplayer. Both ultimately run
on OS threads pulled from a thread pool, with no cap on how many could run
at once — so several simulations triggered around the same time genuinely
execute concurrently, competing for the GIL and CPU.

Measured directly on the production droplet (1 vCPU): running 4 simulations
concurrently was ~12% *slower* in aggregate than running them one after
another — concurrency there was pure lock/GIL contention, not real
parallelism, since there's no second core to actually use. JobQueue caps
concurrency explicitly (default 2, tunable via SIM_QUEUE_MAX_CONCURRENT)
instead of leaving it unbounded, so at most that many simulations ever run
at once, with the rest queued in FIFO order. Everything else (the API,
websockets) stays fully async/responsive — only the CPU-bound simulation
work itself is capped.
"""

from __future__ import annotations

import os
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable

from simulator.logger import get_logger

_DEFAULT_MAX_CONCURRENT = int(os.getenv("SIM_QUEUE_MAX_CONCURRENT", "2"))


class JobQueue:
    def __init__(self, max_concurrent: int = _DEFAULT_MAX_CONCURRENT) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._queue: "queue.Queue[_Job]" = queue.Queue()
        self._lock = threading.Lock()
        # Every submitted-but-not-yet-finished job id, including whichever
        # ones are currently running, in FIFO order. Removal happens only
        # when a job finishes (not when a worker dequeues it to start), so
        # a running job keeps reporting its position for its whole
        # execution, and everyone behind it shifts down by one — via plain
        # list-removal semantics, nothing renumbered by hand — only once it
        # actually completes.
        self._order: list[str] = []
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """Start the worker threads (one per max_concurrent slot). Call once, at app startup."""
        for i in range(self._max_concurrent):
            t = threading.Thread(target=self._run, daemon=True, name=f"sim-job-queue-{i}")
            t.start()
            self._threads.append(t)

    def submit(self, job_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> "Future[Any]":
        """Enqueue fn(*args, **kwargs) to run on the next free worker slot.

        job_id is an explicit tracking key for position() — not introspected
        from args, since some callers (multiplayer) don't have their real
        sim_id yet at submit time and use a different key (e.g. room_id).
        """
        future: "Future[Any]" = Future()
        job = _Job(job_id, fn, args, kwargs, future)
        with self._lock:
            self._order.append(job_id)
        self._queue.put(job)
        return future

    def position(self, job_id: str) -> int | None:
        """0 if there's a free worker slot for this job (queued-to-start or
        already running — up to max_concurrent jobs can share position 0),
        1 if one job is queued ahead of it beyond the active slots, etc.
        None if not tracked (finished, or unknown id)."""
        with self._lock:
            try:
                idx = self._order.index(job_id)
            except ValueError:
                return None
        return max(0, idx - (self._max_concurrent - 1))

    def _run(self) -> None:
        log = get_logger()
        while True:
            job = self._queue.get()
            try:
                result = job.fn(*job.args, **job.kwargs)
                job.future.set_result(result)
            except Exception as exc:
                # run_match_job/run_tournament_job already swallow their own
                # exceptions internally (log + mark the DB row failed), so
                # this rarely fires for them — but multiplayer's
                # _run_simulation can raise before either of those even gets
                # called, and its caller's except block depends on that
                # exception actually propagating through the Future. Either
                # way, log it here too so nothing can vanish silently.
                log.exception("Simulation job failed in queue worker (job_id=%s)", job.job_id)
                job.future.set_exception(exc)
            finally:
                with self._lock:
                    self._order.remove(job.job_id)
                self._queue.task_done()


class _Job:
    __slots__ = ("job_id", "fn", "args", "kwargs", "future")

    def __init__(self, job_id: str, fn: Callable[..., Any], args: tuple, kwargs: dict, future: "Future[Any]") -> None:
        self.job_id = job_id
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.future = future


# Process-level singleton — matching the pattern of _memory_monitor /
# _PRECOMPUTED_CACHE (api/main.py, db/stats_repository.py): fine because
# this deploys as a single uvicorn process (explicitly no --workers, see
# CLAUDE.md). max_concurrent defaults to 2 (env: SIM_QUEUE_MAX_CONCURRENT).
job_queue = JobQueue()
