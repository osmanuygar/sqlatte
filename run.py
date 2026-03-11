#!/usr/bin/env python
"""
SQLatte ☕ - Simple Runner
Run this from project root: python run.py

Port is now read from config/config.yaml → app.port
"""

import sys
import os

# Add project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.api.app import app
from src.core.config_manager_enhanced import config_manager
import uvicorn

if __name__ == "__main__":
    # Load config to get host/port
    config = config_manager.get_config()
    host = config.get('app', {}).get('host', '0.0.0.0')
    port = config.get('app', {}).get('port', 8000)

    print("=" * 60)
    print("☕ SQLatte - Natural Language to SQL")
    print("=" * 60)
    print(f"Starting server on http://{host}:{port}")
    print("=" * 60)

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )