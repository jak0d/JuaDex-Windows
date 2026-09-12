"""Entry point for ``python -m pdf_batch_separator`` and the packaged build."""

from __future__ import annotations

import multiprocessing
import sys

from .app import main

if __name__ == "__main__":
    # Required so a frozen Windows build never re-launches the GUI in a child
    # process if any dependency spawns one.
    multiprocessing.freeze_support()
    sys.exit(main())
