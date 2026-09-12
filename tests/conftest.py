"""Shared pytest fixtures for the PDF Batch Separator test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

SEPARATOR_VALUE = "EAGC-EDMS-00001"


@pytest.fixture(scope="session")
def separator_value() -> str:
    return SEPARATOR_VALUE


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """A clean scratch directory for generated fixtures."""

    directory = tmp_path / "work"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture
def outdir(tmp_path: Path) -> Path:
    directory = tmp_path / "out"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
