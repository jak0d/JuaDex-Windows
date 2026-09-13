"""End-to-end analyse -> export tests over generated fixtures (PRD section 12)."""

from __future__ import annotations

import hashlib
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
    add_other_barcode_page,
    add_separator_page,
    add_text_page,
    build_pdf,
    degrade_pdf_like_scan,
)
from pdf_batch_separator.core.analyzer import analyze_document, regroup
from pdf_batch_separator.core.batch import (
    AnalysisSettings,
    CancellationToken,
    analyze_batch,
    export_batch,
    recommended_workers,
)
from pdf_batch_separator.core.exporter import export_document
from pdf_batch_separator.core.models import (
    BlankSensitivity,
    PageOverrides,
    ProcessingMode,
    WarningCode,
)
from pdf_batch_separator.core.report import build_report, write_report
from pdf_batch_separator.core.separator_pdf import create_separator_pdf
from pdf_batch_separator.core.models import BatchSummary, DocumentExportResult

SEP = "EAGC-EDMS-00001"


def page_texts(path: Path) -> list[str]:
    with pymupdf.open(str(path)) as doc:
        return [page.get_text().strip() for page in doc]


class TestSplitPipeline:
    def test_three_documents(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "Alpha contract")
            add_text_page(doc, "Alpha page two")
            add_separator_page(doc, SEP)
            add_text_page(doc, "Beta invoice")
            add_separator_page(doc, SEP)
            add_text_page(doc, "Gamma memo")

        path = build_pdf(workdir / "batch.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=True)

        assert analysis.error is None
        assert analysis.separator_pages == (2, 4)
        assert analysis.output_groups == ((0, 1), (3,), (5,))

        result = export_document(analysis, outdir)
        assert result.succeeded and len(result.outputs) == 3

        counts = [o.page_count for o in result.outputs]
        assert counts == [2, 1, 1]
        assert "Alpha contract" in page_texts(result.outputs[0].path)[0]
        assert "Beta invoice" in page_texts(result.outputs[1].path)[0]
        assert "Gamma memo" in page_texts(result.outputs[2].path)[0]

    def test_separator_content_never_leaks_into_output(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "Real content")
            add_separator_page(doc, SEP)
            add_text_page(doc, "More content")

        path = build_pdf(workdir / "b.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)

        for output in result.outputs:
            for text in page_texts(output.path):
                assert "DOCUMENT SEPARATOR" not in text
                assert SEP not in text

    def test_split_with_blank_removal(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "One")
            add_blank_page(doc)
            add_separator_page(doc, SEP)
            add_text_page(doc, "Two")
            add_blank_page(doc)

        path = build_pdf(workdir / "b.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=True)
        assert analysis.blank_pages == (1, 4)

        result = export_document(analysis, outdir)
        assert [o.page_count for o in result.outputs] == [1, 1]
        assert result.blanks_removed == 2

    def test_split_without_blank_removal_keeps_blanks(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "One")
            add_blank_page(doc)
            add_separator_page(doc, SEP)
            add_text_page(doc, "Two")

        path = build_pdf(workdir / "b.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=False)
        result = export_document(analysis, outdir)
        assert [o.page_count for o in result.outputs] == [2, 1]
        assert result.blanks_removed == 0

    def test_page_dimensions_and_rotation_preserved(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "Portrait")
            add_text_page(doc, "Landscape", width=841.89, height=595.28)
            add_text_page(doc, "Rotated", rotation=90)
            add_separator_page(doc, SEP)
            add_text_page(doc, "Last")

        path = build_pdf(workdir / "mixed.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)

        with pymupdf.open(str(result.outputs[0].path)) as doc:
            assert doc.page_count == 3
            assert doc[0].rect.width < doc[0].rect.height
            assert doc[1].rect.width > doc[1].rect.height
            assert doc[2].rotation == 90

    def test_unrelated_barcode_reported_not_split(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "One")
            add_other_barcode_page(doc, "INVOICE-9931")
            add_text_page(doc, "Two")

        path = build_pdf(workdir / "other.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP)

        assert analysis.separator_pages == ()
        assert analysis.has_warning(WarningCode.NO_SEPARATOR_FOUND)
        assert analysis.has_warning(WarningCode.OTHER_BARCODE_DETECTED)
        values = {b.value for b in analysis.other_barcodes}
        assert "INVOICE-9931" in values

        result = export_document(analysis, outdir)
        assert result.skipped, "a wrong marker must never be treated as a split"

    def test_correct_plus_unrelated_barcodes(self, workdir, outdir):
        def build(doc):
            add_text_page(doc, "One")
            add_other_barcode_page(doc, "ORDER-4471")
            add_separator_page(doc, SEP)
            add_text_page(doc, "Two")

        path = build_pdf(workdir / "mixed_codes.pdf", build)
        analysis = analyze_document(path, expected_separator=SEP)

        assert analysis.separator_pages == (2,)
        assert analysis.output_groups == ((0, 1), (3,))
        assert analysis.has_warning(WarningCode.OTHER_BARCODE_DETECTED)

    def test_custom_separator_with_whitespace_and_case(self, workdir, outdir):
        value = "Job Sep 42"
        path = build_pdf(
            workdir / "custom.pdf",
            lambda d: (
                add_text_page(d, "A"),
                add_separator_page(d, value),
                add_text_page(d, "B"),
            ),
        )
        analysis = analyze_document(path, expected_separator="  job sep 42  ")
        assert analysis.separator_pages == (1,)
        assert analysis.output_groups == ((0,), (2,))

    def test_patcht_preset(self, workdir):
        path = build_pdf(
            workdir / "patch.pdf",
            lambda d: (
                add_text_page(d, "A"),
                add_separator_page(d, "PATCHT"),
                add_text_page(d, "B"),
            ),
        )
        analysis = analyze_document(path, expected_separator="PATCHT")
        assert analysis.separator_pages == (1,)


class TestDegradedScans:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"rotation": 90},
            {"rotation": 180},
            {"rotation": 270},
            {"scale": 0.45},
            {"inverted": True},
            {"contrast": 0.45},
            {"scale": 0.6, "rotation": 90},
        ],
        ids=["plain", "rot90", "rot180", "rot270", "small", "inverted", "faded", "small_rot"],
    )
    def test_separator_detected_under_degradation(self, workdir, kwargs):
        path = build_pdf(
            workdir / "deg.pdf",
            lambda d: (
                add_text_page(d, "A"),
                add_separator_page(d, SEP, **kwargs),
                add_text_page(d, "B"),
            ),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        assert analysis.separator_pages == (1,), f"missed separator for {kwargs}"

    def test_generated_sheet_survives_print_and_scan(self, workdir):
        """PRD: the generated separator must decode after a scan-style pass."""

        sheet = create_separator_pdf(SEP, workdir / "sheet.pdf")
        document = pymupdf.open()
        try:
            add_text_page(document, "Document one")
            document.insert_pdf(pymupdf.open(str(sheet)))
            add_text_page(document, "Document two")
            combined = workdir / "combined.pdf"
            document.save(str(combined))
        finally:
            document.close()

        degraded = degrade_pdf_like_scan(combined, workdir / "degraded.pdf")
        analysis = analyze_document(degraded, expected_separator=SEP)

        assert analysis.separator_pages == (1,)
        assert analysis.output_groups == ((0,), (2,))


class TestFailureIsolation:
    def test_corrupt_pdf_fails_alone(self, workdir, outdir):
        good = build_pdf(
            workdir / "good.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        corrupt = workdir / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.7\nthis is not a real pdf\n")

        settings = AnalysisSettings(expected_separator=SEP)
        analyses = analyze_batch([good, corrupt], settings)

        assert analyses[0].error is None
        assert analyses[1].error is not None

        results = export_batch(analyses, outdir)
        assert results[0].succeeded
        assert results[1].error is not None
        assert len(list(outdir.glob("*.pdf"))) == 2

    def test_encrypted_pdf_rejected_clearly(self, workdir):
        document = pymupdf.open()
        try:
            add_text_page(document, "Secret")
            path = workdir / "locked.pdf"
            document.save(
                str(path),
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="owner",
                user_pw="user",
            )
        finally:
            document.close()

        analysis = analyze_document(path, expected_separator=SEP)
        assert analysis.error is not None
        assert "password" in analysis.error.lower()

    def test_zero_page_pdf(self, workdir):
        # PyMuPDF refuses to save a page-less document, so craft the minimal
        # valid zero-page PDF by hand.
        path = workdir / "empty.pdf"
        path.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
            b"trailer<</Root 1 0 R>>\n"
        )

        analysis = analyze_document(path, expected_separator=SEP)
        assert analysis.error is not None
        assert "no pages" in analysis.error.lower()

    def test_missing_file(self, workdir):
        analysis = analyze_document(workdir / "nope.pdf", expected_separator=SEP)
        assert analysis.error is not None

    def test_batch_order_preserved(self, workdir, outdir):
        paths = []
        for index in range(6):
            paths.append(
                build_pdf(
                    workdir / f"file{index}.pdf",
                    lambda d, i=index: (
                        add_text_page(d, f"Doc {i}"),
                        add_separator_page(d, SEP),
                        add_text_page(d, f"Doc {i} part two"),
                    ),
                )
            )
        analyses = analyze_batch(paths, AnalysisSettings(expected_separator=SEP))
        assert [a.source_path for a in analyses] == paths

    def test_output_folder_inside_input_tree(self, workdir):
        """Recursive input with the output folder nested inside it."""

        nested_out = workdir / "Processed"
        nested_out.mkdir()
        path = build_pdf(
            workdir / "scan.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, nested_out)

        assert result.succeeded
        from pdf_batch_separator.core.naming import is_within

        for output in result.outputs:
            assert is_within(output.path, nested_out)


class TestCancellation:
    def test_cancel_stops_analysis(self, workdir):
        paths = [
            build_pdf(
                workdir / f"c{i}.pdf",
                lambda d, i=i: (add_text_page(d, f"Doc {i}"), add_separator_page(d, SEP)),
            )
            for i in range(4)
        ]
        token = CancellationToken()
        token.cancel()
        analyses = analyze_batch(paths, AnalysisSettings(expected_separator=SEP), token=token)
        assert all(a.error for a in analyses)

    def test_cancel_stops_export_but_keeps_finished_files(self, workdir, outdir):
        paths = [
            build_pdf(
                workdir / f"e{i}.pdf",
                lambda d, i=i: (
                    add_text_page(d, f"Doc {i}"),
                    add_separator_page(d, SEP),
                    add_text_page(d, "tail"),
                ),
            )
            for i in range(3)
        ]
        analyses = analyze_batch(paths, AnalysisSettings(expected_separator=SEP))

        token = CancellationToken()
        seen: list[int] = []

        def on_result(index, result):
            seen.append(index)
            token.cancel()  # cancel after the first file completes

        results = export_batch(analyses, outdir, token=token, on_result=on_result)

        assert results[0].succeeded
        assert all(r.skipped for r in results[1:])
        for output in results[0].outputs:
            assert output.path.exists()

    def test_no_temp_files_after_cancel(self, workdir, outdir):
        from pdf_batch_separator.core.exporter import TEMP_PREFIX

        paths = [
            build_pdf(
                workdir / f"t{i}.pdf",
                lambda d, i=i: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
            )
            for i in range(3)
        ]
        analyses = analyze_batch(paths, AnalysisSettings(expected_separator=SEP))
        token = CancellationToken()
        token.cancel()
        export_batch(analyses, outdir, token=token)
        assert not list(outdir.glob(f"{TEMP_PREFIX}*"))


class TestRegroup:
    def test_override_without_reanalysis(self, workdir):
        path = build_pdf(
            workdir / "r.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        assert analysis.output_groups == ((0,), (2,))

        updated = regroup(analysis, overrides=PageOverrides(force_not_separator=frozenset({1})))
        assert updated.output_groups == ((0, 1, 2),)
        assert updated.pages == analysis.pages, "page measurements are reused"

    def test_toggle_blank_removal_without_reanalysis(self, workdir):
        path = build_pdf(
            workdir / "rb.pdf",
            lambda d: (add_text_page(d, "A"), add_blank_page(d), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=True)
        assert analysis.output_groups == ((0,), (3,))

        updated = regroup(analysis, remove_blanks=False)
        assert updated.output_groups == ((0, 1), (3,))


class TestUnicodeAndPaths:
    def test_unicode_filenames(self, workdir, outdir):
        path = build_pdf(
            workdir / "Rapport été Zürich 日本語.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)

        assert result.succeeded
        assert "Rapport été Zürich 日本語" in result.outputs[0].path.name

    def test_folder_with_spaces_and_accents(self, tmp_path):
        source_dir = tmp_path / "Mes Documents Numérisés"
        out_dir = tmp_path / "Sortie Traitée"
        source_dir.mkdir(); out_dir.mkdir()
        path = build_pdf(
            source_dir / "scan.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        result = export_document(analyze_document(path, expected_separator=SEP), out_dir)
        assert result.succeeded and len(result.outputs) == 2

    def test_very_long_filename_is_truncated(self, workdir, outdir):
        long_stem = "L" * 200
        path = build_pdf(
            workdir / f"{long_stem}.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        result = export_document(analyze_document(path, expected_separator=SEP), outdir)
        assert result.succeeded
        for output in result.outputs:
            assert len(output.path.name) < 160


class TestReport:
    def test_report_contents(self, workdir, outdir):
        path = build_pdf(
            workdir / "report_src.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)
        summary = BatchSummary(output_folder=outdir, results=(result,))

        text = build_report(
            summary,
            {Path(analysis.source_path): analysis},
            separator=SEP,
            app_version="1.0.0",
        )

        assert "report_src.pdf" in text
        assert str(outdir) in text
        assert "Documents created:     2" in text
        assert "only on this PC" in text

        written = write_report(text, outdir)
        assert written.exists()
        assert written.read_text(encoding="utf-8") == text
        assert written.name.startswith("JuaDex PDFs Separator report")

    def test_report_has_no_page_content(self, workdir, outdir):
        secret = "CONFIDENTIAL-SALARY-DATA-9931"
        path = build_pdf(
            workdir / "secret.pdf",
            lambda d: (add_text_page(d, secret), add_separator_page(d, SEP), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)
        text = build_report(
            BatchSummary(output_folder=outdir, results=(result,)),
            {Path(analysis.source_path): analysis},
            separator=SEP,
        )
        assert secret not in text, "report must never contain PDF page content"

    def test_unreadable_file_reported_as_failed_not_skipped(self, workdir, outdir):
        """A file that could not be opened must not be blamed on the user.

        The batch report is an audit record.  Recording "skipped by the user"
        for a document that actually failed to open would misrepresent what
        happened, so the real error has to survive into the report.
        """
        broken = workdir / "corrupt.pdf"
        broken.write_bytes(b"%PDF-1.4 this is not a real pdf")
        good = build_pdf(
            workdir / "fine.pdf",
            lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B")),
        )

        settings = AnalysisSettings(expected_separator=SEP)
        analyses = analyze_batch([broken, good], settings)
        # The UI marks unreadable rows as blocked, which forwards them as "skip".
        results = export_batch(analyses, outdir, skip=[broken])
        summary = BatchSummary(output_folder=outdir, results=tuple(results))

        failed = {Path(r.source_path).name for r in summary.failures}
        skipped = {Path(r.source_path).name for r in summary.skipped}
        assert failed == {"corrupt.pdf"}
        assert skipped == set()

        text = build_report(
            summary,
            {Path(a.source_path): a for a in analyses},
            separator=SEP,
        )
        corrupt_block = text.split("corrupt.pdf", 1)[1].split("RESULT:", 1)[1]
        assert corrupt_block.lstrip().startswith("FAILED")
        assert "Skipped by the user" not in text
        assert "Files failed:          1" in text

    def test_report_header_fields_are_readable(self, workdir, outdir):
        path = build_pdf(workdir / "hdr.pdf", lambda d: add_text_page(d, "A"))
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=True)
        summary = BatchSummary(
            output_folder=outdir, results=(DocumentExportResult(source_path=path),)
        )
        text = build_report(
            summary,
            {Path(analysis.source_path): analysis},
            separator=SEP,
            remove_blanks=True,
            sensitivity=BlankSensitivity.BALANCED,
        )
        assert "Blank sensitivity: Balanced" in text


class TestWorkerSizing:
    def test_worker_count_is_bounded(self):
        assert 1 <= recommended_workers() <= 4

    def test_worker_count_never_exceeds_file_count(self):
        assert recommended_workers(1) == 1
        assert recommended_workers(2) <= 2
