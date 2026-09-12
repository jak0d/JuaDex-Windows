"""Blank-page detection with user-facing sensitivity profiles (PRD FR-3).

The baseline algorithm is the one specified in the PRD:

1. convert the rendered page to grayscale;
2. compute the mean pixel value;
3. binarize at ``mean - 50``;
4. crop 10% left/right and 5% top/bottom to suppress scanner edge shadows;
5. run a small morphological opening to drop dust specks while keeping strokes;
6. compute the non-white pixel ratio;
7. call the page blank when the ratio is below ``0.005``.

Only the *thresholds* differ between profiles; the pipeline is identical, so a
page's measured ratio is comparable across profiles.  Detection never uses OCR.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import BlankSensitivity


@dataclass(frozen=True)
class BlankProfile:
    """Tunable constants behind a user-facing sensitivity level."""

    ratio_threshold: float
    """Maximum non-white ratio that still counts as blank."""

    binarization_offset: int = 50
    """Binarize at ``mean - offset``; larger keeps only darker ink."""

    crop_horizontal: float = 0.10
    crop_vertical: float = 0.05
    morphology_size: int = 2
    """Square structuring element for the opening pass; 0 disables it."""

    min_dark_pixels: int = 0
    """Absolute floor so a handful of specks can never trip detection."""

    cluster_block_px: int = 48
    """Side of the local-density window, ~4 mm at 300 DPI."""

    cluster_fill_threshold: float = 0.16
    """A block this densely inked means real content, whatever the page ratio."""

    cluster_min_pixels: int = 250
    """Ignore clusters smaller than this many ink pixels (dust, JPEG specks)."""


#: Exact thresholds stay in code, as required by the PRD; the UI shows only the
#: three friendly names.
BLANK_PROFILES: dict[BlankSensitivity, BlankProfile] = {
    # Only pristine, essentially empty pages are removed.
    BlankSensitivity.CONSERVATIVE: BlankProfile(
        ratio_threshold=0.0015,
        binarization_offset=60,
        morphology_size=2,
        min_dark_pixels=0,
    ),
    # Reference-equivalent default from the PRD.
    BlankSensitivity.BALANCED: BlankProfile(
        ratio_threshold=0.005,
        binarization_offset=50,
        morphology_size=2,
        min_dark_pixels=0,
    ),
    # Tolerates speckled / dirty blank backsides.
    BlankSensitivity.AGGRESSIVE: BlankProfile(
        ratio_threshold=0.015,
        binarization_offset=40,
        morphology_size=3,
        min_dark_pixels=0,
    ),
}

DEFAULT_SENSITIVITY = BlankSensitivity.BALANCED


def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert an RGB/RGBA/grayscale uint8 array to 2-D grayscale."""

    if image.ndim == 2:
        return image
    if image.ndim == 3:
        if image.shape[2] == 1:
            return image[:, :, 0]
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        return np.clip(image[:, :, :3].astype(np.float32) @ weights, 0, 255).astype(np.uint8)
    raise ValueError(f"Unsupported image shape: {image.shape}")


def _crop(image: np.ndarray, horizontal: float, vertical: float) -> np.ndarray:
    """Trim the borders where scanner shadow and punch holes live."""

    height, width = image.shape[:2]
    dx = int(width * horizontal)
    dy = int(height * vertical)
    # Never crop away the whole page (tiny pages, odd aspect ratios).
    if width - 2 * dx < 8 or height - 2 * dy < 8:
        return image
    return image[dy : height - dy, dx : width - dx]


def _binary_erode(mask: np.ndarray, size: int) -> np.ndarray:
    """Erode a boolean mask with a ``size`` x ``size`` square element."""

    if size <= 1:
        return mask
    eroded = mask
    # Separable erosion: horizontal then vertical minima via shifted ANDs.
    for axis in (0, 1):
        acc = eroded
        for offset in range(1, size):
            shifted = np.roll(eroded, offset, axis=axis)
            # Roll wraps around; force the wrapped band to False.
            if axis == 0:
                shifted[:offset, :] = False
            else:
                shifted[:, :offset] = False
            acc = acc & shifted
        eroded = acc
    return eroded


def _binary_dilate(mask: np.ndarray, size: int) -> np.ndarray:
    """Dilate a boolean mask with a ``size`` x ``size`` square element."""

    if size <= 1:
        return mask
    dilated = mask
    for axis in (0, 1):
        acc = dilated
        for offset in range(1, size):
            shifted = np.roll(dilated, -offset, axis=axis)
            if axis == 0:
                shifted[-offset:, :] = False
            else:
                shifted[:, -offset:] = False
            acc = acc | shifted
        dilated = acc
    return dilated


def _opening(mask: np.ndarray, size: int) -> np.ndarray:
    """Morphological opening (erode then dilate) to suppress isolated dust."""

    if size <= 1:
        return mask
    return _binary_dilate(_binary_erode(mask, size), size)


#: A page whose average tone is darker than this cannot be blank paper, even
#: when the mean-relative threshold finds little "ink" (solid dark scans).
DARK_PAGE_MEAN = 160.0


def _has_dense_cluster(mask: np.ndarray, profile: BlankProfile) -> bool:
    """True when ink is concentrated somewhere, rather than spread as dust.

    A page holding a single word, a signature or a small stamp has a tiny
    global ink ratio but an obvious *local* concentration.  Summing the mask
    over non-overlapping blocks via reshape is cheap and catches exactly that,
    protecting real content from removal.
    """

    block = max(8, profile.cluster_block_px)
    height, width = mask.shape[:2]
    if height < block or width < block:
        return False

    rows, cols = height // block, width // block
    if rows == 0 or cols == 0:
        return False

    trimmed = mask[: rows * block, : cols * block]
    # (rows, block, cols, block) -> sum over the two block axes.
    blocks = trimmed.reshape(rows, block, cols, block).sum(axis=(1, 3))
    peak = int(blocks.max())
    if peak < profile.cluster_min_pixels:
        return False
    return (peak / float(block * block)) >= profile.cluster_fill_threshold


def measure_page(image: np.ndarray, profile: BlankProfile) -> tuple[float, bool]:
    """Measure a page: ``(non_white_ratio, has_dense_cluster)``."""

    gray = to_grayscale(image)
    if gray.size == 0:
        return 0.0, False

    cropped = _crop(gray, profile.crop_horizontal, profile.crop_vertical)
    if cropped.size == 0:
        return 0.0, False

    mean_value = float(cropped.mean())

    # Guard the pathological "solid dark page" case first: the mean itself is
    # low, so a mean-relative threshold finds almost nothing and the ratio
    # would read ~0.  A dark page (photograph, black scan) is never blank.
    if mean_value < DARK_PAGE_MEAN:
        return 1.0, True

    threshold = mean_value - profile.binarization_offset
    dark = cropped < threshold

    if profile.morphology_size > 1:
        dark = _opening(dark, profile.morphology_size)

    dense = _has_dense_cluster(dark, profile)

    dark_count = int(np.count_nonzero(dark))
    if dark_count <= profile.min_dark_pixels:
        return 0.0, dense
    return dark_count / float(cropped.size), dense


def non_white_ratio(image: np.ndarray, profile: BlankProfile) -> float:
    """Return the fraction of 'ink' pixels remaining after the cleanup pass."""

    return measure_page(image, profile)[0]


def is_blank_page(
    image: np.ndarray,
    sensitivity: BlankSensitivity | BlankProfile = DEFAULT_SENSITIVITY,
) -> tuple[bool, float]:
    """Classify a rendered page.

    Returns ``(is_blank, non_white_ratio)`` so callers can display the measured
    ratio alongside the decision.
    """

    profile = (
        sensitivity
        if isinstance(sensitivity, BlankProfile)
        else BLANK_PROFILES[BlankSensitivity(sensitivity)]
    )
    ratio, dense = measure_page(image, profile)
    # A localised concentration of ink means real content (a single word, a
    # signature, a stamp).  Never remove such a page, whatever the ratio says.
    if dense:
        return False, ratio
    return ratio < profile.ratio_threshold, ratio


def profile_for(sensitivity: BlankSensitivity) -> BlankProfile:
    return BLANK_PROFILES[BlankSensitivity(sensitivity)]


__all__ = [
    "DARK_PAGE_MEAN",
    "measure_page",
    "BLANK_PROFILES",
    "BlankProfile",
    "DEFAULT_SENSITIVITY",
    "is_blank_page",
    "non_white_ratio",
    "profile_for",
    "to_grayscale",
]
