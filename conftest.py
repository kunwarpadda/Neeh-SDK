"""Repo-root pytest config: make the non-shipped `research` package importable."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
