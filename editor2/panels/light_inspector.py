"""editor2/panels/light_inspector.py — Light tool inspector panel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)


class LightInspector(QWidget):
    """Inspector panel for the Light painting tool."""

    def __init__(self, tool, parent=None) -> None:
        super().__init__(parent)
        self._tool = tool
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        lay.addWidget(QLabel("<b>Light Painter</b>"))

        # Step size buttons
        step_grp = QGroupBox("Step Size")
        step_lay = QHBoxLayout(step_grp)
        step_lay.setContentsMargins(4, 4, 4, 4)

        self._step_buttons: list[QPushButton] = []
        for i, val in enumerate(tool.STEPS):
            btn = QPushButton(str(val))
            btn.setCheckable(True)
            btn.setChecked(i == tool.step_idx)
            btn.clicked.connect(lambda checked, idx=i: self._set_step(idx))
            step_lay.addWidget(btn)
            self._step_buttons.append(btn)
        lay.addWidget(step_grp)

        # Current info
        self._info_label = QLabel("Light: —")
        lay.addWidget(self._info_label)

        # Help
        help_lbl = QLabel(
            "<small>"
            "LMB: increase light<br>"
            "Shift+LMB: decrease light<br>"
            "Drag: paint continuously<br>"
            "Middle-click: sample level<br>"
            "Scroll: change step size"
            "</small>"
        )
        help_lbl.setWordWrap(True)
        lay.addWidget(help_lbl)

        lay.addStretch()

    def set_tool(self, tool) -> None:
        self._tool = tool

    def _set_step(self, idx: int) -> None:
        if self._tool:
            self._tool.step_idx = idx
        for i, btn in enumerate(self._step_buttons):
            btn.setChecked(i == idx)

    def refresh(self) -> None:
        if not self._tool:
            return
        # Update step button states
        for i, btn in enumerate(self._step_buttons):
            btn.setChecked(i == self._tool.step_idx)

        hit = self._tool.hover_hit
        if hit is None:
            self._info_label.setText("Light: —")
            return
        zone = self._tool._zone
        r, c = hit.row, hit.col
        ll = zone.light_levels[r][c] if zone.light_levels else 1.0
        self._info_label.setText(
            f"Light: {ll:.2f}  |  Cell: ({c}, {r})  |  Step: {self._tool.step}")
