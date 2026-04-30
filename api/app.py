"""
Main FastAPI application.

Endpoints:
  GET  /health                     — Health check
  POST /api/v1/auth/register       — Create account
  POST /api/v1/auth/login          — Login, get JWT
  GET  /api/v1/auth/me             — Current user
  CRUD /api/v1/strategies/         — Strategy management
  POST /api/v1/strategies/from-prompt — Prompt-to-strategy
  POST /api/v1/backtests/          — Run backtest
  GET  /api/v1/backtests/summary   — List backtests
  GET  /api/v1/backtests/{id}      — Backtest detail + trades
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db

# Import routes
from .routes_auth import router as auth_router
from .routes_strategies import router as strategies_router
from .routes_backtests import router as backtests_router
from .routes_data import router as data_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Trading AI API started")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Trading AI API",
    description="AI-powered trading strategy engine. Create strategies from natural language, backtest, and analyze.",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(strategies_router)
app.include_router(backtests_router)
app.include_router(data_router)


# ── Health Check ────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "0.2.0",
        "engine_indicators": 9,
        "strategies_supported": [
            "sma", "ema", "wma", "rsi", "macd", "bollinger",
            "stochastic", "atr", "adx",
        ],
    }


# ── Frontend (Static Files + SPA) ──────────────────────────────────────

_frontend_dir = Path(__file__).parent.parent / "frontend"

# Serve static files at /frontend/
app.mount("/frontend", StaticFiles(directory=str(_frontend_dir)), name="frontend")


@app.get("/", tags=["frontend"])
async def serve_app(request: Request):
    """Serve the SPA — index.html"""
    return FileResponse(str(_frontend_dir / "index.html"))
