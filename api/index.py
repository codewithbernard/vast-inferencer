import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
SRC_PATH = str(SRC)
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from vast_inferencer.app import app

__all__ = ["app"]
