"""One-pass page analysis: render, decode, classify, group (PRD FR-1/FR-6).

Pages are rendered at 300 DPI with the longest dimension capped, analysed, and
then released immediately so peak memory stays at roughly one page per worker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

try:
    import pymupdf  # PyMuPDF >= 1.24 exposes the modern module name
except ImportError:  # pragma: no cover - older wheels
    import fitz as pymupdf  # type: ignore[no-redef]

from .barcode import decode_page_barcodes
from .blank_pages import is_blank_page, profile_for
from .grouping import build_warnings, group_pages
from .models import (
    AnalysisWarning,
    BlankSensitivity,
    DetectedBarcode,
    DocumentAnalysis,
    PageAnalysis,
    PageOverrides,
    ProcessingMode,
    WarningCode,
)

logger = logging.getLogger(__name__)

ANALYSIS_DPI = 300
"""Render resolution used for barcode and blank analysis (PRD FR-1)."""

MAX_RENDER_DIMENSION = 6000
"""Cap on the longest rendered edge, to bound memory on oversized pages."""

THUMBNAIL_DPI = 40
"""Low-resolution DPI used for the review thumbnails."""

LARGE_DOCUMENT_PAGES = 500
"""Above this page count we warn that analysis will take a while."""


class AnalysisCancelled(Exception):
    """Raised internally when a cancellation callback reports a stop request."""


class DocumentOpenError(Exception):
    """A PDF could not be opened, is encrypted, or is structurally broken."""


@dataclass(frozen=True)
class PageRender:
    """A rendered page plus the data needed to release it deterministically."""

    image: np.ndarray
    width: int
    height: int


def _zoom_for(page, dpi: int) -> float:
    """Scale factor that hits ``dpi`` without exceeding the dimension cap."""

    zoom = dpi / 72.0
    rect = page.rect
    longest_pt = max(rect.width, rect.height)
    if longest_pt <= 0:
        return zoom
    if longest_pt * zoom > MAX_RENDER_DIMENSION:
        zoom = MAX_RENDER_DIMENSION / longest_pt
    return max(zoom, 0.05)


def render_page_array(page, dpi: int = ANALYSIS_DPI, grayscale: bool = True) -> np.ndarray:
    """Render a PyMuPDF page to a numpy array, honouring the dimension cap."""

    zoom = _zoom_for(page, dpi)
    matrix = pymupdf.Matrix(zoom, zoom)
    colorspace = pymupdf.csGRAY if grayscale else pymupdf.csRGB
    pixmap = page.get_pixmap(matrix=matrix, colorspace=colorspace, alpha=False)
    try:
        channels = pixmap.n
        buffer = np.frombuffer(pixmap.samples, dtype=np.uint8)
        array = buffer.reshape(pixmap.height, pixmap.width, channels)
        if channels == 1:
            array = array[:, :, 0]
        # Copy so the array survives the pixmap being freed below.
        return np.array(array, copy=True)
    finally:
        del pixmap


def open_document(path: Path):
    """Open a PDF, converting failure modes into :class:`DocumentOpenError`."""

    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise DocumentOpenError(f"The file could not be opened: {exc}") from exc

    if document.needs_pass:
        document.close()
        raise DocumentOpenError(
            "This PDF is password protected. Remove the password and try again."
        )
    return document


def document_is_signed(document) -> bool:
    """Best-effort detection of a digital signature field."""

    try:
        if getattr(document, "is_form_pdf", False):
            for page in document:
                for widget in page.widgets() or []:
                    if getattr(widget, "field_type", None) == getattr(
                        pymupdf, "PDF_WIDGET_TYPE_SIGNATURE", 6
                    ):
                        return True
    except Exception:  # pragma: no cover - signature probing must never fail hard
        logger.debug("Signature probe failed", exc_info=True)
    return False


def analyze_document(
    source_path: Path,
    *,
    mode: ProcessingMode = ProcessingMode.SPLIT,
    expected_separator: str | None = None,
    remove_blanks: bool = True,
    blank_sensitivity: BlankSensitivity = BlankSensitivity.BALANCED,
    overrides: PageOverrides | None = None,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> DocumentAnalysis:
    """Analyse one PDF and return an immutable :class:`DocumentAnalysis`.

    Failures are captured in the returned object's ``error`` field rather than
    raised, so one bad file never stops a batch (PRD FR-6).
    """

    source_path = Path(source_path)
    decode_barcodes = mode is ProcessingMode.SPLIT
    sensitivity = BlankSensitivity(blank_sensitivity)
    profile = profile_for(sensitivity)

    try:
        document = open_document(source_path)
    except DocumentOpenError as exc:
        return DocumentAnalysis(
            source_path=source_path,
            page_count=0,
            error=str(exc),
            mode=mode,
            expected_separator=expected_separator,
            remove_blanks=remove_blanks,
            blank_sensitivity=sensitivity,
        )

    pages: list[PageAnalysis] = []
    extra_warnings: list[AnalysisWarning] = []
    error: str | None = None
    is_signed = False

    try:
        page_count = document.page_count
        if page_count == 0:
            document.close()
            return DocumentAnalysis(
                source_path=source_path,
                page_count=0,
                error="This PDF contains no pages.",
                mode=mode,
                expected_separator=expected_separator,
                remove_blanks=remove_blanks,
                blank_sensitivity=sensitivity,
            )

        is_signed = document_is_signed(document)
        if page_count > LARGE_DOCUMENT_PAGES:
            extra_warnings.append(
                AnalysisWarning(
                    WarningCode.LARGE_DOCUMENT,
                    f"This PDF has {page_count} pages, so analysis may take a while.",
                )
            )

        if progress:
            progress(0, page_count)

        for page_index in range(page_count):
            if should_cancel and should_cancel():
                raise AnalysisCancelled()

            image: np.ndarray | None = None
            try:
                page = document.load_page(page_index)
                image = render_page_array(page, ANALYSIS_DPI, grayscale=True)

                blank, ratio = is_blank_page(image, profile)

                barcodes: tuple[DetectedBarcode, ...] = ()
                is_separator = False
                if decode_barcodes:
                    # A confidently blank page cannot carry a barcode; skipping
                    # the decode there is a large speed win on duplex scans.
                    if blank and ratio < profile.ratio_threshold * 0.25:
                        outcome = None
                    else:
                        outcome = decode_page_barcodes(image, expected_separator)
                    if outcome is not None:
                        is_separator = outcome.matched
                        barcodes = tuple(
                            DetectedBarcode(page_index=page_index, value=value, format=fmt)
                            for value, fmt in outcome.barcodes
                        )

                if is_separator:
                    # A separator sheet is mostly white; never also call it blank.
                    blank = False

                pages.append(
                    PageAnalysis(
                        page_index=page_index,
                        is_separator=is_separator,
                        is_blank=blank,
                        non_white_ratio=ratio,
                        barcodes=barcodes,
                    )
                )
            except AnalysisCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate per-page failures
                logger.warning("Page %s of %s failed to analyse", page_index + 1, source_path.name)
                logger.debug("Page analysis error", exc_info=True)
                extra_warnings.append(
                    AnalysisWarning(
                        WarningCode.PAGE_ANALYSIS_FAILED,
                        f"Page {page_index + 1} could not be analysed ({exc}). "
                        "It will be kept in the output.",
                    )
                )
                pages.append(
                    PageAnalysis(
                        page_index=page_index,
                        is_separator=False,
                        is_blank=False,
                        non_white_ratio=1.0,
                    )
                )
            finally:
                # Release the full-resolution page image immediately (FR-1).
                del image

            if progress:
                progress(page_index + 1, page_count)

    except AnalysisCancelled:
        document.close()
        return DocumentAnalysis(
            source_path=source_path,
            page_count=len(pages),
            error="Analysis was cancelled.",
            mode=mode,
            expected_separator=expected_separator,
            remove_blanks=remove_blanks,
            blank_sensitivity=sensitivity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Analysis failed for %s", source_path.name)
        error = f"The file could not be analysed: {exc}"
    finally:
        try:
            document.close()
        except Exception:  # pragma: no cover
            pass

    if error is not None:
        return DocumentAnalysis(
            source_path=source_path,
            page_count=len(pages),
            error=error,
            mode=mode,
            expected_separator=expected_separator,
            remove_blanks=remove_blanks,
            blank_sensitivity=sensitivity,
        )

    page_tuple = tuple(pages)
    grouping = group_pages(
        page_tuple, mode=mode, remove_blanks=remove_blanks, overrides=overrides
    )
    warnings = build_warnings(
        grouping,
        pages=page_tuple,
        mode=mode,
        expected_separator=expected_separator,
        blank_sensitivity_is_aggressive=sensitivity is BlankSensitivity.AGGRESSIVE,
        is_signed=is_signed,
    )

    return DocumentAnalysis(
        source_path=source_path,
        page_count=len(page_tuple),
        pages=page_tuple,
        output_groups=grouping.groups,
        expected_separator=expected_separator,
        warnings=tuple(extra_warnings) + warnings,
        error=None,
        mode=mode,
        remove_blanks=remove_blanks,
        blank_sensitivity=sensitivity,
        is_signed=is_signed,
    )


def regroup(
    analysis: DocumentAnalysis,
    *,
    overrides: PageOverrides | None = None,
    remove_blanks: bool | None = None,
) -> DocumentAnalysis:
    """Recompute groups and warnings from cached page data.

    Used when the user overrides a page status: no re-rendering is needed
    because the per-page measurements are unchanged (PRD performance section).
    """

    if analysis.failed:
        return analysis

    effective_remove = analysis.remove_blanks if remove_blanks is None else remove_blanks
    grouping = group_pages(
        analysis.pages,
        mode=analysis.mode,
        remove_blanks=effective_remove,
        overrides=overrides,
    )
    warnings = build_warnings(
        grouping,
        pages=analysis.pages,
        mode=analysis.mode,
        expected_separator=analysis.expected_separator,
        blank_sensitivity_is_aggressive=(
            analysis.blank_sensitivity is BlankSensitivity.AGGRESSIVE
        ),
        is_signed=analysis.is_signed,
    )
    # Preserve non-grouping warnings (e.g. per-page analysis failures).
    carried = tuple(
        w
        for w in analysis.warnings
        if w.code in {WarningCode.PAGE_ANALYSIS_FAILED, WarningCode.LARGE_DOCUMENT}
    )
    from dataclasses import replace

    return replace(
        analysis,
        output_groups=grouping.groups,
        warnings=carried + warnings,
        remove_blanks=effective_remove,
    )


def render_thumbnail_png(source_path: Path, page_index: int, dpi: int = THUMBNAIL_DPI) -> bytes:
    """Render a single low-resolution page thumbnail as PNG bytes."""

    document = open_document(Path(source_path))
    try:
        page = document.load_page(page_index)
        zoom = _zoom_for(page, dpi)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        try:
            return pixmap.tobytes("png")
        finally:
            del pixmap
    finally:
        document.close()


__all__ = [
    "ANALYSIS_DPI",
    "AnalysisCancelled",
    "DocumentOpenError",
    "MAX_RENDER_DIMENSION",
    "analyze_document",
    "document_is_signed",
    "open_document",
    "regroup",
    "render_page_array",
    "render_thumbnail_png",
]
