"""
Cricket Simulator API

Start with:
    uvicorn api.main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()  # loads .env from project root before anything else reads os.getenv()

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.admin import router as admin_router
from api.routes.admin_squads import router as admin_squads_router
from api.routes.auth import router as auth_router
from api.routes.leaderboards import router as lb_router
from api.routes.lov import router as lov_router
from api.routes.sim_history import router as sim_history_router
from api.routes.simulations import router as sim_router
from db.stats_repository import StatsRepository
from simulator.logger import configure_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logger(log_dir="logs")
    StatsRepository.warm_all_caches()
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
app.include_router(admin_squads_router)
app.include_router(auth_router)
app.include_router(lov_router)
app.include_router(sim_router)
app.include_router(lb_router)
app.include_router(sim_history_router)
