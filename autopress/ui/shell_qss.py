# OWNED BY G5
"""Private part of ui.theme: the QSS sections behind ``theme.build_qss`` (selectors listed in
SPEC 6.2 and the theme module docstring). ``c`` maps every token to a QSS colour string, plus the
derived ``<tone>_border`` colours; ``a`` holds the arrow image paths (may be empty)."""

from __future__ import annotations

from .theme import FS_BODY, FS_CAPTION, FS_DISPLAY, FS_MONO, FS_SMALL, FS_TITLE, R_LG, R_MD, R_SM, R_XL

__all__ = ["qss_base", "qss_buttons", "qss_inputs", "qss_misc", "qss_views"]


def qss_base(c: dict[str, str]) -> str:
    return f"""
QWidget {{ color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg_app']}; }}
QWidget#Root, QWidget#Main, QFrame#Root, QFrame#Main {{ background: {c['bg_app']}; }}
QLabel {{ background: transparent; }}
QLabel[role="display"] {{ font-size: {FS_DISPLAY}px; font-weight: bold; }}
QLabel[role="title"] {{ font-size: {FS_TITLE}px; font-weight: bold; }}
QLabel[role="body"] {{ font-size: {FS_BODY}px; }}
QLabel[role="brand"] {{ font-size: 16px; font-weight: bold; }}
QLabel[role="strong"] {{ font-weight: bold; }}
QLabel[role="secondary"] {{ color: {c['text_secondary']}; }}
QLabel[role="muted"] {{ color: {c['text_muted']}; font-size: {FS_SMALL}px; }}
QLabel[role="caption"] {{ color: {c['text_muted']}; font-size: {FS_CAPTION}px; font-weight: bold; }}
QLabel[role="status"] {{ color: {c['text_secondary']}; font-size: {FS_SMALL}px; }}
QLabel[role="mono"] {{ font-family: "Consolas", "Cascadia Mono", "Courier New"; font-size: {FS_MONO}px; }}
QLabel[role="error"] {{ color: {c['error_text']}; }}
QLabel[role="warning"] {{ color: {c['warning_text']}; }}
QLabel[role="success"] {{ color: {c['success_text']}; }}
QLabel[role="info"] {{ color: {c['info_text']}; }}
QLabel[role="link"] {{ color: {c['accent']}; }}
QLabel[role="keycap"] {{
    color: {c['text_secondary']}; font-size: {FS_CAPTION}px; font-weight: bold;
    background: {c['surface_raised']}; border: 1px solid {c['border_strong']}; border-bottom-width: 2px;
    border-radius: {R_SM}px; padding: 0px 5px;
}}
QFrame[role="divider"] {{ background: {c['border']}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[role="vdivider"], QFrame[role="vsep"] {{ background: {c['border_strong']}; border: none; min-width: 1px; max-width: 1px; }}
QFrame[frameRole="card"], QFrame#Card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R_LG}px; }}
QFrame[frameRole="panel"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R_MD}px; }}
QFrame[frameRole="inset"] {{ background: {c['surface_inset']}; border: 1px solid {c['border']}; border-radius: {R_MD}px; }}
QFrame[frameRole="sidebar"], QFrame#Sidebar {{ background: {c['bg_sidebar']}; border: none; border-right: 1px solid {c['border']}; }}
QFrame[frameRole="statusbar"], QFrame#StatusBar {{ background: {c['bg_sidebar']}; border: none; border-top: 1px solid {c['border']}; }}
QFrame#Banner {{ background: {c['warning_soft']}; border: 1px solid {c['warning_border']}; border-radius: 10px; }}
QFrame[frameRole="toast"], QFrame#Toast {{ background: {c['overlay']}; border: 1px solid {c['border_strong']}; border-radius: 10px; }}
QFrame[frameRole="minibar"], QFrame#MiniBar {{ background: {c['overlay']}; border: 1px solid {c['border_strong']}; border-radius: {R_XL}px; }}
QFrame[frameRole="dialog"] {{ background: {c['surface']}; border: none; }}
"""


def qss_buttons(c: dict[str, str]) -> str:
    return f"""
QPushButton, QToolButton[variant] {{
    background: {c['surface_raised']}; color: {c['text']};
    border: 1px solid {c['border_strong']}; border-radius: {R_MD}px;
    padding: 0px 12px; min-height: 30px;
}}
QPushButton:hover, QToolButton[variant]:hover {{ background: {c['surface_hover']}; }}
QPushButton:pressed, QToolButton[variant]:pressed {{ background: {c['border_strong']}; }}
QPushButton:focus, QToolButton[variant]:focus {{ border-color: {c['accent']}; }}
QPushButton:disabled, QToolButton[variant]:disabled {{ color: {c['text_disabled']}; border-color: {c['border']}; }}
QPushButton:checked, QToolButton[variant]:checked {{ background: {c['nav_active']}; border-color: {c['accent']}; }}
QPushButton[variant="primary"] {{
    background: {c['accent_fill']}; border: 1px solid {c['accent_fill']}; color: {c['on_accent']};
    font-weight: bold; padding: 0px 16px;
}}
QPushButton[variant="primary"]:hover {{ background: {c['accent_fill_hover']}; border-color: {c['accent_fill_hover']}; }}
QPushButton[variant="primary"]:pressed {{ background: {c['accent_fill_pressed']}; }}
QPushButton[variant="primary"]:focus {{ border-color: {c['text']}; }}
QPushButton[variant="primary"]:disabled {{ background: {c['surface_inset']}; border-color: {c['border_strong']}; color: {c['text_disabled']}; }}
QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{
    background: transparent; border-color: transparent; color: {c['text_secondary']}; padding: 0px 10px;
}}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton[variant="ghost"]:focus, QToolButton[variant="ghost"]:focus {{ border-color: {c['accent']}; }}
QPushButton[variant="ghost"]:disabled, QToolButton[variant="ghost"]:disabled {{ color: {c['text_disabled']}; border-color: transparent; }}
QPushButton[variant="danger"], QToolButton[variant="danger"] {{
    background: {c['error_soft']}; border-color: {c['error_border']}; color: {c['error_text']}; font-weight: bold;
}}
QPushButton[variant="danger"]:hover, QToolButton[variant="danger"]:hover {{ background: {c['error_border']}; }}
QPushButton[variant="danger"]:focus, QToolButton[variant="danger"]:focus {{ border-color: {c['error_text']}; }}
QPushButton[variant="danger"]:disabled, QToolButton[variant="danger"]:disabled {{ background: transparent; color: {c['text_disabled']}; border-color: {c['border']}; }}
QToolButton[variant="icon"] {{ background: transparent; border-color: transparent; padding: 0px; }}
QToolButton[variant][iconOnly="true"] {{ padding: 0px; }}
QToolButton[variant="icon"]:hover {{ background: {c['hover']}; }}
QToolButton[variant="icon"]:focus {{ border-color: {c['accent']}; }}
QFrame#MiniBar QToolButton[variant="icon"], QFrame[frameRole="minibar"] QToolButton[variant="icon"] {{
    background: {c['surface_raised']}; border: 1px solid {c['border_strong']};
}}
QFrame#MiniBar QToolButton[variant="icon"]:hover, QFrame[frameRole="minibar"] QToolButton[variant="icon"]:hover {{
    background: {c['surface_hover']};
}}
QPushButton[variant]::menu-indicator, QToolButton[variant]::menu-indicator {{ width: 0px; image: none; }}
QFrame[frameRole="segmented"], QFrame#Segmented {{
    background: {c['surface_inset']}; border: 1px solid {c['border']}; border-radius: 9px;
}}
QFrame[frameRole="segmented"] QPushButton, QFrame#Segmented QPushButton {{
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    min-height: 24px; padding: 0px 12px; color: {c['text_secondary']}; font-weight: normal;
}}
QFrame[frameRole="segmented"] QPushButton:hover, QFrame#Segmented QPushButton:hover {{ color: {c['text']}; }}
QFrame[frameRole="segmented"] QPushButton:checked, QFrame#Segmented QPushButton:checked {{
    background: {c['seg_active']}; border-color: {c['border_strong']}; color: {c['text']};
}}
QFrame[frameRole="segmented"] QPushButton:focus, QFrame#Segmented QPushButton:focus {{ border-color: {c['accent']}; }}
"""


def qss_inputs(c: dict[str, str], a: dict[str, str]) -> str:
    arrows = ""
    if a:
        arrows = f"""
QComboBox::down-arrow {{ image: url("{a['down']}"); width: 16px; height: 16px; }}
QComboBox::down-arrow:disabled {{ image: url("{a['down_disabled']}"); }}
QAbstractSpinBox::up-arrow {{ image: url("{a['up']}"); width: 12px; height: 12px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{a['up_disabled']}"); }}
QAbstractSpinBox::down-arrow {{ image: url("{a['down']}"); width: 12px; height: 12px; }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{a['down_disabled']}"); }}
"""
    return f"""
QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit {{
    background: {c['surface_raised']}; border: 1px solid {c['border_strong']}; border-radius: {R_MD}px;
    selection-background-color: {c['accent_fill']}; selection-color: {c['on_accent']};
}}
QLineEdit, QComboBox, QAbstractSpinBox {{ padding: 0px 10px; min-height: 30px; }}
QAbstractSpinBox {{ max-height: 30px; padding-left: 0px; padding-right: 26px; }}
QPlainTextEdit, QTextEdit {{ padding: 4px 6px; }}
QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover, QPlainTextEdit:hover, QTextEdit:hover {{ border-color: {c['text_muted']}; }}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    background: {c['surface_inset']}; border-color: {c['border']}; color: {c['text_disabled']};
}}
QLineEdit[readOnly="true"], QPlainTextEdit[readOnly="true"], QTextEdit[readOnly="true"] {{ background: {c['surface_inset']}; }}
QLineEdit[error="true"], QPlainTextEdit[error="true"] {{ border-color: {c['error']}; }}
QLineEdit QToolButton, QAbstractSpinBox QToolButton {{ background: transparent; border: none; padding: 0px; min-height: 0px; min-width: 0px; }}
QComboBox {{ padding-right: 30px; combobox-popup: 0; }}
QComboBox QLineEdit {{ background: transparent; border: none; padding: 0px; min-height: 0px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none; }}
QComboBox QAbstractItemView {{
    background: {c['overlay']}; border: 1px solid {c['border_strong']}; outline: 0px; padding: 4px;
    selection-background-color: {c['surface_hover']}; selection-color: {c['text']};
}}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0px 8px; border-radius: 6px; }}
QComboBox QAbstractItemView::item:selected, QComboBox QAbstractItemView::item:hover {{ background: {c['surface_hover']}; color: {c['text']}; }}
QAbstractSpinBox::up-button {{
    subcontrol-origin: border; subcontrol-position: top right; width: 22px; border: none;
    margin: 3px 3px 0px 0px; border-radius: {R_SM}px;
}}
QAbstractSpinBox::down-button {{
    subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border: none;
    margin: 0px 3px 3px 0px; border-radius: {R_SM}px;
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c['surface_hover']}; }}
{arrows}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c['text_disabled']}; }}
"""


def qss_views(c: dict[str, str]) -> str:
    return f"""
QAbstractItemView {{
    background: {c['surface']}; border: none; outline: 0px;
    selection-background-color: {c['row_selected']}; selection-color: {c['text']};
    alternate-background-color: {c['surface_hover']};
}}
QAbstractItemView[frameRole="inset"] {{ background: {c['surface_inset']}; border: 1px solid {c['border']}; border-radius: {R_MD}px; }}
QAbstractItemView[frameRole="panel"] {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R_MD}px; }}
QTableView {{ gridline-color: transparent; }}
QTableView::item {{ border: none; border-bottom: 1px solid {c['border']}; padding: 0px 8px; }}
QTableView::item:selected {{ background: {c['row_selected']}; color: {c['text']}; }}
QTableView::item:hover {{ background: {c['hover']}; }}
QListView::item, QTreeView::item {{ min-height: 28px; padding: 0px 6px; border: none; }}
QListView::item:selected, QTreeView::item:selected {{ background: {c['row_selected']}; color: {c['text']}; }}
QListView::item:hover, QTreeView::item:hover {{ background: {c['hover']}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: transparent; color: {c['text_muted']}; border: none; border-bottom: 1px solid {c['border_strong']};
    padding: 0px 12px; min-height: 34px; font-size: {FS_SMALL}px; font-weight: bold;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 1px; }}
QScrollBar::handle:vertical {{ background: {c['scrollbar']}; border-radius: 3px; min-height: 28px; margin: 0px 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['scrollbar_hover']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 1px 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scrollbar']}; border-radius: 3px; min-width: 28px; margin: 2px 0px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['scrollbar_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def qss_misc(c: dict[str, str]) -> str:
    return f"""
QMenu {{ background: {c['overlay']}; border: 1px solid {c['border_strong']}; padding: 6px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; background: transparent; }}
QMenu::item:selected {{ background: {c['surface_hover']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['text_disabled']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 8px; }}
QMenu::icon {{ padding-left: 8px; }}
QToolTip {{ background: {c['overlay']}; color: {c['text']}; border: 1px solid {c['border_strong']}; padding: 4px 8px; }}
QTabWidget::pane {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {R_LG}px; top: -1px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {c['text_secondary']}; border: none; border-bottom: 2px solid transparent;
    padding: 6px 14px; margin-right: 4px; min-height: 22px;
}}
QTabBar::tab:hover {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom-color: {c['accent']}; font-weight: bold; }}
QTabBar::tab:focus {{ color: {c['accent_text']}; }}
QTabBar::tab:disabled {{ color: {c['text_disabled']}; }}
QProgressBar {{
    background: {c['border_strong']}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px;
    color: transparent; text-align: center;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QGroupBox {{ border: 1px solid {c['border']}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0px 4px; color: {c['text_secondary']}; }}
QSplitter::handle {{ background: {c['border']}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['border_strong']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {c['on_accent']}; border: 1px solid {c['border_strong']}; width: 14px; height: 14px;
    margin: -6px 0px; border-radius: 7px;
}}
QSlider::handle:horizontal:focus {{ border-color: {c['accent']}; }}
"""
