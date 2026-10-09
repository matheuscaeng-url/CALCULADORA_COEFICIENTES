"""Disponibiliza as bibliotecas Excel incluídas, inclusive sem pip/internet."""
from __future__ import annotations

import sys
from pathlib import Path


def configure_dependencies():
    bundled = Path(__file__).resolve().parent / 'dependencias'
    if bundled.is_dir() and str(bundled) not in sys.path:
        sys.path.insert(0, str(bundled))


configure_dependencies()
