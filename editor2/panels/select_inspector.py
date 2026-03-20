"""editor2/panels/select_inspector.py — Inspector for the Select tool."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
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

        # Texture picker + fill button
        tex_row = QHBoxLayout()
        self._tex_combo = QComboBox()
        self._tex_combo.setToolTip("Texture to fill with")
        tex_row.addWidget(self._tex_combo, 1)
        self.btn_fill = QPushButton("Fill")
        self.btn_fill.setToolTip("Fill selected cells with chosen texture")
        tex_row.addWidget(self.btn_fill)
        ops_layout.addLayout(tex_row)

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

        self.btn_toggle_ceil = QPushButton("Toggle Ceiling (T)")
        self.btn_toggle_ceil.setToolTip("Toggle ceiling on/off for selection")
        ops_layout.addWidget(self.btn_toggle_ceil)

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
            "Ctrl+C / Ctrl+V → copy / paste<br>"
            "Escape → clear selection<br>"
            "X → toggle floor/ceiling mode<br>"
            "Scroll → raise/lower selection<br>"
            "G → cycle snap grid"
            "</small>"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

    @property
    def selected_texture(self) -> str:
        """Return the texture name selected in the combo box."""
        return self._tex_combo.currentText() or ""

    def set_texture_list(self, names: list[str]) -> None:
        """Populate the texture combo box."""
        prev = self._tex_combo.currentText()
        self._tex_combo.blockSignals(True)
        self._tex_combo.clear()
        self._tex_combo.addItems(names)
        idx = self._tex_combo.findText(prev)
        if idx >= 0:
            self._tex_combo.setCurrentIndex(idx)
        self._tex_combo.blockSignals(False)

    def update_info(self, count: int, ceiling_mode: bool) -> None:
        if count == 0:
            self._info_label.setText("No selection")
        else:
            self._info_label.setText(f"Selected: {count} cell(s)")
        self._mode_label.setText(
            f"Mode: {'Ceiling' if ceiling_mode else 'Floor'}")
