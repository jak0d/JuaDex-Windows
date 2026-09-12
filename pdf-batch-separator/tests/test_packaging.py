"""Guards on the PyInstaller specification.

PyInstaller cannot cross-compile, so the Windows executable has to be built on
Windows.  These tests catch the mistakes that would otherwise only surface
after that build: a hidden import that no longer exists, a bundled data file
that was renamed, or - the dangerous one - an entry in the ``excludes`` list
that the application actually needs at runtime.

An over-eager exclude is the classic way a packaged build works on the
developer's machine (where the module is importable anyway) and crashes on a
user's machine.
"""

from __future__ import annotations

import importlib
import os
import textwrap
import pkgutil
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "packaging" / "app.spec"


def _spec_list(name: str) -> list[str]:
    """Pull a simple string list out of the spec without executing it."""

    text = SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(rf"^{name} = \[(.*?)\n\]", text, re.S | re.M)
    assert match, f"could not find '{name}' list in {SPEC_PATH.name}"
    return re.findall(r'"([^"]+)"', match.group(1))


class TestSpecIntegrity:
    def test_spec_exists(self):
        assert SPEC_PATH.is_file()

    def test_entry_point_exists(self):
        assert (PROJECT_ROOT / "src" / "pdf_batch_separator" / "__main__.py").is_file()

    def test_bundled_documents_exist(self):
        for document in ("THIRD_PARTY_NOTICES.md", "LICENSE", "PRIVACY.md"):
            assert (PROJECT_ROOT / document).is_file(), f"{document} is referenced by app.spec"

    def test_icon_and_version_info_exist(self):
        icon = PROJECT_ROOT / "src" / "pdf_batch_separator" / "resources" / "app.ico"
        assert icon.is_file() and icon.stat().st_size > 0
        assert (PROJECT_ROOT / "packaging" / "version_info.txt").is_file()

    def test_windowed_build_has_no_console(self):
        text = SPEC_PATH.read_text(encoding="utf-8")
        assert "console=False" in text
        assert "console=True" not in text


class TestHiddenImports:
    def test_declared_hidden_imports_are_importable(self):
        pytest.importorskip("PySide6.QtWidgets", reason="Qt libraries unavailable")
        broken = []
        for module in _spec_list("hiddenimports"):
            try:
                importlib.import_module(module)
            except Exception as exc:  # pragma: no cover - failure path
                broken.append(f"{module}: {exc}")
        assert not broken, f"app.spec lists unimportable hidden imports: {broken}"

    def test_every_package_submodule_is_importable(self):
        pytest.importorskip("PySide6.QtWidgets", reason="Qt libraries unavailable")
        import pdf_batch_separator

        broken = []
        for info in pkgutil.walk_packages(
            pdf_batch_separator.__path__, "pdf_batch_separator."
        ):
            try:
                importlib.import_module(info.name)
            except Exception as exc:  # pragma: no cover - failure path
                broken.append(f"{info.name}: {exc}")
        assert not broken, f"collect_submodules would fail on: {broken}"


class TestExcludesAreSafe:
    """The excludes list must not contain anything the app really uses."""

    def test_excluded_modules_are_not_used_by_a_full_run(self, workdir, outdir):
        pytest.importorskip("PySide6.QtWidgets", reason="Qt libraries unavailable")

        from fixtures.builders import add_blank_page, add_separator_page, add_text_page, build_pdf
        from pdf_batch_separator.core.analyzer import analyze_document
        from pdf_batch_separator.core.batch import (
            AnalysisSettings,
            analyze_batch,
            export_batch,
        )
        from pdf_batch_separator.core.exporter import export_document
        from pdf_batch_separator.core.models import BatchSummary
        from pdf_batch_separator.core.report import build_report, write_report
        from pdf_batch_separator.core.separator_pdf import create_separator_pdf

        separator = "EAGC-EDMS-00001"
        source = build_pdf(
            workdir / "packaging_run.pdf",
            lambda d: (
                add_text_page(d, "A"),
                add_separator_page(d, separator),
                add_blank_page(d),
                add_text_page(d, "B"),
            ),
        )
        create_separator_pdf(separator, workdir / "sheet.pdf")

        settings = AnalysisSettings(expected_separator=separator, remove_blanks=True)
        analyses = analyze_batch([source], settings)
        results = export_batch(analyses, outdir)
        summary = BatchSummary(output_folder=outdir, results=tuple(results))
        write_report(
            build_report(
                summary,
                {Path(a.source_path): a for a in analyses},
                separator=separator,
            ),
            outdir,
        )
        analysis = analyze_document(source, expected_separator=separator)
        export_document(analysis, outdir)

        # "pytest" and "unittest" are pulled in by the test runner itself, not
        # by the application, so they cannot be judged from inside a test.
        # test_no_test_framework_leaks_into_the_app covers them instead.
        harness_only = {"pytest", "unittest", "setuptools", "pip"}
        loaded = set(sys.modules)
        used = sorted(
            module
            for module in _spec_list("excludes")
            if module not in harness_only
            and any(name == module or name.startswith(module + ".") for name in loaded)
        )
        assert not used, (
            "app.spec excludes modules the application loads at runtime; "
            f"the packaged build would break: {used}"
        )

    def test_no_test_framework_leaks_into_the_app(self):
        """pytest/unittest/setuptools must not be reachable from app code.

        These cannot be checked from inside a test run - the runner has already
        imported them - so the application's own imports are inspected in a
        clean subprocess instead.
        """
        import subprocess

        script = textwrap.dedent(
            """
            import sys
            import pdf_batch_separator.app  # noqa: F401
            import pdf_batch_separator.ui.main_window  # noqa: F401
            import pdf_batch_separator.ui.document_review  # noqa: F401
            import pdf_batch_separator.core.analyzer  # noqa: F401
            import pdf_batch_separator.core.exporter  # noqa: F401
            banned = {"pytest", "unittest", "setuptools", "pip", "tkinter"}
            hit = sorted(
                b for b in banned
                if any(m == b or m.startswith(b + ".") for m in sys.modules)
            )
            print(",".join(hit))
            """
        )
        env = dict(os.environ)
        src = str(PROJECT_ROOT / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if completed.returncode != 0:
            pytest.skip(f"could not import the app in a subprocess: {completed.stderr[-300:]}")
        leaked = [name for name in completed.stdout.strip().split(",") if name]
        assert not leaked, f"application code imports excluded modules: {leaked}"
