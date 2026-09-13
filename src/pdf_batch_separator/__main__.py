"""Entry point for ``python -m pdf_batch_separator`` and the packaged build.

This file is launched three different ways, and each one gives it a different
idea of where it lives:

``python -m pdf_batch_separator``
    Imported as a submodule, so ``__package__`` is ``"pdf_batch_separator"``.

``python src/pdf_batch_separator/__main__.py``
    Run as a loose script: no parent package, and ``src`` is not on the path.

The PyInstaller executable
    PyInstaller compiles this file as the program's top-level script, which
    means ``__package__`` is empty there too.

A relative import (``from .app import main``) only works in the first case.  In
the other two it raises ``ImportError: attempted relative import with no known
parent package`` before any error handling exists to report it, so the packaged
application dies at launch behind a bare "Failed to execute script" dialog.
The absolute import below works in all three cases.
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def _ensure_package_importable() -> None:
    """Put the package's parent directory on ``sys.path`` when run as a script.

    Only needed for a loose-script launch.  ``python -m`` already resolved the
    package, and a frozen build serves it from the bundled archive, so both are
    left untouched.
    """

    if __package__:
        return
    if getattr(sys, "frozen", False):
        return

    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if package_root not in sys.path:
        sys.path.insert(0, package_root)


def _resolve_main():
    """Return :func:`pdf_batch_separator.app.main` via an absolute import."""

    _ensure_package_importable()

    from pdf_batch_separator.app import main

    return main


def run() -> int:
    """Start the application and return its exit code."""

    return _resolve_main()()


if __name__ == "__main__":
    # Must come first: on Windows a frozen build re-executes this script for
    # every spawned child process, and freeze_support() is what makes such a
    # child do its job and exit instead of opening a second copy of the GUI.
    multiprocessing.freeze_support()
    sys.exit(run())
