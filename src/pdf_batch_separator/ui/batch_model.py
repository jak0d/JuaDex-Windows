"""Qt table model backing the batch list (PRD section 6.2).

Status is conveyed by text *and* icon shape, never by colour alone, to meet
the accessibility requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..core.models import (
    DocumentAnalysis,
    DocumentExportResult,
    PageOverrides,
    ProcessingMode,
    WarningCode,
)
from . import theme


class RowState(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"
    EXPORTING = "exporting"
    DONE = "done"
    SKIPPED = "skipped"

    @property
    def label(self) -> str:
        return {
            RowState.PENDING: "Waiting",
            RowState.ANALYZING: "Analysing",
            RowState.READY: "Ready",
            RowState.WARNING: "Needs attention",
            RowState.ERROR: "Failed",
            RowState.EXPORTING: "Processing",
            RowState.DONE: "Done",
            RowState.SKIPPED: "Skipped",
        }[self]

    @property
    def symbol(self) -> str:
        """A shape prefix so status never depends on colour alone."""

        return {
            RowState.PENDING: "\u2022",       # bullet
            RowState.ANALYZING: "\u25cc",     # dotted circle
            RowState.READY: "\u2713",         # check
            RowState.WARNING: "\u26a0",       # warning triangle
            RowState.ERROR: "\u2715",         # cross
            RowState.EXPORTING: "\u25b6",     # play
            RowState.DONE: "\u2713",          # check
            RowState.SKIPPED: "\u2298",       # circled slash
        }[self]

    @property
    def accent(self) -> str:
        """Design-system accent family used to tint this state."""

        return {
            RowState.PENDING: "neutral",
            RowState.ANALYZING: "info",
            RowState.READY: "success",
            RowState.WARNING: "warning",
            RowState.ERROR: "danger",
            RowState.EXPORTING: "info",
            RowState.DONE: "success",
            RowState.SKIPPED: "neutral",
        }[self]

    @property
    def icon(self) -> str:
        """Name of the vector glyph that accompanies the label."""

        return {
            RowState.PENDING: "clock",
            RowState.ANALYZING: "loader",
            RowState.READY: "check-circle",
            RowState.WARNING: "alert-triangle",
            RowState.ERROR: "x-circle",
            RowState.EXPORTING: "play",
            RowState.DONE: "check-circle",
            RowState.SKIPPED: "slash-circle",
        }[self]


@dataclass
class BatchRow:
    """One input PDF and everything the UI knows about it."""

    path: Path
    state: RowState = RowState.PENDING
    analysis: DocumentAnalysis | None = None
    export_result: DocumentExportResult | None = None
    overrides: PageOverrides = field(default_factory=PageOverrides)
    allow_unsplit: bool = False
    skipped_by_user: bool = False
    pages_done: int = 0
    pages_total: int = 0
    message: str = ""

    # -- derived values ------------------------------------------------
    @property
    def name(self) -> str:
        return self.path.name

    @property
    def page_count(self) -> int:
        return self.analysis.page_count if self.analysis else 0

    def effective_analysis(self) -> DocumentAnalysis | None:
        """Analysis regrouped with the row's overrides applied."""

        if self.analysis is None or self.analysis.failed:
            return self.analysis
        if self.overrides.is_empty:
            return self.analysis
        from ..core.analyzer import regroup

        return regroup(self.analysis, overrides=self.overrides)

    @property
    def separator_pages(self) -> tuple[int, ...]:
        analysis = self.effective_analysis()
        if not analysis or analysis.failed:
            return ()
        from ..core.grouping import effective_statuses
        from ..core.models import PageStatus

        statuses = effective_statuses(
            analysis.pages,
            mode=analysis.mode,
            remove_blanks=analysis.remove_blanks,
            overrides=self.overrides,
        )
        return tuple(
            page.page_index
            for page, status in zip(analysis.pages, statuses)
            if status is PageStatus.SEPARATOR
        )

    @property
    def blank_pages(self) -> tuple[int, ...]:
        analysis = self.effective_analysis()
        if not analysis or analysis.failed:
            return ()
        from ..core.grouping import effective_statuses
        from ..core.models import PageStatus

        statuses = effective_statuses(
            analysis.pages,
            mode=analysis.mode,
            remove_blanks=analysis.remove_blanks,
            overrides=self.overrides,
        )
        return tuple(
            page.page_index
            for page, status in zip(analysis.pages, statuses)
            if status is PageStatus.BLANK
        )

    @property
    def _user_chose_no_split(self) -> bool:
        """True when the user deliberately turned every separator into content.

        That is an explicit instruction, not a failed detection, so the file
        must not be treated as the "no separator found" warning case.
        """

        return bool(self.overrides.force_not_separator or self.overrides.force_keep)

    @property
    def expected_outputs(self) -> int:
        analysis = self.effective_analysis()
        if not analysis or analysis.failed:
            return 0
        if self.skipped_by_user:
            return 0
        if (
            analysis.mode is ProcessingMode.SPLIT
            and not self.separator_pages
            and not self.allow_unsplit
            and not self._user_chose_no_split
        ):
            return 0
        return len(analysis.output_groups)

    @property
    def blocked(self) -> bool:
        """True when this row cannot be exported as currently configured."""

        analysis = self.effective_analysis()
        if analysis is None or analysis.failed:
            return True
        if self.skipped_by_user:
            return False  # intentionally excluded, not blocking
        if not analysis.output_groups:
            return True
        if (
            analysis.mode is ProcessingMode.SPLIT
            and not self.separator_pages
            and not self.allow_unsplit
            and not self._user_chose_no_split
        ):
            return True
        return False

    def refresh_state(self) -> None:
        """Recompute the display state from the current analysis/overrides."""

        if self.state in {RowState.ANALYZING, RowState.EXPORTING}:
            return
        if self.skipped_by_user:
            self.state = RowState.SKIPPED
            self.message = "Skipped by you"
            return
        if self.analysis is None:
            self.state = RowState.PENDING
            self.message = ""
            return
        if self.analysis.failed:
            self.state = RowState.ERROR
            self.message = self.analysis.error or "Failed"
            return
        if self.export_result is not None:
            if self.export_result.error:
                self.state = RowState.ERROR
                self.message = self.export_result.error
            elif self.export_result.skipped:
                self.state = RowState.SKIPPED
                self.message = self.export_result.skip_reason or "Skipped"
            else:
                self.state = RowState.DONE
                self.message = f"{len(self.export_result.outputs)} document(s) written"
            return

        analysis = self.effective_analysis()
        assert analysis is not None
        if self.blocked:
            self.state = RowState.WARNING
            if (
                analysis.mode is ProcessingMode.SPLIT
                and not self.separator_pages
            ):
                self.message = "No separator found \u2014 choose how to handle this file"
            else:
                self.message = "Every page would be removed"
            return
        if analysis.warnings:
            self.state = RowState.WARNING
            self.message = analysis.warnings[0].message
            return
        self.state = RowState.READY
        self.message = "Ready to process"


class BatchTableModel(QAbstractTableModel):
    """Table model for the batch list."""

    COLUMNS = ("File", "Pages", "Separators", "Blanks", "Documents", "Status")
    COL_FILE, COL_PAGES, COL_SEP, COL_BLANK, COL_OUT, COL_STATUS = range(6)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[BatchRow] = []

    # -- Qt plumbing ---------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section]
        return section + 1

    @staticmethod
    def _pages_text(indexes: tuple[int, ...], limit: int = 6) -> str:
        if not indexes:
            return "\u2014"
        shown = [str(i + 1) for i in indexes[:limit]]
        if len(indexes) > limit:
            shown.append(f"+{len(indexes) - limit}")
        return ", ".join(shown)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == self.COL_FILE:
                return row.name
            if column == self.COL_PAGES:
                if row.state is RowState.ANALYZING and row.pages_total:
                    return f"{row.pages_done}/{row.pages_total}"
                return str(row.page_count) if row.analysis else "\u2014"
            if column == self.COL_SEP:
                if not row.analysis or row.analysis.failed:
                    return "\u2014"
                if row.analysis.mode is ProcessingMode.CLEAN_ONLY:
                    return "n/a"
                return self._pages_text(row.separator_pages)
            if column == self.COL_BLANK:
                if not row.analysis or row.analysis.failed:
                    return "\u2014"
                return self._pages_text(row.blank_pages)
            if column == self.COL_OUT:
                if not row.analysis or row.analysis.failed:
                    return "\u2014"
                return str(row.expected_outputs)
            if column == self.COL_STATUS:
                return f"{row.state.symbol}  {row.state.label}"

        if role == Qt.ItemDataRole.ToolTipRole:
            if column == self.COL_FILE:
                return str(row.path)
            if column == self.COL_STATUS:
                return row.message or row.state.label
            if column == self.COL_SEP and row.separator_pages:
                return "Separator pages: " + ", ".join(
                    str(i + 1) for i in row.separator_pages
                )
            if column == self.COL_BLANK and row.blank_pages:
                return "Blank pages: " + ", ".join(str(i + 1) for i in row.blank_pages)

        if role == Qt.ItemDataRole.AccessibleTextRole:
            if column == self.COL_STATUS:
                return f"{row.state.label}. {row.message}"
            if column == self.COL_FILE:
                return row.name

        # Resolved from the active palette rather than hardcoded, so the status
        # text keeps its contrast in the dark theme too.
        if (
            role == Qt.ItemDataRole.ForegroundRole
            and column == self.COL_STATUS
            and row.state.accent
        ):
            return QColor(theme.family(row.state.accent)["soft_fg"])

        if role == Qt.ItemDataRole.TextAlignmentRole and column in {
            self.COL_PAGES,
            self.COL_OUT,
        }:
            return int(Qt.AlignmentFlag.AlignCenter)

        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )

    # -- collection management ----------------------------------------
    @property
    def rows(self) -> list[BatchRow]:
        return self._rows

    def paths(self) -> list[Path]:
        return [row.path for row in self._rows]

    def add_paths(self, paths) -> tuple[int, int]:
        """Add unique PDFs. Returns ``(added, duplicates_skipped)``."""

        existing = {row.path.resolve() for row in self._rows}
        new_rows: list[BatchRow] = []
        duplicates = 0
        for path in paths:
            path = Path(path)
            try:
                resolved = path.resolve()
            except OSError:  # pragma: no cover
                resolved = path
            if resolved in existing:
                duplicates += 1
                continue
            existing.add(resolved)
            new_rows.append(BatchRow(path=path))

        if new_rows:
            start = len(self._rows)
            self.beginInsertRows(QModelIndex(), start, start + len(new_rows) - 1)
            self._rows.extend(new_rows)
            self.endInsertRows()
        return len(new_rows), duplicates

    def remove_rows(self, indexes: list[int]) -> None:
        for row_index in sorted(set(indexes), reverse=True):
            if 0 <= row_index < len(self._rows):
                self.beginRemoveRows(QModelIndex(), row_index, row_index)
                self._rows.pop(row_index)
                self.endRemoveRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def row_at(self, index: int) -> BatchRow | None:
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def emit_row_changed(self, index: int) -> None:
        if 0 <= index < len(self._rows):
            self.dataChanged.emit(
                self.index(index, 0), self.index(index, len(self.COLUMNS) - 1)
            )

    def emit_all_changed(self) -> None:
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, len(self.COLUMNS) - 1)
            )

    def reset_analysis(self) -> None:
        """Drop cached analyses (used when settings change)."""

        for row in self._rows:
            row.analysis = None
            row.export_result = None
            row.allow_unsplit = False
            row.pages_done = 0
            row.pages_total = 0
            row.state = RowState.PENDING
            row.message = ""
        self.emit_all_changed()

    def reset_results(self) -> None:
        for row in self._rows:
            row.export_result = None
            row.refresh_state()
        self.emit_all_changed()


__all__ = ["BatchRow", "BatchTableModel", "RowState"]
