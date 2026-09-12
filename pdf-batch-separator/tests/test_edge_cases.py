"""Remaining PRD section 11 edge cases and acceptance-criteria checks."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

try:
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore[no-redef]

from fixtures.builders import (
    add_blank_page,
    add_dark_page,
    add_faint_text_page,
    add_separator_page,
    add_text_page,
    build_pdf,
)
from pdf_batch_separator.core import exporter as exporter_module
from pdf_batch_separator.core.analyzer import (
    MAX_RENDER_DIMENSION,
    analyze_document,
    render_page_array,
    open_document,
)
from pdf_batch_separator.core.batch import AnalysisSettings, analyze_batch, export_batch
from pdf_batch_separator.core.exporter import TEMP_PREFIX, export_document
from pdf_batch_separator.core.models import BlankSensitivity, ProcessingMode
from pdf_batch_separator.core.separator_pdf import (
    SeparatorGenerationError,
    create_separator_pdf,
)

SEP = "EAGC-EDMS-00001"


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class TestRenderLimits:
    def test_oversized_page_is_capped(self, workdir):
        """A very large page must not blow past the dimension cap."""

        document = pymupdf.open()
        try:
            # 200 x 200 inch page.
            page = document.new_page(width=200 * 72, height=200 * 72)
            page.insert_textbox(
                pymupdf.Rect(100, 100, 5000, 400), "Huge page", fontsize=200
            )
            path = workdir / "huge.pdf"
            document.save(str(path))
        finally:
            document.close()

        source = open_document(path)
        try:
            image = render_page_array(source.load_page(0))
        finally:
            source.close()

        assert max(image.shape[:2]) <= MAX_RENDER_DIMENSION

    def test_tiny_page_still_renders(self, workdir):
        document = pymupdf.open()
        try:
            document.new_page(width=20, height=20)
            path = workdir / "tiny.pdf"
            document.save(str(path))
        finally:
            document.close()

        analysis = analyze_document(path, expected_separator=SEP)
        assert analysis.error is None
        assert analysis.page_count == 1


class TestDocumentShapes:
    def test_separator_only_document(self, workdir, outdir):
        path = build_pdf(
            workdir / "seponly.pdf", lambda d: add_separator_page(d, SEP)
        )
        analysis = analyze_document(path, expected_separator=SEP)
        assert analysis.output_groups == ()

        result = export_document(analysis, outdir)
        assert result.skipped
        assert not list(outdir.glob("*.pdf"))

    def test_blank_only_document(self, workdir, outdir):
        path = build_pdf(
            workdir / "blankonly.pdf",
            lambda d: (add_blank_page(d), add_blank_page(d)),
        )
        analysis = analyze_document(
            path, mode=ProcessingMode.CLEAN_ONLY, remove_blanks=True
        )
        result = export_document(analysis, outdir)
        assert result.skipped
        assert not list(outdir.glob("*.pdf"))

    def test_single_page_document_with_separator_only_mode(self, workdir, outdir):
        path = build_pdf(workdir / "one.pdf", lambda d: add_text_page(d, "Only page"))
        analysis = analyze_document(path, mode=ProcessingMode.CLEAN_ONLY)
        result = export_document(analysis, outdir)
        assert result.succeeded
        assert result.outputs[0].page_count == 1

    def test_mixed_orientation_and_dark_pages(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "Portrait")
            add_dark_page(doc)
            add_text_page(doc, "Landscape", width=841.89, height=595.28)
            add_separator_page(doc, SEP)
            add_faint_text_page(doc)

        path = build_pdf(workdir / "mixed.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=True)

        assert analysis.blank_pages == (), "dark and faint pages must be kept"
        assert analysis.output_groups == ((0, 1, 2), (4,))

    def test_many_pages_analysis(self, workdir):
        """A longer document analyses without error (memory stays bounded)."""

        def build(doc):
            for index in range(40):
                if index % 10 == 9:
                    add_separator_page(doc, SEP)
                else:
                    add_text_page(doc, f"Page {index}")

        path = build_pdf(workdir / "long.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP)

        assert analysis.error is None
        assert analysis.page_count == 40
        # Separators land on pages 10, 20, 30 and 40. The last one is trailing,
        # so it closes the fourth group without opening a fifth.
        assert len(analysis.output_groups) == 4
        assert all(len(group) == 9 for group in analysis.output_groups)


class TestOutputFailures:
    def test_readonly_output_folder_fails_cleanly(self, workdir, tmp_path):
        if os.name == "nt":  # pragma: no cover - POSIX permission model
            pytest.skip("chmod-based read-only test is POSIX specific")
        if os.geteuid() == 0:  # pragma: no cover
            pytest.skip("root ignores directory permissions")

        path = build_pdf(
            workdir / "src.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            analysis = analyze_document(path, expected_separator=SEP)
            result = export_document(analysis, locked)
            assert result.error is not None
            assert not result.outputs
        finally:
            locked.chmod(stat.S_IRWXU)

    def test_disk_full_leaves_no_partial_output(self, workdir, outdir, monkeypatch):
        path = build_pdf(
            workdir / "src.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)

        def full_disk(self, *args, **kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(exporter_module.pymupdf.Document, "save", full_disk)
        result = export_document(analysis, outdir)

        assert result.error is not None
        assert not list(outdir.glob("*.pdf"))
        assert not list(outdir.glob(f"{TEMP_PREFIX}*"))

    def test_output_folder_disappears_midrun(self, workdir, tmp_path, monkeypatch):
        path = build_pdf(
            workdir / "src.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        target = tmp_path / "vanishing"
        target.mkdir()

        original_replace = exporter_module.os.replace
        state = {"n": 0}

        def flaky_replace(src, dst):
            state["n"] += 1
            if state["n"] == 2:
                raise OSError(2, "The system cannot find the path specified")
            return original_replace(src, dst)

        monkeypatch.setattr(exporter_module.os, "replace", flaky_replace)
        result = export_document(analysis, target)

        assert result.error is not None
        assert len(result.outputs) == 1, "the first document survives"
        assert not list(target.glob(f"{TEMP_PREFIX}*"))


class TestSourceIntegrity:
    def test_sources_unchanged_across_a_batch(self, workdir, outdir):
        paths = []
        for index in range(3):
            paths.append(
                build_pdf(
                    workdir / f"src{index}.pdf",
                    lambda d, i=index: (
                        add_text_page(d, f"Doc {i}"),
                        add_separator_page(d, SEP),
                        add_blank_page(d),
                        add_text_page(d, "tail"),
                    ),
                )
            )
        before = {p: digest(p) for p in paths}

        analyses = analyze_batch(paths, AnalysisSettings(expected_separator=SEP))
        export_batch(analyses, outdir)

        for path in paths:
            assert digest(path) == before[path], f"{path.name} was modified"

    def test_source_mtime_unchanged(self, workdir, outdir):
        path = build_pdf(
            workdir / "src.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        before = path.stat().st_mtime_ns
        analysis = analyze_document(path, expected_separator=SEP)
        export_document(analysis, outdir)
        assert path.stat().st_mtime_ns == before


class TestSeparatorSheetGeneration:
    @pytest.mark.parametrize(
        "value", ["EAGC-EDMS-00001", "PATCHT", "A", "Job Sep 42", "X" * 60]
    )
    def test_generated_sheet_is_detected(self, workdir, value):
        """Acceptance criterion 12: generated sheets must be detectable."""

        sheet = create_separator_pdf(value, workdir / "sheet.pdf")

        document = pymupdf.open()
        try:
            add_text_page(document, "Document one")
            with pymupdf.open(str(sheet)) as sheet_doc:
                document.insert_pdf(sheet_doc)
            add_text_page(document, "Document two")
            combined = workdir / "combined.pdf"
            document.save(str(combined))
        finally:
            document.close()

        analysis = analyze_document(combined, expected_separator=value)
        assert analysis.separator_pages == (1,), f"sheet for {value!r} was not detected"
        assert analysis.output_groups == ((0,), (2,))

    def test_generated_sheet_is_a4(self, workdir):
        sheet = create_separator_pdf(SEP, workdir / "sheet.pdf")
        with pymupdf.open(str(sheet)) as doc:
            rect = doc[0].rect
            assert rect.width == pytest.approx(595.276, abs=1)
            assert rect.height == pytest.approx(841.89, abs=1)

    def test_sheet_contains_heading_and_value(self, workdir):
        sheet = create_separator_pdf(SEP, workdir / "sheet.pdf")
        with pymupdf.open(str(sheet)) as doc:
            text = doc[0].get_text()
        assert "DOCUMENT SEPARATOR" in text
        assert SEP in text
        assert "removed" in text.lower()

    @pytest.mark.parametrize("value", ["", "   ", "x" * 200, "bad\x01char"])
    def test_invalid_values_rejected(self, workdir, value):
        with pytest.raises(SeparatorGenerationError):
            create_separator_pdf(value, workdir / "bad.pdf")

    def test_creates_parent_directory(self, workdir):
        target = workdir / "nested" / "deep" / "sheet.pdf"
        created = create_separator_pdf(SEP, target)
        assert created.exists()


class TestSensitivityBehaviour:
    def test_faint_content_survives_all_profiles(self, workdir, outdir):
        """Milestone 4: prefer keeping a blank page over deleting content."""

        path = build_pdf(
            workdir / "faint.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_faint_text_page(d)),
        )
        for sensitivity in BlankSensitivity:
            analysis = analyze_document(
                path,
                expected_separator=SEP,
                remove_blanks=True,
                blank_sensitivity=sensitivity,
            )
            assert analysis.blank_pages == (), f"{sensitivity} removed faint content"
            assert analysis.output_groups == ((0,), (2,))

    def test_aggressive_warns_when_blanks_found(self, workdir):
        from pdf_batch_separator.core.models import WarningCode

        path = build_pdf(
            workdir / "b.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_blank_page(d)),
        )
        analysis = analyze_document(
            path,
            expected_separator=SEP,
            remove_blanks=True,
            blank_sensitivity=BlankSensitivity.AGGRESSIVE,
        )
        assert analysis.has_warning(WarningCode.AGGRESSIVE_BLANKS)


class TestDuplicateAndUnicodeNames:
    def test_three_identically_named_sources(self, workdir, outdir):
        builder = lambda d: (
            add_text_page(d, "A"),
            add_separator_page(d, SEP),
            add_text_page(d, "B"),
        )
        paths = []
        for index in range(3):
            folder = workdir / f"box{index}"
            folder.mkdir()
            paths.append(build_pdf(folder / "scan.pdf", builder))

        analyses = analyze_batch(paths, AnalysisSettings(expected_separator=SEP))
        results = export_batch(analyses, outdir)

        written = sorted(p.name for p in outdir.glob("*.pdf"))
        assert len(written) == 6
        assert len(set(written)) == 6, "every output must have a unique name"
        assert all(r.succeeded for r in results)

    def test_unicode_and_emoji_source_name(self, workdir, outdir):
        path = build_pdf(
            workdir / "Zürich – été 日本語 ✓.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)
        assert result.succeeded
        assert len(result.outputs) == 2
