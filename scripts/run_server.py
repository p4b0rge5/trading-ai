#!/usr/bin/env python3
"""
Trading AI API — Entrypoint.

Usage:
    python -m api.app              # Run with default settings
    python scripts/run_server.py   # Same
    uvicorn api.app:app --reload   # Dev mode with auto-reload
"""

import sys
import os

# Ensure trading-ai root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from api.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8081,
        reload=settings.debug,
        log_level="info",
    )
