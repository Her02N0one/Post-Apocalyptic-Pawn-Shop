"""editor2/panels/select_inspector.py — Inspector for the Select tool."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget,
)


class SelectInspector(QWidget):
    """Right-dock panel for the Select tool.

    Shows selection info and batch operation buttons.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Info ──
        self._info_label = QLabel("No selection")
        layout.addWidget(self._info_label)

        # ── Batch ops ──
        ops = QGroupBox("Batch Operations")
        ops_layout = QVBoxLayout(ops)

        self.btn_fill = QPushButton("Fill Texture")
        self.btn_fill.setToolTip("Fill selected cells with current paint texture")
        ops_layout.addWidget(self.btn_fill)

        self.btn_clear_tex = QPushButton("Clear Textures")
        self.btn_clear_tex.setToolTip("Clear all texture overrides in selection")
        ops_layout.addWidget(self.btn_clear_tex)

        self.btn_reset = QPushButton("Reset Cells")
        self.btn_reset.setToolTip("Reset selected cells to defaults (Delete)")
        ops_layout.addWidget(self.btn_reset)

        self.btn_flatten = QPushButton("Flatten Heights")
        self.btn_flatten.setToolTip("Average heights across selection")
        ops_layout.addWidget(self.btn_flatten)

        self.btn_wall = QPushButton("Make Wall (H)")
        ops_layout.addWidget(self.btn_wall)

        self.btn_open = QPushButton("Make Open (Shift+H)")
        ops_layout.addWidget(self.btn_open)

        layout.addWidget(ops)

        # ── Mode ──
        self._mode_label = QLabel("Mode: Floor")
        layout.addWidget(self._mode_label)

        # ── Help ──
        help_label = QLabel(
            "<small>"
            "Click → set corner 1<br>"
            "Click → set corner 2 (rect)<br>"
            "Ctrl+Click → toggle cell<br>"
            "Shift+Click → line select<br>"
            "Ctrl+A → select all<br>"
            "Escape → clear selection<br>"
            "X → toggle floor/ceiling mode<br>"
            "Scroll → raise/lower selection"
            "</small>"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

    def update_info(self, count: int, ceiling_mode: bool) -> None:
        if count == 0:
            self._info_label.setText("No selection")
        else:
            self._info_label.setText(f"Selected: {count} cell(s)")
        self._mode_label.setText(
            f"Mode: {'Ceiling' if ceiling_mode else 'Floor'}")
