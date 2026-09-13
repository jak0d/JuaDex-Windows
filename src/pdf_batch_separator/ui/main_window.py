"""Main application window (PRD section 6).

A conventional Windows desktop utility: mode choice, settings, batch table,
footer actions.  All heavy work is delegated to worker threads.
"""

from __future__ import annotations

import logging
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.barcode import validate_separator_value
from ..core.batch import AnalysisSettings, CancellationToken
from ..core.exporter import cleanup_stale_temp_files
from ..core.models import (
    DEFAULT_SEPARATOR,
    PRESET_SEPARATORS,
    BatchSummary,
    BlankSensitivity,
    DocumentAnalysis,
    DocumentExportResult,
    ProcessingMode,
    WarningCode,
)
from ..core.report import build_report, write_report
from ..core.separator_pdf import SeparatorGenerationError, create_separator_pdf
from ..settings import AppSettings, SettingsStore
from ..workers import AnalysisWorker, ExportWorker
from . import components as ui
from . import icons
from .batch_delegate import ROW_HEIGHT, BatchRowDelegate
from .batch_model import BatchTableModel, RowState
from .document_review import DocumentReviewDialog
from .theme import SPACE, apply_theme, color

logger = logging.getLogger(__name__)

PRIVACY_TEXT = "Your PDFs are processed only on this PC."

# Author credit: kept in one place so the status bar and the About box never
# drift apart.
AUTHOR_HANDLE = "jak0d"
AUTHOR_PROFILE_URL = "https://github.com/jak0d"
COPYRIGHT_TEXT = "© 2026 jak0d"


class DropTableView(QTableView):
    """Table view that accepts dropped PDFs and folders.

    ``hover_changed`` lets the window highlight the empty-state drop zone while
    a drag is in flight, so the target is obvious before the user releases.
    """

    files_dropped = Signal(list)
    hover_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            self.hover_changed.emit(True)
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802
        self.hover_changed.emit(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        self.hover_changed.emit(False)
        urls = event.mimeData().urls()
        paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class MainWindow(QMainWindow):
    """The application's single main window."""

    def __init__(self, store: SettingsStore | None = None) -> None:
        super().__init__()
        self.store = store or SettingsStore()
        self.settings: AppSettings = self.store.load()

        # Set until the widgets have been populated from the loaded settings.
        # Widget signals fire while the UI is being built, and without this
        # guard they would persist half-initialised widget state over the
        # user's real preferences.
        self._loading = True

        self.model = BatchTableModel(self)
        self.token: CancellationToken | None = None
        self.thread: QThread | None = None
        self.worker = None
        self.busy = False
        self.phase = ""  # "analyze" | "export"
        self.analysis_signature: tuple | None = None
        self.last_summary: BatchSummary | None = None
        self.last_report_text: str = ""
        self._export_started_at = ""
        self._export_row_by_analysis_index: dict[int, int] = {}
        self.dark_mode = False

        self.setWindowTitle("PDF Batch Separator")
        self.resize(1180, 760)
        self.setMinimumSize(980, 660)
        self.setObjectName("mainWindow")

        self._build_ui()
        self._apply_settings_to_ui()
        self._loading = False
        self._update_actions()

        QTimer.singleShot(0, self._startup_cleanup)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_app_bar())
        root.addWidget(self._build_page_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        body_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._build_sidebar())
        self.splitter.addWidget(self._build_workspace())
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([352, 900])
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(SPACE["lg"])
        body_layout.addWidget(self.splitter)
        root.addWidget(body, 1)

        root.addWidget(self._build_action_bar())
        self.statusBar().showMessage(PRIVACY_TEXT)
        self._add_copyright_credit()

    def _add_copyright_credit(self) -> None:
        """Pin a small author credit to the bottom-right of the status bar.

        ``addPermanentWidget`` keeps it on screen whatever transient status
        message is showing, in the conventional spot for a copyright line.
        """

        self.copyright_label = ui.label(
            f'<a href="{AUTHOR_PROFILE_URL}">{COPYRIGHT_TEXT}</a>', "subtle"
        )
        self.copyright_label.setOpenExternalLinks(True)
        self.copyright_label.setToolTip(f"Author: {AUTHOR_HANDLE} on GitHub")
        self.copyright_label.setAccessibleName(
            f"Copyright {COPYRIGHT_TEXT}. Opens the author's GitHub profile."
        )
        self.statusBar().addPermanentWidget(self.copyright_label)

    # -- chrome ---------------------------------------------------------
    def _build_app_bar(self) -> QWidget:
        """Top bar: brand, offline assurance, batch identity and utilities."""

        bar = QWidget()
        bar.setObjectName("appBar")
        bar.setFixedHeight(58)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        layout.setSpacing(SPACE["md"])

        self.brand_mark = ui.BrandMark(30)
        layout.addWidget(self.brand_mark)
        self.wordmark = ui.label("JuaDex", "wordmark")
        layout.addWidget(self.wordmark)

        self.version_pill = ui.Pill(f"v{__version__}", "neutral", mono=True)
        self.version_pill.setToolTip(f"PDF Batch Separator {__version__}")
        layout.addWidget(self.version_pill)

        layout.addSpacing(SPACE["sm"])
        layout.addWidget(ui.divider(Qt.Orientation.Vertical))
        layout.addSpacing(SPACE["sm"])

        # The privacy promise is the product's core claim, so it lives in the
        # chrome rather than buried in an About box.
        self.offline_badge = ui.Pill("100% LOCAL", "success", uppercase=True)
        self.offline_badge.setToolTip(PRIVACY_TEXT)
        self.offline_badge.setAccessibleName(
            "Privacy notice: this application works offline. " + PRIVACY_TEXT
        )
        layout.addWidget(self.offline_badge)

        self.batch_pill = ui.Pill("NO BATCH LOADED", "neutral", mono=True)
        self.batch_pill.setToolTip("Files currently queued in this batch")
        layout.addWidget(self.batch_pill)

        layout.addStretch(1)

        self.theme_button = ui.icon_button(
            "moon", "Switch between light and dark appearance", checkable=True
        )
        self.theme_button.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.theme_button.toggled.connect(self._toggle_theme)
        layout.addWidget(self.theme_button)

        self.help_button = ui.icon_button(
            "help-circle", "Version, privacy and licence information (F1)"
        )
        self.help_button.setShortcut(QKeySequence(Qt.Key.Key_F1))
        self.help_button.clicked.connect(self._show_about)
        layout.addWidget(self.help_button)

        bar.setStyleSheet(
            f"QWidget#appBar {{ background: {color('surface')};"
            f" border-bottom: 1px solid {color('line')}; }}"
        )
        return bar

    def _build_page_header(self) -> QWidget:
        """Batch title, live metrics and the keyboard-shortcut card."""

        header = QWidget()
        header.setObjectName("pageHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(SPACE["lg"], SPACE["lg"], SPACE["lg"], SPACE["sm"])
        layout.setSpacing(SPACE["xl"])

        left = QVBoxLayout()
        left.setSpacing(SPACE["sm"])

        self.mode_eyebrow = ui.SectionHeader("Page separation", icon_name="scissors")
        left.addWidget(self.mode_eyebrow)

        self.batch_title = ui.label("Scanning Separation & Blank Cleanup", "display")
        self.batch_title.setWordWrap(True)
        left.addWidget(self.batch_title)

        stats = QHBoxLayout()
        stats.setSpacing(SPACE["lg"])
        self.stat_total = ui.StatChip("0", "Total Pages", "info")
        self.stat_separators = ui.StatChip("0", "Separator Sheets", "separator")
        self.stat_blanks = ui.StatChip("0", "Blank Pages", "warning")
        self.stat_content = ui.StatChip("0", "Documents Out", "success")
        for chip in (
            self.stat_total,
            self.stat_separators,
            self.stat_blanks,
            self.stat_content,
        ):
            stats.addWidget(chip)
        stats.addStretch(1)
        left.addLayout(stats)
        layout.addLayout(left, 1)

        layout.addWidget(self._build_shortcut_card(), 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_shortcut_card(self) -> QWidget:
        """A compact legend of the keyboard accelerators."""

        card = ui.Card(padding=SPACE["md"], spacing=SPACE["sm"])
        card.setMaximumWidth(340)

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])
        for keys, text in (("F5", "Analyse"), ("Ctrl+\u21b5", "Process")):
            row.addWidget(ui.KeyHint(keys))
            caption = ui.label(text, "subtle")
            row.addWidget(caption)
            row.addSpacing(SPACE["xs"])
        row.addStretch(1)
        card.body.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(SPACE["sm"])
        row2.addWidget(ui.KeyHint("Del"))
        row2.addWidget(ui.label("Remove file", "subtle"))
        row2.addSpacing(SPACE["xs"])
        row2.addWidget(ui.KeyHint("Enter"))
        row2.addWidget(ui.label("Review pages", "subtle"))
        row2.addStretch(1)
        card.body.addLayout(row2)
        return card

    # -- sidebar --------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        """The configuration column: mode, detection settings, destination."""

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(330)
        scroll.setMaximumWidth(430)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, SPACE["xs"], 0)
        layout.setSpacing(SPACE["md"])

        layout.addWidget(self._build_mode_card())
        layout.addWidget(self._build_settings_card())
        layout.addWidget(self._build_output_card())
        layout.addStretch(1)

        scroll.setWidget(panel)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return scroll

    def _build_mode_card(self) -> QWidget:
        card = ui.Card()
        card.body.addWidget(ui.SectionHeader("1 · What do you want to do?", icon_name="sliders"))

        self.mode_group = QButtonGroup(self)

        self.split_radio = QRadioButton("Split by separator")
        self.split_radio.setStyleSheet("font-weight: 700;")
        split_hint = ui.label(
            "Find the barcode separator sheets, remove them, and save each "
            "document between them as its own PDF.",
            "muted",
        )
        split_hint.setWordWrap(True)
        split_hint.setContentsMargins(25, 0, 0, 0)

        self.clean_radio = QRadioButton("Remove blank pages only")
        self.clean_radio.setStyleSheet("font-weight: 700;")
        clean_hint = ui.label(
            "Keep each PDF as one document and only remove the blank pages, "
            "such as empty backsides.",
            "muted",
        )
        clean_hint.setWordWrap(True)
        clean_hint.setContentsMargins(25, 0, 0, 0)

        self.mode_group.addButton(self.split_radio, 0)
        self.mode_group.addButton(self.clean_radio, 1)

        card.body.addWidget(self.split_radio)
        card.body.addWidget(split_hint)
        card.body.addSpacing(SPACE["xs"])
        card.body.addWidget(self.clean_radio)
        card.body.addWidget(clean_hint)
        self.mode_group.idToggled.connect(self._on_mode_changed)
        return card

    def _build_settings_card(self) -> QWidget:
        self.settings_box = ui.Card()
        body = self.settings_box.body
        body.addWidget(ui.SectionHeader("2 · Detection settings", icon_name="barcode"))

        self.separator_label = ui.label("Separator barcode value", "muted")
        body.addWidget(self.separator_label)

        self.separator_combo = QComboBox()
        self.separator_combo.setEditable(False)
        for preset in PRESET_SEPARATORS:
            self.separator_combo.addItem(preset, preset)
        self.separator_combo.addItem("Custom value\u2026", "")
        self.separator_combo.setAccessibleName("Separator barcode preset")
        self.separator_combo.currentIndexChanged.connect(self._on_preset_changed)
        body.addWidget(self.separator_combo)

        self.separator_edit = QLineEdit()
        self.separator_edit.setMaxLength(128)
        self.separator_edit.setProperty("variant", "path")
        self.separator_edit.setPlaceholderText("Enter the exact barcode text")
        self.separator_edit.setAccessibleName("Custom separator barcode value")
        self.separator_edit.textChanged.connect(self._on_separator_text_changed)
        body.addWidget(self.separator_edit)

        self.separator_error = ui.label("", "error")
        self.separator_error.setWordWrap(True)
        self.separator_error.setVisible(False)
        body.addWidget(self.separator_error)

        self.print_button = ui.text_button(
            "Create printable separator sheet\u2026",
            icon_name="printer",
            tooltip="Save an A4 PDF with this barcode that you can print and use as a separator.",
        )
        self.print_button.clicked.connect(self._create_separator_sheet)
        body.addWidget(self.print_button)

        body.addSpacing(SPACE["xs"])
        body.addWidget(ui.divider())
        body.addSpacing(SPACE["xs"])

        self.blank_check = QCheckBox("Also remove blank pages")
        self.blank_check.setStyleSheet("font-weight: 600;")
        self.blank_check.toggled.connect(self._on_blank_toggled)
        body.addWidget(self.blank_check)

        self.sensitivity_label = ui.label("Blank page sensitivity", "muted")
        body.addWidget(self.sensitivity_label)

        self.sensitivity_combo = QComboBox()
        for level in BlankSensitivity:
            self.sensitivity_combo.addItem(level.label, level.value)
        self.sensitivity_combo.setAccessibleName("Blank page sensitivity")
        self.sensitivity_combo.currentIndexChanged.connect(self._on_sensitivity_changed)
        body.addWidget(self.sensitivity_combo)

        self.sensitivity_hint = ui.label("", "subtle")
        self.sensitivity_hint.setWordWrap(True)
        body.addWidget(self.sensitivity_hint)
        return self.settings_box

    def _build_output_card(self) -> QWidget:
        card = ui.Card()
        card.body.addWidget(ui.SectionHeader("3 · Output folder", icon_name="folder"))

        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setProperty("variant", "path")
        self.output_edit.setPlaceholderText("Choose where to save the results")
        self.output_edit.setAccessibleName("Output folder")
        card.body.addWidget(self.output_edit)

        buttons = QHBoxLayout()
        buttons.setSpacing(SPACE["sm"])
        self.choose_output_button = ui.text_button("Choose folder\u2026", icon_name="folder-open")
        self.choose_output_button.clicked.connect(self._choose_output_folder)
        buttons.addWidget(self.choose_output_button, 1)
        self.open_output_button = ui.text_button(
            "Open",
            icon_name="external-link",
            tooltip="Open the output folder in File Explorer",
        )
        self.open_output_button.clicked.connect(self._open_output_folder)
        buttons.addWidget(self.open_output_button)
        card.body.addLayout(buttons)

        self.recursive_check = QCheckBox("Include subfolders when adding a folder")
        self.recursive_check.toggled.connect(self._on_recursive_toggled)
        card.body.addWidget(self.recursive_check)
        return card

    # -- workspace ------------------------------------------------------
    def _build_workspace(self) -> QWidget:
        """The batch list with its toolbar, empty state and warning rail."""

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])

        layout.addWidget(self._build_toolbar())

        self.table = DropTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(BatchRowDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.setSortingEnabled(False)
        self.table.files_dropped.connect(self._on_files_dropped)
        self.table.hover_changed.connect(self._on_drop_hover)
        self.table.doubleClicked.connect(lambda _: self._review_selected())
        self.table.setAccessibleName("List of PDF files to process")

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(BatchTableModel.COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        header.setFixedHeight(34)
        for column, width in (
            (BatchTableModel.COL_PAGES, 74),
            (BatchTableModel.COL_SEP, 128),
            (BatchTableModel.COL_BLANK, 118),
            (BatchTableModel.COL_OUT, 104),
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        header.setSectionResizeMode(
            BatchTableModel.COL_STATUS, QHeaderView.ResizeMode.Fixed
        )
        self.table.setColumnWidth(BatchTableModel.COL_STATUS, 186)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_actions()
        )
        layout.addWidget(self.table, 1)

        self.empty_hint = ui.DropZone()
        self.empty_hint.clicked.connect(self._add_files)
        self.empty_hint.files_dropped.connect(self._on_files_dropped)
        layout.addWidget(self.empty_hint, 1)
        # The list and its empty state occupy the same slot; only one shows.
        self.table.setVisible(False)

        layout.addWidget(self._build_detail_rail())
        return panel

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self.add_files_button = ui.text_button(
            "Add files", icon_name="file-plus", kind="info"
        )
        self.add_files_button.clicked.connect(self._add_files)
        self.add_folder_button = ui.text_button("Add folder", icon_name="folder-plus")
        self.add_folder_button.clicked.connect(self._add_folder)
        self.remove_button = ui.text_button("Remove", icon_name="x")
        self.remove_button.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = ui.text_button("Clear list", icon_name="trash")
        self.clear_button.clicked.connect(self._clear_list)

        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
        ):
            layout.addWidget(button)

        layout.addStretch(1)

        self.review_button = ui.text_button(
            "Review pages\u2026",
            icon_name="eye",
            tooltip="Look at the detected pages and correct them before processing",
        )
        self.review_button.clicked.connect(self._review_selected)
        layout.addWidget(self.review_button)
        return bar

    def _build_detail_rail(self) -> QWidget:
        """Contextual warnings plus the per-file resolution choices."""

        self.detail_card = ui.Card(
            accent="warning", accent_fill=True, padding=SPACE["md"], spacing=SPACE["sm"]
        )

        top = QHBoxLayout()
        top.setSpacing(SPACE["sm"])
        self.detail_icon = QLabel()
        self.detail_icon.setFixedSize(16, 16)
        self.detail_icon.setPixmap(
            icons.pixmap("alert-triangle", color("warning_soft_fg"), 16)
        )
        top.addWidget(self.detail_icon, 0, Qt.AlignmentFlag.AlignTop)

        self.detail = ui.label("", "body")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.detail, 1)
        self.detail_card.body.addLayout(top)

        self.resolve_bar = QWidget()
        resolve_layout = QHBoxLayout(self.resolve_bar)
        resolve_layout.setContentsMargins(26, 0, 0, 0)
        resolve_layout.setSpacing(SPACE["sm"])

        resolve_layout.addWidget(ui.label("For the selected file:", "subtle"))
        self.copy_one_button = ui.text_button(
            "Save as one cleaned document",
            icon_name="copy",
            kind="info-outline",
            tooltip="Do not split this file; write a single cleaned copy instead.",
        )
        self.copy_one_button.clicked.connect(self._resolve_as_single_copy)
        self.skip_button = ui.text_button(
            "Skip this file", icon_name="slash-circle", kind="danger-outline"
        )
        self.skip_button.clicked.connect(self._resolve_as_skip)
        self.unskip_button = ui.text_button("Include again", icon_name="rotate-ccw")
        self.unskip_button.clicked.connect(self._resolve_unskip)
        for button in (self.copy_one_button, self.skip_button, self.unskip_button):
            resolve_layout.addWidget(button)
        resolve_layout.addStretch(1)

        self.detail_card.body.addWidget(self.resolve_bar)
        self.resolve_bar.setVisible(False)
        self.detail_card.setVisible(False)
        return self.detail_card

    # -- action bar -----------------------------------------------------
    def _build_action_bar(self) -> QWidget:
        """The sticky footer: selection summary, progress and commit actions."""

        bar = QWidget()
        bar.setObjectName("actionBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(SPACE["md"])

        self.selection_count = ui.Pill("0", "neutral", solid=True)
        self.selection_count.setFixedWidth(34)
        layout.addWidget(self.selection_count)

        summary = QVBoxLayout()
        summary.setSpacing(0)
        self.selection_title = ui.label("No files queued", "body")
        self.selection_title.setStyleSheet("font-weight: 700;")
        summary.addWidget(self.selection_title)
        self.selection_hint = ui.label("Add scanned PDFs to begin", "subtle")
        summary.addWidget(self.selection_hint)
        layout.addLayout(summary)

        layout.addSpacing(SPACE["lg"])

        progress_box = QVBoxLayout()
        progress_box.setSpacing(SPACE["xs"])
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        self.progress.setMinimumWidth(220)
        self.progress.setAccessibleName("Overall progress")
        progress_box.addWidget(self.progress)
        self.progress_label = ui.label("", "subtle")
        progress_box.addWidget(self.progress_label)
        layout.addLayout(progress_box, 1)

        self.cancel_button = ui.text_button("Cancel", icon_name="x")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setEnabled(False)
        layout.addWidget(self.cancel_button)

        self.analyze_button = ui.text_button(
            "Analyse",
            icon_name="search",
            tooltip="Check the PDFs and show what would happen (F5)",
        )
        self.analyze_button.setShortcut(QKeySequence(Qt.Key.Key_F5))
        self.analyze_button.clicked.connect(self._start_analysis)
        layout.addWidget(self.analyze_button)

        self.process_button = ui.text_button(
            "Process batch", icon_name="zap", kind="primary"
        )
        self.process_button.setObjectName("processButton")
        self.process_button.setProperty("role", "primary")
        self.process_button.setShortcut(QKeySequence("Ctrl+Return"))
        self.process_button.setDefault(True)
        self.process_button.clicked.connect(self._start_export)
        layout.addWidget(self.process_button)

        bar.setStyleSheet(
            f"QWidget#actionBar {{ background: {color('surface')};"
            f" border-top: 1px solid {color('line')}; }}"
        )
        return bar

    def _toggle_theme(self, dark: bool) -> None:
        """Switch appearance without rebuilding the active batch or review state."""
        self.dark_mode = dark
        app = QGuiApplication.instance()
        if app is not None:
            apply_theme(app, dark=dark)

        # Widgets that bake tokens into their own stylesheet (or cache tinted
        # pixmaps) cannot be restyled by the global sheet alone, so refresh the
        # icon cache and re-emit the few values that were computed at build time.
        icons.clear_cache()
        self.theme_button.setIcon(icons.icon("sun" if dark else "moon", "muted", 16))
        self.theme_button.setToolTip(
            "Switch to light appearance" if dark else "Switch to dark appearance"
        )
        self.brand_mark.update()
        self._restyle_chrome()
        self.statusBar().showMessage(
            "Dark appearance enabled." if dark else "Light appearance enabled.", 3000
        )
        self._persist()

    def _restyle_chrome(self) -> None:
        """Re-apply palette-dependent styling after a theme change."""

        for name, widget in (
            ("appBar", self.centralWidget().findChild(QWidget, "appBar")),
            ("actionBar", self.centralWidget().findChild(QWidget, "actionBar")),
        ):
            if widget is None:  # pragma: no cover - defensive
                continue
            edge = "border-bottom" if name == "appBar" else "border-top"
            widget.setStyleSheet(
                f"QWidget#{name} {{ background: {color('surface')};"
                f" {edge}: 1px solid {color('line')}; }}"
            )

        for pill in (
            self.version_pill,
            self.offline_badge,
            self.batch_pill,
            self.selection_count,
        ):
            pill.set_accent(pill._accent)
        self.detail_card.set_accent(self.detail_card._accent, self.detail_card._accent_fill)
        self.detail_icon.setPixmap(
            icons.pixmap("alert-triangle", color("warning_soft_fg"), 16)
        )
        for chip in (
            self.stat_total,
            self.stat_separators,
            self.stat_blanks,
            self.stat_content,
        ):
            chip.set_value(chip._value)
        self._update_sensitivity_hint()
        self._refresh_stats()
        self.model.emit_all_changed()
        self.table.viewport().update()

    # ------------------------------------------------------------------
    # Analysis attention helper
    # ------------------------------------------------------------------
    def _select_first_attention(self) -> bool:
        """Select the first row whose details can help the user move forward."""

        for index, row in enumerate(self.model.rows):
            if row.skipped_by_user:
                continue
            if row.analysis and (row.blocked or row.analysis.failed or row.display_warnings()):
                self.table.selectRow(index)
                self.table.scrollTo(
                    self.model.index(index, 0),
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self.table.setFocus(Qt.FocusReason.OtherFocusReason)
                if row.blocked and row.analysis.has_warning(WarningCode.NO_SEPARATOR_FOUND):
                    self.statusBar().showMessage(
                        "Choose “Save as one cleaned document”, skip the file, or review pages to mark a separator.",
                        9000,
                    )
                elif row.analysis.failed:
                    self.statusBar().showMessage("The selected file could not be analysed.", 7000)
                else:
                    self.statusBar().showMessage("Review the selected warning before processing.", 7000)
                return True
        return False

    # ------------------------------------------------------------------
    # Settings binding
    # ------------------------------------------------------------------
    def _apply_settings_to_ui(self) -> None:
        blocked = [
            self.separator_combo,
            self.separator_edit,
            self.blank_check,
            self.sensitivity_combo,
            self.recursive_check,
        ]
        for widget in blocked:
            widget.blockSignals(True)

        if self.settings.mode is ProcessingMode.SPLIT:
            self.split_radio.setChecked(True)
        else:
            self.clean_radio.setChecked(True)

        value = self.settings.separator_value
        if value in PRESET_SEPARATORS:
            self.separator_combo.setCurrentIndex(PRESET_SEPARATORS.index(value))
        else:
            self.separator_combo.setCurrentIndex(self.separator_combo.count() - 1)
        self.separator_edit.setText(value)

        self.blank_check.setChecked(self.settings.remove_blanks)
        index = self.sensitivity_combo.findData(self.settings.blank_sensitivity.value)
        self.sensitivity_combo.setCurrentIndex(max(0, index))
        self.recursive_check.setChecked(self.settings.recursive)
        self.output_edit.setText(self.settings.output_folder)

        # Restore the remembered appearance. "system" keeps the light default
        # rather than guessing, so the first run always looks the same.
        if self.settings.theme == "dark":
            self.theme_button.blockSignals(True)
            self.theme_button.setChecked(True)
            self.theme_button.blockSignals(False)
            self._toggle_theme(True)

        for widget in blocked:
            widget.blockSignals(False)

        self._sync_mode_controls()
        self._update_sensitivity_hint()

    def _persist(self) -> None:
        if self._loading:
            return
        self.settings.separator_value = self.separator_edit.text().strip() or DEFAULT_SEPARATOR
        self.settings.mode = (
            ProcessingMode.SPLIT if self.split_radio.isChecked() else ProcessingMode.CLEAN_ONLY
        )
        self.settings.remove_blanks = self.blank_check.isChecked()
        self.settings.blank_sensitivity = BlankSensitivity(
            self.sensitivity_combo.currentData()
        )
        self.settings.recursive = self.recursive_check.isChecked()
        self.settings.output_folder = self.output_edit.text()
        self.settings.theme = "dark" if self.dark_mode else "light"
        self.store.save(self.settings)

    def _current_settings(self) -> AnalysisSettings:
        mode = (
            ProcessingMode.SPLIT if self.split_radio.isChecked() else ProcessingMode.CLEAN_ONLY
        )
        return AnalysisSettings(
            mode=mode,
            expected_separator=(
                self.separator_edit.text().strip() if mode is ProcessingMode.SPLIT else None
            ),
            remove_blanks=(
                self.blank_check.isChecked() if mode is ProcessingMode.SPLIT else True
            ),
            blank_sensitivity=BlankSensitivity(self.sensitivity_combo.currentData()),
        )

    # ------------------------------------------------------------------
    # Settings-change handlers (all invalidate the cached analysis)
    # ------------------------------------------------------------------
    def _sync_mode_controls(self) -> None:
        split = self.split_radio.isChecked()

        # The page header narrates the active mode.
        self.batch_title.setText(
            "Scanning Separation & Blank Cleanup" if split else "Blank Page Cleanup"
        )

        for widget in (
            self.separator_label,
            self.separator_combo,
            self.separator_edit,
            self.print_button,
        ):
            widget.setVisible(split)
        self.separator_error.setVisible(split and bool(self.separator_error.text()))
        self.blank_check.setVisible(split)

        custom = self.separator_combo.currentIndex() == self.separator_combo.count() - 1
        self.separator_edit.setEnabled(custom and split)

        blanks_on = (not split) or self.blank_check.isChecked()
        self.sensitivity_label.setVisible(blanks_on)
        self.sensitivity_combo.setVisible(blanks_on)
        self.sensitivity_hint.setVisible(blanks_on)

    def _invalidate_analysis(self, reason: str = "") -> None:
        if self._loading:
            return
        if self.analysis_signature is None:
            return
        self.analysis_signature = None
        self.model.reset_analysis()
        for row in self.model.rows:
            row.skipped_by_user = False
        if reason:
            self.statusBar().showMessage(f"{reason} Analyse again to refresh.", 6000)
        self._update_actions()

    @Slot(int, bool)
    def _on_mode_changed(self, _id: int, checked: bool) -> None:
        if not checked:
            return
        self._sync_mode_controls()
        self._invalidate_analysis("The mode changed.")
        self._persist()

    def _on_preset_changed(self, index: int) -> None:
        data = self.separator_combo.itemData(index)
        if data:
            self.separator_edit.setText(str(data))
        self._sync_mode_controls()

    def _on_separator_text_changed(self, text: str) -> None:
        valid, message = validate_separator_value(text)
        self.separator_error.setText("" if valid else message)
        self.separator_error.setVisible(bool(message) and self.split_radio.isChecked())
        self._invalidate_analysis("The separator value changed.")
        self._update_actions()
        if valid:
            self._persist()

    def _on_blank_toggled(self, _checked: bool) -> None:
        self._sync_mode_controls()
        self._invalidate_analysis("The blank page option changed.")
        self._persist()

    def _on_sensitivity_changed(self, _index: int) -> None:
        self._update_sensitivity_hint()
        self._invalidate_analysis("The blank page sensitivity changed.")
        self._persist()

    def _on_recursive_toggled(self, _checked: bool) -> None:
        self._persist()

    def _update_sensitivity_hint(self) -> None:
        data = self.sensitivity_combo.currentData()
        if not data:
            return
        level = BlankSensitivity(data)
        self.sensitivity_hint.setText(level.description)
        if level is BlankSensitivity.AGGRESSIVE:
            self.sensitivity_hint.setStyleSheet(
                f"color: {color('warning_soft_fg')}; font-weight: 600;"
            )
        else:
            self.sensitivity_hint.setStyleSheet(f"color: {color('subtle')};")

    # ------------------------------------------------------------------
    # Input management
    # ------------------------------------------------------------------
    def _add_paths(self, paths: list[Path]) -> None:
        pdfs: list[Path] = []
        ignored: list[str] = []
        output_folder = Path(self.output_edit.text()) if self.output_edit.text() else None

        for path in paths:
            if path.is_dir():
                found, skipped = self._scan_folder(path, output_folder)
                pdfs.extend(found)
                ignored.extend(skipped)
            elif path.suffix.lower() == ".pdf":
                pdfs.append(path)
            else:
                ignored.append(path.name)

        added, duplicates = self.model.add_paths(pdfs)
        if added:
            self._invalidate_analysis()
            if not self.output_edit.text() and pdfs:
                suggestion = pdfs[0].parent / "Processed"
                self.output_edit.setText(str(suggestion))
                self._persist()

        parts = []
        if added:
            parts.append(f"Added {added} PDF(s).")
        if duplicates:
            parts.append(f"{duplicates} already in the list.")
        if ignored:
            preview = ", ".join(ignored[:3])
            more = f" and {len(ignored) - 3} more" if len(ignored) > 3 else ""
            parts.append(f"Ignored non-PDF files: {preview}{more}.")
        if parts:
            self.statusBar().showMessage(" ".join(parts), 8000)
        self._refresh_empty_hint()
        self._update_actions()

    def _scan_folder(
        self, folder: Path, output_folder: Path | None
    ) -> tuple[list[Path], list[str]]:
        """Collect PDFs, excluding the active output directory (PRD 6.3)."""

        from ..core.naming import is_within

        pdfs: list[Path] = []
        ignored: list[str] = []
        pattern = "**/*" if self.recursive_check.isChecked() else "*"
        try:
            for entry in sorted(folder.glob(pattern)):
                if entry.is_dir():
                    continue
                if output_folder and is_within(entry, output_folder):
                    continue  # never re-ingest our own output
                if entry.suffix.lower() == ".pdf":
                    pdfs.append(entry)
                else:
                    ignored.append(entry.name)
        except OSError as exc:  # pragma: no cover - permission denied
            QMessageBox.warning(
                self, "Folder could not be read", f"{folder}\n\n{exc}"
            )
        return pdfs, ignored

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add PDF files", str(Path.home()), "PDF files (*.pdf)"
        )
        if paths:
            self._add_paths([Path(p) for p in paths])

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add folder", str(Path.home()))
        if folder:
            self._add_paths([Path(folder)])

    def _on_files_dropped(self, paths: list[Path]) -> None:
        self._add_paths(paths)

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _remove_selected(self) -> None:
        rows = self._selected_rows()
        if rows:
            self.model.remove_rows(rows)
            self._refresh_empty_hint()
            self._update_actions()

    def _clear_list(self) -> None:
        if not self.model.rows:
            return
        self.model.clear()
        self.analysis_signature = None
        self._refresh_empty_hint()
        self._update_actions()

    def _refresh_empty_hint(self) -> None:
        empty = not self.model.rows
        self.empty_hint.setVisible(empty)
        self.table.setVisible(not empty)
        self._refresh_stats()

    def _on_drop_hover(self, hovering: bool) -> None:
        self.empty_hint.set_hover(hovering)

    def _refresh_stats(self) -> None:
        """Update the header metrics and the footer selection summary."""

        rows = self.model.rows
        analysed = [row for row in rows if row.analysis and not row.analysis.failed]

        pages = sum(row.page_count for row in analysed)
        separators = sum(len(row.separator_pages) for row in analysed)
        blanks = sum(len(row.blank_pages) for row in analysed)
        outputs = sum(row.expected_outputs for row in analysed)

        self.stat_total.set_value(str(pages))
        self.stat_separators.set_value(str(separators))
        self.stat_blanks.set_value(str(blanks))
        self.stat_content.set_value(str(outputs))

        # Batch identity chip
        if not rows:
            self.batch_pill.set_text("NO BATCH LOADED")
        else:
            self.batch_pill.set_text(f"BATCH: {len(rows)} FILE{'S' if len(rows) != 1 else ''}")

        # Footer summary
        self.selection_count.set_text(str(len(rows)))
        if not rows:
            self.selection_title.setText("No files queued")
            self.selection_hint.setText("Add scanned PDFs to begin")
            return

        ready = sum(
            1 for row in rows
            if row.analysis and not row.blocked and not row.skipped_by_user
        )
        attention = sum(1 for row in rows if row.state is RowState.WARNING)
        failed = sum(1 for row in rows if row.state is RowState.ERROR)

        self.selection_title.setText(
            f"{len(rows)} file{'s' if len(rows) != 1 else ''} queued"
        )
        if self.analysis_signature is None:
            self.selection_hint.setText("Not analysed yet \u2014 press Analyse (F5)")
            return

        parts = [f"{ready} ready"]
        if attention:
            parts.append(f"{attention} need attention")
        if failed:
            parts.append(f"{failed} failed")
        parts.append(f"{outputs} document{'s' if outputs != 1 else ''} to export")
        self.selection_hint.setText(" \u00b7 ".join(parts))

    # ------------------------------------------------------------------
    # Output folder
    # ------------------------------------------------------------------
    def _choose_output_folder(self) -> None:
        start = self.output_edit.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if folder:
            self.output_edit.setText(folder)
            self._persist()
            self._update_actions()

    def _open_output_folder(self) -> None:
        folder = self.output_edit.text()
        if not folder:
            return
        path = Path(folder)
        if not path.exists():
            QMessageBox.information(
                self, "Folder not created yet",
                "The output folder will be created when you process the batch.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------
    # Separator sheet
    # ------------------------------------------------------------------
    def _create_separator_sheet(self) -> None:
        value = self.separator_edit.text().strip()
        valid, message = validate_separator_value(value)
        if not valid:
            QMessageBox.warning(self, "Cannot create separator sheet", message)
            return

        default_name = f"Separator sheet - {value}.pdf"
        safe_default = "".join(c for c in default_name if c not in '<>:"/\\|?*')
        start = Path(self.output_edit.text() or Path.home()) / safe_default
        path, _ = QFileDialog.getSaveFileName(
            self, "Save separator sheet", str(start), "PDF files (*.pdf)"
        )
        if not path:
            return
        try:
            created = create_separator_pdf(value, Path(path))
        except SeparatorGenerationError as exc:
            QMessageBox.critical(self, "Could not create separator sheet", str(exc))
            return

        answer = QMessageBox.information(
            self,
            "Separator sheet saved",
            f"Saved to:\n{created}\n\nPrint this page at 100% scale and place it "
            "between your documents before scanning.",
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )
        if answer == QMessageBox.StandardButton.Open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(created)))

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    def _start_analysis(self) -> None:
        if self.busy or not self.model.rows:
            return
        settings = self._current_settings()
        if settings.mode is ProcessingMode.SPLIT:
            valid, message = validate_separator_value(settings.expected_separator or "")
            if not valid:
                QMessageBox.warning(self, "Check the separator value", message)
                return

        self.model.reset_analysis()
        for row in self.model.rows:
            row.skipped_by_user = False
        self.last_summary = None

        self.token = CancellationToken()
        self.worker = AnalysisWorker(self.model.paths(), settings, self.token)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.file_started.connect(self._on_analysis_started)
        self.worker.file_progress.connect(self._on_analysis_progress)
        self.worker.file_finished.connect(self._on_analysis_file_done)
        self.worker.batch_finished.connect(self._on_analysis_done)
        self.worker.failed.connect(self._on_worker_failed)

        self.phase = "analyze"
        self._set_busy(True, f"Analysing {len(self.model.rows)} file(s)\u2026")
        self.progress.setRange(0, len(self.model.rows))
        self.progress.setValue(0)
        self._pending_settings = settings
        self.thread.start()

    @Slot(int, str)
    def _on_analysis_started(self, index: int, _path: str) -> None:
        row = self.model.row_at(index)
        if row:
            row.state = RowState.ANALYZING
            row.message = "Analysing\u2026"
            self.model.emit_row_changed(index)

    @Slot(int, int, int)
    def _on_analysis_progress(self, index: int, done: int, total: int) -> None:
        row = self.model.row_at(index)
        if row:
            row.pages_done, row.pages_total = done, total
            self.model.emit_row_changed(index)

    @Slot(int, object)
    def _on_analysis_file_done(self, index: int, analysis: DocumentAnalysis) -> None:
        row = self.model.row_at(index)
        if row:
            row.analysis = analysis
            row.state = RowState.PENDING
            row.refresh_state()
            self.model.emit_row_changed(index)
        self.progress.setValue(min(self.progress.value() + 1, self.progress.maximum()))
        self.progress_label.setText(
            f"{self.progress.value()} of {self.progress.maximum()} analysed"
        )

    @Slot(list)
    def _on_analysis_done(self, _results: list) -> None:
        cancelled = bool(self.token and self.token.cancelled)
        self.analysis_signature = None if cancelled else self._pending_settings.signature()
        self._teardown_thread()
        self._set_busy(False)
        for row in self.model.rows:
            row.refresh_state()
        self.model.emit_all_changed()

        if cancelled:
            self.statusBar().showMessage("Analysis cancelled.", 6000)
        else:
            warnings = sum(1 for r in self.model.rows if r.state is RowState.WARNING)
            errors = sum(1 for r in self.model.rows if r.state is RowState.ERROR)
            message = "Analysis finished."
            if warnings:
                message += f" {warnings} file(s) need attention."
            if errors:
                message += f" {errors} file(s) failed."
            self.statusBar().showMessage(message, 10000)
            if warnings or errors:
                self._select_first_attention()
        self._update_actions()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _start_export(self) -> None:
        if self.busy:
            return
        output_folder = self.output_edit.text().strip()
        if not output_folder:
            QMessageBox.information(
                self, "Choose an output folder", "Select where the results should be saved."
            )
            return

        exportable = [
            row for row in self.model.rows if not row.blocked and not row.skipped_by_user
        ]
        if not exportable:
            QMessageBox.information(
                self,
                "Nothing to process",
                "No file is ready to process. Resolve the warnings, or choose how to "
                "handle files where no separator was found.",
            )
            return

        blocked = [row for row in self.model.rows if row.blocked]
        if blocked and not self.confirm_skipping_blocked(blocked, len(exportable)):
            return

        if any(row.analysis and row.analysis.is_signed for row in exportable):
            if not self.settings.warned_about_signatures:
                if not self.confirm_signed_documents():
                    return
                self.settings.warned_about_signatures = True
                self._persist()

        folder = Path(output_folder)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(
                self, "Output folder unavailable",
                f"The output folder could not be created:\n{folder}\n\n{exc}",
            )
            return

        self.model.reset_results()
        analyses = []
        self._export_row_by_analysis_index = {}
        for row_index, row in enumerate(self.model.rows):
            if row.analysis:
                self._export_row_by_analysis_index[len(analyses)] = row_index
                analyses.append(row.analysis)
                if not row.blocked and not row.skipped_by_user:
                    row.state = RowState.EXPORTING
                    row.message = "Processing…"
                    self.model.emit_row_changed(row_index)
        overrides = {
            Path(row.analysis.source_path): row.overrides
            for row in self.model.rows
            if row.analysis and not row.overrides.is_empty
        }
        allow = {
            Path(row.analysis.source_path)
            for row in self.model.rows
            if row.analysis and row.allow_unsplit
        }
        skip = {
            Path(row.analysis.source_path)
            for row in self.model.rows
            if row.analysis and (row.skipped_by_user or row.blocked)
        }

        self.token = CancellationToken()
        self.worker = ExportWorker(analyses, folder, overrides, allow, skip, self.token)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.file_finished.connect(self._on_export_file_done)
        self.worker.batch_finished.connect(self._on_export_done)
        self.worker.failed.connect(self._on_worker_failed)

        self.phase = "export"
        self._export_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._set_busy(True, f"Processing {len(exportable)} file(s)\u2026")
        self.progress.setRange(0, len(analyses))
        self.progress.setValue(0)
        self.thread.start()

    # -- confirmations (separated so tests can drive them headlessly) ---
    def confirm_skipping_blocked(self, blocked: list, exportable_count: int) -> bool:
        """Ask before processing a batch where some files must be left out."""

        names = "\n".join(f"  \u2022 {row.name}" for row in blocked[:6])
        more = f"\n  \u2026and {len(blocked) - 6} more" if len(blocked) > 6 else ""
        answer = QMessageBox.question(
            self,
            "Some files will be left out",
            f"{len(blocked)} file(s) cannot be processed as configured:\n\n"
            f"{names}{more}\n\nProcess the remaining {exportable_count} file(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_signed_documents(self) -> bool:
        """Warn that rewriting pages invalidates existing digital signatures."""

        answer = QMessageBox.warning(
            self,
            "Digital signatures will not be preserved",
            "At least one PDF appears to be digitally signed. Because pages are "
            "rewritten, the exported documents will not keep the original "
            "signature validity.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    @Slot(int, object)
    def _on_export_file_done(self, index: int, result: DocumentExportResult) -> None:
        row_index = self._export_row_by_analysis_index.get(index, index)
        row = self.model.row_at(row_index)
        if row:
            row.export_result = result
            row.state = RowState.PENDING
            row.refresh_state()
            self.model.emit_row_changed(row_index)
        self.progress.setValue(min(self.progress.value() + 1, self.progress.maximum()))
        self.progress_label.setText(
            f"{self.progress.value()} of {self.progress.maximum()} files checked"
        )

    @Slot(list)
    def _on_export_done(self, results: list) -> None:
        cancelled = bool(self.token and self.token.cancelled)
        self._teardown_thread()
        self._set_busy(False)

        folder = Path(self.output_edit.text())
        summary = BatchSummary(
            output_folder=folder,
            results=tuple(results),
            cancelled=cancelled,
            started_at=self._export_started_at,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.last_summary = summary

        analyses = {
            Path(row.analysis.source_path): row.analysis
            for row in self.model.rows
            if row.analysis
        }
        settings = self._current_settings()
        self.last_report_text = build_report(
            summary,
            analyses,
            mode=settings.mode,
            separator=settings.expected_separator,
            remove_blanks=settings.remove_blanks,
            sensitivity=settings.blank_sensitivity,
            app_version=__version__,
        )
        report_path = None
        if results:
            try:
                report_path = write_report(self.last_report_text, folder)
            except OSError as exc:  # pragma: no cover
                logger.warning("Could not write report: %s", exc)

        for row in self.model.rows:
            row.refresh_state()
        self.model.emit_all_changed()
        self._update_actions()
        self._show_summary(summary, report_path)

    def _show_summary(self, summary: BatchSummary, report_path: Path | None) -> None:
        lines = [
            f"PDFs processed: {summary.documents_processed}",
            f"Documents created: {summary.outputs_created}",
            f"Separator pages removed: {summary.separators_removed}",
            f"Blank pages removed: {summary.blanks_removed}",
        ]
        if summary.skipped:
            lines.append(f"Files skipped: {len(summary.skipped)}")
        if summary.failures:
            lines.append(f"Files failed: {len(summary.failures)}")
        if summary.cancelled:
            lines.insert(0, "The run was cancelled; finished documents were kept.")

        box = QMessageBox(self)
        box.setWindowTitle("Batch finished")
        box.setIcon(
            QMessageBox.Icon.Warning
            if (summary.failures or summary.skipped)
            else QMessageBox.Icon.Information
        )
        box.setText("\n".join(lines))
        detail = f"Output folder:\n{summary.output_folder}"
        if report_path:
            detail += f"\n\nReport:\n{report_path.name}"
        box.setInformativeText(detail)

        open_button = box.addButton("Open output folder", QMessageBox.ButtonRole.AcceptRole)
        copy_button = box.addButton("Copy report", QMessageBox.ButtonRole.ActionRole)
        another_button = box.addButton(
            "Process another batch", QMessageBox.ButtonRole.ResetRole
        )
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()

        clicked = box.clickedButton()
        if clicked is open_button:
            self._open_output_folder()
        elif clicked is copy_button:
            QGuiApplication.clipboard().setText(self.last_report_text)
            self.statusBar().showMessage("Report copied to the clipboard.", 5000)
        elif clicked is another_button:
            self._clear_list()

    # ------------------------------------------------------------------
    # Warning resolution
    # ------------------------------------------------------------------
    def _resolve_as_single_copy(self) -> None:
        for index in self._selected_rows():
            row = self.model.row_at(index)
            if row and row.analysis and not row.analysis.failed:
                row.allow_unsplit = True
                row.skipped_by_user = False
                row.refresh_state()
                self.model.emit_row_changed(index)
        self._update_actions()

    def _resolve_as_skip(self) -> None:
        for index in self._selected_rows():
            row = self.model.row_at(index)
            if row:
                row.skipped_by_user = True
                row.refresh_state()
                self.model.emit_row_changed(index)
        self._update_actions()

    def _resolve_unskip(self) -> None:
        for index in self._selected_rows():
            row = self.model.row_at(index)
            if row:
                row.skipped_by_user = False
                row.refresh_state()
                self.model.emit_row_changed(index)
        self._update_actions()

    def _review_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        row = self.model.row_at(rows[0])
        if not row or not row.analysis or row.analysis.failed:
            QMessageBox.information(
                self, "Nothing to review",
                "Analyse this file first, or check the error message.",
            )
            return

        dialog = DocumentReviewDialog(row.analysis, row.overrides, self)
        if dialog.exec() == QDialog.DialogCode.Accepted.value:
            row.overrides = dialog.result_overrides
            row.refresh_state()
            self.model.emit_row_changed(rows[0])
            self._update_actions()

    # ------------------------------------------------------------------
    # Shared plumbing
    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        self.progress.setVisible(busy)
        if not busy:
            self.progress_label.setText("")
        if message:
            self.statusBar().showMessage(message)
        elif not busy:
            self.statusBar().showMessage(PRIVACY_TEXT)
        self._update_actions()

    def _update_actions(self) -> None:
        has_rows = bool(self.model.rows)
        analysed = self.analysis_signature is not None
        current = self._current_settings().signature()
        stale = analysed and current != self.analysis_signature
        selection = bool(self._selected_rows())

        separator_ok = True
        if self.split_radio.isChecked():
            separator_ok = validate_separator_value(self.separator_edit.text())[0]

        self.analyze_button.setEnabled(has_rows and not self.busy and separator_ok)
        self.analyze_button.setText("Refresh analysis" if analysed and not stale else "Analyse")

        ready = any(
            not row.blocked and not row.skipped_by_user and row.analysis
            for row in self.model.rows
        )
        self.process_button.setEnabled(
            analysed and not stale and ready and not self.busy and bool(self.output_edit.text())
        )
        self.cancel_button.setEnabled(self.busy)

        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.clear_button,
            self.choose_output_button,
        ):
            button.setEnabled(not self.busy)
        self.remove_button.setEnabled(selection and not self.busy)
        self.review_button.setEnabled(selection and not self.busy and analysed)

        self._refresh_stats()
        self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        rows = self._selected_rows()
        row = self.model.row_at(rows[0]) if rows else None

        if row is None or row.analysis is None:
            self.detail_card.setVisible(False)
            self.resolve_bar.setVisible(False)
            return

        analysis = row.effective_analysis() or row.analysis
        messages: list[str] = []
        accent = "warning"
        if analysis.failed:
            accent = "danger"
            messages.append(f"<b>{escape(row.name)}</b>: {escape(analysis.error or 'Failed')}")
        else:
            display_warnings = row.display_warnings()
            if display_warnings:
                accent = "warning"
                messages.extend(escape(warning.message) for warning in display_warnings)
            if row.allow_unsplit:
                if not display_warnings:
                    accent = "info"
                messages.append("This file will be saved as a single cleaned document.")
            if row.skipped_by_user:
                accent = "neutral"
                messages.append("This file will be skipped.")

        self.detail.setText("<br>".join(messages) if messages else "")
        self.detail_card.setVisible(bool(messages))

        # Re-tint the rail so its severity reads at a glance.
        if messages:
            self.detail_card.set_accent(accent, fill=True)
            glyph = {
                "danger": "x-circle",
                "info": "info",
                "neutral": "slash-circle",
            }.get(accent, "alert-triangle")
            self.detail_icon.setPixmap(
                icons.pixmap(glyph, color(f"{accent}_soft_fg"), 16)
            )

        needs_choice = bool(
            analysis
            and not analysis.failed
            and analysis.mode is ProcessingMode.SPLIT
            and analysis.has_warning(WarningCode.NO_SEPARATOR_FOUND)
        )
        self.resolve_bar.setVisible(needs_choice or row.skipped_by_user)
        self.copy_one_button.setEnabled(needs_choice and not row.allow_unsplit)
        self.skip_button.setEnabled(not row.skipped_by_user)
        self.unskip_button.setEnabled(row.skipped_by_user)

    def _cancel(self) -> None:
        if self.token:
            self.token.cancel()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("Cancelling\u2026 finishing the current file.")

    def _teardown_thread(self) -> None:
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(8000)
            self.thread.deleteLater()
        self.thread = None
        self.worker = None

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        QMessageBox.critical(
            self, "Something went wrong", f"The operation could not be completed.\n\n{message}"
        )

    def _startup_cleanup(self) -> None:
        """Remove our own stale temp files left by a previous crash."""

        folder = self.output_edit.text()
        if folder and Path(folder).is_dir():
            removed = cleanup_stale_temp_files(Path(folder), max_age_seconds=3600)
            if removed:
                logger.info("Removed %s stale temporary file(s)", removed)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PDF Batch Separator",
            f"<h3>PDF Batch Separator {__version__}</h3>"
            "<p><b>Credits</b><br>"
            f"Created and maintained by <a href='{AUTHOR_PROFILE_URL}'>{AUTHOR_HANDLE}</a> "
            f"({AUTHOR_PROFILE_URL}).<br>"
            f"{COPYRIGHT_TEXT}. Released under the MIT licence.</p>"
            f"<p>{PRIVACY_TEXT} It works completely offline: no internet connection, "
            "no cloud account and no telemetry.</p>"
            "<p><b>Split by separator</b> finds barcode separator sheets, removes them "
            "and saves each document between them separately.<br>"
            "<b>Remove blank pages only</b> keeps each PDF whole and removes empty pages.</p>"
            "<p>Your original PDFs are never changed, and existing files are never "
            "overwritten.</p>"
            "<p>Pages are rewritten during export, so digital signatures in the source "
            "PDF will not remain valid in the output.</p>"
            "<p>See THIRD_PARTY_NOTICES.md for open-source licences.</p>",
        )

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        if self.busy:
            answer = QMessageBox.question(
                self,
                "Work in progress",
                "Processing is still running. Closing now will stop it.\n\n"
                "Documents that were already written will be kept. Close anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.token:
                self.token.cancel()
            if self.thread is not None:
                self.thread.quit()
                self.thread.wait(5000)
        self._persist()
        event.accept()


__all__ = ["MainWindow"]
