"""Main application window (PRD section 6).

A conventional Windows desktop utility: mode choice, settings, batch table,
footer actions.  All heavy work is delegated to worker threads.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
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
from .batch_model import BatchRow, BatchTableModel, RowState
from .document_review import DocumentReviewDialog

logger = logging.getLogger(__name__)

PRIVACY_TEXT = "Your PDFs are processed only on this PC."


class DropTableView(QTableView):
    """Table view that accepts dropped PDFs and folders."""

    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
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

        self.setWindowTitle("PDF Batch Separator")
        self.resize(1240, 820)
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
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 780])
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        root.addWidget(self._build_footer())
        self.statusBar().showMessage(PRIVACY_TEXT)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("PDF Batch Separator")
        title.setObjectName("appTitle")
        title.setStyleSheet("font-size: 18pt; font-weight: 700; letter-spacing: 0.2px;")
        layout.addWidget(title)

        subtitle = QLabel("Prepare, review, and export scanned documents")
        subtitle.setStyleSheet("color: #64748B; margin-left: 2px;")
        layout.addWidget(subtitle)

        badge = QLabel("\U0001f512  Offline \u2014 " + PRIVACY_TEXT)
        badge.setStyleSheet(
            "padding: 3px 10px; border-radius: 9px;"
            " background: rgba(15,123,15,0.12); color: #0f7b0f; font-weight: 600;"
        )
        badge.setAccessibleName(
            "Privacy notice: this application works offline. " + PRIVACY_TEXT
        )
        layout.addSpacing(14)
        layout.addWidget(badge)
        layout.addStretch(1)

        self.help_button = QPushButton("Help / About")
        self.help_button.setToolTip("Version, privacy and licence information (F1)")
        self.help_button.setShortcut(QKeySequence(Qt.Key.Key_F1))
        self.help_button.clicked.connect(self._show_about)
        layout.addWidget(self.help_button)
        return header

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # -- mode -----------------------------------------------------
        mode_box = QGroupBox("1. What do you want to do?")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.setSpacing(10)

        self.mode_group = QButtonGroup(self)

        self.split_radio = QRadioButton("Split by separator")
        self.split_radio.setStyleSheet("font-weight: 600;")
        split_hint = QLabel(
            "Find the barcode separator sheets, remove them, and save each "
            "document between them as its own PDF."
        )
        split_hint.setWordWrap(True)
        split_hint.setContentsMargins(24, 0, 0, 6)

        self.clean_radio = QRadioButton("Remove blank pages only")
        self.clean_radio.setStyleSheet("font-weight: 600;")
        clean_hint = QLabel(
            "Keep each PDF as one document and only remove the blank pages, "
            "such as empty backsides."
        )
        clean_hint.setWordWrap(True)
        clean_hint.setContentsMargins(24, 0, 0, 0)

        self.mode_group.addButton(self.split_radio, 0)
        self.mode_group.addButton(self.clean_radio, 1)
        for widget in (self.split_radio, split_hint, self.clean_radio, clean_hint):
            mode_layout.addWidget(widget)
        self.mode_group.idToggled.connect(self._on_mode_changed)
        layout.addWidget(mode_box)

        # -- settings -------------------------------------------------
        self.settings_box = QGroupBox("2. Settings")
        settings_layout = QVBoxLayout(self.settings_box)
        settings_layout.setSpacing(8)

        self.separator_label = QLabel("Separator barcode value")
        settings_layout.addWidget(self.separator_label)

        self.separator_combo = QComboBox()
        self.separator_combo.setEditable(False)
        for preset in PRESET_SEPARATORS:
            self.separator_combo.addItem(preset, preset)
        self.separator_combo.addItem("Custom value\u2026", "")
        self.separator_combo.setAccessibleName("Separator barcode preset")
        self.separator_combo.currentIndexChanged.connect(self._on_preset_changed)
        settings_layout.addWidget(self.separator_combo)

        self.separator_edit = QLineEdit()
        self.separator_edit.setMaxLength(128)
        self.separator_edit.setPlaceholderText("Enter the exact barcode text")
        self.separator_edit.setAccessibleName("Custom separator barcode value")
        self.separator_edit.textChanged.connect(self._on_separator_text_changed)
        settings_layout.addWidget(self.separator_edit)

        self.separator_error = QLabel()
        self.separator_error.setWordWrap(True)
        self.separator_error.setStyleSheet("color: #c42b1c;")
        self.separator_error.setVisible(False)
        settings_layout.addWidget(self.separator_error)

        self.print_button = QPushButton("Create printable separator sheet\u2026")
        self.print_button.setToolTip(
            "Save an A4 PDF with this barcode that you can print and use as a separator."
        )
        self.print_button.clicked.connect(self._create_separator_sheet)
        settings_layout.addWidget(self.print_button)

        settings_layout.addSpacing(6)
        self.blank_check = QCheckBox("Also remove blank pages")
        self.blank_check.toggled.connect(self._on_blank_toggled)
        settings_layout.addWidget(self.blank_check)

        self.sensitivity_label = QLabel("Blank page sensitivity")
        settings_layout.addWidget(self.sensitivity_label)
        self.sensitivity_combo = QComboBox()
        for level in BlankSensitivity:
            self.sensitivity_combo.addItem(level.label, level.value)
        self.sensitivity_combo.setAccessibleName("Blank page sensitivity")
        self.sensitivity_combo.currentIndexChanged.connect(self._on_sensitivity_changed)
        settings_layout.addWidget(self.sensitivity_combo)

        self.sensitivity_hint = QLabel()
        self.sensitivity_hint.setWordWrap(True)
        self.sensitivity_hint.setStyleSheet("color: palette(mid-text);")
        settings_layout.addWidget(self.sensitivity_hint)

        layout.addWidget(self.settings_box)

        # -- output ---------------------------------------------------
        output_box = QGroupBox("3. Output folder")
        output_layout = QVBoxLayout(output_box)
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Choose where to save the results")
        self.output_edit.setAccessibleName("Output folder")
        output_layout.addWidget(self.output_edit)

        buttons = QHBoxLayout()
        self.choose_output_button = QPushButton("Choose folder\u2026")
        self.choose_output_button.clicked.connect(self._choose_output_folder)
        buttons.addWidget(self.choose_output_button)
        self.open_output_button = QPushButton("Open")
        self.open_output_button.setToolTip("Open the output folder in File Explorer")
        self.open_output_button.clicked.connect(self._open_output_folder)
        buttons.addWidget(self.open_output_button)
        output_layout.addLayout(buttons)

        self.recursive_check = QCheckBox("Include subfolders when adding a folder")
        self.recursive_check.toggled.connect(self._on_recursive_toggled)
        output_layout.addWidget(self.recursive_check)

        layout.addWidget(output_box)
        layout.addStretch(1)

        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        panel.setMinimumWidth(320)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.add_files_button = QPushButton("Add files\u2026")
        self.add_files_button.clicked.connect(self._add_files)
        self.add_folder_button = QPushButton("Add folder\u2026")
        self.add_folder_button.clicked.connect(self._add_folder)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = QPushButton("Clear list")
        self.clear_button.clicked.connect(self._clear_list)
        for button in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.review_button = QPushButton("Review pages\u2026")
        self.review_button.setToolTip(
            "Look at the detected pages and correct them before processing"
        )
        self.review_button.clicked.connect(self._review_selected)
        toolbar.addWidget(self.review_button)
        layout.addLayout(toolbar)

        self.table = DropTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.files_dropped.connect(self._on_files_dropped)
        self.table.doubleClicked.connect(lambda _: self._review_selected())
        self.table.setAccessibleName("List of PDF files to process")

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(BatchTableModel.COL_FILE, QHeaderView.ResizeMode.Stretch)
        for column in (
            BatchTableModel.COL_PAGES,
            BatchTableModel.COL_SEP,
            BatchTableModel.COL_BLANK,
            BatchTableModel.COL_OUT,
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            BatchTableModel.COL_STATUS, QHeaderView.ResizeMode.Interactive
        )
        self.table.setColumnWidth(BatchTableModel.COL_STATUS, 220)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_actions()
        )
        layout.addWidget(self.table, 1)

        self.empty_hint = QLabel(
            "<b>Drop PDF files here</b><br>or use <b>Add files</b> / <b>Add folder</b> to get started"
        )
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setStyleSheet(
            "color: palette(mid-text); padding: 10px; border: 1px dashed palette(mid);"
            " border-radius: 8px;"
        )
        layout.addWidget(self.empty_hint)

        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.RichText)
        self.detail.setVisible(False)
        self.detail.setStyleSheet(
            "padding: 8px; border-radius: 6px; background: rgba(157,93,0,0.10);"
        )
        layout.addWidget(self.detail)

        self.resolve_bar = QWidget()
        resolve_layout = QHBoxLayout(self.resolve_bar)
        resolve_layout.setContentsMargins(0, 0, 0, 0)
        self.copy_one_button = QPushButton("Save as one cleaned document")
        self.copy_one_button.setToolTip(
            "Do not split this file; write a single cleaned copy instead."
        )
        self.copy_one_button.clicked.connect(self._resolve_as_single_copy)
        self.skip_button = QPushButton("Skip this file")
        self.skip_button.clicked.connect(self._resolve_as_skip)
        self.unskip_button = QPushButton("Include again")
        self.unskip_button.clicked.connect(self._resolve_unskip)
        resolve_layout.addWidget(QLabel("For the selected file:"))
        resolve_layout.addWidget(self.copy_one_button)
        resolve_layout.addWidget(self.skip_button)
        resolve_layout.addWidget(self.unskip_button)
        resolve_layout.addStretch(1)
        self.resolve_bar.setVisible(False)
        layout.addWidget(self.resolve_bar)

        return panel

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMinimumWidth(260)
        self.progress.setAccessibleName("Overall progress")
        layout.addWidget(self.progress, 1)

        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)
        layout.addStretch(1)

        self.analyze_button = QPushButton("Analyse")
        self.analyze_button.setToolTip("Check the PDFs and show what would happen (F5)")
        self.analyze_button.setShortcut(QKeySequence(Qt.Key.Key_F5))
        self.analyze_button.clicked.connect(self._start_analysis)
        layout.addWidget(self.analyze_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.setEnabled(False)
        layout.addWidget(self.cancel_button)

        self.process_button = QPushButton("Process batch")
        self.process_button.setObjectName("processButton")
        self.process_button.setProperty("role", "primary")
        self.process_button.setDefault(True)
        self.process_button.clicked.connect(self._start_export)
        layout.addWidget(self.process_button)

        return footer

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
            self.sensitivity_hint.setStyleSheet("color: #9d5d00; font-weight: 600;")
        else:
            self.sensitivity_hint.setStyleSheet("color: palette(mid-text);")

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
        self.empty_hint.setVisible(not self.model.rows)

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
        analyses = [row.analysis for row in self.model.rows if row.analysis]
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
        row = self.model.row_at(index)
        if row:
            row.export_result = result
            row.state = RowState.PENDING
            row.refresh_state()
            self.model.emit_row_changed(index)
        self.progress.setValue(min(self.progress.value() + 1, self.progress.maximum()))
        self.progress_label.setText(
            f"{self.progress.value()} of {self.progress.maximum()} processed"
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

        self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        rows = self._selected_rows()
        row = self.model.row_at(rows[0]) if rows else None

        if row is None or row.analysis is None:
            self.detail.setVisible(False)
            self.resolve_bar.setVisible(False)
            return

        analysis = row.analysis
        messages: list[str] = []
        if analysis.failed:
            messages.append(f"<b>{row.name}</b>: {analysis.error}")
        else:
            for warning in analysis.warnings:
                messages.append(f"\u26a0 {warning.message}")
            if row.allow_unsplit:
                messages.append(
                    "\u2713 This file will be saved as a single cleaned document."
                )
            if row.skipped_by_user:
                messages.append("\u2298 This file will be skipped.")

        self.detail.setText("<br>".join(messages) if messages else "")
        self.detail.setVisible(bool(messages))

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
