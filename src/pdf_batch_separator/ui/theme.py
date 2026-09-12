"""Centralized visual system for the PySide6 desktop client.

The original UI relied heavily on platform defaults. Keeping the visual tokens
here gives the whole application one predictable, compact, flat treatment and
makes the light/dark choice a single operation.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


LIGHT = {
    "bg": "#F4F7F8", "surface": "#FFFFFF", "surface_alt": "#F8FAFC",
    "text": "#263238", "muted": "#5F6B73", "line": "#D7E0E4",
    "accent": "#58CC02", "accent_dark": "#3F9300", "accent_soft": "#EAF8DF",
    "blue_soft": "#EAF5FE", "warning_soft": "#FFF5DA", "danger_soft": "#FDEBEC",
}
DARK = {
    "bg": "#151A1D", "surface": "#20282D", "surface_alt": "#293238",
    "text": "#ECF2F3", "muted": "#AAB8BD", "line": "#3B484F",
    "accent": "#72D52A", "accent_dark": "#9BE96A", "accent_soft": "#263B25",
    "blue_soft": "#193441", "warning_soft": "#44371A", "danger_soft": "#45252A",
}


def _stylesheet(colors: dict[str, str]) -> str:
    c = colors
    return f"""
QWidget {{ color: {c['text']}; font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 9.5pt; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QGroupBox {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 6px; margin-top: 10px; padding: 14px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; color: {c['text']}; font-weight: 700; }}
QPushButton {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 5px; padding: 5px 10px; min-height: 18px; }}
QPushButton:hover {{ background: {c['surface_alt']}; border-color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['accent_soft']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface_alt']}; border-color: {c['line']}; }}
QPushButton[role="primary"] {{ color: #FFFFFF; background: {c['accent_dark']}; border-color: {c['accent_dark']}; font-weight: 700; padding-left: 16px; padding-right: 16px; }}
QPushButton[role="primary"]:hover {{ background: {c['accent']}; border-color: {c['accent']}; }}
QLineEdit, QComboBox {{ background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 5px; padding: 5px 7px; min-height: 18px; }}
QLineEdit:focus, QComboBox:focus, QTableView:focus, QPushButton:focus-visible {{ border: 2px solid {c['accent']}; }}
QCheckBox, QRadioButton {{ spacing: 6px; }}
QTableView {{ background: {c['surface']}; alternate-background-color: {c['surface_alt']}; border: 1px solid {c['line']}; border-radius: 6px; gridline-color: {c['line']}; selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; padding: 1px; }}
QHeaderView::section {{ background: {c['surface_alt']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['line']}; padding: 6px 7px; font-weight: 700; }}
QProgressBar {{ background: {c['surface_alt']}; border: none; border-radius: 4px; text-align: center; color: {c['text']}; min-height: 7px; max-height: 7px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: {c['surface_alt']}; color: {c['muted']}; border-top: 1px solid {c['line']}; }}
QToolTip {{ background: {c['text']}; color: {c['surface']}; border: none; padding: 5px; }}
"""


def apply_theme(app: QApplication, dark: bool = False) -> None:
    """Apply the selected theme without changing application behaviour."""
    colors = DARK if dark else LIGHT
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["surface_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent_soft"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["text"]))
    app.setPalette(palette)
    app.setStyleSheet(_stylesheet(colors))
    app.setProperty("juadex-dark", dark)
