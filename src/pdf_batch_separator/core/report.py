"""Human-readable UTF-8 batch report (PRD section 5.1).

The report deliberately contains no PDF page content and no barcode image
data: only file names, page numbers, counts and status messages.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import (
    BatchSummary,
    BlankSensitivity,
    DocumentAnalysis,
    ProcessingMode,
)

REPORT_PREFIX = "PDF Batch Separator report"


def report_filename(when: datetime | None = None) -> str:
    """``PDF Batch Separator report YYYY-MM-DD HHmmss.txt``."""

    when = when or datetime.now()
    return f"{REPORT_PREFIX} {when:%Y-%m-%d %H%M%S}.txt"


def _mode_label(mode: ProcessingMode) -> str:
    return {
        ProcessingMode.SPLIT: "Split by separator",
        ProcessingMode.CLEAN_ONLY: "Remove blank pages only",
    }[mode]


def _page_list(numbers: tuple[int, ...], limit: int = 40) -> str:
    """Format zero-based indexes as a one-based, comma-separated list."""

    if not numbers:
        return "none"
    shown = [str(n + 1) for n in numbers[:limit]]
    if len(numbers) > limit:
        shown.append(f"and {len(numbers) - limit} more")
    return ", ".join(shown)


def build_report(
    summary: BatchSummary,
    analyses: dict[Path, DocumentAnalysis] | None = None,
    *,
    mode: ProcessingMode = ProcessingMode.SPLIT,
    separator: str | None = None,
    remove_blanks: bool = True,
    sensitivity: BlankSensitivity = BlankSensitivity.BALANCED,
    app_version: str = "",
) -> str:
    """Render the batch report as plain UTF-8 text."""

    analyses = analyses or {}
    lines: list[str] = []
    add = lines.append

    add("PDF Batch Separator \u2014 batch report")
    add("=" * 60)
    add("")
    add(f"Started:          {summary.started_at or 'n/a'}")
    add(f"Finished:         {summary.finished_at or 'n/a'}")
    if app_version:
        add(f"Application:      version {app_version}")
    add(f"Mode:             {_mode_label(mode)}")
    if mode is ProcessingMode.SPLIT:
        add(f"Separator value:  {separator or '(none)'}")
    add(f"Remove blanks:    {'yes' if remove_blanks else 'no'}")
    if remove_blanks:
        add(f"Blank sensitivity: {sensitivity.label}")
    add(f"Output folder:    {summary.output_folder}")
    if summary.cancelled:
        add("Run was CANCELLED before all files were processed.")
    add("")

    add("Summary")
    add("-" * 60)
    add(f"PDFs processed:        {summary.documents_processed}")
    add(f"Documents created:     {summary.outputs_created}")
    add(f"Separator pages removed: {summary.separators_removed}")
    add(f"Blank pages removed:   {summary.blanks_removed}")
    add(f"Files skipped:         {len(summary.skipped)}")
    add(f"Files failed:          {len(summary.failures)}")
    add(f"Warnings:              {summary.warning_count}")
    add("")

    add("Details")
    add("-" * 60)
    for result in summary.results:
        source = Path(result.source_path)
        add(f"\n{source.name}")
        add(f"  Folder: {source.parent}")

        analysis = analyses.get(source)
        if analysis and not analysis.failed:
            add(f"  Pages: {analysis.page_count}")
            if mode is ProcessingMode.SPLIT:
                add(f"  Separator pages: {_page_list(analysis.separator_pages)}")
            add(f"  Blank pages detected: {_page_list(analysis.blank_pages)}")

        if result.error:
            add(f"  RESULT: FAILED \u2014 {result.error}")
        elif result.skipped:
            add(f"  RESULT: SKIPPED \u2014 {result.skip_reason}")
        else:
            add(f"  RESULT: OK \u2014 {len(result.outputs)} document(s) written")
            add(f"  Separator pages removed: {result.separators_removed}")
            add(f"  Blank pages removed: {result.blanks_removed}")
            for output in result.outputs:
                add(f"    - {output.path.name}  ({output.page_count} page(s))")

        for warning in result.warnings:
            add(f"  WARNING: {warning}")

    add("")
    add("-" * 60)
    add("Your PDFs are processed only on this PC.")
    add("No document content, barcode data or file contents are included in this report.")

    return "\n".join(lines) + "\n"


def write_report(
    text: str, output_folder: Path, *, when: datetime | None = None
) -> Path:
    """Write ``text`` as UTF-8 into ``output_folder`` and return the path."""

    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / report_filename(when)
    counter = 2
    while path.exists():
        stem = report_filename(when)[:-4]
        path = output_folder / f"{stem} ({counter}).txt"
        counter += 1
    path.write_text(text, encoding="utf-8")
    return path


__all__ = ["build_report", "report_filename", "write_report"]
