"""Blank-detection thresholds and false-positive protection (PRD FR-3).

The guiding rule from the PRD: it is far better to leave an unwanted blank
page than to delete a page holding real content.
"""

from __future__ import annotations

import numpy as np
import pytest

from fixtures.builders import (
    add_blank_page,
    add_dark_page,
    add_faint_text_page,
    add_separator_page,
    add_text_page,
    build_pdf,
)
from pdf_batch_separator.core.analyzer import open_document, render_page_array
from pdf_batch_separator.core.blank_pages import (
    BLANK_PROFILES,
    is_blank_page,
    measure_page,
    non_white_ratio,
    profile_for,
)
from pdf_batch_separator.core.models import BlankSensitivity

ALL_PROFILES = list(BlankSensitivity)


def render_first_page(path):
    document = open_document(path)
    try:
        return render_page_array(document.load_page(0))
    finally:
        document.close()


def make_page(workdir, name, builder):
    path = build_pdf(workdir / f"{name}.pdf", builder)
    return render_first_page(path)


class TestSyntheticArrays:
    def test_pure_white_is_blank(self):
        image = np.full((1000, 800), 255, np.uint8)
        blank, ratio = is_blank_page(image)
        assert blank and ratio == 0.0

    def test_solid_black_is_not_blank(self):
        """A dark page has a low mean, so a naive mean-50 rule would call it
        blank; the dark-page guard must prevent that."""

        blank, ratio = is_blank_page(np.zeros((1000, 800), np.uint8))
        assert not blank
        assert ratio == pytest.approx(1.0)

    def test_mid_grey_page_is_not_blank(self):
        blank, _ = is_blank_page(np.full((1000, 800), 120, np.uint8))
        assert not blank

    def test_half_inked_page_is_not_blank(self):
        image = np.full((1000, 800), 255, np.uint8)
        image[:500, :] = 0
        assert not is_blank_page(image)[0]

    def test_edge_noise_is_cropped_away(self):
        image = np.full((1000, 800), 255, np.uint8)
        image[:, :60] = 0  # left-edge scanner shadow inside the 10% crop
        assert is_blank_page(image)[0]

    def test_dust_speck_is_opened_away(self):
        image = np.full((1000, 800), 255, np.uint8)
        rng = np.random.default_rng(1)
        for _ in range(30):
            y, x = rng.integers(200, 800), rng.integers(200, 600)
            image[y, x] = 0  # isolated single pixels
        assert is_blank_page(image)[0]

    def test_concentrated_mark_is_not_blank(self):
        """A stamp or a single word: tiny global ratio, obvious local cluster."""

        image = np.full((2000, 1500), 255, np.uint8)
        image[900:960, 700:820] = 0
        blank, ratio = is_blank_page(image)
        assert ratio < 0.005, "global ratio really is tiny"
        assert not blank, "but the page must be protected as real content"

    def test_empty_array_is_safe(self):
        assert non_white_ratio(np.zeros((0, 0), np.uint8), profile_for(BlankSensitivity.BALANCED)) == 0.0

    def test_tiny_image_is_not_cropped_to_nothing(self):
        assert is_blank_page(np.full((4, 4), 255, np.uint8))[0]

    def test_rgb_input_supported(self):
        assert is_blank_page(np.full((500, 400, 3), 255, np.uint8))[0]


class TestRenderedPages:
    def test_blank_page_removed_by_every_profile(self, workdir):
        image = make_page(workdir, "blank", lambda d: add_blank_page(d))
        for profile in ALL_PROFILES:
            assert is_blank_page(image, profile)[0], profile

    def test_text_page_kept_by_every_profile(self, workdir):
        image = make_page(workdir, "text", lambda d: add_text_page(d, "Contract"))
        for profile in ALL_PROFILES:
            assert not is_blank_page(image, profile)[0], profile

    def test_faint_pencil_never_removed(self, workdir):
        """PRD section 11 + milestone 4: faint real content must survive."""

        image = make_page(workdir, "faint", add_faint_text_page)
        for profile in ALL_PROFILES:
            assert not is_blank_page(image, profile)[0], (
                f"{profile} deleted a page with real content"
            )

    def test_dark_photo_never_removed(self, workdir):
        image = make_page(workdir, "dark", add_dark_page)
        for profile in ALL_PROFILES:
            assert not is_blank_page(image, profile)[0], profile

    def test_separator_sheet_is_not_blank(self, workdir):
        image = make_page(
            workdir, "sep", lambda d: add_separator_page(d, "EAGC-EDMS-00001")
        )
        for profile in ALL_PROFILES:
            assert not is_blank_page(image, profile)[0], profile

    def test_single_word_page_never_removed(self, workdir):
        image = make_page(
            workdir, "word", lambda d: add_text_page(d, "X", paragraphs=0)
        )
        for profile in ALL_PROFILES:
            assert not is_blank_page(image, profile)[0], profile

    def test_edge_shadow_page_still_blank(self, workdir):
        image = make_page(
            workdir, "shadow", lambda d: add_blank_page(d, edge_shadow=True)
        )
        assert is_blank_page(image, BlankSensitivity.BALANCED)[0]

    def test_speckled_blank_removed_at_balanced(self, workdir):
        image = make_page(
            workdir, "speckled", lambda d: add_blank_page(d, speckles=90, seed=3)
        )
        assert is_blank_page(image, BlankSensitivity.BALANCED)[0]

    def test_landscape_blank_page(self, workdir):
        image = make_page(
            workdir, "landscape", lambda d: add_blank_page(d, width=841.89, height=595.28)
        )
        assert is_blank_page(image)[0]


class TestProfileOrdering:
    def test_thresholds_increase_with_sensitivity(self):
        conservative = profile_for(BlankSensitivity.CONSERVATIVE).ratio_threshold
        balanced = profile_for(BlankSensitivity.BALANCED).ratio_threshold
        aggressive = profile_for(BlankSensitivity.AGGRESSIVE).ratio_threshold
        assert conservative < balanced < aggressive

    def test_balanced_matches_prd_baseline(self):
        """The PRD fixes the reference default at 0.005 with a mean-50 cut."""

        profile = profile_for(BlankSensitivity.BALANCED)
        assert profile.ratio_threshold == 0.005
        assert profile.binarization_offset == 50
        assert profile.crop_horizontal == 0.10
        assert profile.crop_vertical == 0.05

    def test_aggressive_removes_a_superset(self):
        """Anything blank at a lower sensitivity stays blank at a higher one."""

        rng = np.random.default_rng(5)
        for _ in range(6):
            image = np.full((1200, 900), 255, np.uint8)
            for _ in range(int(rng.integers(0, 60))):
                y, x = int(rng.integers(100, 1100)), int(rng.integers(100, 800))
                image[y : y + 2, x : x + 2] = 90
            conservative = is_blank_page(image, BlankSensitivity.CONSERVATIVE)[0]
            balanced = is_blank_page(image, BlankSensitivity.BALANCED)[0]
            aggressive = is_blank_page(image, BlankSensitivity.AGGRESSIVE)[0]
            assert not conservative or balanced
            assert not balanced or aggressive

    def test_measure_returns_ratio_and_cluster_flag(self):
        ratio, dense = measure_page(
            np.full((900, 700), 255, np.uint8), profile_for(BlankSensitivity.BALANCED)
        )
        assert ratio == 0.0 and dense is False
