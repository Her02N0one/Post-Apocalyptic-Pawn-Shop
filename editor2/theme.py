"""editor2/theme.py — Dark editor theme (stylesheet + palette).

Provides ``apply_dark_theme(app)`` to apply the Fusion-based dark theme
to a ``QApplication``.  Extracted from main.py to keep styling isolated.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ── Dark editor CSS ───────────────────────────────────────────────

DARK_STYLE = """
/* ── Global ── */
QMainWindow, QDialog, QMessageBox {
    background-color: #2b2b2b;
}

/* ── Menu bar ── */
QMenuBar {
    background-color: #2d2d2d;
    color: #ccc;
    border-bottom: 1px solid #3a3a3a;
    padding: 2px 0;
}
QMenuBar::item {
    padding: 4px 10px;
    background: transparent;
    border-radius: 3px;
}
QMenuBar::item:selected {
    background-color: #404040;
}
QMenuBar::item:pressed {
    background-color: #4a4a4a;
}

/* ── Menus ── */
QMenu {
    background-color: #2d2d2d;
    color: #ccc;
    border: 1px solid #404040;
    padding: 4px 0;
}
QMenu::item {
    padding: 5px 28px 5px 22px;
}
QMenu::item:selected {
    background-color: #3a6ea5;
}
QMenu::item:disabled {
    color: #666;
}
QMenu::separator {
    height: 1px;
    background: #404040;
    margin: 4px 10px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
    margin-left: 6px;
}

/* ── Toolbar ── */
QToolBar {
    background-color: #303030;
    border: none;
    border-bottom: 1px solid #222;
    spacing: 3px;
    padding: 3px 6px;
}
QToolBar QToolButton {
    background: #3a3a3a;
    color: #b0b0b0;
    border: 1px solid #4a4a4a;
    border-radius: 3px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 600;
    min-width: 44px;
}
QToolBar QToolButton:hover {
    background: #484848;
    border-color: #5a5a5a;
    color: #eee;
}
QToolBar QToolButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4a9eff, stop:1 #3a8eef);
    color: #fff;
    border-color: #5aa4ff;
}
QToolBar QToolButton:pressed {
    background: #2a2a2a;
}
QToolBar::separator {
    width: 1px;
    background: #505050;
    margin: 4px 6px;
}

/* ── Dock widgets ── */
QDockWidget {
    color: #ccc;
    font-weight: bold;
    font-size: 11px;
}
QDockWidget::title {
    background: #353535;
    padding: 6px 8px;
    border-bottom: 2px solid #4a9eff;
    text-align: left;
}
QDockWidget::close-button, QDockWidget::float-button {
    background: transparent;
    border: none;
    padding: 2px;
}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {
    background: #505050;
    border-radius: 2px;
}
QDockWidget > QWidget {
    background-color: #2e2e2e;
}

/* ── Status bar ── */
QStatusBar {
    background: #252525;
    color: #999;
    border-top: 1px solid #3a3a3a;
    font-size: 11px;
    min-height: 22px;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    color: #999;
    padding: 0 6px;
}

/* ── Group boxes ── */
QGroupBox {
    border: 1px solid #444;
    border-radius: 4px;
    margin-top: 12px;
    padding: 12px 6px 6px 6px;
    font-weight: bold;
    font-size: 11px;
    color: #aaa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #bbb;
}

/* ── Tree / list widgets ── */
QTreeWidget, QListWidget, QTreeView, QListView {
    background-color: #1e1e1e;
    color: #ccc;
    border: 1px solid #3a3a3a;
    alternate-background-color: #242424;
    outline: none;
}
QTreeWidget::item, QListWidget::item {
    padding: 3px 0;
}
QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #2a5a8a;
    color: #fff;
}
QTreeWidget::item:hover, QListWidget::item:hover {
    background-color: #333;
}
QTreeWidget::branch {
    background-color: transparent;
}
QHeaderView::section {
    background-color: #333;
    color: #ccc;
    border: 1px solid #3a3a3a;
    padding: 3px 6px;
}

/* ── Inputs ── */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #1e1e1e;
    color: #ccc;
    border: 1px solid #444;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #2a5a8a;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #4a9eff;
}
QComboBox {
    background-color: #1e1e1e;
    color: #ccc;
    border: 1px solid #444;
    border-radius: 3px;
    padding: 3px 6px;
    min-height: 20px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #ccc;
    selection-background-color: #2a5a8a;
    border: 1px solid #444;
}

/* ── Buttons ── */
QPushButton {
    background-color: #3a3a3a;
    color: #ccc;
    border: 1px solid #505050;
    border-radius: 3px;
    padding: 5px 14px;
    min-height: 20px;
}
QPushButton:hover {
    background-color: #454545;
    border-color: #5a5a5a;
}
QPushButton:pressed {
    background-color: #2e2e2e;
}
QPushButton:disabled {
    background-color: #333;
    color: #666;
    border-color: #3a3a3a;
}

/* ── Checkboxes & Radio ── */
QCheckBox, QRadioButton {
    color: #ccc;
    spacing: 6px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #555;
    background: #1e1e1e;
}
QCheckBox::indicator {
    border-radius: 3px;
}
QRadioButton::indicator {
    border-radius: 8px;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: #4a9eff;
    border-color: #4a9eff;
}

/* ── Sliders ── */
QSlider::groove:horizontal {
    height: 4px;
    background: #333;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #4a9eff;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::groove:vertical {
    width: 4px;
    background: #333;
    border-radius: 2px;
}
QSlider::handle:vertical {
    background: #4a9eff;
    width: 14px;
    height: 14px;
    margin: 0 -5px;
    border-radius: 7px;
}

/* ── Scrollbars ── */
QScrollBar:vertical {
    background: #2b2b2b;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #505050;
    min-height: 24px;
    border-radius: 4px;
    margin: 1px;
}
QScrollBar::handle:vertical:hover {
    background: #636363;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background: #2b2b2b;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: #505050;
    min-width: 24px;
    border-radius: 4px;
    margin: 1px;
}
QScrollBar::handle:horizontal:hover {
    background: #636363;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* ── Tabs ── */
QTabWidget::pane {
    border: 1px solid #3a3a3a;
    background: #2b2b2b;
}
QTabBar::tab {
    background: #333;
    color: #999;
    padding: 5px 14px;
    border: 1px solid #3a3a3a;
    border-bottom: none;
    margin-right: 1px;
}
QTabBar::tab:selected {
    background: #2b2b2b;
    color: #ccc;
    border-bottom: 2px solid #4a9eff;
}
QTabBar::tab:hover {
    background: #3a3a3a;
    color: #ccc;
}

/* ── Plain text / text edits ── */
QPlainTextEdit, QTextEdit {
    background-color: #1e1e1e;
    color: #ccc;
    border: 1px solid #3a3a3a;
    selection-background-color: #2a5a8a;
}

/* ── Tooltips ── */
QToolTip {
    background-color: #3a3a3a;
    color: #ddd;
    border: 1px solid #555;
    padding: 4px;
}

/* ── Splitter handles ── */
QSplitter::handle {
    background-color: #3a3a3a;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}

/* ── Labels ── */
QLabel {
    color: #ccc;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Apply a dark editor theme (Fusion base + custom palette + stylesheet)."""
    app.setStyle("Fusion")

    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(43, 43, 43))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(204, 204, 204))
    p.setColor(QPalette.ColorRole.Base,            QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(58, 58, 58))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(204, 204, 204))
    p.setColor(QPalette.ColorRole.Text,            QColor(204, 204, 204))
    p.setColor(QPalette.ColorRole.Button,          QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(204, 204, 204))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Link,            QColor(74, 158, 255))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(74, 158, 255))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

    # Muted disabled state
    p.setColor(QPalette.ColorGroup.Disabled,
               QPalette.ColorRole.WindowText, QColor(128, 128, 128))
    p.setColor(QPalette.ColorGroup.Disabled,
               QPalette.ColorRole.Text, QColor(128, 128, 128))
    p.setColor(QPalette.ColorGroup.Disabled,
               QPalette.ColorRole.ButtonText, QColor(128, 128, 128))

    app.setPalette(p)
    app.setStyleSheet(DARK_STYLE)
