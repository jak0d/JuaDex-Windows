"""Qt worker objects wrapping the framework-independent core (PRD FR-6).

All heavy work happens on a QThread; the GUI thread only receives signals, so
the interface stays responsive and cancellation is immediate.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal, Slot

from .core.batch import AnalysisSettings, CancellationToken, analyze_batch, export_batch
from .core.models import (
    DocumentAnalysis,
    DocumentExportResult,
    PageOverrides,
)

logger = logging.getLogger(__name__)


class AnalysisWorker(QObject):
    """Runs a batch analysis and reports progress per file and per page."""

    file_started = Signal(int, str)
    file_progress = Signal(int, int, int)  # index, pages done, pages total
    file_finished = Signal(int, object)  # index, DocumentAnalysis
    batch_finished = Signal(list)  # list[DocumentAnalysis]
    failed = Signal(str)

    def __init__(
        self,
        paths: Sequence[Path],
        settings: AnalysisSettings,
        token: CancellationToken,
    ) -> None:
        super().__init__()
        self._paths = list(paths)
        self._settings = settings
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            results = analyze_batch(
                self._paths,
                self._settings,
                token=self._token,
                on_start=lambda index, path: self.file_started.emit(index, str(path)),
                on_page=lambda index, done, total: self.file_progress.emit(
                    index, done, total
                ),
                on_result=lambda index, analysis: self.file_finished.emit(index, analysis),
            )
            self.batch_finished.emit(list(results))
        except Exception as exc:  # noqa: BLE001 - a worker crash must surface, not vanish
            logger.exception("Analysis batch failed")
            self.failed.emit(str(exc))
            self.batch_finished.emit([])


class ExportWorker(QObject):
    """Runs the export phase for already-analysed documents."""

    file_finished = Signal(int, object)  # index, DocumentExportResult
    batch_finished = Signal(list)  # list[DocumentExportResult]
    failed = Signal(str)

    def __init__(
        self,
        analyses: Sequence[DocumentAnalysis],
        output_folder: Path,
        overrides: dict[Path, PageOverrides],
        allow_unsplit: set[Path],
        skip: set[Path],
        token: CancellationToken,
    ) -> None:
        super().__init__()
        self._analyses = list(analyses)
        self._output_folder = Path(output_folder)
        self._overrides = dict(overrides)
        self._allow_unsplit = set(allow_unsplit)
        self._skip = set(skip)
        self._token = token

    @Slot()
    def run(self) -> None:
        try:
            results = export_batch(
                self._analyses,
                self._output_folder,
                overrides=self._overrides,
                allow_unsplit=self._allow_unsplit,
                skip=self._skip,
                token=self._token,
                on_result=lambda index, result: self.file_finished.emit(index, result),
            )
            self.batch_finished.emit(list(results))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Export batch failed")
            self.failed.emit(str(exc))
            self.batch_finished.emit([])


class ThumbnailWorker(QObject):
    """Renders page thumbnails for the review dialog, one page at a time."""

    thumbnail_ready = Signal(int, bytes)  # page index, PNG bytes
    finished = Signal()

    def __init__(self, source_path: Path, page_indexes: Sequence[int], dpi: int = 40) -> None:
        super().__init__()
        self._source_path = Path(source_path)
        self._page_indexes = list(page_indexes)
        self._dpi = dpi
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        from .core.analyzer import open_document, _zoom_for

        try:
            import pymupdf
        except ImportError:  # pragma: no cover
            import fitz as pymupdf  # type: ignore

        document = None
        try:
            document = open_document(self._source_path)
            for page_index in self._page_indexes:
                if self._cancelled:
                    break
                try:
                    page = document.load_page(page_index)
                    zoom = _zoom_for(page, self._dpi)
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    try:
                        self.thumbnail_ready.emit(page_index, pixmap.tobytes("png"))
                    finally:
                        del pixmap
                except Exception:  # noqa: BLE001 - a bad page just gets no preview
                    logger.debug("Thumbnail failed for page %s", page_index, exc_info=True)
        except Exception:  # noqa: BLE001
            logger.debug("Thumbnail worker failed", exc_info=True)
        finally:
            if document is not None:
                try:
                    document.close()
                except Exception:  # pragma: no cover
                    pass
            self.finished.emit()


__all__ = ["AnalysisWorker", "ExportWorker", "ThumbnailWorker"]
