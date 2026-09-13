"""Generators for the non-confidential fixture corpus (PRD section 12).

Every fixture is synthesised at test time from code — no real documents, no
personal data, nothing binary committed to source control.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

try:
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore[no-redef]

from pdf_batch_separator.core.separator_pdf import A4_HEIGHT_PT, A4_WIDTH_PT, _barcode_png

TEXT_BLOCK = (
    "This is a synthetic test document generated for the JuaDex PDFs Separator "
    "test corpus. It contains ordinary paragraph text so that the blank-page "
    "detector sees a realistic amount of ink on the page. "
)


def add_text_page(
    document,
    title: str = "Test page",
    *,
    width: float = A4_WIDTH_PT,
    height: float = A4_HEIGHT_PT,
    rotation: int = 0,
    paragraphs: int = 6,
) -> None:
    """Append a normal, clearly non-blank text page."""

    page = document.new_page(width=width, height=height)
    page.insert_textbox(
        pymupdf.Rect(60, 70, width - 60, 130),
        title,
        fontname="hebo",
        fontsize=20,
    )
    body = "\n\n".join(TEXT_BLOCK for _ in range(paragraphs))
    page.insert_textbox(
        pymupdf.Rect(60, 150, width - 60, height - 70),
        body,
        fontname="helv",
        fontsize=11,
    )
    if rotation:
        page.set_rotation(rotation)


def add_blank_page(
    document,
    *,
    width: float = A4_WIDTH_PT,
    height: float = A4_HEIGHT_PT,
    speckles: int = 0,
    edge_shadow: bool = False,
    seed: int = 0,
) -> None:
    """Append a blank page, optionally with scanner-like noise."""

    page = document.new_page(width=width, height=height)
    if edge_shadow:
        # Dark band along the left edge, as a sheet-feeder shadow would appear.
        page.draw_rect(
            pymupdf.Rect(0, 0, 14, height), color=None, fill=(0.25, 0.25, 0.25)
        )
    if speckles:
        rng = np.random.default_rng(seed)
        for _ in range(speckles):
            x = float(rng.uniform(40, width - 40))
            y = float(rng.uniform(40, height - 40))
            radius = float(rng.uniform(0.4, 1.1))
            page.draw_circle(
                pymupdf.Point(x, y), radius, color=None, fill=(0.35, 0.35, 0.35)
            )


def add_faint_text_page(
    document, *, width: float = A4_WIDTH_PT, height: float = A4_HEIGHT_PT
) -> None:
    """Append a page with light pencil-like content that must NOT be removed."""

    page = document.new_page(width=width, height=height)
    page.insert_textbox(
        pymupdf.Rect(70, 260, width - 70, 460),
        "Received 14 March - please file under contracts\n"
        "Checked by A. Mwangi\n"
        "Reference 2291-B",
        fontname="helv",
        fontsize=15,
        color=(0.58, 0.58, 0.58),
        lineheight=2.0,
    )


def add_dark_page(
    document, *, width: float = A4_WIDTH_PT, height: float = A4_HEIGHT_PT
) -> None:
    """Append a solid dark page (e.g. a photograph) which is never blank."""

    page = document.new_page(width=width, height=height)
    page.draw_rect(
        pymupdf.Rect(0, 0, width, height), color=None, fill=(0.08, 0.08, 0.1)
    )


def add_separator_page(
    document,
    value: str,
    *,
    width: float = A4_WIDTH_PT,
    height: float = A4_HEIGHT_PT,
    scale: float = 1.0,
    rotation: int = 0,
    inverted: bool = False,
    contrast: float = 1.0,
) -> None:
    """Append a Code 128 separator sheet, optionally degraded.

    ``scale`` shrinks the barcode, ``rotation`` rotates the page, ``inverted``
    prints light-on-dark, and ``contrast`` < 1 fades the barcode toward grey to
    emulate a poor photocopy.
    """

    page = document.new_page(width=width, height=height)
    png = _barcode_png(value, scale=4)

    if inverted:
        page.draw_rect(pymupdf.Rect(0, 0, width, height), color=None, fill=(0, 0, 0))

    barcode_width = (width - 220) * scale
    barcode_height = 150 * scale
    x0 = (width - barcode_width) / 2
    y0 = 240
    rect = pymupdf.Rect(x0, y0, x0 + barcode_width, y0 + barcode_height)

    page.draw_rect(
        pymupdf.Rect(rect.x0 - 30, rect.y0 - 30, rect.x1 + 30, rect.y1 + 30),
        color=None,
        fill=(1, 1, 1),
    )
    page.insert_image(rect, stream=png, keep_proportion=True)

    page.insert_textbox(
        pymupdf.Rect(60, 120, width - 60, 170),
        "DOCUMENT SEPARATOR",
        fontname="hebo",
        fontsize=24,
        align=pymupdf.TEXT_ALIGN_CENTER,
        color=(1, 1, 1) if inverted else (0, 0, 0),
    )
    page.insert_textbox(
        pymupdf.Rect(60, rect.y1 + 40, width - 60, rect.y1 + 80),
        value,
        fontname="cobo",
        fontsize=14,
        align=pymupdf.TEXT_ALIGN_CENTER,
        color=(1, 1, 1) if inverted else (0, 0, 0),
    )

    if contrast < 1.0:
        # Wash the whole page out with a translucent white overlay.
        page.draw_rect(
            pymupdf.Rect(0, 0, width, height),
            color=None,
            fill=(1, 1, 1),
            fill_opacity=1.0 - contrast,
        )
    if rotation:
        page.set_rotation(rotation)


def add_other_barcode_page(
    document, value: str, *, width: float = A4_WIDTH_PT, height: float = A4_HEIGHT_PT
) -> None:
    """Append a page carrying an unrelated barcode."""

    add_separator_page(document, value, width=width, height=height, scale=0.75)


def build_pdf(path: Path, build) -> Path:
    """Create a PDF at ``path`` using the ``build(document)`` callback."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    try:
        build(document)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()
    return path


def degrade_pdf_like_scan(
    source: Path, destination: Path, *, dpi: int = 200, noise: int = 14, seed: int = 7
) -> Path:
    """Rasterise a PDF and add noise/skew to emulate a print-and-scan cycle."""

    source, destination = Path(source), Path(destination)
    rng = np.random.default_rng(seed)
    src = pymupdf.open(str(source))
    out = pymupdf.open()
    try:
        zoom = dpi / 72.0
        for page in src:
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False
            )
            array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width
            )
            noisy = array.astype(np.int16)
            noisy += rng.integers(-noise, noise + 1, size=noisy.shape)
            # Gentle vertical brightness gradient, like uneven illumination.
            gradient = np.linspace(-12, 12, noisy.shape[0], dtype=np.int16)[:, None]
            noisy += gradient
            noisy = np.clip(noisy, 0, 255).astype(np.uint8)

            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            degraded = pymupdf.Pixmap(
                pymupdf.csGRAY, noisy.shape[1], noisy.shape[0], bytes(noisy.tobytes()), False
            )
            new_page.insert_image(page.rect, pixmap=degraded)
            del degraded, pixmap
        out.save(str(destination), garbage=4, deflate=True)
    finally:
        src.close()
        out.close()
    return destination


__all__ = [
    "add_blank_page",
    "add_dark_page",
    "add_faint_text_page",
    "add_other_barcode_page",
    "add_separator_page",
    "add_text_page",
    "build_pdf",
    "degrade_pdf_like_scan",
]
