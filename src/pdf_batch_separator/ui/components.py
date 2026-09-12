"""Reusable presentation widgets shared by the window and the review dialog.

These are the small, composable pieces of the JuaDex visual language: status
pills, metric chips, keyboard hints, card shells and inset metadata rows.  They
own their own styling (built from :mod:`theme` tokens) so screens can be laid
out declaratively and stay consistent.

Nothing here holds application state; every widget is a pure function of the
values passed in, which keeps them safe to rebuild on a theme change.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .theme import MONO, RADIUS, SPACE


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------
def label(text: str = "", variant: str = "body", parent: QWidget | None = None) -> QLabel:
    """A :class:`QLabel` tagged with a typography role from the stylesheet."""

    widget = QLabel(text, parent)
    widget.setProperty("variant", variant)
    return widget


def divider(orientation: Qt.Orientation = Qt.Orientation.Horizontal) -> QFrame:
    """A one-pixel hairline that follows the theme."""

    line = QFrame()
    line.setProperty("role", "divider")
    horizontal = orientation is Qt.Orientation.Horizontal
    line.setFixedHeight(1) if horizontal else line.setFixedWidth(1)
    line.setSizePolicy(
        QSizePolicy.Policy.Expanding if horizontal else QSizePolicy.Policy.Fixed,
        QSizePolicy.Policy.Fixed if horizontal else QSizePolicy.Policy.Expanding,
    )
    return line


def icon_button(
    name: str,
    tooltip: str = "",
    *,
    token: str = "muted",
    size: int = 16,
    checkable: bool = False,
) -> QPushButton:
    """A square, icon-only button (theme switch, settings, help…)."""

    button = QPushButton()
    button.setProperty("kind", "icon")
    button.setIcon(icons.icon(name, token, size))
    button.setIconSize(QSize(size, size))
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
    return button


def text_button(
    text: str,
    *,
    icon_name: str = "",
    kind: str = "default",
    token: str = "",
    tooltip: str = "",
) -> QPushButton:
    """A labelled button, optionally with a leading icon.

    ``kind`` selects the stylesheet treatment (``primary``, ``danger``,
    ``info-outline``, ``ghost``, ``segment``…).  When ``token`` is omitted the
    icon tint is inferred from the kind so solid buttons get white glyphs.
    """

    button = QPushButton(text)
    if kind != "default":
        button.setProperty("kind", kind)
    if icon_name:
        if not token:
            solid = {"primary", "danger", "info", "warning"}
            token = "on_accent" if kind in solid else "muted"
            if kind == "danger-outline":
                token = "danger_soft_fg"
            elif kind == "info-outline":
                token = "info_soft_fg"
        button.setIcon(icons.icon(icon_name, token, 15))
        button.setIconSize(QSize(15, 15))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def shadow(widget: QWidget, *, blur: int = 18, y: int = 2, alpha: int = 26) -> None:
    """Attach a soft elevation shadow (skipped when it would be invisible)."""

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(y)
    tint = QColor(0, 0, 0)
    tint.setAlpha(alpha if not theme.is_dark() else min(alpha + 40, 140))
    effect.setColor(tint)
    widget.setGraphicsEffect(effect)


# ---------------------------------------------------------------------------
# Badges and pills
# ---------------------------------------------------------------------------
class Pill(QLabel):
    """A rounded status chip: soft background, matching text, optional dot.

    Used for page statuses (``Blank``, ``Separator``, ``Keep``) and for the
    row-state column in the batch table.
    """

    def __init__(
        self,
        text: str = "",
        accent: str = "success",
        *,
        solid: bool = False,
        uppercase: bool = False,
        mono: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._accent = accent
        self._solid = solid
        self._uppercase = uppercase
        self._mono = mono
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self.setText(text.upper() if self._uppercase else text)
        self._restyle()

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self._restyle()

    def _restyle(self) -> None:
        shades = theme.family(self._accent)
        if self._solid:
            # Most families are dark enough for white text, but the neutral
            # family inverts between themes and publishes its own ``fg``.
            foreground = shades.get("fg", theme.color("on_accent"))
            background, border = shades["base"], shades["base"]
        else:
            background = shades["soft"]
            foreground = shades["soft_fg"]
            border = shades["soft_line"]
        font = MONO if self._mono else theme.SANS
        size = theme.FONT_SIZE_XS if (self._uppercase or self._mono) else theme.FONT_SIZE_SM
        spacing = "letter-spacing: 0.7px;" if self._uppercase else ""
        self.setStyleSheet(
            f"background: {background}; color: {foreground};"
            f" border: 1px solid {border}; border-radius: {RADIUS['pill']}px;"
            f" padding: 2px 9px; font-family: {font}; font-size: {size}pt;"
            f" font-weight: 700; {spacing}"
        )


class StatusPill(QWidget):
    """An icon + label chip used for row states in the batch table.

    Status is carried by the glyph *and* the wording, never colour alone, so
    the table stays readable for colour-blind users and in high contrast.
    """

    def __init__(
        self,
        text: str = "",
        accent: str = "success",
        icon_name: str = "check-circle",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["xs"] + 2)

        self._icon = QLabel()
        self._icon.setFixedSize(16, 16)
        self._text = QLabel()
        layout.addWidget(self._icon)
        layout.addWidget(self._text)
        layout.addStretch(1)

        self.set_state(text, accent, icon_name)

    def set_state(self, text: str, accent: str, icon_name: str) -> None:
        shades = theme.family(accent)
        self._icon.setPixmap(icons.pixmap(icon_name, shades["soft_fg"], 15))
        self._text.setText(text)
        self._text.setStyleSheet(
            f"color: {shades['soft_fg']}; font-weight: 600;"
            f" font-size: {theme.FONT_SIZE_SM}pt;"
        )


class KeyHint(QLabel):
    """A keyboard-cap glyph, e.g. ``Del`` or ``Ctrl+A``."""

    def __init__(self, keys: str, parent: QWidget | None = None) -> None:
        super().__init__(keys, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        c = theme.colors()
        self.setStyleSheet(
            f"background: {c['surface_alt']}; color: {c['muted']};"
            f" border: 1px solid {c['line_strong']};"
            f" border-bottom-width: 2px; border-radius: {RADIUS['sm']}px;"
            f" padding: 1px 6px; font-family: {MONO};"
            f" font-size: {theme.FONT_SIZE_XS}pt; font-weight: 700;"
        )


class StatChip(QWidget):
    """A coloured dot, a count and a caption — the batch summary metrics."""

    def __init__(
        self,
        count: str,
        caption: str,
        accent: str = "info",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._text = QLabel()
        self._text.setTextFormat(Qt.TextFormat.RichText)
        # Rich text has no intrinsic elision, so a squeezed layout would clip
        # the caption mid-word.  Never let the chip shrink below its content.
        self._text.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._text)

        self._value = count
        self._caption = caption
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.set_value(count, accent)

    def set_value(self, count: str, accent: str | None = None) -> None:
        if accent:
            self._accent = accent
        self._value = count
        shades = theme.family(self._accent)
        self._dot.setPixmap(icons.pixmap("dot", shades["base"], 10))
        self._text.setText(
            f"<span style='font-weight:700;color:{theme.color('ink')};'>{count}</span>"
            f"&nbsp;<span style='color:{theme.color('muted')};'>{self._caption}</span>"
        )
        metrics = self._text.fontMetrics()
        self._text.setMinimumWidth(
            metrics.horizontalAdvance(f"{count} {self._caption}") + 10
        )


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
_card_serial = 0


class Card(QFrame):
    """A white surface with a hairline border and rounded corners.

    ``accent`` tints the border and, with ``accent_fill``, the whole card —
    the treatment used by flagged triage cards.

    The accent is applied through an ``#objectName`` selector rather than a
    bare declaration: an unscoped widget stylesheet in Qt cascades into every
    child, which would repaint the nested pills, buttons and meta blocks too.
    """

    def __init__(
        self,
        *,
        accent: str | None = None,
        accent_fill: bool = False,
        padding: int = SPACE["lg"],
        spacing: int = SPACE["md"],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        global _card_serial
        _card_serial += 1
        self.setObjectName(f"card{_card_serial}")
        self.setProperty("surface", "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)
        self.set_accent(accent, accent_fill)

    def set_accent(self, accent: str | None, fill: bool = False) -> None:
        self._accent = accent
        self._accent_fill = fill
        if accent is None:
            self.setStyleSheet("")
            self.style().unpolish(self)
            self.style().polish(self)
            return
        shades = theme.family(accent)
        background = shades["soft"] if fill else theme.color("surface")
        self.setStyleSheet(
            f"QFrame#{self.objectName()} {{"
            f" background: {background};"
            f" border: 1.5px solid {shades['soft_line']};"
            f" border-radius: {RADIUS['lg']}px; }}"
        )


class BrandMark(QLabel):
    """The JuaDex app mark: a rounded accent tile with a scan glyph."""

    def __init__(self, size: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), RADIUS["md"], RADIUS["md"])
        painter.fillPath(path, QColor(theme.color("success")))
        glyph = int(self._size * 0.62)
        painter.drawPixmap(
            (self._size - glyph) // 2,
            (self._size - glyph) // 2,
            icons.pixmap("scan-line", theme.color("on_accent"), glyph, 2.2),
        )
        painter.end()


class SectionHeader(QWidget):
    """An eyebrow row: monospace caption, optional icon, optional trailing widget."""

    def __init__(
        self,
        text: str,
        *,
        icon_name: str = "",
        accent: str = "muted",
        trailing: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        try:
            tint = theme.family(accent)["soft_fg"]
        except KeyError:
            tint = theme.color(accent)

        if icon_name:
            glyph = QLabel()
            glyph.setPixmap(icons.pixmap(icon_name, tint, 14))
            glyph.setFixedSize(14, 14)
            layout.addWidget(glyph)

        caption = QLabel(text.upper())
        caption.setStyleSheet(
            f"color: {tint}; font-family: {MONO};"
            f" font-size: {theme.FONT_SIZE_XS}pt; font-weight: 700;"
            " letter-spacing: 1.1px;"
        )
        layout.addWidget(caption)
        layout.addStretch(1)
        if trailing is not None:
            layout.addWidget(trailing)


class MetaRow(QWidget):
    """One ``label → value`` line inside an inset metadata block."""

    def __init__(
        self,
        key: str,
        value: str = "",
        *,
        accent: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self._key = QLabel(key.upper())
        self._key.setStyleSheet(
            f"color: {theme.color('muted')}; font-family: {MONO};"
            f" font-size: {theme.FONT_SIZE_XS}pt; letter-spacing: 0.6px;"
        )
        # The key may shrink when the row is tight, but the value carries the
        # information and is protected by its own minimum width below.
        self._key.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._key, 0)

        self._value = QLabel()
        self._value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._value.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._value, 1)
        self.set_value(value, accent)

    def set_key(self, key: str) -> None:
        self._key.setText(key.upper())

    def set_value(self, value: str, accent: str | None = None) -> None:
        if accent:
            try:
                tint = theme.family(accent)["soft_fg"]
            except KeyError:
                tint = theme.color(accent)
        else:
            tint = theme.color("ink")
        self._value.setText(value)
        self._value.setToolTip(value)
        self._value.setStyleSheet(
            f"color: {tint}; font-weight: 600; font-size: {theme.FONT_SIZE_SM}pt;"
        )
        self._value.setMinimumWidth(
            self._value.fontMetrics().horizontalAdvance(value) + 4
        )


class MetaBlock(QFrame):
    """The inset, slightly sunken panel that groups :class:`MetaRow` lines."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("surface", "sunken")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            SPACE["md"], SPACE["sm"] + 2, SPACE["md"], SPACE["sm"] + 2
        )
        self._layout.setSpacing(SPACE["xs"] + 2)

    def add_row(self, key: str, value: str = "", accent: str | None = None) -> MetaRow:
        row = MetaRow(key, value, accent=accent)
        self._layout.addWidget(row)
        return row


class PagePreview(QFrame):
    """The dashed page-thumbnail frame used by the review cards.

    Renders a placeholder (with an optional caption such as ``Empty Scan``)
    until the real rasterised page arrives from the thumbnail worker.
    """

    def __init__(
        self,
        width: int = 92,
        height: int = 118,
        *,
        accent: str | None = None,
        caption: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._accent = accent
        self._caption = caption
        self._pixmap = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_accent(self, accent: str | None, caption: str = "") -> None:
        self._accent = accent
        self._caption = caption
        self.update()

    def set_pixmap(self, pixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS["sm"], RADIUS["sm"])

        painter.fillPath(path, QColor(theme.color("thumb_bg")))

        if self._pixmap is not None and not self._pixmap.isNull():
            painter.save()
            painter.setClipPath(path)
            scaled = self._pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.x() + (rect.width() - scaled.width() / scaled.devicePixelRatio()) / 2
            y = rect.y() + (rect.height() - scaled.height() / scaled.devicePixelRatio()) / 2
            painter.drawPixmap(int(x), int(y), scaled)
            painter.restore()

        if self._accent:
            shades = theme.family(self._accent)
            pen = QPen(QColor(shades["base"]), 1.4)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([3, 3])
        else:
            pen = QPen(QColor(theme.color("line_strong")), 1.0)
        painter.setPen(pen)
        painter.drawPath(path)

        if self._caption and self._pixmap is None:
            font = QFont()
            font.setPointSizeF(theme.FONT_SIZE_XS - 0.5)
            painter.setFont(font)
            tint = theme.family(self._accent)["soft_fg"] if self._accent else theme.color("subtle")
            painter.setPen(QColor(tint))
            painter.drawText(
                rect.adjusted(2, 0, -2, -6),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                self._caption,
            )
        painter.end()


class DropZone(QFrame):
    """The dashed empty-state panel shown when the batch list is empty."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self.setMinimumHeight(210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["xl"], SPACE["xl"], SPACE["xl"], SPACE["xl"])
        layout.setSpacing(SPACE["sm"])
        layout.addStretch(1)

        self._glyph = QLabel()
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph.setPixmap(icons.pixmap("inbox", theme.color("subtle"), 40, 1.6))
        layout.addWidget(self._glyph)

        self._title = label("Drop scanned PDFs here", "title")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title)

        self._hint = label(
            "or use Add files / Add folder to build a batch", "muted"
        )
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def set_hover(self, hover: bool) -> None:
        if hover != self._hover:
            self._hover = hover
            self._glyph.setPixmap(
                icons.pixmap(
                    "inbox",
                    theme.color("success") if hover else theme.color("subtle"),
                    40,
                    1.6,
                )
            )
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS["lg"], RADIUS["lg"])
        painter.fillPath(
            path,
            QColor(theme.color("green_soft") if self._hover else theme.color("surface")),
        )
        pen = QPen(
            QColor(theme.color("success") if self._hover else theme.color("line_strong")),
            1.6,
        )
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


__all__ = [
    "BrandMark",
    "Card",
    "DropZone",
    "KeyHint",
    "MetaBlock",
    "MetaRow",
    "PagePreview",
    "Pill",
    "SectionHeader",
    "StatChip",
    "StatusPill",
    "divider",
    "icon_button",
    "label",
    "shadow",
    "text_button",
]
