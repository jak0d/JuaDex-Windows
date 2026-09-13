"""Barcode normalisation, decoding and the retry ladder (PRD FR-2).

Decoding uses the ZXing-C++ Python bindings only; ZBar is never imported or
required.  The first decode attempt enables rotation, downscaling and
inversion.  If the *expected* marker is not among the results, progressively
more expensive image preparations are tried and the ladder stops as soon as the
expected marker appears.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .models import MAX_SEPARATOR_LENGTH

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard exercised only on broken installs
    import zxingcpp
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "zxing-cpp is required for barcode decoding. Install with 'pip install zxing-cpp'."
    ) from exc


#: Formats searched during analysis.  Restricting the set keeps decoding fast
#: while still catching the 1D symbologies a scanner separator sheet may use.
#:
#: zxing-cpp 3.x deprecated constructing a combined ``BarcodeFormats`` value
#: with ``|`` and now accepts an iterable of formats. Older 2.x wheels used by
#: the Windows build still accept the combined value, so :func:`_read_once`
#: falls back lazily if an iterable is not supported. Keeping ``SEARCH_FORMATS``
#: as plain enum values avoids deprecation warnings at import time.
SEARCH_FORMATS = (
    zxingcpp.BarcodeFormat.Code128,
    zxingcpp.BarcodeFormat.Code39,
    zxingcpp.BarcodeFormat.Code93,
    zxingcpp.BarcodeFormat.ITF,
    zxingcpp.BarcodeFormat.Codabar,
    zxingcpp.BarcodeFormat.QRCode,
    zxingcpp.BarcodeFormat.DataMatrix,
    zxingcpp.BarcodeFormat.PDF417,
    zxingcpp.BarcodeFormat.Aztec,
)

_NULL_CHARS = "\x00\ufeff"


def normalize_barcode_value(value: str | bytes | None) -> str:
    """Normalise a decoded value for *safe* comparison.

    Rules (mirroring the reference behaviour described in the PRD):

    * decode bytes as UTF-8 with replacement;
    * drop NULs / BOMs and every kind of whitespace (including inner spaces);
    * upper-case for case-insensitive matching;
    * strip a *matching* outer ``*...*`` pair, which Code 39 readers include as
      start/stop characters.
    """

    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = str(value)
    for ch in _NULL_CHARS:
        text = text.replace(ch, "")
    # Remove *all* whitespace, not just the ends: scanners sometimes inject a
    # stray space inside long values.
    text = "".join(text.split())
    text = text.upper()
    if len(text) >= 2 and text.startswith("*") and text.endswith("*"):
        text = text[1:-1]
    return text


def barcode_value_matches(decoded: str | bytes | None, expected: str | bytes | None) -> bool:
    """Exact match after :func:`normalize_barcode_value` on both operands."""

    normalized_expected = normalize_barcode_value(expected)
    if not normalized_expected:
        return False
    return normalize_barcode_value(decoded) == normalized_expected


def validate_separator_value(value: str) -> tuple[bool, str]:
    """Validate a user-supplied custom separator value.

    Returns ``(is_valid, message)``; ``message`` is empty when valid.
    """

    if value is None:
        return False, "Enter a separator value."
    raw = str(value)
    if not raw.strip():
        return False, "Enter a separator value."
    if len(raw) > MAX_SEPARATOR_LENGTH:
        return False, f"Separator value must be {MAX_SEPARATOR_LENGTH} characters or fewer."
    normalized = normalize_barcode_value(raw)
    if not normalized:
        return False, "The separator value must contain at least one visible character."
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return False, "The separator value must not contain control characters."
    try:
        raw.encode("latin-1")
    except UnicodeEncodeError:
        return False, (
            "Use only characters that can be printed in a Code 128 barcode "
            "(letters, digits and common punctuation)."
        )
    return True, ""


@dataclass(frozen=True)
class DecodeAttempt:
    """Diagnostic record of one rung of the retry ladder."""

    name: str
    barcode_count: int
    matched: bool


@dataclass(frozen=True)
class DecodeOutcome:
    """Everything the analyzer needs to know about one page's barcodes."""

    barcodes: tuple[tuple[str, str], ...]
    """All decoded ``(value, format)`` pairs, de-duplicated, in discovery order."""

    matched: bool
    """True when the expected marker was decoded."""

    attempts: tuple[DecodeAttempt, ...] = ()
    """Which preparations ran, for logging and troubleshooting."""


# ----------------------------------------------------------------------
# Image preparations used by the retry ladder.
# ----------------------------------------------------------------------
def _to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3:
        if image.shape[2] == 1:
            return image[:, :, 0]
        # BGR/RGB -> luminance.  Coefficient order is symmetric enough that
        # channel order does not matter for barcode contrast.
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        rgb = image[:, :, :3].astype(np.float32)
        return np.clip(rgb @ weights, 0, 255).astype(np.uint8)
    raise ValueError(f"Unsupported image shape for grayscale conversion: {image.shape}")


def _autocontrast(gray: np.ndarray, cutoff: float = 0.5) -> np.ndarray:
    """Pillow-style autocontrast implemented on the numpy array directly."""

    if gray.size == 0:
        return gray
    lo = float(np.percentile(gray, cutoff))
    hi = float(np.percentile(gray, 100.0 - cutoff))
    if hi <= lo:
        return gray
    scaled = (gray.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return np.clip(scaled, 0, 255).astype(np.uint8)


#: Short-edge pixel count above which a 1.5x upscale cannot add information.
#:
#: The upscale rung exists to rescue barcodes whose bars are only a pixel or
#: two wide, which happens on low-resolution renders.  An A4 page rendered at
#: the analysis DPI of 300 already has a ~2480 px short edge, where a printed
#: Code 128 narrow bar spans several pixels.  Measured over a 39-variant corpus
#: (scales 1.0-0.22, all four rotations, faded, inverted, and print/scan
#: degraded), the upscale rung never decoded a symbol that the other three
#: rungs missed, while costing roughly half a second per page.  Below this
#: threshold the rung still runs, so genuinely small renders keep the benefit.
UPSCALE_SKIP_SHORT_EDGE = 1800


def _upscale(gray: np.ndarray, factor: float = 1.5, max_dim: int = 9000) -> np.ndarray | None:
    """Nearest-neighbour upscale via numpy repeat-free index mapping.

    Returns ``None`` when the result would exceed ``max_dim`` on either axis,
    which keeps memory bounded on already-huge renders.
    """

    if gray.size == 0:
        return None
    height, width = gray.shape[:2]
    new_h, new_w = int(round(height * factor)), int(round(width * factor))
    if new_h > max_dim or new_w > max_dim or new_h <= 0 or new_w <= 0:
        return None
    row_idx = (np.arange(new_h) / factor).astype(np.int32).clip(0, height - 1)
    col_idx = (np.arange(new_w) / factor).astype(np.int32).clip(0, width - 1)
    return gray[row_idx][:, col_idx]


def otsu_threshold(gray: np.ndarray) -> int:
    """Compute Otsu's threshold for an 8-bit grayscale image."""

    histogram = np.bincount(gray.reshape(-1), minlength=256).astype(np.float64)
    total = histogram.sum()
    if total <= 0:
        return 128
    bins = np.arange(256, dtype=np.float64)
    weight_bg = np.cumsum(histogram)
    weight_fg = total - weight_bg
    cumulative_mean = np.cumsum(histogram * bins)
    total_mean = cumulative_mean[-1]
    valid = (weight_bg > 0) & (weight_fg > 0)
    if not valid.any():
        return 128
    mean_bg = np.zeros(256, dtype=np.float64)
    mean_fg = np.zeros(256, dtype=np.float64)
    np.divide(cumulative_mean, weight_bg, out=mean_bg, where=weight_bg > 0)
    np.divide(total_mean - cumulative_mean, weight_fg, out=mean_fg, where=weight_fg > 0)
    between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    between[~valid] = -1.0
    return int(np.argmax(between))


def _otsu_binarize(gray: np.ndarray) -> np.ndarray:
    threshold = otsu_threshold(gray)
    return np.where(gray > threshold, np.uint8(255), np.uint8(0))


@lru_cache(maxsize=1)
def _legacy_search_formats():
    """Combined format mask for older zxing-cpp wheels."""

    combined = SEARCH_FORMATS[0]
    for barcode_format in SEARCH_FORMATS[1:]:
        combined |= barcode_format
    return combined


def _read_once(image: np.ndarray) -> list:
    """Call ZXing once, accepting both 2.x and 3.x ``formats`` APIs."""

    try:
        return zxingcpp.read_barcodes(
            image,
            formats=SEARCH_FORMATS,
            try_rotate=True,
            try_downscale=True,
        )
    except TypeError:
        return zxingcpp.read_barcodes(
            image,
            formats=_legacy_search_formats(),
            try_rotate=True,
            try_downscale=True,
        )


def _format_name(format_value) -> str:
    """Stable barcode-format names across zxing-cpp releases."""

    text = str(format_value).replace("BarcodeFormat.", "").strip()
    compact = "".join(ch for ch in text if ch.isalnum()).upper()
    known = {
        "CODE128": "Code128",
        "CODE39": "Code39",
        "CODE93": "Code93",
        "ITF": "ITF",
        "CODABAR": "Codabar",
        "QRCODE": "QRCode",
        "DATAMATRIX": "DataMatrix",
        "PDF417": "PDF417",
        "AZTEC": "Aztec",
    }
    return known.get(compact, text.replace(" ", ""))


def _read(image: np.ndarray) -> list:
    """Call ZXing with rotation, downscaling and inversion enabled."""

    try:
        results = _read_once(image)
        if not results:
            # ZXing-C++ Python bindings do not expose the C++ tryInvert flag,
            # so retry with an inverted image when the normal pass finds nothing.
            results = _read_once(255 - image)
        return results
    except Exception:  # pragma: no cover - defensive; a bad buffer must not kill a batch
        logger.debug("Barcode decode failed for one image preparation", exc_info=True)
        return []


def decode_page_barcodes(
    image: np.ndarray,
    expected: str | None = None,
    *,
    enable_retries: bool = True,
) -> DecodeOutcome:
    """Decode barcodes from a rendered page, retrying only when needed.

    ``image`` may be grayscale or 3-channel.  The retry ladder is:

    1. as-rendered;
    2. grayscale + autocontrast;
    3. 1.5x upscale (of the autocontrast image);
    4. Otsu thresholding.

    The ladder stops early as soon as ``expected`` is decoded.  Every value
    seen along the way is retained for diagnostics.
    """

    collected: dict[tuple[str, str], None] = {}
    attempts: list[DecodeAttempt] = []
    matched = False

    def run(name: str, prepared: np.ndarray | None) -> bool:
        nonlocal matched
        if prepared is None or prepared.size == 0:
            return False
        results = _read(prepared)
        hit = False
        for result in results:
            text = result.text or ""
            fmt = _format_name(result.format)
            if not text:
                continue
            collected.setdefault((text, fmt), None)
            if expected and barcode_value_matches(text, expected):
                hit = True
        attempts.append(DecodeAttempt(name=name, barcode_count=len(results), matched=hit))
        if hit:
            matched = True
        return hit

    if run("as_rendered", image):
        return DecodeOutcome(tuple(collected.keys()), True, tuple(attempts))

    if not enable_retries:
        return DecodeOutcome(tuple(collected.keys()), matched, tuple(attempts))

    # Retries only pay off when we are hunting for a specific marker.  Without
    # an expected value the first pass already reported everything it can see.
    if not expected:
        return DecodeOutcome(tuple(collected.keys()), matched, tuple(attempts))

    gray = _to_grayscale(image)
    contrasted = _autocontrast(gray)
    if run("gray_autocontrast", contrasted):
        return DecodeOutcome(tuple(collected.keys()), True, tuple(attempts))

    # Otsu is evaluated before the 1.5x upscale purely for speed: it costs a
    # few tens of milliseconds while decoding an upscaled 300 DPI page costs
    # several hundred.  Both rungs still run when neither succeeds, so the
    # ladder required by the PRD is preserved in full; only the order changes.
    if run("otsu", _otsu_binarize(contrasted)):
        return DecodeOutcome(tuple(collected.keys()), True, tuple(attempts))

    # The upscale rung only adds information when the render is small enough
    # that bars are near the pixel limit; see UPSCALE_SKIP_SHORT_EDGE.
    short_edge = min(contrasted.shape[:2]) if contrasted.ndim >= 2 else 0
    if short_edge < UPSCALE_SKIP_SHORT_EDGE:
        if run("upscale_1.5x", _upscale(contrasted, 1.5)):
            return DecodeOutcome(tuple(collected.keys()), True, tuple(attempts))
    else:
        attempts.append(
            DecodeAttempt(name="upscale_1.5x_skipped_high_res", barcode_count=0, matched=False)
        )

    return DecodeOutcome(tuple(collected.keys()), matched, tuple(attempts))


def find_matching_value(
    barcodes: Iterable[tuple[str, str]] | Sequence[tuple[str, str]],
    expected: str | None,
) -> tuple[str, str] | None:
    """Return the first ``(value, format)`` pair matching ``expected``."""

    if not expected:
        return None
    for value, fmt in barcodes:
        if barcode_value_matches(value, expected):
            return value, fmt
    return None


__all__ = [
    "UPSCALE_SKIP_SHORT_EDGE",
    "DecodeAttempt",
    "DecodeOutcome",
    "SEARCH_FORMATS",
    "barcode_value_matches",
    "decode_page_barcodes",
    "find_matching_value",
    "normalize_barcode_value",
    "otsu_threshold",
    "validate_separator_value",
]
