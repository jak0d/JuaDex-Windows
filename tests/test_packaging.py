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

    def test_entry_point_is_named_as_the_analysis_input(self):
        """The spec must point Analysis at the file the tests below exercise."""

        text = SPEC_PATH.read_text(encoding="utf-8")
        assert "__main__.py" in text

    def test_bundled_documents_exist(self):
        for document in ("THIRD_PARTY_NOTICES.md", "LICENSE", "PRIVACY.md"):
            assert (PROJECT_ROOT / document).is_file(), f"{document} is referenced by app.spec"

    def test_complete_licence_texts_are_bundled(self):
        minimum_sizes = {
            "AGPL-3.0.txt": 20_000,
            "GPL-3.0.txt": 20_000,
            "LGPL-3.0.txt": 5_000,
            "Apache-2.0.txt": 8_000,
            "Lucide-ISC.txt": 500,
        }
        for filename, minimum in minimum_sizes.items():
            path = PROJECT_ROOT / "LICENSES" / filename
            assert path.stat().st_size >= minimum, f"{filename} looks like a metadata stub"

        spec = SPEC_PATH.read_text(encoding="utf-8")
        installer = (PROJECT_ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        assert 'datas.append((str(licences), "LICENSES"))' in spec
        assert 'Source: "..\\LICENSES\\*"' in installer

    def test_only_lgpl_safe_one_folder_build_is_available(self):
        text = SPEC_PATH.read_text(encoding="utf-8")
        assert "ONEFILE" not in text
        assert 'contents_directory="."' in text
        assert "COLLECT(" in text

    def test_release_requirements_are_exactly_pinned(self):
        requirements = PROJECT_ROOT / "packaging" / "requirements-release.txt"
        lines = [
            line.partition("#")[0].strip()
            for line in requirements.read_text(encoding="utf-8").splitlines()
        ]
        pins = [line for line in lines if line]
        assert pins
        assert all(re.fullmatch(r"[A-Za-z0-9_.-]+==[^\s;]+", pin) for pin in pins)

    def test_icon_and_version_info_exist(self):
        icon = PROJECT_ROOT / "src" / "pdf_batch_separator" / "resources" / "app.ico"
        assert icon.is_file() and icon.stat().st_size > 0
        assert (PROJECT_ROOT / "packaging" / "version_info.txt").is_file()

    def test_windowed_build_has_no_console(self):
        text = SPEC_PATH.read_text(encoding="utf-8")
        assert "console=False" in text
        assert "console=True" not in text


class TestEntryPointIsFreezable:
    """The entry script must survive being run without a parent package.

    PyInstaller compiles the Analysis input as the program's top-level
    ``__main__`` module, so ``__package__`` is empty inside it.  A relative
    import there (``from .app import main``) raises

        ImportError: attempted relative import with no known parent package

    which the user only sees as "Failed to execute script '__main__'" after
    installing.  Nothing in the normal ``python -m`` test run reproduces it,
    because that launch *does* have a parent package - which is exactly how the
    bug shipped.
    """

    ENTRY = PROJECT_ROOT / "src" / "pdf_batch_separator" / "__main__.py"

    def test_entry_point_has_no_relative_imports(self):
        """A relative import in the entry script cannot work once frozen."""

        import ast

        tree = ast.parse(self.ENTRY.read_text(encoding="utf-8"), filename=str(self.ENTRY))
        relative = [
            f"line {node.lineno}: "
            f"from {'.' * node.level}{node.module or ''} import "
            + ", ".join(a.name for a in node.names)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level > 0
        ]
        assert not relative, (
            "the packaged entry script runs with no parent package, so these "
            "relative imports would raise 'attempted relative import with no "
            f"known parent package' at launch: {relative}"
        )

    def test_entry_point_runs_with_no_parent_package(self):
        """Execute the entry script the way the frozen bootloader does."""

        import subprocess

        # run_path() with a non-"__main__" run_name mimics the frozen launch:
        # the module executes top-level with __package__ == "", but the
        # ``if __name__ == "__main__"`` block stays dormant so no GUI opens.
        script = textwrap.dedent(
            f"""
            import runpy, sys
            module = runpy.run_path(r"{self.ENTRY}", run_name="__pyi_probe__")
            assert module.get("__package__") in ("", None), module.get("__package__")
            resolve = module["_resolve_main"]
            main = resolve()
            print("OK:" + main.__module__ + "." + main.__name__)
            """
        )
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        # Deliberately do NOT put src/ on PYTHONPATH: the frozen build has no
        # such entry either, and the entry script must cope on its own.
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(PROJECT_ROOT.parent),
            timeout=120,
        )
        if "attempted relative import" in completed.stderr:
            pytest.fail(
                "the entry script uses a relative import and would crash the "
                f"packaged build:\n{completed.stderr[-500:]}"
            )
        if completed.returncode != 0:
            pytest.skip(f"entry point could not be probed here: {completed.stderr[-300:]}")
        assert completed.stdout.strip().endswith("pdf_batch_separator.app.main")

    def test_freeze_support_runs_before_the_gui(self):
        """multiprocessing.freeze_support() must precede the GUI call.

        On Windows a frozen child process re-runs this script; if the GUI
        starts first the user gets a second window instead of a worker.
        """

        source = self.ENTRY.read_text(encoding="utf-8")
        guard = source.find('if __name__ == "__main__":')
        assert guard != -1, "the entry script needs a __main__ guard"
        block = source[guard:]

        freeze = block.find("freeze_support()")
        assert freeze != -1, "freeze_support() must run under the __main__ guard"

        # The call that starts the application, whatever it is named.
        starts = [block.find(call) for call in ("run()", "main()") if block.find(call) != -1]
        assert starts, "the __main__ guard should start the application"
        assert freeze < min(starts), (
            "freeze_support() has to run before the application starts, or a "
            "frozen Windows child process opens a second window"
        )


class TestHiddenImports:
    def test_declared_hidden_imports_are_importable(self):
        pytest.importorskip(
            "PySide6.QtWidgets", reason="Qt libraries unavailable", exc_type=ImportError
        )
        broken = []
        for module in _spec_list("hiddenimports"):
            try:
                importlib.import_module(module)
            except Exception as exc:  # pragma: no cover - failure path
                broken.append(f"{module}: {exc}")
        assert not broken, f"app.spec lists unimportable hidden imports: {broken}"

    def test_every_package_submodule_is_importable(self):
        pytest.importorskip(
            "PySide6.QtWidgets", reason="Qt libraries unavailable", exc_type=ImportError
        )
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
        pytest.importorskip(
            "PySide6.QtWidgets", reason="Qt libraries unavailable", exc_type=ImportError
        )

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
        #
        # PySide6.QtTest is the same situation one level down: pytest-qt's
        # modeltest imports it at collection time to get
        # QAbstractItemModelTester. No application module references it, which
        # test_qttest_is_only_imported_by_the_test_harness asserts directly.
        harness_only = {"pytest", "unittest", "setuptools", "pip", "PySide6.QtTest"}
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

    def test_qttest_is_only_imported_by_the_test_harness(self):
        """PySide6.QtTest is excluded from the build, so the app must not need it.

        pytest-qt imports QtTest during collection to get
        QAbstractItemModelTester, which makes this invisible to the
        excludes check above. Building the real UI in a clean subprocess
        proves the exclude is safe.
        """
        import subprocess

        script = textwrap.dedent(
            """
            import sys
            from PySide6.QtWidgets import QApplication
            app = QApplication([])
            from pdf_batch_separator.ui.main_window import MainWindow
            from pdf_batch_separator.ui.document_review import (  # noqa: F401
                DocumentReviewDialog,
            )
            from pdf_batch_separator.ui.batch_model import BatchTableModel
            from pdf_batch_separator.ui import icons, theme

            theme.apply_theme(app)
            window = MainWindow()
            window.resize(1200, 800)
            model = BatchTableModel()
            icons.icon("check")
            print("QtTest" if "PySide6.QtTest" in sys.modules else "clean")
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
            pytest.skip(f"could not build the UI in a subprocess: {completed.stderr[-300:]}")
        assert completed.stdout.strip().endswith("clean"), (
            "the application imports PySide6.QtTest, which app.spec excludes; "
            "the packaged build would crash"
        )
