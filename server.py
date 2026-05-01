"""
Desk Talk server entry point.

Runs `backend/server.py` with the project root as the working directory so
paths (config, .env, YOLO weights) resolve consistently.

Usage:  python server.py
"""

from __future__ import annotations

import os
import runpy

_ROOT = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    os.chdir(_ROOT)
    runpy.run_path(os.path.join(_ROOT, "backend", "server.py"), run_name="__main__")
