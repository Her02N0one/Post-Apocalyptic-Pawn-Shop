"""editor2/panels/sculpt_inspector.py — Sculpt tool inspector panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout, QPushButton,
)

from editor2.tools.sculpt import SculptTool, SNAP_LABELS


class SculptInspector(QWidget):
    """Dock panel showing sculpt tool state and settings."""

    def __init__(self, tool: SculptTool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool = tool

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Info ──
        info_box = QGroupBox("Sculpt Tool")
        info_lay = QVBoxLayout(info_box)

        self._lbl_hover = QLabel("Hover: —")
        self._lbl_field = QLabel("Field: —")
        self._lbl_value = QLabel("Height: —")
        info_lay.addWidget(self._lbl_hover)
        info_lay.addWidget(self._lbl_field)
        info_lay.addWidget(self._lbl_value)
        layout.addWidget(info_box)

        # ── Snap presets ──
        snap_box = QGroupBox("Snap Grid (G to cycle)")
        snap_lay = QHBoxLayout(snap_box)
        self._snap_btns: list[QPushButton] = []
        for i, label in enumerate(SNAP_LABELS):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == tool.snap_idx)
            btn.clicked.connect(lambda checked, idx=i: self._on_snap_clicked(idx))
            snap_lay.addWidget(btn)
            self._snap_btns.append(btn)
        layout.addWidget(snap_box)

        # ── Help ──
        help_box = QGroupBox("Controls")
        help_lay = QVBoxLayout(help_box)
        help_lbl = QLabel(
            "Left-click: raise\n"
            "Shift+click: lower\n"
            "Drag to sculpt area\n"
            "G: cycle snap grid"
        )
        help_lbl.setWordWrap(True)
        help_lay.addWidget(help_lbl)
        layout.addWidget(help_box)

        layout.addStretch()

    def _on_snap_clicked(self, idx: int) -> None:
        self._tool.snap_idx = idx
        self._sync_snap_buttons()

    def _sync_snap_buttons(self) -> None:
        for i, btn in enumerate(self._snap_btns):
            btn.setChecked(i == self._tool.snap_idx)

    def refresh(self) -> None:
        """Update display from tool state."""
        hit = self._tool.hover_hit
        if hit:
            self._lbl_hover.setText(
                f"Hover: ({hit.row},{hit.col}) {hit.part}.{hit.face.name}")
            field = self._tool._field_for_hit(hit)
            self._lbl_field.setText(f"Field: {field or '—'}")
            if field:
                grid = getattr(self._tool._zone, field, None)
                if grid:
                    val = grid[hit.row][hit.col]
                    self._lbl_value.setText(f"Height: {val:.2f}")
                else:
                    self._lbl_value.setText("Height: —")
            else:
                self._lbl_value.setText("Height: —")
        else:
            self._lbl_hover.setText("Hover: —")
            self._lbl_field.setText("Field: —")
            self._lbl_value.setText("Height: —")
        self._sync_snap_buttons()

    def set_tool(self, tool: SculptTool) -> None:
        """Swap the underlying tool (e.g. after zone switch)."""
        self._tool = tool
        self._sync_snap_buttons()
        self.refresh()
