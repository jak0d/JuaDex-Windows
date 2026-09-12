"""Per-document review: page thumbnails, badges and status overrides.

Implements the PRD's requirement that a user can verify every detected page
and correct it *before* anything is written to disk.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.grouping import effective_statuses
from ..core.models import (
    DocumentAnalysis,
    PageOverrides,
    PageStatus,
    ProcessingMode,
)
from ..workers import ThumbnailWorker

BADGE_STYLES = {
    PageStatus.KEPT: ("Kept", "#0f7b0f", "#e6f4e6"),
    PageStatus.SEPARATOR: ("Separator", "#8a3ffc", "#f2e8ff"),
    PageStatus.BLANK: ("Blank", "#9d5d00", "#fff4e0"),
}

THUMB_WIDTH = 150
THUMB_HEIGHT = 205


class PageCard(QFrame):
    """One page: thumbnail, badge and the controls to override its status."""

    changed = Signal()

    def __init__(self, page_index: int, mode: ProcessingMode, parent=None) -> None:
        super().__init__(parent)
        self.page_index = page_index
        self.mode = mode
        self._status = PageStatus.KEPT

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("pageCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setStyleSheet(
            "background: palette(base); border: 1px solid palette(mid);"
        )
        self.thumbnail.setText("Loading\u2026")
        self.thumbnail.setAccessibleName(f"Preview of page {page_index + 1}")
        layout.addWidget(self.thumbnail, alignment=Qt.AlignmentFlag.AlignHCenter)

        header = QHBoxLayout()
        self.page_label = QLabel(f"Page {page_index + 1}")
        self.page_label.setStyleSheet("font-weight: 600;")
        header.addWidget(self.page_label)
        header.addStretch(1)
        self.badge = QLabel()
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.badge)
        layout.addLayout(header)

        self.remove_box = QCheckBox("Remove this page")
        self.remove_box.setToolTip(
            "Leave the page out of the exported document."
        )
        self.remove_box.toggled.connect(self._on_toggle)
        layout.addWidget(self.remove_box)

        self.separator_box = QCheckBox("Treat as separator")
        self.separator_box.setToolTip(
            "Split here. Separator pages are never included in the output."
        )
        self.separator_box.toggled.connect(self._on_toggle)
        layout.addWidget(self.separator_box)
        self.separator_box.setVisible(mode is ProcessingMode.SPLIT)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _on_toggle(self) -> None:
        self.changed.emit()

    def set_thumbnail(self, png: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(png, "PNG"):
            self.thumbnail.setPixmap(
                pixmap.scaled(
                    QSize(THUMB_WIDTH - 4, THUMB_HEIGHT - 4),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.thumbnail.setText("")

    def set_status(self, status: PageStatus) -> None:
        self._status = status
        label, foreground, background = BADGE_STYLES[status]
        self.badge.setText(f" {label} ")
        self.badge.setStyleSheet(
            f"color: {foreground}; background: {background};"
            " border-radius: 6px; padding: 1px 6px; font-weight: 600;"
        )
        self.badge.setAccessibleName(f"Page {self.page_index + 1} status: {label}")
        self.page_label.setAccessibleName(
            f"Page {self.page_index + 1}, currently marked {label}"
        )

    def sync_controls(self, status: PageStatus) -> None:
        """Update checkbox states without re-emitting change signals."""

        for box, value in (
            (self.remove_box, status is PageStatus.BLANK),
            (self.separator_box, status is PageStatus.SEPARATOR),
        ):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)


class DocumentReviewDialog(QDialog):
    """Review one document's pages and adjust their statuses."""

    def __init__(
        self,
        analysis: DocumentAnalysis,
        overrides: PageOverrides,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.analysis = analysis
        self.result_overrides = overrides
        self._cards: dict[int, PageCard] = {}
        self._thread: QThread | None = None
        self._worker: ThumbnailWorker | None = None

        self.setWindowTitle(f"Review \u2014 {Path(analysis.source_path).name}")
        self.resize(1000, 720)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        heading = QLabel(Path(analysis.source_path).name)
        heading.setStyleSheet("font-size: 15pt; font-weight: 600;")
        layout.addWidget(heading)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        hint = QLabel(
            "Tick <b>Remove this page</b> to leave a page out, or untick it to keep a "
            "page that was detected as blank. In split mode, tick "
            "<b>Treat as separator</b> to split at that page."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid-text); ")
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setSpacing(12)
        self.grid.setContentsMargins(4, 4, 4, 4)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        self._build_cards()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply changes")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        reset = buttons.addButton(
            "Reset to detected", QDialogButtonBox.ButtonRole.ResetRole
        )
        reset.clicked.connect(self._reset)
        layout.addWidget(buttons)

        self._refresh_statuses()
        self._start_thumbnails()

    # -- construction --------------------------------------------------
    def _build_cards(self) -> None:
        columns = 5
        for position, page in enumerate(self.analysis.pages):
            card = PageCard(page.page_index, self.analysis.mode)
            card.changed.connect(self._on_card_changed)
            self.grid.addWidget(card, position // columns, position % columns)
            self._cards[page.page_index] = card
        self.grid.setRowStretch(self.grid.rowCount(), 1)

    def _start_thumbnails(self) -> None:
        indexes = [page.page_index for page in self.analysis.pages]
        self._thread = QThread(self)
        self._worker = ThumbnailWorker(Path(self.analysis.source_path), indexes)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.thumbnail_ready.connect(self._on_thumbnail)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_thumbnail(self, page_index: int, png: bytes) -> None:
        card = self._cards.get(page_index)
        if card is not None:
            card.set_thumbnail(png)

    # -- override handling ---------------------------------------------
    def _collect_overrides(self) -> PageOverrides:
        """Translate checkbox state into a minimal override set."""

        detected_blank = {
            page.page_index
            for page in self.analysis.pages
            if page.is_blank and self.analysis.remove_blanks
        }
        detected_separator = {
            page.page_index
            for page in self.analysis.pages
            if page.is_separator and self.analysis.mode is ProcessingMode.SPLIT
        }

        force_keep, force_remove = set(), set()
        force_separator, force_not_separator = set(), set()

        for index, card in self._cards.items():
            wants_separator = (
                card.separator_box.isChecked()
                and self.analysis.mode is ProcessingMode.SPLIT
            )
            wants_removed = card.remove_box.isChecked()

            if wants_separator and index not in detected_separator:
                force_separator.add(index)
            if not wants_separator and index in detected_separator:
                force_not_separator.add(index)

            if wants_separator:
                continue  # a separator is dropped anyway

            if wants_removed and index not in detected_blank:
                force_remove.add(index)
            if not wants_removed and (index in detected_blank or index in detected_separator):
                force_keep.add(index)

        return PageOverrides(
            force_keep=frozenset(force_keep),
            force_remove=frozenset(force_remove),
            force_separator=frozenset(force_separator),
            force_not_separator=frozenset(force_not_separator),
        )

    def _current_statuses(self, overrides: PageOverrides) -> tuple[PageStatus, ...]:
        return effective_statuses(
            self.analysis.pages,
            mode=self.analysis.mode,
            remove_blanks=self.analysis.remove_blanks,
            overrides=overrides,
        )

    def _refresh_statuses(self, *, sync_controls: bool = True) -> None:
        overrides = self.result_overrides
        statuses = self._current_statuses(overrides)
        for page, status in zip(self.analysis.pages, statuses):
            card = self._cards[page.page_index]
            card.set_status(status)
            if sync_controls:
                card.sync_controls(status)
        self._update_summary(statuses)

    def _on_card_changed(self) -> None:
        self.result_overrides = self._collect_overrides()
        statuses = self._current_statuses(self.result_overrides)
        for page, status in zip(self.analysis.pages, statuses):
            self._cards[page.page_index].set_status(status)
        self._update_summary(statuses)

    def _reset(self) -> None:
        self.result_overrides = PageOverrides()
        self._refresh_statuses()

    def _update_summary(self, statuses: tuple[PageStatus, ...]) -> None:
        kept = sum(1 for s in statuses if s is PageStatus.KEPT)
        separators = sum(1 for s in statuses if s is PageStatus.SEPARATOR)
        blanks = sum(1 for s in statuses if s is PageStatus.BLANK)

        from ..core.grouping import group_pages

        groups = group_pages(
            self.analysis.pages,
            mode=self.analysis.mode,
            remove_blanks=self.analysis.remove_blanks,
            overrides=self.result_overrides,
        ).groups

        text = (
            f"{len(self.analysis.pages)} pages \u2014 "
            f"{kept} kept, {separators} separator, {blanks} removed. "
            f"<b>{len(groups)} document(s)</b> would be exported."
        )
        if not groups:
            text += (
                " <span style='color:#c42b1c;'>Nothing would be exported. "
                "Keep at least one page.</span>"
            )
        self.summary.setText(text)
        self.summary.setAccessibleName(
            f"{len(self.analysis.pages)} pages, {kept} kept, {separators} separator, "
            f"{blanks} removed, {len(groups)} documents would be exported"
        )

    # -- lifecycle -----------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        self._stop_worker()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._stop_worker()
        super().done(result)

    def _stop_worker(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
            self._worker = None


__all__ = ["DocumentReviewDialog", "PageCard"]
