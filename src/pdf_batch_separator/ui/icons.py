"""Vector icon set for the desktop client.

The icons are stored as SVG path data rather than binary assets so they can be
recoloured for any theme at run time and stay crisp at every DPI.  Geometry
follows the Lucide conventions — a 24x24 box, 2px strokes, round caps and
joins — which is why the outlines sit comfortably next to Segoe UI.

Call :func:`icon` to get a themed :class:`QIcon`::

    button.setIcon(icons.icon("play", "on_accent"))

``color`` accepts any token understood by :func:`theme.color`, so icons follow
the light/dark switch automatically as long as they are rebuilt afterwards.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

# ---------------------------------------------------------------------------
# Path data (24x24 viewBox, stroked)
# ---------------------------------------------------------------------------
STROKE: dict[str, str] = {
    # -- brand / chrome ---------------------------------------------------
    "shield-check": "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z M9 12l2 2 4-4",
    "scissors": "M6 6a3 3 0 1 0 0-.01z M6 21a3 3 0 1 0 0-.01z M20 4 8.12 15.88 M14.47 14.48 20 20 M8.12 8.12 12 12",
    "sun": "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z M12 1v2 M12 21v2 M4.22 4.22l1.42 1.42 M18.36 18.36l1.42 1.42 M1 12h2 M21 12h2 M4.22 19.78l1.42-1.42 M18.36 5.64l1.42-1.42",
    "moon": "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z",
    "help-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3 M12 17h.01",
    "keyboard": "M3 6h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z M6 10h.01 M10 10h.01 M14 10h.01 M18 10h.01 M8 14h8",
    "settings": "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
    "sliders": "M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 14h6 M9 8h6 M17 16h6",
    # -- files ------------------------------------------------------------
    "file-text": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8",
    "file-plus": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M12 18v-6 M9 15h6",
    "files": "M15 2H9a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7z M15 2v5h5 M4 8v11a3 3 0 0 0 3 3h9",
    "folder": "M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2z",
    "folder-plus": "M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2z M12 11v6 M9 14h6",
    "folder-open": "M6 20h13a2 2 0 0 0 1.9-1.37l1.7-5.1A1 1 0 0 0 21.66 12H8.5a2 2 0 0 0-1.9 1.37l-2.1 6.3 M4 19.7V6a2 2 0 0 1 2-2h5l2 3h5a2 2 0 0 1 2 2v3",
    "printer": "M6 9V2h12v7 M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2 M6 14h12v8H6z",
    # -- actions ----------------------------------------------------------
    "plus": "M12 5v14 M5 12h14",
    "x": "M18 6 6 18 M6 6l12 12",
    "trash": "M3 6h18 M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2 M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6 M10 11v6 M14 11v6",
    "eye": "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    "flag": "M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z M4 22v-7",
    "refresh": "M21 12a9 9 0 1 1-3.2-6.9 M21 3v6h-6",
    "rotate-ccw": "M3 12a9 9 0 1 0 3.2-6.9 M3 3v6h6",
    "play": "M7 4.5v15l12-7.5z",
    "zap": "M13 2 4 14h7l-1 8 9-12h-7z",
    "copy": "M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1",
    "external-link": "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6 M15 3h6v6 M10 14 21 3",
    "search": "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M21 21l-4.35-4.35",
    "sort": "M11 5h10 M11 9h7 M11 13h4 M7 4v16 M3 16l4 4 4-4",
    "list-checks": "M11 6h10 M11 12h10 M11 18h10 M3 6l2 2 3-3 M3 13l2 2 3-3",
    "check": "M20 6 9 17l-5-5",
    "minus": "M5 12h14",
    # -- status -----------------------------------------------------------
    "check-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M8.5 12.2l2.4 2.4 4.6-4.9",
    "alert-triangle": "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z M12 9v4 M12 17h.01",
    "alert-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 8v5 M12 16h.01",
    "x-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M15 9l-6 6 M9 9l6 6",
    "slash-circle": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M5.6 5.6l12.8 12.8",
    "clock": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",
    "loader": "M12 2v4 M12 18v4 M4.9 4.9l2.8 2.8 M16.2 16.2l2.8 2.8 M2 12h4 M18 12h4 M4.9 19.1l2.8-2.8 M16.2 7.8l2.8-2.8",
    "info": "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 16v-5 M12 8h.01",
    # -- domain -----------------------------------------------------------
    "split": "M6 3v12a3 3 0 0 0 3 3h9 M15 15l3 3-3 3 M6 3 3 6 M6 3l3 3",
    "scan-line": "M3 7V5a2 2 0 0 1 2-2h2 M17 3h2a2 2 0 0 1 2 2v2 M21 17v2a2 2 0 0 1-2 2h-2 M7 21H5a2 2 0 0 1-2-2v-2 M7 12h10",
    "barcode": "M3 5v14 M6 5v14 M9.5 5v14 M13 5v10 M16.5 5v14 M20 5v14",
    "qr-code": "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h2v2h-2z M18 14h2v2h-2z M14 18h2v2h-2z M18 18h2v2h-2z",
    "layers": "M12 2 2 7l10 5 10-5z M2 17l10 5 10-5 M2 12l10 5 10-5",
    "inbox": "M22 12h-6l-2 3h-4l-2-3H2 M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
    # -- navigation -------------------------------------------------------
    "chevron-down": "M6 9l6 6 6-6",
    "chevron-right": "M9 18l6-6-6-6",
    "chevron-left": "M15 18l-6-6 6-6",
    "arrow-right": "M5 12h14 M12 5l7 7-7 7",
    "user": "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M20 21a8 8 0 1 0-16 0",
}

# Icons drawn as solid shapes instead of strokes.
FILLED: dict[str, str] = {
    "dot": "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    "play-solid": "M7 4.5v15l12-7.5z",
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'fill="{fill}" stroke="{stroke}" stroke-width="{width}" '
    'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


def _document(name: str, tint: str, width: float) -> bytes:
    if name in FILLED:
        body = f'<path d="{FILLED[name]}"/>'
        return _SVG.format(fill=tint, stroke="none", width=0, body=body).encode()
    if name not in STROKE:
        raise KeyError(f"Unknown icon: {name!r}")
    body = f'<path d="{STROKE[name]}"/>'
    return _SVG.format(fill="none", stroke=tint, width=width, body=body).encode()


@lru_cache(maxsize=512)
def pixmap(name: str, tint: str, size: int = 16, width: float = 2.0, dpr: float = 2.0) -> QPixmap:
    """Render one icon to a device-pixel-ratio-aware pixmap.

    ``tint`` is a literal colour string; :func:`icon` resolves design tokens
    before calling this.
    """

    renderer = QSvgRenderer(QByteArray(_document(name, tint, width)))
    pm = QPixmap(QSize(int(size * dpr), int(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # The target rectangle must be given explicitly and in *logical* units.
    # QSvgRenderer.render(painter) alone falls back to the painter's device
    # viewport, which on a DPR-scaled pixmap is twice the logical size — the
    # glyph would be drawn at 2x and clipped to its top-left quadrant.
    renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
    painter.end()
    return pm


def icon(name: str, token: str = "ink", size: int = 16, width: float = 2.0) -> QIcon:
    """A themed :class:`QIcon`.

    ``token`` is resolved through :func:`theme.color`, so ``"muted"``,
    ``"danger"`` and ``"on_accent"`` all work.  Unknown tokens are treated as
    literal colours, which keeps one-off tints possible.
    """

    try:
        tint = theme.color(token)
    except KeyError:
        tint = token
    return QIcon(pixmap(name, tint, size, width))


def clear_cache() -> None:
    """Drop cached pixmaps, e.g. after the palette changed."""

    pixmap.cache_clear()


__all__ = ["FILLED", "STROKE", "clear_cache", "icon", "pixmap"]
