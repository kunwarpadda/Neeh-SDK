"""Packaging contracts: the core imports without any optional dependency."""
from __future__ import annotations

import subprocess
import sys

# Simulates an environment where Pillow is not installed by poisoning the
# import machinery before neeh is imported. Every public package must still
# import; only the actual raster call may require the optional dependency.
_NO_PIL_PROBE = """
import sys

class _BlockPIL:
    def find_spec(self, name, path=None, target=None):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("PIL blocked for packaging test")
        return None

sys.meta_path.insert(0, _BlockPIL())

import neeh
import neeh.agents
import neeh.canvas
import neeh.tools
import neeh.adapters
from neeh import Canvas
from neeh.agents import analyze_ink, reduce_ink, build_observation_workspace
from neeh.ink import Author

canvas = Canvas()
stroke = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
assert analyze_ink(canvas, "latest_mark")["latest"]["id"] == stroke.id
workspace = build_observation_workspace(canvas, "latest mark?")
assert workspace["analysis"]["operation"] == "latest_mark"

# The raster path must fail with the documented, actionable message.
try:
    from neeh.rendering.png import render_page_png
except ImportError as exc:
    assert "neeh[png]" in str(exc), str(exc)
else:
    raise AssertionError("png import unexpectedly succeeded with PIL blocked")

print("OK")
"""


def test_core_and_agents_import_without_pillow():
    completed = subprocess.run(
        [sys.executable, "-c", _NO_PIL_PROBE],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "OK"


def test_runtime_version_matches_installed_metadata():
    # neeh.__version__ must track the distribution version (pyproject.toml),
    # never a stale hardcode: v0.2.0 shipped reporting 0.1.0 at runtime.
    from importlib.metadata import version

    import neeh

    assert neeh.__version__ == version("neeh")
