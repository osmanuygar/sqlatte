#!/usr/bin/env python
"""
SQLatte ☕ - Simple Runner
Run this from project root: python run.py
"""

import sys
import os

# Add project root to Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import and run
from src.api.app import app
import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print("☕ SQLatte - Natural Language to SQL")
    print("=" * 60)
    print("Starting server...")
    print("Open: http://localhost:8000")
    print("=" * 60)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
