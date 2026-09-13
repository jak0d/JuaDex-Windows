"""Per-document triage: page thumbnails, detection evidence and overrides.

Implements the PRD's requirement that a user can verify every detected page
and correct it *before* anything is written to disk.

The dialog is laid out as a triage grid.  Each page is a card that states what
was detected, why (ink density, barcode payload, target document) and offers
the one action that resolves it.  Cards needing a decision are tinted and
sorted to the front; pages that are simply being kept stay quiet and neutral,
so attention goes where it is needed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
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
from . import components as ui
from . import icons
from .theme import SPACE, color

# label, accent family, icon, eyebrow used on the card header
STATUS_STYLE: dict[PageStatus, tuple[str, str, str, str]] = {
    PageStatus.KEPT: ("Keep", "success", "check-circle", "Content page"),
    PageStatus.SEPARATOR: ("Separator", "separator", "split", "Document break detected"),
    PageStatus.BLANK: ("Blank", "danger", "trash", "Blank page detected"),
}

THUMB_WIDTH = 96
THUMB_HEIGHT = 124
CARD_WIDTH = 352


class PageCard(ui.Card):
    """One page: preview, detection evidence and the controls to override it."""

    changed = Signal()

    def __init__(self, page_index: int, mode: ProcessingMode, parent=None) -> None:
        super().__init__(padding=SPACE["md"], spacing=SPACE["sm"], parent=parent)
        self.page_index = page_index
        self.mode = mode
        self._status = PageStatus.KEPT
        self.setFixedWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # -- header: eyebrow + state pill ------------------------------
        self.eyebrow_icon = QLabel()
        self.eyebrow_icon.setFixedSize(14, 14)
        self.eyebrow_text = QLabel()
        # Sentence case: the eyebrow directly above is already uppercase mono,
        # and two shouting elements side by side fight each other.
        self.state_pill = ui.Pill("", "success")
        # Kept as the historical name for the status chip so existing callers
        # and tests that read ``card.badge`` keep working.
        self.badge = self.state_pill

        header = QHBoxLayout()
        header.setSpacing(SPACE["sm"])
        header.addWidget(self.eyebrow_icon)
        header.addWidget(self.eyebrow_text)
        header.addStretch(1)
        header.addWidget(self.state_pill)
        self.body.addLayout(header)

        # -- identity: preview + page number ---------------------------
        identity = QHBoxLayout()
        identity.setSpacing(SPACE["md"])

        self.preview = ui.PagePreview(THUMB_WIDTH, THUMB_HEIGHT)
        self.preview.setAccessibleName(f"Preview of page {page_index + 1}")
        identity.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        self.page_label = ui.label(f"Page {page_index + 1}", "filename")
        self.page_label.setTextFormat(Qt.TextFormat.PlainText)
        text_column.addWidget(self.page_label)

        self.detail_label = ui.label("", "subtle")
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setWordWrap(True)
        text_column.addWidget(self.detail_label)
        text_column.addSpacing(SPACE["xs"])

        self.meta = ui.MetaBlock()
        self.meta_primary = self.meta.add_row("Ink density", "\u2014")
        self.meta_secondary = self.meta.add_row("Outcome", "\u2014")
        text_column.addWidget(self.meta)
        text_column.addStretch(1)
        identity.addLayout(text_column, 1)
        self.body.addLayout(identity)

        # -- controls ---------------------------------------------------
        self.body.addWidget(ui.divider())

        controls = QHBoxLayout()
        controls.setSpacing(SPACE["md"])
        self.remove_box = QCheckBox("Remove this page")
        self.remove_box.setToolTip("Leave the page out of the exported document.")
        self.remove_box.toggled.connect(self._on_remove_toggled)
        controls.addWidget(self.remove_box)

        self.separator_box = QCheckBox("Treat as separator")
        self.separator_box.setToolTip(
            "Split here. Separator pages are never included in the output."
        )
        self.separator_box.toggled.connect(self._on_separator_toggled)
        self.separator_box.setVisible(mode is ProcessingMode.SPLIT)
        controls.addWidget(self.separator_box)
        controls.addStretch(1)
        self.body.addLayout(controls)

    # -- behaviour ------------------------------------------------------
    def _on_remove_toggled(self, checked: bool) -> None:
        if checked and self.separator_box.isChecked():
            self.separator_box.blockSignals(True)
            self.separator_box.setChecked(False)
            self.separator_box.blockSignals(False)
        self.changed.emit()

    def _on_separator_toggled(self, checked: bool) -> None:
        if checked and self.remove_box.isChecked():
            self.remove_box.blockSignals(True)
            self.remove_box.setChecked(False)
            self.remove_box.blockSignals(False)
        self.changed.emit()

    def set_thumbnail(self, png: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(png, "PNG"):
            self.preview.set_pixmap(pixmap)

    def set_status(self, status: PageStatus) -> None:
        self._status = status
        label, accent, glyph, eyebrow = STATUS_STYLE[status]
        shades = color(f"{accent}_soft_fg")

        self.eyebrow_icon.setPixmap(icons.pixmap(glyph, shades, 14))
        self.eyebrow_text.setText(eyebrow.upper())
        self.eyebrow_text.setStyleSheet(
            f"color: {shades}; font-family: {ui.MONO}; font-size: 8pt;"
            " font-weight: 700; letter-spacing: 1.1px;"
        )
        self.state_pill.set_text(label)
        self.state_pill.set_accent(accent)

        # Pages that will be dropped or split at are tinted; kept pages stay
        # neutral so the eye is drawn only to the decisions that matter.
        self.set_accent(accent if status is not PageStatus.KEPT else None, fill=False)
        self.preview.set_accent(
            accent if status is not PageStatus.KEPT else None,
            "Empty Scan" if status is PageStatus.BLANK else "",
        )

        self.state_pill.setAccessibleName(f"Page {self.page_index + 1} status: {label}")
        self.page_label.setAccessibleName(
            f"Page {self.page_index + 1}, currently marked {label}"
        )

    def set_evidence(self, page, remove_blanks: bool) -> None:
        """Show why this page was classified the way it was."""

        ink = page.non_white_ratio * 100.0
        barcodes = list(page.barcodes)

        if page.is_separator and barcodes:
            payload = barcodes[0].value
            self.detail_label.setText(f"{barcodes[0].format} separator sheet")
            self.meta_primary.set_key("Barcode")
            self.meta_primary.set_value(
                payload if len(payload) <= 18 else payload[:17] + "\u2026", "separator"
            )
            self.meta_primary.setToolTip(payload)
        elif page.is_blank:
            self.detail_label.setText("No detectable content")
            self.meta_primary.set_key("Ink density")
            self.meta_primary.set_value(f"{ink:.2f}%", "danger")
        else:
            self.detail_label.setText("Standard content page")
            self.meta_primary.set_key("Ink density")
            self.meta_primary.set_value(f"{ink:.2f}%")

        if barcodes and not page.is_separator:
            other = ", ".join(sorted({b.value for b in barcodes}))
            self.detail_label.setText(f"Other barcode found: {other}")

    def set_outcome(self, text: str, accent: str | None) -> None:
        self.meta_secondary.set_key("Outcome")
        self.meta_secondary.set_value(text, accent)

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

    FILTER_ALL = "all"
    FILTER_FLAGGED = "flagged"
    FILTER_SEPARATOR = "separator"
    FILTER_BLANK = "blank"
    FILTER_KEPT = "kept"

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
        self._filter = self.FILTER_ALL
        self._columns = 3

        name = Path(analysis.source_path).name
        self.setWindowTitle(f"Review \u2014 {name}")
        self.resize(1240, 860)
        self.setMinimumSize(980, 640)
        self.setSizeGripEnabled(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header(name))
        layout.addWidget(self._build_filter_bar())
        layout.addWidget(self._build_grid(), 1)
        layout.addWidget(self._build_footer())

        self._build_cards()
        self._refresh_statuses()
        self._start_thumbnails()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.reject)

    # -- construction ---------------------------------------------------
    def _build_header(self, name: str) -> QWidget:
        header = QWidget()
        header.setObjectName("reviewHeader")
        header.setStyleSheet(
            f"QWidget#reviewHeader {{ background: {color('surface')};"
            f" border-bottom: 1px solid {color('line')}; }}"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(SPACE["xl"], SPACE["lg"], SPACE["xl"], SPACE["md"])
        layout.setSpacing(SPACE["xl"])

        left = QVBoxLayout()
        left.setSpacing(SPACE["xs"])
        left.addWidget(ui.SectionHeader("Page triage", icon_name="layers"))

        title = ui.label(name, "display")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        left.addWidget(title)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(self.summary)
        layout.addLayout(left, 1)

        hint_card = ui.Card(padding=SPACE["md"], spacing=SPACE["xs"])
        hint_card.setMaximumWidth(320)
        hint_card.body.addWidget(
            ui.SectionHeader("How to correct a page", icon_name="keyboard")
        )
        hint = ui.label(
            "Tick <b>Remove this page</b> to leave a page out, or untick it to keep "
            "a page detected as blank. In split mode, tick <b>Treat as separator</b> "
            "to split at that page.",
            "subtle",
        )
        hint.setWordWrap(True)
        hint_card.body.addWidget(hint)
        layout.addWidget(hint_card, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(SPACE["xl"], SPACE["md"], SPACE["xl"], SPACE["sm"])
        layout.setSpacing(SPACE["sm"])

        self.filter_group = QButtonGroup(self)
        self.filter_group.setExclusive(True)
        self._filter_buttons: dict[str, object] = {}

        for key, text in (
            (self.FILTER_ALL, "All pages"),
            (self.FILTER_FLAGGED, "Needs a decision"),
            (self.FILTER_SEPARATOR, "Separators"),
            (self.FILTER_BLANK, "Blanks"),
            (self.FILTER_KEPT, "Kept"),
        ):
            button = ui.text_button(text, kind="segment")
            button.setCheckable(True)
            button.setChecked(key == self.FILTER_ALL)
            button.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.filter_group.addButton(button)
            self._filter_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.filter_status = ui.label("", "subtle")
        layout.addWidget(self.filter_status)
        return bar

    def _build_grid(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setSpacing(SPACE["md"])
        self.grid.setContentsMargins(
            SPACE["xl"], SPACE["sm"], SPACE["xl"], SPACE["xl"]
        )
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(container)
        self._scroll = scroll
        return scroll

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("reviewFooter")
        footer.setStyleSheet(
            f"QWidget#reviewFooter {{ background: {color('surface')};"
            f" border-top: 1px solid {color('line')}; }}"
        )
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(SPACE["xl"], SPACE["md"], SPACE["xl"], SPACE["md"])
        layout.setSpacing(SPACE["md"])

        self.outcome_pill = ui.Pill("", "success")
        layout.addWidget(self.outcome_pill)
        layout.addStretch(1)

        reset = ui.text_button("Reset to detected", icon_name="rotate-ccw")
        reset.clicked.connect(self._reset)
        layout.addWidget(reset)

        cancel = ui.text_button("Cancel", icon_name="x")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

        apply_button = ui.text_button(
            "Apply changes", icon_name="check", kind="primary"
        )
        apply_button.setDefault(True)
        apply_button.clicked.connect(self.accept)
        layout.addWidget(apply_button)
        return footer

    def _build_cards(self) -> None:
        for page in self.analysis.pages:
            card = PageCard(page.page_index, self.analysis.mode)
            card.changed.connect(self._on_card_changed)
            card.set_evidence(page, self.analysis.remove_blanks)
            self._cards[page.page_index] = card
        self._relayout()

    # -- filtering and layout -------------------------------------------
    def _set_filter(self, key: str) -> None:
        self._filter = key
        self._relayout()

    def _visible_indexes(self) -> list[int]:
        statuses = self._current_statuses(self.result_overrides)
        visible = []
        for page, status in zip(self.analysis.pages, statuses, strict=True):
            if self._filter == self.FILTER_ALL:
                keep = True
            elif self._filter == self.FILTER_FLAGGED:
                keep = status is not PageStatus.KEPT
            elif self._filter == self.FILTER_SEPARATOR:
                keep = status is PageStatus.SEPARATOR
            elif self._filter == self.FILTER_BLANK:
                keep = status is PageStatus.BLANK
            else:
                keep = status is PageStatus.KEPT
            if keep:
                visible.append(page.page_index)
        return visible

    def _relayout(self) -> None:
        """Re-flow the grid for the active filter."""

        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        visible = self._visible_indexes()
        for position, index in enumerate(visible):
            card = self._cards[index]
            card.setParent(None)
            self.grid.addWidget(card, position // self._columns, position % self._columns)
            card.show()

        for index, card in self._cards.items():
            if index not in visible:
                card.hide()

        total = len(self.analysis.pages)
        self.filter_status.setText(
            f"Showing {len(visible)} of {total} page{'s' if total != 1 else ''}"
        )

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
        for page, status in zip(self.analysis.pages, statuses, strict=True):
            card = self._cards[page.page_index]
            card.set_status(status)
            if sync_controls:
                card.sync_controls(status)
        self._apply_outcomes(statuses)
        self._update_summary(statuses)

    def _on_card_changed(self) -> None:
        self.result_overrides = self._collect_overrides()
        statuses = self._current_statuses(self.result_overrides)
        for page, status in zip(self.analysis.pages, statuses, strict=True):
            self._cards[page.page_index].set_status(status)
        self._apply_outcomes(statuses)
        self._update_summary(statuses)
        if self._filter != self.FILTER_ALL:
            self._relayout()

    def _reset(self) -> None:
        self.result_overrides = PageOverrides()
        self._refresh_statuses()
        self._relayout()

    def _apply_outcomes(self, statuses: tuple[PageStatus, ...]) -> None:
        """Tell each card which exported document it will land in."""

        from ..core.grouping import group_pages

        groups = group_pages(
            self.analysis.pages,
            mode=self.analysis.mode,
            remove_blanks=self.analysis.remove_blanks,
            overrides=self.result_overrides,
        ).groups
        position = {
            index: number
            for number, group in enumerate(groups, start=1)
            for index in group
        }

        for page, status in zip(self.analysis.pages, statuses, strict=True):
            card = self._cards[page.page_index]
            if status is PageStatus.SEPARATOR:
                card.set_outcome("Split point", "separator")
            elif status is PageStatus.BLANK:
                card.set_outcome("Removed", "danger")
            else:
                number = position.get(page.page_index)
                if number:
                    card.set_outcome(f"Doc #{number:02d}", "success")
                else:
                    card.set_outcome("Not exported", "warning")

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

        muted = color("muted")
        ink = color("ink")
        text = (
            f"<span style='color:{muted};'>"
            f"<b style='color:{ink};'>{len(self.analysis.pages)}</b> pages &nbsp;\u00b7&nbsp; "
            f"<b style='color:{ink};'>{kept}</b> kept &nbsp;\u00b7&nbsp; "
            f"<b style='color:{ink};'>{separators}</b> separator &nbsp;\u00b7&nbsp; "
            f"<b style='color:{ink};'>{blanks}</b> removed</span>"
        )
        self.summary.setText(text)

        if groups:
            self.outcome_pill.set_accent("success")
            self.outcome_pill.set_text(
                f"{len(groups)} document{'s' if len(groups) != 1 else ''} will be exported"
            )
        else:
            self.outcome_pill.set_accent("danger")
            self.outcome_pill.set_text("Nothing would be exported \u2014 keep at least one page")

        self.summary.setAccessibleName(
            f"{len(self.analysis.pages)} pages, {kept} kept, {separators} separator, "
            f"{blanks} removed, {len(groups)} documents would be exported"
        )

    # -- lifecycle -----------------------------------------------------
    def _reflow_columns(self) -> None:
        """Pick the column count that fits the current viewport width."""

        usable = self._scroll.viewport().width() - SPACE["xl"] * 2
        if usable <= 0:  # not laid out yet
            return
        columns = max(1, int((usable + SPACE["md"]) // (CARD_WIDTH + SPACE["md"])))
        if columns != self._columns:
            self._columns = columns
            self._relayout()

    def showEvent(self, event):  # noqa: N802 - Qt naming
        # The viewport only has its real width once the dialog is shown, so the
        # first accurate column count can not be computed in __init__.
        super().showEvent(event)
        self._reflow_columns()

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        """Re-flow the grid so cards always fill the available width."""

        super().resizeEvent(event)
        self._reflow_columns()

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


__all__ = ["DocumentReviewDialog", "PageCard", "STATUS_STYLE"]
