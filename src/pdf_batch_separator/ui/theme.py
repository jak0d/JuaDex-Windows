"""Visual theme for the desktop client.

The application deliberately uses native Qt widgets, but a restrained visual
system makes the workflow easier to scan than the platform default palette.
This is kept in one module so the UI can be refreshed without touching the
processing code.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


ACCENT = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
TEXT = "#172033"
MUTED = "#64748B"
SURFACE = "#FFFFFF"
CANVAS = "#F4F7FB"
BORDER = "#D9E1EC"


STYLESHEET = f"""
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI", "Noto Sans", sans-serif;
    font-size: 9.5pt;
}}
QMainWindow, QDialog {{ background: {CANVAS}; }}
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 12px;
    padding: 18px 12px 12px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT};
    font-weight: 700;
}}
QPushButton {{
    background: {SURFACE};
    border: 1px solid #C8D2E1;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 18px;
}}
QPushButton:hover {{ background: #EEF4FF; border-color: #93B4F8; }}
QPushButton:pressed {{ background: #DCE9FF; }}
QPushButton:disabled {{ color: #A2ADBC; background: #F1F4F8; border-color: #E2E7EE; }}
QPushButton[role="primary"] {{
    color: white;
    background: {ACCENT};
    border-color: {ACCENT};
    font-weight: 700;
    padding-left: 18px;
    padding-right: 18px;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QLineEdit, QComboBox {{
    background: {SURFACE};
    border: 1px solid #C8D2E1;
    border-radius: 6px;
    padding: 6px 8px;
    min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus, QTableView:focus {{ border: 1px solid {ACCENT}; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QTableView {{
    background: {SURFACE};
    alternate-background-color: #F8FAFD;
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: #E8EDF4;
    selection-background-color: #DCE9FF;
    selection-color: {TEXT};
    padding: 2px;
}}
QHeaderView::section {{
    background: #EEF2F7;
    color: #475569;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-weight: 700;
}}
QProgressBar {{
    background: #E7EDF5;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: {TEXT};
    min-height: 8px;
    max-height: 8px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: #EAF0F8; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QToolTip {{ background: #172033; color: white; border: none; padding: 5px; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the light, high-contrast visual system to *app*."""

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(CANVAS))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F8FAFD"))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#DCE9FF"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
