"""Page grouping rules (PRD FR-4), kept free of rendering and file I/O.

Indexes are zero-based here; the UI and the report add one when displaying.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    AnalysisWarning,
    PageAnalysis,
    PageOverrides,
    PageStatus,
    ProcessingMode,
    WarningCode,
)


@dataclass(frozen=True)
class GroupingResult:
    """Groups plus the diagnostics the UI needs to explain them."""

    groups: tuple[tuple[int, ...], ...]
    statuses: tuple[PageStatus, ...]
    empty_group_count: int = 0

    @property
    def separator_pages(self) -> tuple[int, ...]:
        return tuple(i for i, s in enumerate(self.statuses) if s is PageStatus.SEPARATOR)

    @property
    def blank_pages(self) -> tuple[int, ...]:
        return tuple(i for i, s in enumerate(self.statuses) if s is PageStatus.BLANK)

    @property
    def kept_pages(self) -> tuple[int, ...]:
        return tuple(i for i, s in enumerate(self.statuses) if s is PageStatus.KEPT)


def effective_statuses(
    pages: tuple[PageAnalysis, ...],
    *,
    mode: ProcessingMode,
    remove_blanks: bool,
    overrides: PageOverrides | None = None,
) -> tuple[PageStatus, ...]:
    """Resolve detection plus user overrides into one status per page.

    Precedence, chosen so an explicit user decision always wins:

    1. ``force_keep`` -> page is kept, whatever detection said;
    2. ``force_remove`` -> page is dropped as blank;
    3. separator flags (``force_separator`` / ``force_not_separator``);
    4. detected blank, but only when blank removal is switched on.
    """

    overrides = overrides or PageOverrides()
    statuses: list[PageStatus] = []

    for page in pages:
        index = page.page_index

        is_separator = page.is_separator
        if index in overrides.force_separator:
            is_separator = True
        if index in overrides.force_not_separator:
            is_separator = False
        # Barcode separators are meaningless in blank-cleanup mode: nothing is
        # split there, so every page is either kept or dropped as blank.
        if mode is ProcessingMode.CLEAN_ONLY:
            is_separator = False

        # An explicit "keep this page" always wins, including over a detected
        # separator the user chose to retain as content.
        if index in overrides.force_keep:
            statuses.append(PageStatus.KEPT)
            continue
        if index in overrides.force_remove:
            statuses.append(PageStatus.BLANK)
            continue
        if is_separator:
            statuses.append(PageStatus.SEPARATOR)
            continue
        if remove_blanks and page.is_blank:
            statuses.append(PageStatus.BLANK)
            continue
        statuses.append(PageStatus.KEPT)

    return tuple(statuses)


def group_pages(
    pages: tuple[PageAnalysis, ...],
    *,
    mode: ProcessingMode,
    remove_blanks: bool,
    overrides: PageOverrides | None = None,
) -> GroupingResult:
    """Split retained pages into output groups.

    * A separator page ends the current group and starts the next one.
    * Separator pages are never included in any group.
    * Blank pages are omitted when removal is enabled.
    * Empty groups (leading/trailing/consecutive separators) are discarded and
      counted so the caller can raise a warning.
    * In blank-cleanup mode every retained page forms a single group.
    """

    statuses = effective_statuses(
        pages, mode=mode, remove_blanks=remove_blanks, overrides=overrides
    )

    if mode is ProcessingMode.CLEAN_ONLY:
        kept = tuple(
            page.page_index
            for page, status in zip(pages, statuses)
            if status is PageStatus.KEPT
        )
        groups = (kept,) if kept else ()
        return GroupingResult(groups=groups, statuses=statuses, empty_group_count=0)

    groups: list[tuple[int, ...]] = []
    current: list[int] = []
    empty_groups = 0
    saw_separator = False

    for page, status in zip(pages, statuses):
        if status is PageStatus.SEPARATOR:
            saw_separator = True
            if current:
                groups.append(tuple(current))
                current = []
            else:
                empty_groups += 1
            continue
        if status is PageStatus.BLANK:
            continue
        current.append(page.page_index)

    if current:
        groups.append(tuple(current))
    elif saw_separator:
        # Trailing separator with nothing after it.
        empty_groups += 1

    return GroupingResult(
        groups=tuple(groups), statuses=statuses, empty_group_count=empty_groups
    )


def build_warnings(
    result: GroupingResult,
    *,
    pages: tuple[PageAnalysis, ...],
    mode: ProcessingMode,
    expected_separator: str | None,
    blank_sensitivity_is_aggressive: bool = False,
    is_signed: bool = False,
) -> tuple[AnalysisWarning, ...]:
    """Derive the user-visible warnings for a grouped document."""

    warnings: list[AnalysisWarning] = []
    page_count = len(pages)

    if mode is ProcessingMode.SPLIT:
        if not result.separator_pages:
            warnings.append(
                AnalysisWarning(
                    WarningCode.NO_SEPARATOR_FOUND,
                    f"No page matching the separator \u201c{expected_separator}\u201d was found. "
                    "This file will not be split until you choose how to handle it.",
                )
            )
        other = [
            (bc.page_index + 1, bc.value)
            for page, status in zip(pages, result.statuses)
            for bc in page.barcodes
            if status is not PageStatus.SEPARATOR
        ]
        if other:
            preview = ", ".join(f"page {num}: \u201c{val}\u201d" for num, val in other[:4])
            if len(other) > 4:
                preview += f", and {len(other) - 4} more"
            warnings.append(
                AnalysisWarning(
                    WarningCode.OTHER_BARCODE_DETECTED,
                    f"Other barcodes were detected ({preview}). "
                    "Check that the separator value is correct.",
                )
            )
        if result.empty_group_count:
            plural = "s" if result.empty_group_count > 1 else ""
            warnings.append(
                AnalysisWarning(
                    WarningCode.EMPTY_GROUP_SKIPPED,
                    f"{result.empty_group_count} empty section{plural} caused by adjacent, "
                    "leading or trailing separator sheets will be ignored.",
                )
            )

    if page_count and not result.groups:
        warnings.append(
            AnalysisWarning(
                WarningCode.ALL_PAGES_REMOVED,
                "Every page would be removed, so nothing can be exported. "
                "Correct a page status or skip this file.",
            )
        )

    if blank_sensitivity_is_aggressive and result.blank_pages:
        warnings.append(
            AnalysisWarning(
                WarningCode.AGGRESSIVE_BLANKS,
                "Aggressive blank detection is enabled. Review the detected blank pages "
                "before processing \u2014 faint content can be removed.",
            )
        )

    if is_signed:
        warnings.append(
            AnalysisWarning(
                WarningCode.SIGNED_PDF,
                "This PDF appears to contain a digital signature. Exported documents are "
                "rewritten page by page, so the original signature will not stay valid.",
            )
        )

    return tuple(warnings)


__all__ = [
    "GroupingResult",
    "build_warnings",
    "effective_statuses",
    "group_pages",
]
