"""Custom painting for the batch table.

Qt's default item rendering can only draw a string per cell, which is not
enough for the redesigned list: the file column pairs an icon with a filename
and a path, the page columns show tinted chips, and the status column needs a
pill.  :class:`BatchRowDelegate` paints all of that directly, reading its
colours from the design tokens so it follows the theme.

The delegate is purely presentational — every value it draws comes from the
model's existing roles, so sorting, selection and accessibility keep working.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from . import icons, theme
from .batch_model import BatchTableModel, RowState

ROW_HEIGHT = 58
_PAD_X = 12


class BatchRowDelegate(QStyledItemDelegate):
    """Draws one batch row: file identity, page metrics and status."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        return QSize(size.width(), ROW_HEIGHT)

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _row(index: QModelIndex):
        model = index.model()
        source = getattr(model, "row_at", None)
        return source(index.row()) if source else None

    @staticmethod
    def _elide(
        painter: QPainter,
        text: str,
        width: float,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
    ) -> str:
        """Shorten ``text`` to ``width``.

        Paths and filenames elide in the middle so the distinguishing tail
        stays visible; sentences elide at the end so they still read normally.
        """

        metrics = painter.fontMetrics()
        return metrics.elidedText(text, mode, int(width))

    def _paint_background(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        rect = QRectF(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.fillRect(rect, QColor(theme.color("blue_soft")))
        elif hovered:
            painter.fillRect(rect, QColor(theme.color("surface_alt")))
        else:
            painter.fillRect(rect, QColor(theme.color("surface")))

        painter.setPen(QPen(QColor(theme.color("line_soft")), 1))
        painter.drawLine(
            QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom())
        )

        # A selected row gets an accent rail on its leading edge.
        if selected and index.column() == BatchTableModel.COL_FILE:
            painter.fillRect(
                QRectF(rect.left(), rect.top(), 3.0, rect.height()),
                QColor(theme.color("blue_base")),
            )

    def _paint_chip(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        accent: str | None,
    ) -> None:
        """A small rounded count/list chip, centred in ``rect``."""

        font = QFont(painter.font())
        font.setPointSizeF(theme.FONT_SIZE_SM)
        font.setBold(True)
        painter.setFont(font)

        if not text or text in {"\u2014", "n/a"}:
            painter.setPen(QColor(theme.color("subtle")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text or "\u2014")
            return

        metrics = painter.fontMetrics()
        width = min(metrics.horizontalAdvance(text) + 16, rect.width() - 6)
        height = 21
        box = QRectF(
            rect.center().x() - width / 2.0,
            rect.center().y() - height / 2.0,
            width,
            height,
        )
        path = QPainterPath()
        path.addRoundedRect(box, 6, 6)

        if accent:
            shades = theme.family(accent)
            painter.fillPath(path, QColor(shades["soft"]))
            painter.setPen(QPen(QColor(shades["soft_line"]), 1))
            painter.drawPath(path)
            painter.setPen(QColor(shades["soft_fg"]))
        else:
            painter.fillPath(path, QColor(theme.color("sunken")))
            painter.setPen(QColor(theme.color("muted")))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- entry point ---------------------------------------------------
    def paint(  # noqa: C901 - one branch per column keeps the painting legible
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_background(painter, option, index)

        row = self._row(index)
        column = index.column()
        rect = option.rect
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        if column == BatchTableModel.COL_FILE:
            self._paint_file(painter, rect, row, text)
        elif column == BatchTableModel.COL_STATUS:
            self._paint_status(painter, rect, row)
        elif column == BatchTableModel.COL_PAGES:
            self._paint_chip(painter, rect, str(text), None)
        elif column == BatchTableModel.COL_SEP:
            self._paint_chip(painter, rect, str(text), "separator")
        elif column == BatchTableModel.COL_BLANK:
            self._paint_chip(painter, rect, str(text), "warning")
        elif column == BatchTableModel.COL_OUT:
            accent = "success" if str(text) not in {"0", "\u2014"} else None
            self._paint_chip(painter, rect, str(text), accent)
        else:  # pragma: no cover - defensive
            painter.setPen(QColor(theme.color("ink")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text))

        painter.restore()

    # -- columns -------------------------------------------------------
    def _paint_file(self, painter: QPainter, rect: QRect, row, text: str) -> None:
        glyph_size = 17
        x = rect.left() + _PAD_X + 4
        centre = rect.center().y()

        state = row.state if row else RowState.PENDING
        tint = theme.family(state.accent)["soft_fg"]
        painter.drawPixmap(
            x,
            int(centre - glyph_size / 2) - 4,
            icons.pixmap("file-text", tint, glyph_size),
        )

        text_x = x + glyph_size + 10
        available = rect.right() - text_x - _PAD_X

        font = QFont(painter.font())
        font.setPointSizeF(theme.FONT_SIZE)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.color("ink")))
        painter.drawText(
            QRect(text_x, rect.top() + 9, int(available), 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._elide(painter, str(text), available),
        )

        # Secondary line: the message for this row, or its folder.
        detail = ""
        is_message = False
        if row is not None:
            if row.message:
                detail, is_message = row.message, True
            else:
                detail = str(row.path.parent)
        if detail:
            small = QFont(painter.font())
            small.setPointSizeF(theme.FONT_SIZE_SM)
            small.setBold(False)
            painter.setFont(small)
            painter.setPen(QColor(theme.color("muted")))
            mode = (
                Qt.TextElideMode.ElideRight
                if is_message
                else Qt.TextElideMode.ElideMiddle
            )
            painter.drawText(
                QRect(text_x, rect.top() + 28, int(available), 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._elide(painter, detail, available, mode),
            )

    def _paint_status(self, painter: QPainter, rect: QRect, row) -> None:
        state = row.state if row else RowState.PENDING
        shades = theme.family(state.accent)

        font = QFont(painter.font())
        font.setPointSizeF(theme.FONT_SIZE_SM)
        font.setBold(True)
        painter.setFont(font)

        label = state.label
        metrics = painter.fontMetrics()
        glyph = 14
        width = min(metrics.horizontalAdvance(label) + glyph + 26, rect.width() - 12)
        height = 24
        box = QRectF(
            rect.left() + 10,
            rect.center().y() - height / 2.0,
            width,
            height,
        )

        path = QPainterPath()
        path.addRoundedRect(box, height / 2.0, height / 2.0)
        painter.fillPath(path, QColor(shades["soft"]))
        painter.setPen(QPen(QColor(shades["soft_line"]), 1))
        painter.drawPath(path)

        painter.drawPixmap(
            int(box.left() + 9),
            int(box.center().y() - glyph / 2),
            icons.pixmap(state.icon, shades["soft_fg"], glyph),
        )
        painter.setPen(QColor(shades["soft_fg"]))
        painter.drawText(
            QRectF(box.left() + glyph + 15, box.top(), box.width() - glyph - 20, box.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )


__all__ = ["ROW_HEIGHT", "BatchRowDelegate"]
