"""Visual language for the app.

The reference point is a two-channel oscilloscope rather than a dashboard
template: a near-black instrument face, hairline rules, and two signal colours
that stay distinct by both hue and brightness so the traces are still readable
without colour vision.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase


class Palette:
    """Named colours. Nothing in the UI hard-codes a hex value."""

    ink = "#0A0E14"          # window base
    panel = "#111823"        # raised surfaces
    panel_high = "#18212E"   # hover / selected rows
    rule = "#1E2836"         # hairlines and borders
    text = "#DCE4EF"
    muted = "#77879C"
    faint = "#4A5A6E"

    download = "#34D1E0"     # channel 1 — inbound
    upload = "#FFAF45"       # channel 2 — outbound
    ok = "#5FD97A"
    warn = "#FFC94A"
    alert = "#FF5A5F"
    accent = "#6E8BFF"

    @staticmethod
    def rgba(hex_colour: str, alpha: float) -> QColor:
        colour = QColor(hex_colour)
        colour.setAlphaF(alpha)
        return colour


# Type scale, in points. Ratio is roughly 1.25 between adjacent steps.
class Type:
    readout = 30
    title = 19
    heading = 14
    body = 11
    label = 10
    small = 9


_UI_STACK = ["Inter", "Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Ubuntu", "Noto Sans"]
_MONO_STACK = ["JetBrains Mono", "Cascadia Mono", "SF Mono", "Consolas", "DejaVu Sans Mono", "Menlo"]


def _first_available(candidates: list[str], fallback: str) -> str:
    installed = set(QFontDatabase.families())
    for name in candidates:
        if name in installed:
            return name
    return fallback


def ui_font(size: int = Type.body, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(_first_available(_UI_STACK, "Sans Serif"), size)
    font.setWeight(weight)
    return font


def mono_font(size: int = Type.body, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Monospace with tabular figures.

    Live readouts change several times a second. Proportional digits make the
    numbers shuffle sideways as they change; fixed-width digits hold still.
    """
    font = QFont(_first_available(_MONO_STACK, "Monospace"), size)
    font.setWeight(weight)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def stylesheet() -> str:
    """Application-wide Qt Style Sheet."""
    p = Palette
    return f"""
    QWidget {{
        background-color: {p.ink};
        color: {p.text};
    }}

    /* ---------------------------------------------------- navigation rail */
    #NavRail {{
        background-color: {p.panel};
        border-right: 1px solid {p.rule};
    }}
    #NavRail QPushButton {{
        background: transparent;
        border: none;
        border-left: 2px solid transparent;
        padding: 11px 16px;
        text-align: left;
        color: {p.muted};
        font-size: {Type.body}pt;
    }}
    #NavRail QPushButton:hover {{
        background-color: {p.panel_high};
        color: {p.text};
    }}
    #NavRail QPushButton:checked {{
        background-color: {p.panel_high};
        border-left: 2px solid {p.download};
        color: {p.text};
    }}
    #Wordmark {{
        color: {p.text};
        font-size: {Type.title}pt;
        padding: 18px 16px 2px 16px;
        background: transparent;
    }}
    #WordmarkSub {{
        color: {p.faint};
        font-size: {Type.small}pt;
        padding: 0 16px 16px 16px;
        background: transparent;
    }}

    /* --------------------------------------------------------- surfaces */
    #Panel {{
        background-color: {p.panel};
        border: 1px solid {p.rule};
        border-radius: 6px;
    }}
    #Divider {{
        background-color: {p.rule};
        max-height: 1px;
        border: none;
    }}
    QLabel#SectionTitle {{
        color: {p.text};
        font-size: {Type.heading}pt;
        background: transparent;
    }}
    QLabel#SectionNote {{
        color: {p.muted};
        font-size: {Type.label}pt;
        background: transparent;
    }}
    QLabel {{ background: transparent; }}

    /* ----------------------------------------------------------- inputs */
    QLineEdit, QComboBox, QSpinBox {{
        background-color: {p.ink};
        border: 1px solid {p.rule};
        border-radius: 4px;
        padding: 6px 9px;
        color: {p.text};
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {p.download};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        color: {p.faint};
        border-color: {p.rule};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background-color: {p.panel};
        border: 1px solid {p.rule};
        selection-background-color: {p.panel_high};
        outline: none;
        padding: 4px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}

    /* ---------------------------------------------------------- buttons */
    QPushButton {{
        background-color: {p.panel_high};
        border: 1px solid {p.rule};
        border-radius: 4px;
        padding: 6px 15px;
        color: {p.text};
    }}
    QPushButton:hover {{ border-color: {p.faint}; }}
    QPushButton:pressed {{ background-color: {p.panel}; }}
    QPushButton:disabled {{ color: {p.faint}; background-color: {p.panel}; }}
    QPushButton#Primary {{
        background-color: {p.download};
        border: none;
        color: {p.ink};
    }}
    QPushButton#Primary:hover {{ background-color: #52DCEA; }}
    QPushButton#Primary:disabled {{ background-color: {p.rule}; color: {p.faint}; }}
    QPushButton#Danger {{
        background-color: transparent;
        border: 1px solid {p.alert};
        color: {p.alert};
    }}
    QPushButton#Danger:hover {{ background-color: rgba(255, 90, 95, 0.12); }}

    /* ----------------------------------------------------------- tables */
    QTableView, QTableWidget {{
        background-color: {p.panel};
        alternate-background-color: {p.panel};
        gridline-color: transparent;
        border: 1px solid {p.rule};
        border-radius: 6px;
        selection-background-color: {p.panel_high};
        selection-color: {p.text};
        outline: none;
    }}
    QTableView::item, QTableWidget::item {{
        padding: 5px 8px;
        border-bottom: 1px solid {p.rule};
    }}
    QHeaderView::section {{
        background-color: {p.panel};
        color: {p.muted};
        border: none;
        border-bottom: 1px solid {p.rule};
        padding: 7px 8px;
        font-size: {Type.label}pt;
    }}
    QTableCornerButton::section {{ background-color: {p.panel}; border: none; }}

    /* ------------------------------------------------------------- misc */
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{
        background: transparent;
        color: {p.muted};
        padding: 7px 14px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.download}; }}
    QTabBar::tab:hover {{ color: {p.text}; }}

    QPlainTextEdit, QTextEdit {{
        background-color: {p.panel};
        border: 1px solid {p.rule};
        border-radius: 6px;
        padding: 8px;
        color: {p.text};
        selection-background-color: {p.accent};
    }}

    QProgressBar {{
        background-color: {p.panel};
        border: 1px solid {p.rule};
        border-radius: 3px;
        height: 5px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{ background-color: {p.download}; border-radius: 2px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {p.rule}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{
        background: {p.rule}; border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QToolTip {{
        background-color: {p.panel_high};
        color: {p.text};
        border: 1px solid {p.rule};
        padding: 5px 8px;
    }}

    QStatusBar {{
        background-color: {p.panel};
        border-top: 1px solid {p.rule};
        color: {p.muted};
    }}
    QStatusBar::item {{ border: none; }}
    """
