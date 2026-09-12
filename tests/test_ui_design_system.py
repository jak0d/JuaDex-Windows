"""Tests for the redesigned presentation layer.

These cover the parts of the UI that carry meaning rather than behaviour: the
design tokens, the icon set, the themed components and the new triage filters.
They are deliberately headless and fast — nothing here rasterises a PDF.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 is required for the UI tests")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pdf_batch_separator.core.models import PageStatus, ProcessingMode  # noqa: E402
from pdf_batch_separator.ui import components as ui  # noqa: E402
from pdf_batch_separator.ui import icons, theme  # noqa: E402
from pdf_batch_separator.ui.batch_model import RowState  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from pdf_batch_separator.app import create_application

    app = QApplication.instance() or create_application([])
    yield app
    theme.apply_theme(app, dark=False)


class TestTokens:
    def test_both_palettes_define_the_same_tokens(self):
        """A token missing from one palette would crash only in that theme."""

        assert set(theme.LIGHT) == set(theme.DARK)

    def test_semantic_aliases_resolve_to_their_family(self, qapp):
        theme.apply_theme(qapp, dark=False)
        assert theme.color("danger") == theme.color("red_base")
        assert theme.color("danger_soft") == theme.color("red_soft")
        assert theme.color("success_soft_fg") == theme.color("green_soft_fg")

    def test_unknown_token_is_an_error(self, qapp):
        with pytest.raises(KeyError):
            theme.color("chartreuse")

    @pytest.mark.parametrize(
        "name", ["success", "info", "danger", "warning", "separator", "neutral"]
    )
    def test_every_accent_family_is_complete(self, qapp, name):
        """Components rely on these shades existing for any accent they take."""

        shades = theme.family(name)
        for shade in ("base", "soft", "soft_fg", "soft_line"):
            assert shade in shades, f"{name} is missing {shade}"

    def test_apply_theme_switches_the_active_palette(self, qapp):
        theme.apply_theme(qapp, dark=True)
        assert theme.is_dark()
        dark_canvas = theme.color("canvas")

        theme.apply_theme(qapp, dark=False)
        assert not theme.is_dark()
        assert theme.color("canvas") != dark_canvas

    def test_stylesheet_is_produced_for_both_themes(self, qapp):
        for dark in (False, True):
            sheet = theme.stylesheet(theme.DARK if dark else theme.LIGHT, dark)
            assert "QPushButton" in sheet
            # An unresolved f-string placeholder would leave a literal brace pair.
            assert "{'" not in sheet

    def test_stylesheet_urls_are_quoted(self, qapp):
        """A frozen build unpacks to a temp path that often contains spaces.

        An unquoted ``url()`` stops parsing at the first space, which would
        silently drop the checkbox, radio and combo-box glyphs on Windows.
        """

        import re

        sheet = theme.stylesheet(theme.LIGHT, False)
        urls = re.findall(r"url\(([^)]*)\)", sheet)
        assert urls, "the stylesheet should reference the SVG assets"
        for url in urls:
            assert url.startswith('"') and url.endswith('"'), url

    def test_referenced_svg_assets_are_shipped(self):
        """Every asset named by the stylesheet must exist in the package."""

        for name in (
            "check-on.svg",
            "radio-on.svg",
            "chevron-down.svg",
            "chevron-down-dark.svg",
        ):
            assert (theme.ICON_DIR / name).is_file(), f"{name} is missing"


class TestIcons:
    def test_every_icon_renders(self, qapp):
        for name in list(icons.STROKE) + list(icons.FILLED):
            pixmap = icons.pixmap(name, "#000000", 16)
            assert not pixmap.isNull(), f"{name} failed to render"

    def test_icon_fills_its_box(self, qapp):
        """Guards the DPR bug that clipped glyphs to their top-left quadrant."""

        pixmap = icons.pixmap("check", "#000000", 16, dpr=2.0)
        assert pixmap.width() == 32 and pixmap.height() == 32

        image = pixmap.toImage()
        # The tick's stroke must reach into the lower-right half of the box.
        assert any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(16, 32)
            for y in range(16, 32)
        )

    def test_unknown_icon_is_an_error(self, qapp):
        with pytest.raises(KeyError):
            icons.pixmap("no-such-icon", "#000000", 16)

    def test_tokens_are_accepted_as_tints(self, qapp):
        assert not icons.icon("check", "success").isNull()

    def test_cache_can_be_cleared_for_a_theme_change(self, qapp):
        icons.pixmap("check", "#111111", 16)
        icons.clear_cache()
        assert icons.pixmap.cache_info().currsize == 0


class TestRowState:
    @pytest.mark.parametrize("state", list(RowState))
    def test_every_state_is_fully_described(self, qapp, state):
        """The table renders each state as icon + accent + words."""

        assert state.label and state.symbol
        assert state.icon in icons.STROKE
        assert theme.family(state.accent)


class TestComponents:
    def test_pill_restyles_on_accent_change(self, qapp):
        pill = ui.Pill("Ready", "success")
        before = pill.styleSheet()
        pill.set_accent("danger")
        assert pill.styleSheet() != before
        assert theme.color("danger_soft") in pill.styleSheet()

    def test_solid_neutral_pill_stays_legible_in_both_themes(self, qapp):
        """Neutral inverts between themes, so it carries its own text colour."""

        for dark in (False, True):
            theme.apply_theme(qapp, dark=dark)
            pill = ui.Pill("5", "neutral", solid=True)
            assert theme.family("neutral")["fg"] in pill.styleSheet()
        theme.apply_theme(qapp, dark=False)

    def test_card_accent_does_not_cascade_to_children(self, qapp):
        """An unscoped stylesheet would repaint every nested widget."""

        card = ui.Card(accent="danger", accent_fill=True)
        assert card.styleSheet().startswith(f"QFrame#{card.objectName()}")

    def test_cards_get_unique_object_names(self, qapp):
        first, second = ui.Card(accent="info"), ui.Card(accent="info")
        assert first.objectName() != second.objectName()

    def test_stat_chip_reserves_room_for_its_caption(self, qapp):
        """Guards the clipped "Total Page" regression."""

        chip = ui.StatChip("16", "Total Pages", "info")
        needed = chip._text.fontMetrics().horizontalAdvance("16 Total Pages")
        assert chip._text.minimumWidth() >= needed

    def test_stat_chip_remembers_its_value_for_restyling(self, qapp):
        chip = ui.StatChip("3", "Blank Pages", "warning")
        chip.set_value("7")
        assert chip._value == "7"

    def test_meta_row_protects_its_value(self, qapp):
        row = ui.MetaRow("Ink density", "4.37%")
        assert row._value.minimumWidth() > 0
        row.set_key("Barcode")
        assert row._key.text() == "BARCODE"

    def test_status_pill_pairs_a_glyph_with_words(self, qapp):
        """Status must never be carried by colour alone."""

        pill = ui.StatusPill("Needs attention", "warning", "alert-triangle")
        assert pill._text.text() == "Needs attention"
        assert not pill._icon.pixmap().isNull()


class TestReviewFilters:
    """The triage grid's segmented filters."""

    @pytest.fixture
    def dialog(self, qapp, workdir):
        from fixtures.builders import (
            add_blank_page,
            add_separator_page,
            add_text_page,
            build_pdf,
        )

        from pdf_batch_separator.core.analyzer import analyze_document
        from pdf_batch_separator.core.models import PageOverrides
        from pdf_batch_separator.ui.document_review import DocumentReviewDialog

        separator = "EAGC-EDMS-00001"

        def build(doc):
            add_text_page(doc, "A")
            add_text_page(doc, "B")
            add_separator_page(doc, separator)
            add_text_page(doc, "C")
            add_blank_page(doc)

        path = build_pdf(workdir / "triage.pdf", build)
        analysis = analyze_document(
            path, expected_separator=separator, remove_blanks=True
        )
        dialog = DocumentReviewDialog(analysis, PageOverrides())
        yield dialog
        dialog._stop_worker()
        dialog.deleteLater()

    def test_cards_report_the_detected_status(self, qapp, dialog):
        assert dialog._cards[2].badge.text() == "Separator"
        assert dialog._cards[4].badge.text() == "Blank"
        assert dialog._cards[0].badge.text() == "Keep"

    @pytest.mark.parametrize(
        "key,expected",
        [("all", 5), ("flagged", 2), ("separator", 1), ("blank", 1), ("kept", 3)],
    )
    def test_filters_select_the_right_pages(self, qapp, dialog, key, expected):
        dialog._set_filter(key)
        qapp.processEvents()
        assert len(dialog._visible_indexes()) == expected

    def test_filter_follows_an_override(self, qapp, dialog):
        """Keeping a blank page removes it from the flagged set."""

        dialog._set_filter("flagged")
        assert len(dialog._visible_indexes()) == 2

        dialog._cards[4].remove_box.setChecked(False)
        qapp.processEvents()
        assert 4 in dialog.result_overrides.force_keep
        assert len(dialog._visible_indexes()) == 1

    def test_outcome_names_the_destination_document(self, qapp, dialog):
        assert "Doc #01" in dialog._cards[0].meta_secondary._value.text()
        assert "Split point" in dialog._cards[2].meta_secondary._value.text()
        assert "Removed" in dialog._cards[4].meta_secondary._value.text()

    def test_reset_restores_detection(self, qapp, dialog):
        dialog._cards[4].remove_box.setChecked(False)
        qapp.processEvents()
        assert not dialog.result_overrides.is_empty

        dialog._reset()
        qapp.processEvents()
        assert dialog.result_overrides.is_empty
        assert dialog._cards[4].badge.text() == "Blank"


class TestPageCardStatus:
    def test_kept_pages_stay_untinted(self, qapp):
        """Only pages needing a decision are allowed to shout."""

        from pdf_batch_separator.ui.document_review import PageCard

        card = PageCard(0, ProcessingMode.SPLIT)
        card.set_status(PageStatus.KEPT)
        assert card.styleSheet() == ""

        card.set_status(PageStatus.BLANK)
        assert card.styleSheet() != ""
