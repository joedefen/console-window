"""A syntax and import gate for the demo scripts.

The demos are showcase programs, not part of the installed package.  They are
meant to be changed freely, so the library suite asserts nothing about their
screens, keys, help pages or feature manifest: those are content decisions for
whoever edits a demo.  The one thing the suite still guards is that every
``demos/*.py`` compiles and imports against the public API, which keeps a broken
demo from rotting silently.  Behaviour is checked by running the demo.

The import runs in a subprocess so module-level statements in a demo (they set
``ConsoleWindow.timeout_ms``, for example) cannot leak into other tests.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMOS = ROOT / 'demos'

_IMPORT_DEMO = """\
import importlib.util
import sys

sys.path.insert(0, {root!r})
sys.path.insert(0, {demos!r})

name = {name!r}
spec = importlib.util.spec_from_file_location(name, {path!r})
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
"""


def _demo_paths() -> list[pathlib.Path]:
    return sorted(DEMOS.glob('*.py'))


@pytest.mark.parametrize('path', _demo_paths(), ids=lambda path: path.stem)
def test_every_demo_compiles_and_imports(path: pathlib.Path) -> None:
    """Syntax plus every API name the demo uses at import time must exist."""
    program = _IMPORT_DEMO.format(
        root=str(ROOT),
        demos=str(DEMOS),
        name='demo_under_test_' + path.stem.replace('-', '_'),
        path=str(path),
    )
    result = subprocess.run(
        [sys.executable, '-c', program],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
