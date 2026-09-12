"""Typed, immutable result structures shared by the processing core and the UI.

Everything in this module is deliberately free of Qt and of any I/O so that the
core can be unit-tested head-lessly and reused from a CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Iterable


class ProcessingMode(str, Enum):
    """Top-level operation chosen by the user."""

    SPLIT = "split"
    """Split by separator sheets (optionally also removing blank pages)."""

    CLEAN_ONLY = "clean_only"
    """Remove blank pages only; never decode barcodes."""


class BlankSensitivity(str, Enum):
    """User-facing blank-detection profiles (thresholds live in blank_pages)."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"

    @property
    def label(self) -> str:
        return {
            BlankSensitivity.CONSERVATIVE: "Conservative",
            BlankSensitivity.BALANCED: "Balanced",
            BlankSensitivity.AGGRESSIVE: "Aggressive",
        }[self]

    @property
    def description(self) -> str:
        return {
            BlankSensitivity.CONSERVATIVE: (
                "Removes only very clean blank pages. Lowest risk of deleting real content."
            ),
            BlankSensitivity.BALANCED: (
                "Recommended default. Removes ordinary scanner blank backsides."
            ),
            BlankSensitivity.AGGRESSIVE: (
                "Handles noisy or speckled blank scans. Review the results before filing."
            ),
        }[self]


class PageStatus(str, Enum):
    """Effective per-page decision after user overrides are applied."""

    KEPT = "kept"
    SEPARATOR = "separator"
    BLANK = "blank"


class WarningCode(str, Enum):
    """Stable identifiers for warnings so the UI can react, not just display text."""

    NO_SEPARATOR_FOUND = "no_separator_found"
    OTHER_BARCODE_DETECTED = "other_barcode_detected"
    ALL_PAGES_REMOVED = "all_pages_removed"
    EMPTY_GROUP_SKIPPED = "empty_group_skipped"
    SIGNED_PDF = "signed_pdf"
    AGGRESSIVE_BLANKS = "aggressive_blanks"
    PAGE_ANALYSIS_FAILED = "page_analysis_failed"
    LARGE_DOCUMENT = "large_document"


@dataclass(frozen=True)
class AnalysisWarning:
    """A single, displayable warning attached to a document."""

    code: WarningCode
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


@dataclass(frozen=True)
class DetectedBarcode:
    """One decoded barcode symbol found on a page."""

    page_index: int
    value: str
    format: str


@dataclass(frozen=True)
class PageAnalysis:
    """Immutable per-page analysis result (zero-based ``page_index``)."""

    page_index: int
    is_separator: bool
    is_blank: bool
    non_white_ratio: float
    barcodes: tuple[DetectedBarcode, ...] = ()

    @property
    def page_number(self) -> int:
        """One-based page number for display in the UI and the report."""
        return self.page_index + 1


@dataclass(frozen=True)
class DocumentAnalysis:
    """Immutable analysis of one source PDF.

    ``output_groups`` holds the retained (zero-based) page indexes for each
    document that would be exported with the settings used during analysis.
    User overrides are stored separately (see :class:`PageOverrides`) so that a
    published analysis is never mutated in place.
    """

    source_path: Path
    page_count: int
    pages: tuple[PageAnalysis, ...] = ()
    output_groups: tuple[tuple[int, ...], ...] = ()
    expected_separator: str | None = None
    warnings: tuple[AnalysisWarning, ...] = ()
    error: str | None = None
    mode: ProcessingMode = ProcessingMode.SPLIT
    remove_blanks: bool = True
    blank_sensitivity: BlankSensitivity = BlankSensitivity.BALANCED
    is_signed: bool = False

    # ------------------------------------------------------------------
    # Convenience accessors used by the UI and the report writer.
    # ------------------------------------------------------------------
    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def separator_pages(self) -> tuple[int, ...]:
        return tuple(p.page_index for p in self.pages if p.is_separator)

    @property
    def blank_pages(self) -> tuple[int, ...]:
        return tuple(p.page_index for p in self.pages if p.is_blank and not p.is_separator)

    @property
    def other_barcodes(self) -> tuple[DetectedBarcode, ...]:
        found: list[DetectedBarcode] = []
        for page in self.pages:
            for barcode in page.barcodes:
                if page.is_separator:
                    continue
                found.append(barcode)
        return tuple(found)

    @property
    def expected_output_count(self) -> int:
        return len(self.output_groups)

    def warning_codes(self) -> frozenset[WarningCode]:
        return frozenset(w.code for w in self.warnings)

    def has_warning(self, code: WarningCode) -> bool:
        return any(w.code is code for w in self.warnings)

    def page(self, page_index: int) -> PageAnalysis | None:
        for candidate in self.pages:
            if candidate.page_index == page_index:
                return candidate
        return None

    def with_warnings(self, warnings: Iterable[AnalysisWarning]) -> "DocumentAnalysis":
        return replace(self, warnings=tuple(warnings))


@dataclass(frozen=True)
class PageOverrides:
    """Explicit user corrections for a single document.

    Overrides are kept apart from :class:`DocumentAnalysis` so re-analysis can
    either drop them (with confirmation) or re-apply the ones that still refer
    to valid page indexes.
    """

    force_keep: frozenset[int] = frozenset()
    """Pages the user insists on keeping even if detected blank."""

    force_remove: frozenset[int] = frozenset()
    """Pages the user wants dropped even though they are not blank."""

    force_separator: frozenset[int] = frozenset()
    """Pages the user marked as separators."""

    force_not_separator: frozenset[int] = frozenset()
    """Detected separators the user wants treated as normal content."""

    @property
    def is_empty(self) -> bool:
        return not (
            self.force_keep
            or self.force_remove
            or self.force_separator
            or self.force_not_separator
        )

    def compatible_with(self, page_count: int) -> "PageOverrides":
        """Drop overrides that fall outside a document of ``page_count`` pages."""

        def _clip(values: frozenset[int]) -> frozenset[int]:
            return frozenset(v for v in values if 0 <= v < page_count)

        return PageOverrides(
            force_keep=_clip(self.force_keep),
            force_remove=_clip(self.force_remove),
            force_separator=_clip(self.force_separator),
            force_not_separator=_clip(self.force_not_separator),
        )


@dataclass(frozen=True)
class ExportedFile:
    """One successfully written output document."""

    path: Path
    page_count: int
    source_pages: tuple[int, ...]


@dataclass(frozen=True)
class DocumentExportResult:
    """Outcome of exporting a single source PDF."""

    source_path: Path
    outputs: tuple[ExportedFile, ...] = ()
    separators_removed: int = 0
    blanks_removed: int = 0
    warnings: tuple[str, ...] = ()
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and not self.skipped


@dataclass(frozen=True)
class BatchSummary:
    """Aggregate result presented on the results screen and in the report."""

    output_folder: Path
    results: tuple[DocumentExportResult, ...] = ()
    cancelled: bool = False
    started_at: str = ""
    finished_at: str = ""

    @property
    def documents_processed(self) -> int:
        return sum(1 for r in self.results if r.succeeded)

    @property
    def outputs_created(self) -> int:
        return sum(len(r.outputs) for r in self.results)

    @property
    def separators_removed(self) -> int:
        return sum(r.separators_removed for r in self.results)

    @property
    def blanks_removed(self) -> int:
        return sum(r.blanks_removed for r in self.results)

    @property
    def failures(self) -> tuple[DocumentExportResult, ...]:
        return tuple(r for r in self.results if r.error is not None)

    @property
    def skipped(self) -> tuple[DocumentExportResult, ...]:
        return tuple(r for r in self.results if r.skipped)

    @property
    def warning_count(self) -> int:
        return sum(len(r.warnings) for r in self.results)


@dataclass(frozen=True)
class SeparatorConfig:
    """The separator marker the user expects, plus matching behaviour."""

    value: str
    """Raw user-entered value (kept verbatim for display and regeneration)."""

    PRESET_EAGC: "str" = field(default="EAGC-EDMS-00001", init=False, repr=False)
    PRESET_PATCH_T: "str" = field(default="PATCHT", init=False, repr=False)


PRESET_SEPARATORS: tuple[str, ...] = ("EAGC-EDMS-00001", "PATCHT")
DEFAULT_SEPARATOR: str = "EAGC-EDMS-00001"
MAX_SEPARATOR_LENGTH: int = 128
