"""Grouping rules and warning derivation (PRD FR-4, section 11 edge cases).

These tests never render a PDF: grouping is pure logic over PageAnalysis.
"""

from __future__ import annotations

import pytest

from pdf_batch_separator.core.grouping import build_warnings, effective_statuses, group_pages
from pdf_batch_separator.core.models import (
    PageAnalysis,
    PageOverrides,
    PageStatus,
    ProcessingMode,
    WarningCode,
)

SPLIT = ProcessingMode.SPLIT
CLEAN = ProcessingMode.CLEAN_ONLY


def pages(spec: str) -> tuple[PageAnalysis, ...]:
    """Build pages from a compact spec string.

    ``t`` = text, ``s`` = separator, ``b`` = blank.
    """

    out = []
    for index, char in enumerate(spec):
        out.append(
            PageAnalysis(
                page_index=index,
                is_separator=char == "s",
                is_blank=char == "b",
                non_white_ratio=0.0 if char == "b" else 0.04,
            )
        )
    return tuple(out)


def groups_of(spec: str, *, mode=SPLIT, remove_blanks=True, overrides=None):
    return group_pages(
        pages(spec), mode=mode, remove_blanks=remove_blanks, overrides=overrides
    ).groups


class TestBasicGrouping:
    def test_simple_split(self):
        assert groups_of("ttstt") == ((0, 1), (3, 4))

    def test_no_separator_yields_one_group(self):
        assert groups_of("tttt") == ((0, 1, 2, 3),)

    def test_separator_never_appears_in_output(self):
        for group in groups_of("tstst"):
            assert 1 not in group and 3 not in group

    def test_page_order_preserved(self):
        assert groups_of("tttstt") == ((0, 1, 2), (4, 5))

    def test_empty_document(self):
        assert groups_of("") == ()


class TestSeparatorEdges:
    """PRD section 11: first/last/consecutive separators."""

    def test_separator_on_first_page(self):
        result = group_pages(pages("stt"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ((1, 2),)
        assert result.empty_group_count == 1

    def test_separator_on_last_page(self):
        result = group_pages(pages("tts"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ((0, 1),)
        assert result.empty_group_count == 1

    def test_consecutive_separators(self):
        result = group_pages(pages("tsst"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ((0,), (3,))
        assert result.empty_group_count == 1

    def test_three_consecutive_separators(self):
        result = group_pages(pages("tssst"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ((0,), (4,))
        assert result.empty_group_count == 2

    def test_only_separators(self):
        """Three separators create four empty gaps: before, between x2, after."""

        result = group_pages(pages("sss"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ()
        assert result.empty_group_count == 4

    def test_only_separators_and_blanks(self):
        assert group_pages(pages("sbsb"), mode=SPLIT, remove_blanks=True).groups == ()

    def test_leading_and_trailing_separators(self):
        result = group_pages(pages("stts"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ((1, 2),)
        assert result.empty_group_count == 2


class TestBlankHandling:
    def test_blanks_removed_when_enabled(self):
        assert groups_of("tbt", remove_blanks=True) == ((0, 2),)

    def test_blanks_kept_when_disabled(self):
        assert groups_of("tbt", remove_blanks=False) == ((0, 1, 2),)

    def test_blank_only_document_yields_nothing(self):
        assert groups_of("bbb", remove_blanks=True) == ()

    def test_blank_only_document_kept_when_removal_off(self):
        assert groups_of("bbb", remove_blanks=False) == ((0, 1, 2),)

    def test_group_becomes_empty_after_blank_removal(self):
        result = group_pages(pages("tsbst"), mode=SPLIT, remove_blanks=True)
        assert result.groups == ((0,), (4,))
        assert result.empty_group_count == 1


class TestCleanOnlyMode:
    def test_all_pages_in_one_group(self):
        assert groups_of("ttt", mode=CLEAN) == ((0, 1, 2),)

    def test_blanks_removed_but_no_split(self):
        assert groups_of("tbtbt", mode=CLEAN) == ((0, 2, 4),)

    def test_barcode_pages_are_not_separators(self):
        """Clean-only mode must never split, even if a page carries a marker."""

        assert groups_of("tst", mode=CLEAN) == ((0, 1, 2),)

    def test_no_output_when_everything_blank(self):
        assert groups_of("bb", mode=CLEAN) == ()


class TestOverrides:
    def test_force_keep_rescues_a_blank_page(self):
        assert groups_of("tbt", overrides=PageOverrides(force_keep=frozenset({1}))) == (
            (0, 1, 2),
        )

    def test_force_remove_drops_a_content_page(self):
        assert groups_of("ttt", overrides=PageOverrides(force_remove=frozenset({1}))) == (
            (0, 2),
        )

    def test_force_separator_creates_a_split(self):
        assert groups_of("ttt", overrides=PageOverrides(force_separator=frozenset({1}))) == (
            (0,),
            (2,),
        )

    def test_force_not_separator_keeps_the_page_as_content(self):
        assert groups_of(
            "tst", overrides=PageOverrides(force_not_separator=frozenset({1}))
        ) == ((0, 1, 2),)

    def test_force_keep_wins_over_detected_separator(self):
        statuses = effective_statuses(
            pages("tst"),
            mode=SPLIT,
            remove_blanks=True,
            overrides=PageOverrides(force_keep=frozenset({1})),
        )
        assert statuses[1] is PageStatus.KEPT

    def test_force_keep_wins_over_force_remove(self):
        statuses = effective_statuses(
            pages("ttt"),
            mode=SPLIT,
            remove_blanks=True,
            overrides=PageOverrides(
                force_keep=frozenset({1}), force_remove=frozenset({1})
            ),
        )
        assert statuses[1] is PageStatus.KEPT

    def test_overrides_clipped_to_page_count(self):
        overrides = PageOverrides(force_keep=frozenset({0, 5, 99})).compatible_with(3)
        assert overrides.force_keep == frozenset({0})

    def test_empty_overrides_detected(self):
        assert PageOverrides().is_empty
        assert not PageOverrides(force_keep=frozenset({1})).is_empty


class TestStatuses:
    def test_status_per_page(self):
        statuses = effective_statuses(pages("tsb"), mode=SPLIT, remove_blanks=True)
        assert statuses == (PageStatus.KEPT, PageStatus.SEPARATOR, PageStatus.BLANK)

    def test_blank_shown_as_kept_when_removal_disabled(self):
        statuses = effective_statuses(pages("tb"), mode=SPLIT, remove_blanks=False)
        assert statuses[1] is PageStatus.KEPT


class TestWarnings:
    def _warn(self, spec, **kwargs):
        page_tuple = pages(spec)
        result = group_pages(page_tuple, mode=kwargs.get("mode", SPLIT), remove_blanks=True)
        return build_warnings(
            result,
            pages=page_tuple,
            mode=kwargs.get("mode", SPLIT),
            expected_separator=kwargs.get("separator", "EAGC-EDMS-00001"),
            blank_sensitivity_is_aggressive=kwargs.get("aggressive", False),
            is_signed=kwargs.get("signed", False),
        )

    def test_no_separator_warns(self):
        codes = {w.code for w in self._warn("ttt")}
        assert WarningCode.NO_SEPARATOR_FOUND in codes

    def test_separator_present_does_not_warn(self):
        codes = {w.code for w in self._warn("tst")}
        assert WarningCode.NO_SEPARATOR_FOUND not in codes

    def test_clean_mode_never_warns_about_separators(self):
        codes = {w.code for w in self._warn("ttt", mode=CLEAN)}
        assert WarningCode.NO_SEPARATOR_FOUND not in codes

    def test_all_pages_removed_warns(self):
        codes = {w.code for w in self._warn("sss")}
        assert WarningCode.ALL_PAGES_REMOVED in codes

    def test_empty_group_warns(self):
        codes = {w.code for w in self._warn("tsst")}
        assert WarningCode.EMPTY_GROUP_SKIPPED in codes

    def test_signed_pdf_warns(self):
        codes = {w.code for w in self._warn("tst", signed=True)}
        assert WarningCode.SIGNED_PDF in codes

    def test_aggressive_profile_warns_only_with_blanks(self):
        assert WarningCode.AGGRESSIVE_BLANKS in {
            w.code for w in self._warn("tbs t".replace(" ", ""), aggressive=True)
        }
        assert WarningCode.AGGRESSIVE_BLANKS not in {
            w.code for w in self._warn("tst", aggressive=True)
        }
