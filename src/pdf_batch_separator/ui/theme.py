"""The JuaDex design system: tokens, palettes and the global stylesheet.

Every colour, radius, space and font used by the desktop client is declared
here once.  Widgets never hard-code a hex value; they either read a token from
:func:`colors` or rely on the stylesheet built by :func:`stylesheet`.  That
keeps the light and dark themes in lock-step and makes a restyle a one-file
operation.

The vocabulary intentionally mirrors the product design:

``canvas`` / ``surface`` / ``sunken``
    The three background planes: the window, the cards sitting on it and the
    inset detail blocks inside those cards.

``ink`` / ``muted`` / ``subtle``
    The text ramp, from primary copy down to secondary metadata.

accent families (``green``, ``blue``, ``red``, ``amber``, ``purple``)
    Each exposes ``base``/``hover``/``press`` for solid fills plus
    ``soft``/``soft_fg``/``soft_line`` for the tinted badges and card headers.
    Semantic aliases (``success``, ``info``, ``danger``, ``warning``) map the
    families onto meanings so call sites read intently.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
# Font *stacks*: the first family present on the machine wins.  Windows 10/11
# resolve to Segoe UI and Cascadia/Consolas; the Linux CI boxes fall back to
# the DejaVu pair.  Nothing is bundled, so there is no font licence to ship.
SANS = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif'
DISPLAY = '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Inter", sans-serif'
MONO = '"Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", monospace'

FONT_SIZE = 9.5      # pt — body copy
FONT_SIZE_SM = 8.5   # pt — metadata, badges
FONT_SIZE_XS = 8.0   # pt — key hints, eyebrow labels

# ---------------------------------------------------------------------------
# Spacing and shape
# ---------------------------------------------------------------------------
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32}
RADIUS = {"sm": 5, "md": 8, "lg": 11, "xl": 14, "pill": 999}

ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def _url(name: str) -> str:
    """Absolute, quoted, forward-slashed path for use in a Qt stylesheet.

    The quotes matter for the packaged build: PyInstaller unpacks to a temp
    directory that frequently contains spaces (``C:/Users/Jane Doe/...``), and
    an unquoted ``url()`` would stop parsing at the first space and silently
    drop the checkbox and combo-box glyphs.
    """

    return f'"{(ICON_DIR / name).as_posix()}"'


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
LIGHT: dict[str, str] = {
    # planes
    "canvas": "#F5F7F9",
    "surface": "#FFFFFF",
    "surface_alt": "#F9FAFB",
    "sunken": "#F3F5F8",
    "overlay": "#FFFFFF",
    # lines
    "line": "#E4E7EC",
    "line_soft": "#EFF1F4",
    "line_strong": "#D0D5DD",
    # text
    "ink": "#0F172A",
    "muted": "#667085",
    "subtle": "#98A2B3",
    "on_accent": "#FFFFFF",
    # neutral/"selected" pill — the dark chip in the filter row
    "neutral_base": "#101828",
    "neutral_hover": "#1D2939",
    "neutral_press": "#000000",
    "neutral_fg": "#FFFFFF",
    "neutral_soft": "#F2F4F7",
    "neutral_soft_fg": "#475467",
    "neutral_soft_line": "#E0E4EA",
    # accent families
    "green_base": "#16A34A", "green_hover": "#1BB757", "green_press": "#12833C",
    "green_soft": "#E7F8EE", "green_soft_fg": "#10803C", "green_soft_line": "#BCEBCE",
    "blue_base": "#1570EF", "blue_hover": "#2E86FF", "blue_press": "#1259C3",
    "blue_soft": "#EFF6FF", "blue_soft_fg": "#1257C9", "blue_soft_line": "#BBD9FB",
    "red_base": "#DC2626", "red_hover": "#EF4444", "red_press": "#B91C1C",
    "red_soft": "#FEF2F2", "red_soft_fg": "#B42318", "red_soft_line": "#FBCFCB",
    "amber_base": "#DB7712", "amber_hover": "#F08C1E", "amber_press": "#B45309",
    "amber_soft": "#FFF8EB", "amber_soft_fg": "#B45309", "amber_soft_line": "#FAE0B0",
    "purple_base": "#7E3AF2", "purple_hover": "#9061F9", "purple_press": "#6C2BD9",
    "purple_soft": "#F5F3FF", "purple_soft_fg": "#6423D7", "purple_soft_line": "#DDD3FD",
    # misc
    "shadow": "rgba(16, 24, 40, 0.06)",
    "scroll": "#CDD5DF",
    "scroll_hover": "#B3BECC",
    "focus": "#1570EF",
    "thumb_bg": "#FFFFFF",
}

DARK: dict[str, str] = {
    "canvas": "#0B0F14",
    "surface": "#131A22",
    "surface_alt": "#18212B",
    "sunken": "#0F161E",
    "overlay": "#18212B",
    "line": "#24303C",
    "line_soft": "#1C2732",
    "line_strong": "#33414F",
    "ink": "#E8EDF2",
    "muted": "#97A6B5",
    "subtle": "#6D7E8F",
    "on_accent": "#FFFFFF",
    "neutral_base": "#E8EDF2",
    "neutral_hover": "#FFFFFF",
    "neutral_press": "#C9D4DF",
    "neutral_fg": "#0B0F14",
    "neutral_soft": "#1B242F",
    "neutral_soft_fg": "#A3B2C1",
    "neutral_soft_line": "#2B3846",
    "green_base": "#2EBE63", "green_hover": "#3FD277", "green_press": "#249B50",
    "green_soft": "#11281B", "green_soft_fg": "#5CDD90", "green_soft_line": "#1F4A32",
    "blue_base": "#3B8DF5", "blue_hover": "#5AA1FF", "blue_press": "#2A76D8",
    "blue_soft": "#0E2033", "blue_soft_fg": "#78B4FB", "blue_soft_line": "#1D4066",
    "red_base": "#EF5350", "red_hover": "#FF6B68", "red_press": "#D13F3C",
    "red_soft": "#2B1517", "red_soft_fg": "#FF8D87", "red_soft_line": "#5A2522",
    "amber_base": "#E8912B", "amber_hover": "#F7A544", "amber_press": "#C6781C",
    "amber_soft": "#2B1F0D", "amber_soft_fg": "#F5B451", "amber_soft_line": "#573C16",
    "purple_base": "#8B5CF6", "purple_hover": "#A47EF9", "purple_press": "#7745E0",
    "purple_soft": "#1D1636", "purple_soft_fg": "#B89CFA", "purple_soft_line": "#3C2C6B",
    "shadow": "rgba(0, 0, 0, 0.45)",
    "scroll": "#2E3B49",
    "scroll_hover": "#3D4D5E",
    "focus": "#3B8DF5",
    "thumb_bg": "#0F161E",
}

# Semantic aliases resolved on top of whichever palette is active.
_SEMANTIC = {
    "success": "green",
    "info": "blue",
    "danger": "red",
    "warning": "amber",
    "separator": "purple",
}

_active: dict[str, str] = dict(LIGHT)
_is_dark = False


def colors() -> dict[str, str]:
    """The palette currently applied to the application."""

    return _active


def is_dark() -> bool:
    """True when the dark palette is active."""

    return _is_dark


def color(token: str) -> str:
    """Look up a single token, resolving semantic aliases.

    ``color("danger_soft")`` and ``color("red_soft")`` return the same value,
    so widgets can speak in meanings rather than hues.
    """

    if token in _active:
        return _active[token]
    head, _, tail = token.partition("_")
    family = _SEMANTIC.get(head)
    if family:
        return _active[f"{family}_{tail}" if tail else f"{family}_base"]
    raise KeyError(f"Unknown design token: {token!r}")


def qcolor(token: str) -> QColor:
    """:func:`color` as a :class:`QColor`, for custom painting."""

    return QColor(color(token))


def family(name: str) -> dict[str, str]:
    """Every shade of one accent family, keyed ``base``/``soft``/``soft_fg``…

    Handy for widgets that are told *which* accent to wear at construction
    time, such as status pills and triage cards.
    """

    name = _SEMANTIC.get(name, name)
    prefix = f"{name}_"
    shades = {k[len(prefix):]: v for k, v in _active.items() if k.startswith(prefix)}
    if not shades:
        raise KeyError(f"Unknown accent family: {name!r}")
    return shades


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
def stylesheet(c: dict[str, str], dark: bool) -> str:
    """Build the global stylesheet for one palette."""

    check = _url("check-on.svg")
    dot = _url("radio-on.svg")
    chevron = _url("chevron-down-dark.svg" if dark else "chevron-down.svg")

    return f"""
/* ---------- base ---------- */
QWidget {{
    color: {c['ink']};
    font-family: {SANS};
    font-size: {FONT_SIZE}pt;
}}
QMainWindow, QDialog {{ background: {c['canvas']}; }}
QWidget#appBar, QWidget#actionBar {{ background: {c['surface']}; }}
QWidget#pageHeader {{ background: {c['canvas']}; }}

/* ---------- typography roles ---------- */
QLabel[variant="display"] {{
    font-family: {DISPLAY};
    font-size: 17pt;
    font-weight: 700;
    color: {c['ink']};
}}
QLabel[variant="title"] {{
    font-family: {DISPLAY};
    font-size: 11.5pt;
    font-weight: 700;
}}
QLabel[variant="wordmark"] {{
    font-family: {DISPLAY};
    font-size: 13pt;
    font-weight: 800;
    color: {c['ink']};
}}
QLabel[variant="section"] {{
    font-family: {MONO};
    font-size: {FONT_SIZE_XS}pt;
    font-weight: 700;
    color: {c['muted']};
    letter-spacing: 1.2px;
}}
QLabel[variant="body"] {{ color: {c['ink']}; }}
QLabel[variant="muted"] {{ color: {c['muted']}; }}
QLabel[variant="subtle"] {{ color: {c['subtle']}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[variant="mono"] {{ font-family: {MONO}; font-size: {FONT_SIZE_SM}pt; color: {c['muted']}; }}
QLabel[variant="filename"] {{
    font-family: {DISPLAY};
    font-size: 10.5pt;
    font-weight: 700;
    color: {c['ink']};
}}
QLabel[variant="error"] {{ color: {c['red_soft_fg']}; font-size: {FONT_SIZE_SM}pt; }}
QLabel:disabled {{ color: {c['subtle']}; }}

/* ---------- surfaces ---------- */
QFrame[surface="card"] {{
    background: {c['surface']};
    border: 1px solid {c['line']};
    border-radius: {RADIUS['lg']}px;
}}
QFrame[surface="sunken"] {{
    background: {c['sunken']};
    border: 1px solid {c['line_soft']};
    border-radius: {RADIUS['md']}px;
}}
QFrame[surface="plain"] {{ background: transparent; border: none; }}
QFrame[role="divider"] {{ background: {c['line']}; border: none; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {c['surface']};
    color: {c['ink']};
    border: 1px solid {c['line_strong']};
    border-radius: {RADIUS['md']}px;
    padding: 7px 14px;
    font-weight: 600;
    min-height: 18px;
}}
QPushButton:hover {{ background: {c['surface_alt']}; border-color: {c['muted']}; }}
QPushButton:pressed {{ background: {c['sunken']}; }}
QPushButton:disabled {{
    color: {c['subtle']};
    background: {c['surface_alt']};
    border-color: {c['line']};
}}
QPushButton:focus {{ border-color: {c['focus']}; }}

QPushButton[kind="primary"] {{
    background: {c['green_base']};
    color: {c['on_accent']};
    border-color: {c['green_base']};
    padding: 8px 18px;
}}
QPushButton[kind="primary"]:hover {{ background: {c['green_hover']}; border-color: {c['green_hover']}; }}
QPushButton[kind="primary"]:pressed {{ background: {c['green_press']}; border-color: {c['green_press']}; }}
QPushButton[kind="primary"]:disabled {{
    background: {c['surface_alt']}; color: {c['subtle']}; border-color: {c['line']};
}}

QPushButton[kind="danger"] {{
    background: {c['red_base']}; color: {c['on_accent']}; border-color: {c['red_base']};
}}
QPushButton[kind="danger"]:hover {{ background: {c['red_hover']}; border-color: {c['red_hover']}; }}
QPushButton[kind="danger"]:pressed {{ background: {c['red_press']}; border-color: {c['red_press']}; }}

QPushButton[kind="info"] {{
    background: {c['blue_base']}; color: {c['on_accent']}; border-color: {c['blue_base']};
}}
QPushButton[kind="info"]:hover {{ background: {c['blue_hover']}; border-color: {c['blue_hover']}; }}
QPushButton[kind="info"]:pressed {{ background: {c['blue_press']}; border-color: {c['blue_press']}; }}

QPushButton[kind="warning"] {{
    background: {c['amber_base']}; color: {c['on_accent']}; border-color: {c['amber_base']};
}}
QPushButton[kind="warning"]:hover {{ background: {c['amber_hover']}; border-color: {c['amber_hover']}; }}

/* tinted outline buttons — used by the bulk actions in the footer */
QPushButton[kind="danger-outline"] {{
    background: {c['red_soft']}; color: {c['red_soft_fg']}; border-color: {c['red_soft_line']};
}}
QPushButton[kind="danger-outline"]:hover {{ background: {c['surface']}; border-color: {c['red_base']}; }}
QPushButton[kind="info-outline"] {{
    background: {c['blue_soft']}; color: {c['blue_soft_fg']}; border-color: {c['blue_soft_line']};
}}
QPushButton[kind="info-outline"]:hover {{ background: {c['surface']}; border-color: {c['blue_base']}; }}
QPushButton[kind="info-outline"]:disabled, QPushButton[kind="danger-outline"]:disabled {{
    background: {c['surface_alt']}; color: {c['subtle']}; border-color: {c['line']};
}}

QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; color: {c['muted']}; }}
QPushButton[kind="ghost"]:hover {{ background: {c['surface_alt']}; color: {c['ink']}; }}
QPushButton[kind="ghost"]:checked {{ background: {c['sunken']}; color: {c['ink']}; }}

QPushButton[kind="icon"] {{
    background: {c['surface']}; border: 1px solid {c['line']};
    border-radius: {RADIUS['md']}px; padding: 6px; min-width: 16px;
}}
QPushButton[kind="icon"]:hover {{ background: {c['surface_alt']}; border-color: {c['line_strong']}; }}
QPushButton[kind="icon"]:checked {{
    background: {c['blue_soft']}; border-color: {c['blue_soft_line']};
}}

QPushButton[kind="link"] {{
    background: transparent; border: none; color: {c['muted']};
    font-family: {MONO}; font-size: {FONT_SIZE_SM}pt; padding: 2px 4px;
    text-decoration: underline;
}}
QPushButton[kind="link"]:hover {{ color: {c['ink']}; }}

/* segmented filter chips */
QPushButton[kind="segment"] {{
    background: {c['surface']}; border: 1px solid {c['line']};
    border-radius: {RADIUS['pill']}px; padding: 6px 14px; font-weight: 600;
    color: {c['muted']};
}}
QPushButton[kind="segment"]:hover {{ border-color: {c['line_strong']}; color: {c['ink']}; }}
QPushButton[kind="segment"]:checked {{
    background: {c['neutral_base']}; border-color: {c['neutral_base']}; color: {c['neutral_fg']};
}}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {c['surface']};
    border: 1px solid {c['line_strong']};
    border-radius: {RADIUS['md']}px;
    padding: 7px 10px;
    selection-background-color: {c['blue_soft']};
    selection-color: {c['ink']};
    min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['focus']}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {c['surface_alt']}; color: {c['subtle']}; }}
QLineEdit[variant="path"] {{ font-family: {MONO}; font-size: {FONT_SIZE_SM}pt; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {c['overlay']};
    border: 1px solid {c['line']};
    border-radius: {RADIUS['md']}px;
    padding: 4px;
    selection-background-color: {c['blue_soft']};
    selection-color: {c['ink']};
    outline: none;
}}

/* ---------- choice controls ---------- */
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1.5px solid {c['line_strong']};
    background: {c['surface']};
}}
QCheckBox::indicator {{ border-radius: {RADIUS['sm']}px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c['green_base']}; }}
QCheckBox::indicator:checked {{
    background: {c['green_base']}; border-color: {c['green_base']}; image: url({check});
}}
QRadioButton::indicator:checked {{
    background: {c['green_base']}; border-color: {c['green_base']}; image: url({dot});
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {c['surface_alt']}; border-color: {c['line']};
}}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['subtle']}; }}

/* ---------- table ---------- */
QTableView {{
    background: {c['surface']};
    alternate-background-color: {c['surface']};
    border: 1px solid {c['line']};
    border-radius: {RADIUS['lg']}px;
    gridline-color: transparent;
    selection-background-color: {c['blue_soft']};
    selection-color: {c['ink']};
    outline: none;
    padding: 2px;
}}
QTableView::item {{ border-bottom: 1px solid {c['line_soft']}; padding: 4px 6px; }}
QTableView::item:selected {{ background: {c['blue_soft']}; color: {c['ink']}; }}
QTableView:focus {{ border-color: {c['focus']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {c['surface_alt']};
    color: {c['muted']};
    border: none;
    border-bottom: 1px solid {c['line']};
    padding: 9px 8px;
    font-family: {MONO};
    font-size: {FONT_SIZE_XS}pt;
    font-weight: 700;
}}
QHeaderView::section:first {{ border-top-left-radius: {RADIUS['md']}px; }}
QHeaderView::section:last {{ border-top-right-radius: {RADIUS['md']}px; }}
QTableCornerButton::section {{ background: {c['surface_alt']}; border: none; }}

/* ---------- scrollbars ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {c['scroll']}; border-radius: 5px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['scroll_hover']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {c['scroll']}; border-radius: 5px; min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- feedback ---------- */
QProgressBar {{
    background: {c['sunken']};
    border: none;
    border-radius: 4px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {c['green_base']}; border-radius: 4px; }}
QStatusBar {{
    background: {c['surface']};
    color: {c['muted']};
    border-top: 1px solid {c['line']};
    font-size: {FONT_SIZE_SM}pt;
}}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {c['neutral_base']};
    color: {c['neutral_fg']};
    border: none;
    border-radius: {RADIUS['sm']}px;
    padding: 6px 9px;
}}

/* ---------- containers ---------- */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: {SPACE['lg']}px; }}
QMenu {{
    background: {c['overlay']}; border: 1px solid {c['line']};
    border-radius: {RADIUS['md']}px; padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: {RADIUS['sm']}px; }}
QMenu::item:selected {{ background: {c['blue_soft']}; }}
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ color: {c['ink']}; }}
"""


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def _palette(c: dict[str, str]) -> QPalette:
    """Keep native-drawn chrome (dialogs, headers) in step with the theme."""

    p = QPalette()
    role = QPalette.ColorRole
    p.setColor(role.Window, QColor(c["canvas"]))
    p.setColor(role.WindowText, QColor(c["ink"]))
    p.setColor(role.Base, QColor(c["surface"]))
    p.setColor(role.AlternateBase, QColor(c["surface_alt"]))
    p.setColor(role.Text, QColor(c["ink"]))
    p.setColor(role.PlaceholderText, QColor(c["subtle"]))
    p.setColor(role.Button, QColor(c["surface"]))
    p.setColor(role.ButtonText, QColor(c["ink"]))
    p.setColor(role.Highlight, QColor(c["blue_soft"]))
    p.setColor(role.HighlightedText, QColor(c["ink"]))
    p.setColor(role.ToolTipBase, QColor(c["neutral_base"]))
    p.setColor(role.ToolTipText, QColor(c["neutral_fg"]))
    p.setColor(role.Link, QColor(c["blue_base"]))
    disabled = QPalette.ColorGroup.Disabled
    p.setColor(disabled, role.Text, QColor(c["subtle"]))
    p.setColor(disabled, role.ButtonText, QColor(c["subtle"]))
    p.setColor(disabled, role.WindowText, QColor(c["subtle"]))
    return p


def apply_theme(app: QApplication, dark: bool = False) -> None:
    """Apply a palette to the whole application without touching behaviour."""

    global _active, _is_dark
    _active = dict(DARK if dark else LIGHT)
    _is_dark = dark

    app.setPalette(_palette(_active))
    app.setStyleSheet(stylesheet(_active, dark))
    app.setProperty("juadex-dark", dark)


__all__ = [
    "DARK",
    "DISPLAY",
    "FONT_SIZE",
    "FONT_SIZE_SM",
    "FONT_SIZE_XS",
    "LIGHT",
    "MONO",
    "RADIUS",
    "SANS",
    "SPACE",
    "apply_theme",
    "color",
    "colors",
    "family",
    "is_dark",
    "qcolor",
    "stylesheet",
]
