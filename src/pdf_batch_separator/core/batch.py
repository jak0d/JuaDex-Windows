"""Bounded, cancellable batch execution (PRD FR-6), independent of Qt.

Work runs in a thread pool whose size is derived from CPU and memory, capped
conservatively.  Results are always yielded in *input* order even though the
underlying work completes out of order, and a failure in one PDF never stops
the rest of the batch.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .analyzer import analyze_document
from .exporter import export_document
from .models import (
    BlankSensitivity,
    DocumentAnalysis,
    DocumentExportResult,
    PageOverrides,
    ProcessingMode,
)

logger = logging.getLogger(__name__)

MAX_WORKERS_CAP = 4
"""Conservative ceiling from the PRD: never more than four files at once."""

#: Rough peak footprint of one 300-DPI grayscale A4 render plus retry copies.
_MEMORY_PER_WORKER_MB = 320


def recommended_workers(file_count: int | None = None) -> int:
    """Pick a worker count from CPU count, available memory and batch size."""

    cpu = os.cpu_count() or 2
    workers = max(1, min(MAX_WORKERS_CAP, cpu - 1 if cpu > 2 else 1))

    # Trim further when the machine is short on memory.
    try:
        import shutil  # noqa: F401  (kept local; psutil is not a dependency)

        if hasattr(os, "sysconf") and "SC_AVPHYS_PAGES" in os.sysconf_names:
            available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            budget = int(available * 0.5) // (_MEMORY_PER_WORKER_MB * 1024 * 1024)
            workers = max(1, min(workers, budget or 1))
    except (OSError, ValueError, AttributeError):  # pragma: no cover - Windows
        pass

    if file_count:
        workers = max(1, min(workers, file_count))
    return workers


class CancellationToken:
    """Thread-safe cancellation flag shared by every job in a run."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def __call__(self) -> bool:  # allows passing the token as should_cancel
        return self._event.is_set()


@dataclass(frozen=True)
class AnalysisSettings:
    """Everything that influences an analysis result."""

    mode: ProcessingMode = ProcessingMode.SPLIT
    expected_separator: str | None = None
    remove_blanks: bool = True
    blank_sensitivity: BlankSensitivity = BlankSensitivity.BALANCED

    def signature(self) -> tuple:
        """Key used to decide whether a cached analysis is still valid."""

        return (
            self.mode,
            (self.expected_separator or "").strip().upper(),
            self.remove_blanks,
            self.blank_sensitivity,
        )


def analyze_batch(
    paths: Sequence[Path],
    settings: AnalysisSettings,
    *,
    token: CancellationToken | None = None,
    on_start: Callable[[int, Path], None] | None = None,
    on_page: Callable[[int, int, int], None] | None = None,
    on_result: Callable[[int, DocumentAnalysis], None] | None = None,
    max_workers: int | None = None,
) -> list[DocumentAnalysis]:
    """Analyse many PDFs concurrently, returning results in input order.

    Callbacks receive the *input index* so a UI can update the right row.
    They are invoked from worker threads; a Qt caller must marshal to the GUI
    thread (``workers.py`` does this with signals).
    """

    token = token or CancellationToken()
    paths = list(paths)
    if not paths:
        return []

    workers = max_workers or recommended_workers(len(paths))
    results: list[DocumentAnalysis | None] = [None] * len(paths)

    def job(index: int, path: Path) -> DocumentAnalysis:
        if token.cancelled:
            return DocumentAnalysis(
                source_path=path, page_count=0, error="Analysis was cancelled."
            )
        if on_start:
            on_start(index, path)

        def page_progress(done: int, total: int) -> None:
            if on_page:
                on_page(index, done, total)

        return analyze_document(
            path,
            mode=settings.mode,
            expected_separator=settings.expected_separator,
            remove_blanks=settings.remove_blanks,
            blank_sensitivity=settings.blank_sensitivity,
            progress=page_progress,
            should_cancel=token,
        )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pbs-analyze") as pool:
        futures: dict[Future, int] = {
            pool.submit(job, index, path): index for index, path in enumerate(paths)
        }
        # Surface each finished file as soon as it is ready. The returned list
        # still preserves input order, but a short file no longer waits behind
        # a slow first file before the UI can show its status.
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - isolate a crashed worker
                logger.exception("Analysis worker crashed for %s", paths[index])
                results[index] = DocumentAnalysis(
                    source_path=paths[index],
                    page_count=0,
                    error=f"Analysis failed unexpectedly: {exc}",
                )
            if on_result and results[index] is not None:
                on_result(index, results[index])  # type: ignore[arg-type]

    return [
        r
        if r is not None
        else DocumentAnalysis(source_path=paths[i], page_count=0, error="No result produced.")
        for i, r in enumerate(results)
    ]


def export_batch(
    analyses: Sequence[DocumentAnalysis],
    output_folder: Path,
    *,
    overrides: dict[Path, PageOverrides] | None = None,
    allow_unsplit: Iterable[Path] = (),
    skip: Iterable[Path] = (),
    token: CancellationToken | None = None,
    on_result: Callable[[int, DocumentExportResult], None] | None = None,
) -> list[DocumentExportResult]:
    """Export analysed documents sequentially, isolating per-file failures.

    Export is deliberately serial: writes are I/O bound and serialising them
    keeps output-name reservation simple and race-free, which matters more
    than raw speed for the "never overwrite" guarantee.
    """

    token = token or CancellationToken()
    overrides = overrides or {}
    allow_unsplit = {Path(p) for p in allow_unsplit}
    skip_set = {Path(p) for p in skip}
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    reserved: set[Path] = set()
    results: list[DocumentExportResult] = []

    for index, analysis in enumerate(analyses):
        source = Path(analysis.source_path)

        if analysis.error:
            # The document never analysed successfully, so it was never the
            # user's choice to leave it out.  Report the real reason: writing
            # "skipped by the user" into an audit record would be wrong.
            result = DocumentExportResult(source_path=source, error=analysis.error)
        elif source in skip_set:
            result = DocumentExportResult(
                source_path=source, skipped=True, skip_reason="Skipped by the user."
            )
        elif token.cancelled:
            result = DocumentExportResult(
                source_path=source, skipped=True, skip_reason="Cancelled before processing."
            )
        else:
            try:
                result = export_document(
                    analysis,
                    output_folder,
                    overrides=overrides.get(source),
                    reserved=reserved,
                    allow_unsplit_copy=source in allow_unsplit,
                    should_cancel=token,
                )
            except Exception as exc:  # noqa: BLE001 - never let one file stop the batch
                logger.exception("Export crashed for %s", source)
                result = DocumentExportResult(
                    source_path=source, error=f"Export failed unexpectedly: {exc}"
                )

        results.append(result)
        if on_result:
            on_result(index, result)

    return results


__all__ = [
    "AnalysisSettings",
    "CancellationToken",
    "MAX_WORKERS_CAP",
    "analyze_batch",
    "export_batch",
    "recommended_workers",
]
