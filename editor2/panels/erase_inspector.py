"""editor2/panels/erase_inspector.py — Inspector for the Erase tool."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class EraseInspector(QWidget):
    """Right-dock panel for the Erase tool — shows click-mode help."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("<b>Erase Tool</b>")
        layout.addWidget(title)

        help_label = QLabel(
            "<table cellpadding='4'>"
            "<tr><td><b>Left-click</b></td>"
            "<td>Full cell reset<br>"
            "<small>(grass, flat floor, sky ceiling, clear textures)</small></td></tr>"
            "<tr><td><b>Shift+Click</b></td>"
            "<td>Clear textures only<br>"
            "<small>(keep tile type and geometry)</small></td></tr>"
            "<tr><td><b>Right-click</b></td>"
            "<td>Reset height only<br>"
            "<small>(keep tile and textures)</small></td></tr>"
            "</table>"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        layout.addStretch()
