"""
Cricket Simulator API

Start with:
    uvicorn api.main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # loads .env from project root before anything else reads os.getenv()

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.job_queue import job_queue
from api.routes.admin import router as admin_router
from api.routes.admin_squads import router as admin_squads_router
from api.routes.auth import router as auth_router
from api.routes.leaderboards import router as lb_router
from api.routes.lov import router as lov_router
from api.routes.multiplayer import router as multiplayer_router
from api.routes.sim_history import router as sim_history_router
from api.routes.simulations import router as sim_router
from api.worker import run_match_job, run_tournament_job
from db.database import get_db_connection
from db.stats_repository import StatsRepository
from simulator.logger import configure_logger, get_logger

# Clear the stats cache when available RAM drops below this threshold.
_LOW_RAM_THRESHOLD_MB = int(os.getenv("LOW_RAM_THRESHOLD_MB", "250"))
# 10s, not 30s — most simulations finish in well under 30s, so a 30s interval
# would often take zero samples during a run's own lifetime. The check itself
# is two cheap syscalls plus a dict len(), negligible even at this frequency.
_RAM_CHECK_INTERVAL_S = 10

# Startup default for simulation.log's level — same knob as PUT /admin/log-level,
# just what it starts at before anyone changes it at runtime. Distinct from the
# pre-existing LOG_LEVEL env var, which controls the console handler only.
_SIM_LOG_LEVEL = getattr(logging, os.getenv("SIM_LOG_LEVEL", "INFO").upper(), logging.INFO)


def _memory_monitor() -> None:
    """Daemon thread: evicts the stats cache under memory pressure.

    Logs available system RAM, this process's own RSS, and the cache's
    top-level key count on EVERY check (not just when evicting) at INFO —
    one short line every 10s, not high-volume enough to warrant gating behind
    DEBUG. A below-threshold-only log only shows the moment the threshold was
    crossed, not the shape of the decline leading up to it, which is what's
    actually needed to tell "cache growth" apart from "RSS not being
    released back to the OS" as the cause of a low-RAM period.
    """
    log = get_logger()
    proc = psutil.Process(os.getpid())
    while True:
        time.sleep(_RAM_CHECK_INTERVAL_S)
        available_mb = psutil.virtual_memory().available / 1024 / 1024
        rss_mb = proc.memory_info().rss / 1024 / 1024
        cache_keys = StatsRepository.cache_key_count()
        log.info(
            "[MemMonitor] available=%.0fMB rss=%.0fMB cache_keys=%d",
            available_mb, rss_mb, cache_keys,
        )
        if available_mb < _LOW_RAM_THRESHOLD_MB:
            cleared = StatsRepository.clear_cache()
            log.warning(
                "[MemMonitor] Low RAM (%.0f MB free, rss=%.0f MB) — evicted %d cache entries",
                available_mb, rss_mb, cleared,
            )


def _resume_or_fail_interrupted_sims() -> None:
    """On startup, sweep sims left mid-flight by a previous process lifetime
    (crash/restart) — this deploys as a single uvicorn process with no
    external job broker (see [[job_queue]]), so anything queued or running
    when the process died is otherwise stuck forever with a stale status
    the frontend would poll against indefinitely.

    - status='pending' (never actually started — nothing persisted yet) is
      safe and cheap to just re-submit to the fresh job_queue.
    - status='running' is NOT auto-resumed: a partially-completed sim may
      already have rows written across matches/deliveries/teams/etc (none
      of which cascade-delete), so safely retrying would mean deleting all
      of that first. Out of scope for now — marked failed instead, so a
      client polling it gets a clean failure rather than hanging forever.
    """
    log = get_logger()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE simulation.simulations SET status = 'failed', "
            "error_message = 'Interrupted by server restart' WHERE status = 'running'"
        )
        if cur.rowcount:
            log.warning("Marked %d simulation(s) failed: interrupted by restart while running", cur.rowcount)

        cur.execute(
            "SELECT sim_id, simulation_type, config, client_id FROM simulation.simulations WHERE status = 'pending'"
        )
        pending = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    for sim_id, sim_type, config, client_id in pending:
        if sim_type == "match":
            job_queue.submit(sim_id, run_match_job, sim_id, config)
        else:
            # user_team_name isn't persisted anywhere (it only ever existed
            # as a local variable in the original request handler) — the
            # resumed job still runs and completes correctly, it just can't
            # back-fill this one session's personalized team name/placement
            # the way a normal run does. Narrow, rare-edge-case-of-a-rare-
            # edge-case cost, not worth a new persisted column for.
            job_queue.submit(sim_id, run_tournament_job, sim_id, config, client_id=client_id)
        log.info("Resumed queued simulation %s (%s) after restart", sim_id, sim_type)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logger(log_dir="logs", sim_log_level=_SIM_LOG_LEVEL)
    threading.Thread(target=_memory_monitor, daemon=True, name="mem-monitor").start()
    job_queue.start()
    _resume_or_fail_interrupted_sims()
    yield


app = FastAPI(
    title="Cricket Simulator API",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow the Vite dev server (and any configured prod origin) to call the API.
_allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra = os.getenv("CORS_ORIGINS", "")
if _extra:
    _allowed_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
# Also mount under /cricsimapi — every other route the frontend calls goes through
# this prefix (nginx proxies it in production), whereas bare /admin/* is only used
# for direct ops access (curl/SSH). Registering both keeps the new Admin page
# reachable from the browser without touching how /admin/* has always been used.
app.include_router(admin_router, prefix="/cricsimapi")
app.include_router(admin_squads_router)
app.include_router(auth_router)
app.include_router(lov_router)
app.include_router(sim_router)
app.include_router(lb_router)
app.include_router(sim_history_router)
app.include_router(multiplayer_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all safety net: any exception a route doesn't handle itself still
    gets logged with a traceback before the client sees a generic 500."""
    get_logger().exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
