"""UI workflow tests driven headlessly through the real widgets.

These exercise the user-visible contract from PRD section 6: adding files,
analysing, resolving warnings, overriding page statuses and exporting.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is required for the UI tests")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fixtures.builders import (  # noqa: E402
    add_blank_page,
    add_other_barcode_page,
    add_separator_page,
    add_text_page,
    build_pdf,
)
from pdf_batch_separator.core.models import (  # noqa: E402
    BlankSensitivity,
    PageOverrides,
    ProcessingMode,
)
from pdf_batch_separator.settings import AppSettings, SettingsStore  # noqa: E402
from pdf_batch_separator.ui.batch_model import BatchTableModel, RowState  # noqa: E402

SEP = "EAGC-EDMS-00001"


@pytest.fixture(scope="session")
def qapp():
    from pdf_batch_separator.app import create_application

    app = QApplication.instance() or create_application([])
    yield app


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An isolated QSettings store so tests never touch the real profile."""

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return SettingsStore(settings)


@pytest.fixture
def window(qapp, store):
    from pdf_batch_separator.ui.main_window import MainWindow

    win = MainWindow(store=store)
    # Modal dialogs would block a headless run; answer them automatically.
    win.confirm_skipping_blocked = lambda blocked, count: True
    win.confirm_signed_documents = lambda: True
    win._show_summary = lambda *a, **k: None
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def pump(app, window, timeout: float = 90.0) -> None:
    """Run the event loop until background work finishes."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if not window.busy:
            return
        time.sleep(0.02)
    raise AssertionError("Background work did not finish in time")


@pytest.fixture
def split_pdf(workdir):
    def build(doc):
        add_text_page(doc, "Alpha")
        add_separator_page(doc, SEP)
        add_text_page(doc, "Beta")
        add_blank_page(doc)

    return build_pdf(workdir / "split.pdf", build)


@pytest.fixture
def nomarker_pdf(workdir):
    return build_pdf(
        workdir / "nomarker.pdf",
        lambda d: (add_text_page(d, "One"), add_blank_page(d), add_text_page(d, "Two")),
    )


class TestDefaults:
    def test_defaults_match_the_prd(self, window):
        assert window.split_radio.isChecked(), "split mode is the default"
        assert window.separator_edit.text() == SEP
        assert window.blank_check.isChecked(), "blank removal defaults to on"
        assert window.sensitivity_combo.currentData() == BlankSensitivity.BALANCED.value

    def test_privacy_statement_visible(self, window):
        assert "only on this PC" in window.statusBar().currentMessage()

    def test_author_credit_in_status_bar(self, window):
        """A small copyright for the author is pinned to the status bar."""

        label = window.copyright_label
        # A permanent widget survives transient status messages.
        assert label.parent() is window.statusBar()
        assert "© 2026 jak0d" in label.text()
        assert "https://github.com/jak0d" in label.text()
        assert label.openExternalLinks()

    def test_about_box_credits_the_author(self, window, monkeypatch):
        """The About box names the author and links to their GitHub profile."""

        from pdf_batch_separator.ui import main_window

        captured = {}

        class FakeMessageBox:
            @staticmethod
            def about(parent, title, text):
                captured["text"] = text

        monkeypatch.setattr(main_window, "QMessageBox", FakeMessageBox)
        window._show_about()
        assert "jak0d" in captured["text"]
        assert "https://github.com/jak0d" in captured["text"]
        assert "© 2026 jak0d" in captured["text"]

    def test_process_disabled_before_analysis(self, window, split_pdf):
        window._add_paths([split_pdf])
        assert not window.process_button.isEnabled()

    def test_accessible_names_present(self, window):
        assert window.table.accessibleName()
        assert window.separator_combo.accessibleName()
        assert window.sensitivity_combo.accessibleName()


class TestInputHandling:
    def test_add_files(self, window, split_pdf):
        window._add_paths([split_pdf])
        assert window.model.rowCount() == 1

    def test_duplicates_ignored(self, window, split_pdf):
        window._add_paths([split_pdf])
        window._add_paths([split_pdf])
        assert window.model.rowCount() == 1

    def test_non_pdf_ignored(self, window, workdir, split_pdf):
        junk = workdir / "notes.txt"
        junk.write_text("hello")
        window._add_paths([split_pdf, junk])
        assert window.model.rowCount() == 1

    def test_add_folder(self, window, workdir, split_pdf, nomarker_pdf):
        window._add_paths([workdir])
        assert window.model.rowCount() == 2

    def test_output_folder_suggested(self, window, split_pdf):
        window._add_paths([split_pdf])
        assert window.output_edit.text().endswith("Processed")

    def test_output_folder_excluded_from_folder_scan(self, window, workdir, split_pdf):
        """PRD 6.3: recursive input must not re-ingest generated output."""

        output = workdir / "Processed"
        output.mkdir()
        build_pdf(output / "already - 001.pdf", lambda d: add_text_page(d, "old output"))
        window.output_edit.setText(str(output))
        window.recursive_check.setChecked(True)
        window._add_paths([workdir])

        names = [row.name for row in window.model.rows]
        assert "already - 001.pdf" not in names

    def test_clear_list(self, window, split_pdf):
        window._add_paths([split_pdf])
        window._clear_list()
        assert window.model.rowCount() == 0

    def test_remove_selected(self, window, split_pdf, nomarker_pdf):
        window._add_paths([split_pdf, nomarker_pdf])
        window.table.selectRow(0)
        window._remove_selected()
        assert window.model.rowCount() == 1


class TestAnalysisWorkflow:
    def test_analyse_then_process(self, qapp, window, split_pdf, outdir):
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        row = window.model.rows[0]
        assert row.state is RowState.READY
        assert row.separator_pages == (1,)
        assert row.blank_pages == (3,)
        assert row.expected_outputs == 2
        assert window.process_button.isEnabled()

        window._start_export()
        pump(qapp, window)

        outputs = sorted(p.name for p in outdir.glob("*.pdf"))
        assert outputs == ["split - 001.pdf", "split - 002.pdf"]
        assert list(outdir.glob("PDF Batch Separator report*.txt"))

    def test_no_marker_blocks_export(self, qapp, window, nomarker_pdf, outdir):
        window._add_paths([nomarker_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        row = window.model.rows[0]
        assert row.state is RowState.WARNING
        assert row.blocked
        assert row.expected_outputs == 0
        assert not window.process_button.isEnabled()

    def test_resolve_no_marker_as_single_copy(self, qapp, window, nomarker_pdf, outdir):
        window._add_paths([nomarker_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        window.table.selectRow(0)
        window._resolve_as_single_copy()

        row = window.model.rows[0]
        assert row.allow_unsplit and not row.blocked
        assert window.process_button.isEnabled()

        window._start_export()
        pump(qapp, window)

        assert [p.name for p in outdir.glob("*.pdf")] == ["nomarker - cleaned.pdf"]

    def test_resolve_no_marker_as_skip(self, qapp, window, nomarker_pdf, split_pdf, outdir):
        window._add_paths([nomarker_pdf, split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        window.table.selectRow(0)
        window._resolve_as_skip()
        assert window.model.rows[0].state is RowState.SKIPPED

        window._start_export()
        pump(qapp, window)

        names = sorted(p.name for p in outdir.glob("*.pdf"))
        assert names == ["split - 001.pdf", "split - 002.pdf"]

    def test_failed_file_does_not_stop_batch(self, qapp, window, workdir, split_pdf, outdir):
        corrupt = workdir / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.4 broken")
        window._add_paths([corrupt, split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        assert window.model.rows[0].state is RowState.ERROR
        assert window.model.rows[1].state is RowState.READY

        window._start_export()
        pump(qapp, window)
        assert len(list(outdir.glob("*.pdf"))) == 2

    def test_other_barcode_warning_surfaces(self, qapp, window, workdir, outdir):
        path = build_pdf(
            workdir / "other.pdf",
            lambda d: (add_text_page(d, "A"), add_other_barcode_page(d, "PO-8842")),
        )
        window._add_paths([path])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        analysis = window.model.rows[0].analysis
        assert any("PO-8842" in w.message for w in analysis.warnings)


class TestSettingsInvalidation:
    def test_changing_separator_invalidates(self, qapp, window, split_pdf, outdir):
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)
        assert window.process_button.isEnabled()

        window.separator_combo.setCurrentIndex(1)  # PATCHT
        assert not window.process_button.isEnabled()
        assert window.model.rows[0].analysis is None

    def test_changing_sensitivity_invalidates(self, qapp, window, split_pdf, outdir):
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        window.sensitivity_combo.setCurrentIndex(2)  # Aggressive
        assert not window.process_button.isEnabled()

    def test_changing_mode_invalidates(self, qapp, window, split_pdf, outdir):
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        window.clean_radio.setChecked(True)
        assert not window.process_button.isEnabled()

    def test_invalid_separator_blocks_analysis(self, window, split_pdf):
        window._add_paths([split_pdf])
        window.separator_combo.setCurrentIndex(window.separator_combo.count() - 1)
        window.separator_edit.setText("   ")
        assert not window.analyze_button.isEnabled()
        # isVisibleTo(): the window itself is never shown in headless tests.
        assert window.separator_error.isVisibleTo(window)


class TestCleanOnlyMode:
    def test_clean_mode_hides_separator_controls(self, window):
        window.clean_radio.setChecked(True)
        assert not window.separator_combo.isVisibleTo(window)
        assert not window.blank_check.isVisibleTo(window)
        assert window.sensitivity_combo.isVisibleTo(window)

    def test_clean_mode_exports_one_file(self, qapp, window, split_pdf, outdir):
        window.clean_radio.setChecked(True)
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        row = window.model.rows[0]
        assert row.analysis.mode is ProcessingMode.CLEAN_ONLY
        assert row.expected_outputs == 1

        window._start_export()
        pump(qapp, window)
        assert [p.name for p in outdir.glob("*.pdf")] == ["split - cleaned.pdf"]


class TestOverrides:
    def test_override_changes_expected_outputs(self, qapp, window, split_pdf, outdir):
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        row = window.model.rows[0]
        assert row.expected_outputs == 2

        row.overrides = PageOverrides(force_not_separator=frozenset({1}))
        row.refresh_state()
        assert row.expected_outputs == 1
        assert row.separator_pages == ()

    def test_keeping_a_blank_page(self, qapp, window, split_pdf, outdir):
        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        row = window.model.rows[0]
        assert row.blank_pages == (3,)
        row.overrides = PageOverrides(force_keep=frozenset({3}))
        row.refresh_state()
        assert row.blank_pages == ()

    def test_review_dialog_builds(self, qapp, window, split_pdf, outdir):
        from pdf_batch_separator.ui.document_review import DocumentReviewDialog

        window._add_paths([split_pdf])
        window.output_edit.setText(str(outdir))
        window._start_analysis()
        pump(qapp, window)

        row = window.model.rows[0]
        dialog = DocumentReviewDialog(row.analysis, row.overrides)
        try:
            qapp.processEvents()
            assert len(dialog._cards) == row.analysis.page_count
            # The separator page card must be badged as a separator.
            from pdf_batch_separator.core.models import PageStatus

            dialog._cards[1].set_status(PageStatus.SEPARATOR)
            assert "Separator" in dialog._cards[1].badge.text()
        finally:
            dialog._stop_worker()
            dialog.deleteLater()


class TestSettingsPersistence:
    def test_roundtrip(self, store):
        settings = AppSettings(
            output_folder="",
            separator_value="CUSTOM-1",
            mode=ProcessingMode.CLEAN_ONLY,
            remove_blanks=False,
            blank_sensitivity=BlankSensitivity.AGGRESSIVE,
            recursive=True,
            theme="dark",
        )
        store.save(settings)
        loaded = store.load()

        assert loaded.separator_value == "CUSTOM-1"
        assert loaded.mode is ProcessingMode.CLEAN_ONLY
        assert loaded.remove_blanks is False
        assert loaded.blank_sensitivity is BlankSensitivity.AGGRESSIVE
        assert loaded.recursive is True
        assert loaded.theme == "dark"

    def test_defaults_when_empty(self, store):
        loaded = store.load()
        assert loaded.separator_value == SEP
        assert loaded.remove_blanks is True
        assert loaded.blank_sensitivity is BlankSensitivity.BALANCED

    def test_corrupt_values_fall_back(self, tmp_path):
        settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        settings.setValue("mode", "nonsense")
        settings.setValue("blank_sensitivity", "nonsense")
        settings.setValue("theme", "nonsense")
        loaded = SettingsStore(settings).load()

        assert loaded.mode is ProcessingMode.SPLIT
        assert loaded.blank_sensitivity is BlankSensitivity.BALANCED
        assert loaded.theme == "system"

    def test_missing_output_folder_is_dropped(self, tmp_path):
        settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
        settings.setValue("output_folder", str(tmp_path / "gone"))
        assert SettingsStore(settings).load().output_folder == ""

    def test_no_document_history_persisted(self, store, tmp_path):
        """FR-7: preferences only, never document names."""

        store.save(AppSettings(separator_value="X-1"))
        text = ""
        for candidate in tmp_path.rglob("*"):
            if candidate.is_file():
                text += candidate.read_text(errors="ignore")
        assert ".pdf" not in text.lower()


class TestBatchModel:
    def test_columns(self):
        model = BatchTableModel()
        assert model.columnCount() == 6
        assert model.COLUMNS[0] == "File"

    def test_status_uses_symbol_not_only_colour(self):
        for state in RowState:
            assert state.symbol and state.label
