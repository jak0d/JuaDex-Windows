"""Export safety: atomicity, collisions, naming, source preservation (FR-5)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

try:
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore[no-redef]

from fixtures.builders import add_blank_page, add_separator_page, add_text_page, build_pdf
from pdf_batch_separator.core import exporter
from pdf_batch_separator.core.analyzer import analyze_document, open_document
from pdf_batch_separator.core.exporter import (
    TEMP_PREFIX,
    cleanup_stale_temp_files,
    export_document,
    write_group,
)
from pdf_batch_separator.core.models import PageOverrides, ProcessingMode
from pdf_batch_separator.core.naming import (
    cleaned_name,
    is_within,
    sanitize_stem,
    split_name,
    unique_path,
)

SEP = "EAGC-EDMS-00001"


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def three_part_pdf(workdir):
    def build(doc):
        add_text_page(doc, "Part one")
        add_separator_page(doc, SEP)
        add_text_page(doc, "Part two")
        add_separator_page(doc, SEP)
        add_text_page(doc, "Part three")

    return build_pdf(workdir / "batch.pdf", build)


class TestNaming:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("simple", "simple"),
            ("with/slash", "slash"),   # path components are stripped, not escaped
            ("back\\slash", "slash"),
            ("colon:name", "colon_name"),
            ("star*name", "star_name"),
            ("trailing dots...", "trailing dots"),
            ("trailing space   ", "trailing space"),
            ("  leading", "leading"),
            ("", "document"),
            ("...", "document"),
            ("../../etc/passwd", "passwd"),
            ("a\x00b", "a_b"),
        ],
    )
    def test_sanitize(self, raw, expected):
        assert sanitize_stem(raw) == expected

    @pytest.mark.parametrize("name", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"])
    def test_reserved_names_are_prefixed(self, name):
        result = sanitize_stem(name)
        assert result != name
        assert result.split(".")[0].upper() not in {
            "CON", "PRN", "AUX", "NUL", "COM1", "LPT9",
        }

    def test_reserved_name_with_extension(self):
        assert sanitize_stem("CON.pdf").upper() != "CON.PDF"

    def test_unicode_preserved(self):
        assert sanitize_stem("Rapport été Zürich 日本語") == "Rapport été Zürich 日本語"

    def test_long_name_truncated(self):
        assert len(sanitize_stem("x" * 400)) <= 120

    def test_split_naming_three_digits(self):
        assert split_name("Scan", 1) == "Scan - 001.pdf"
        assert split_name("Scan", 42) == "Scan - 042.pdf"

    def test_split_naming_widens_beyond_999(self):
        assert split_name("Scan", 1000, 1000) == "Scan - 1000.pdf"

    def test_cleaned_naming(self):
        assert cleaned_name("Scan") == "Scan - cleaned.pdf"

    def test_is_within(self, tmp_path):
        inner = tmp_path / "a" / "b"
        inner.mkdir(parents=True)
        assert is_within(inner, tmp_path)
        assert is_within(tmp_path, tmp_path)
        assert not is_within(tmp_path, inner)


class TestUniquePath:
    def test_returns_plain_name_when_free(self, outdir):
        assert unique_path(outdir, "a.pdf").name == "a.pdf"

    def test_appends_counter_on_collision(self, outdir):
        (outdir / "a.pdf").write_bytes(b"x")
        assert unique_path(outdir, "a.pdf").name == "a (2).pdf"

    def test_counter_increments(self, outdir):
        (outdir / "a.pdf").write_bytes(b"x")
        (outdir / "a (2).pdf").write_bytes(b"x")
        (outdir / "a (3).pdf").write_bytes(b"x")
        assert unique_path(outdir, "a.pdf").name == "a (4).pdf"

    def test_reserved_names_avoided(self, outdir):
        reserved = {outdir / "a.pdf"}
        assert unique_path(outdir, "a.pdf", reserved=reserved).name == "a (2).pdf"


class TestWriteGroup:
    def test_writes_expected_pages(self, three_part_pdf, outdir):
        source = open_document(three_part_pdf)
        try:
            result = write_group(source, [0, 2], outdir / "out.pdf")
        finally:
            source.close()

        assert result.path.exists()
        assert result.page_count == 2
        with pymupdf.open(str(result.path)) as doc:
            assert doc.page_count == 2

    def test_never_overwrites(self, three_part_pdf, outdir):
        (outdir / "out.pdf").write_bytes(b"original data")
        source = open_document(three_part_pdf)
        try:
            result = write_group(source, [0], outdir / "out.pdf")
        finally:
            source.close()

        assert result.path.name == "out (2).pdf"
        assert (outdir / "out.pdf").read_bytes() == b"original data"

    def test_no_temp_files_remain(self, three_part_pdf, outdir):
        source = open_document(three_part_pdf)
        try:
            write_group(source, [0], outdir / "out.pdf")
        finally:
            source.close()
        assert not list(outdir.glob(f"{TEMP_PREFIX}*"))

    def test_temp_removed_when_validation_fails(self, three_part_pdf, outdir, monkeypatch):
        real_open = pymupdf.open

        def fake_open(path=None, *args, **kwargs):
            if path is None:  # pymupdf.open() -> new empty document
                return real_open()
            document = real_open(path, *args, **kwargs)
            if str(path).startswith(str(outdir)):
                class Wrapper:
                    page_count = 99  # force a validation mismatch

                    def close(self_inner):
                        document.close()

                return Wrapper()
            return document

        monkeypatch.setattr(exporter.pymupdf, "open", fake_open)
        source = open_document(three_part_pdf)
        try:
            with pytest.raises(OSError, match="Validation failed"):
                write_group(source, [0], outdir / "out.pdf")
        finally:
            source.close()

        assert not list(outdir.glob(f"{TEMP_PREFIX}*")), "temp file must be cleaned up"
        assert not (outdir / "out.pdf").exists(), "no partial output may be published"

    def test_temp_removed_when_save_fails(self, three_part_pdf, outdir, monkeypatch):
        def boom(self, *args, **kwargs):
            raise OSError("No space left on device")

        monkeypatch.setattr(exporter.pymupdf.Document, "save", boom)
        source = open_document(three_part_pdf)
        try:
            with pytest.raises(OSError, match="No space left"):
                write_group(source, [0], outdir / "out.pdf")
        finally:
            source.close()

        assert not list(outdir.glob(f"{TEMP_PREFIX}*"))
        assert not (outdir / "out.pdf").exists()

    def test_temp_name_is_unpredictable(self, outdir):
        names = {exporter._temp_path(outdir).name for _ in range(20)}
        assert len(names) == 20
        assert all(n.startswith(TEMP_PREFIX) for n in names)


class TestExportDocument:
    def test_split_export(self, three_part_pdf, outdir):
        analysis = analyze_document(
            three_part_pdf, expected_separator=SEP, remove_blanks=True
        )
        result = export_document(analysis, outdir)

        assert result.succeeded
        assert len(result.outputs) == 3
        assert result.separators_removed == 2
        names = [o.path.name for o in result.outputs]
        assert names == ["batch - 001.pdf", "batch - 002.pdf", "batch - 003.pdf"]

    def test_source_is_unchanged(self, three_part_pdf, outdir):
        before = digest(three_part_pdf)
        analysis = analyze_document(three_part_pdf, expected_separator=SEP)
        export_document(analysis, outdir)
        assert digest(three_part_pdf) == before, "source PDF must be byte-identical"

    def test_missing_separator_is_skipped_not_split(self, workdir, outdir):
        path = build_pdf(
            workdir / "nomarker.pdf",
            lambda d: (add_text_page(d, "A"), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP)
        result = export_document(analysis, outdir)

        assert result.skipped
        assert not result.outputs, "must not emit a misleading one-part split"
        assert "No separator" in (result.skip_reason or "")

    def test_missing_separator_with_explicit_opt_in(self, workdir, outdir):
        path = build_pdf(
            workdir / "nomarker.pdf",
            lambda d: (add_text_page(d, "A"), add_blank_page(d), add_text_page(d, "B")),
        )
        analysis = analyze_document(path, expected_separator=SEP, remove_blanks=True)
        result = export_document(analysis, outdir, allow_unsplit_copy=True)

        assert result.succeeded
        assert [o.path.name for o in result.outputs] == ["nomarker - cleaned.pdf"]
        assert result.blanks_removed == 1

    def test_clean_only_mode(self, workdir, outdir):
        path = build_pdf(
            workdir / "scan.pdf",
            lambda d: (
                add_text_page(d, "A"),
                add_blank_page(d),
                add_text_page(d, "B"),
                add_blank_page(d),
            ),
        )
        analysis = analyze_document(path, mode=ProcessingMode.CLEAN_ONLY, remove_blanks=True)
        result = export_document(analysis, outdir)

        assert result.succeeded
        assert [o.path.name for o in result.outputs] == ["scan - cleaned.pdf"]
        assert result.blanks_removed == 2
        with pymupdf.open(str(result.outputs[0].path)) as doc:
            assert doc.page_count == 2

    def test_all_pages_removed_is_blocked(self, workdir, outdir):
        path = build_pdf(
            workdir / "empty.pdf", lambda d: (add_blank_page(d), add_blank_page(d))
        )
        analysis = analyze_document(path, mode=ProcessingMode.CLEAN_ONLY, remove_blanks=True)
        result = export_document(analysis, outdir)

        assert result.skipped
        assert not result.outputs
        assert not list(outdir.glob("*.pdf"))

    def test_overrides_change_the_output(self, three_part_pdf, outdir):
        analysis = analyze_document(three_part_pdf, expected_separator=SEP)
        overrides = PageOverrides(force_not_separator=frozenset({1}))
        result = export_document(analysis, outdir, overrides=overrides)

        assert result.succeeded
        assert len(result.outputs) == 2, "one separator neutralised -> two parts"
        assert result.separators_removed == 1

    def test_failed_analysis_becomes_failed_export(self, outdir):
        from pdf_batch_separator.core.models import DocumentAnalysis

        analysis = DocumentAnalysis(
            source_path=Path("missing.pdf"), page_count=0, error="broken"
        )
        result = export_document(analysis, outdir)
        assert result.error == "broken"

    def test_collision_across_two_sources(self, workdir, outdir):
        """Two same-named sources in different folders must not overwrite."""

        first_dir, second_dir = workdir / "a", workdir / "b"
        first_dir.mkdir(); second_dir.mkdir()
        builder = lambda d: (add_text_page(d, "A"), add_separator_page(d, SEP), add_text_page(d, "B"))
        paths = [build_pdf(first_dir / "scan.pdf", builder), build_pdf(second_dir / "scan.pdf", builder)]

        reserved: set[Path] = set()
        names: list[str] = []
        for path in paths:
            analysis = analyze_document(path, expected_separator=SEP)
            result = export_document(analysis, outdir, reserved=reserved)
            names.extend(o.path.name for o in result.outputs)

        assert len(names) == len(set(names)) == 4
        assert len(list(outdir.glob("*.pdf"))) == 4

    def test_cancellation_stops_writing(self, three_part_pdf, outdir):
        analysis = analyze_document(three_part_pdf, expected_separator=SEP)
        state = {"n": 0}

        def should_cancel():
            state["n"] += 1
            return state["n"] > 2  # allow the first output, then cancel

        result = export_document(analysis, outdir, should_cancel=should_cancel)
        assert result.skipped
        assert len(result.outputs) < 3
        for output in result.outputs:
            assert output.path.exists(), "already-written outputs stay intact"
        assert not list(outdir.glob(f"{TEMP_PREFIX}*"))


class TestTempCleanup:
    def test_removes_only_our_files(self, outdir):
        ours = outdir / f"{TEMP_PREFIX}abc123.tmp"
        ours.write_bytes(b"x")
        theirs = outdir / "important.tmp"
        theirs.write_bytes(b"x")
        other = outdir / "document.pdf"
        other.write_bytes(b"x")

        removed = cleanup_stale_temp_files(outdir)

        assert removed == 1
        assert not ours.exists()
        assert theirs.exists() and other.exists()

    def test_missing_directory_is_safe(self, tmp_path):
        assert cleanup_stale_temp_files(tmp_path / "nope") == 0

    def test_age_filter(self, outdir):
        recent = outdir / f"{TEMP_PREFIX}recent.tmp"
        recent.write_bytes(b"x")
        assert cleanup_stale_temp_files(outdir, max_age_seconds=3600) == 0
        assert recent.exists()
