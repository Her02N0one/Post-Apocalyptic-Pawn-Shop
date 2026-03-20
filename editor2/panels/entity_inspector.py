"""editor2/panels/entity_inspector.py — Entity tool palette and inspector."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.entity_defs import entity_registry, get_entity_def


class EntityInspector(QWidget):
    """Left/right panel for the Entity tool.

    - Entity type palette (tree grouped by category)
    - Selected entity inspector (type, position, angle)
    """

    def __init__(self, tool, parent=None) -> None:
        super().__init__(parent)
        self._tool = tool
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        # ── Entity palette ─────────────────────────────────────────
        lay.addWidget(QLabel("<b>Entity Palette</b>"))

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter entities...")
        self._filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self._filter)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.currentItemChanged.connect(self._on_select)
        lay.addWidget(self._tree, 3)

        self._populate_tree()

        # ── Selected entity info ────────────────────────────────────
        grp = QGroupBox("Selected Entity")
        grp_lay = QVBoxLayout(grp)
        grp_lay.setContentsMargins(4, 4, 4, 4)

        self._sel_type_label = QLabel("Type: —")
        self._sel_uid_label = QLabel("UID: —")
        grp_lay.addWidget(self._sel_type_label)
        grp_lay.addWidget(self._sel_uid_label)

        pos_row = QWidget()
        pos_lay = QHBoxLayout(pos_row)
        pos_lay.setContentsMargins(0, 0, 0, 0)
        pos_lay.addWidget(QLabel("X:"))
        self._pos_x = QDoubleSpinBox()
        self._pos_x.setRange(-999, 999)
        self._pos_x.setDecimals(2)
        self._pos_x.setReadOnly(True)
        pos_lay.addWidget(self._pos_x)
        pos_lay.addWidget(QLabel("Y:"))
        self._pos_y = QDoubleSpinBox()
        self._pos_y.setRange(-999, 999)
        self._pos_y.setDecimals(2)
        self._pos_y.setReadOnly(True)
        pos_lay.addWidget(self._pos_y)
        grp_lay.addWidget(pos_row)

        angle_row = QWidget()
        angle_lay = QHBoxLayout(angle_row)
        angle_lay.setContentsMargins(0, 0, 0, 0)
        angle_lay.addWidget(QLabel("Angle:"))
        self._angle_spin = QDoubleSpinBox()
        self._angle_spin.setRange(0, 360)
        self._angle_spin.setDecimals(1)
        self._angle_spin.setSuffix("°")
        self._angle_spin.setReadOnly(True)
        angle_lay.addWidget(self._angle_spin)
        grp_lay.addWidget(angle_row)

        lay.addWidget(grp)

        # ── Help text ────────────────────────────────────────────────
        help_lbl = QLabel(
            "<small>"
            "LMB: place / select entity<br>"
            "Shift+LMB: always place<br>"
            "RMB: delete entity<br>"
            "R: rotate selected 90°<br>"
            "Delete: delete selected"
            "</small>"
        )
        help_lbl.setWordWrap(True)
        lay.addWidget(help_lbl)

        lay.addStretch()

    def set_tool(self, tool) -> None:
        self._tool = tool

    def _populate_tree(self, filter_text: str = "") -> None:
        self._tree.clear()
        reg = entity_registry()
        # Group by category
        cats: dict[str, list] = {}
        ft = filter_text.lower()
        for eid, edef in sorted(reg.items()):
            if ft and ft not in eid.lower() and ft not in edef.display_name.lower():
                continue
            cats.setdefault(edef.category, []).append(edef)

        for cat_name in sorted(cats):
            cat_item = QTreeWidgetItem(self._tree, [cat_name.title()])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            cat_item.setExpanded(True)

            for edef in cats[cat_name]:
                child = QTreeWidgetItem(cat_item, [edef.display_name])
                child.setData(0, Qt.ItemDataRole.UserRole, edef.id)
                # Color swatch
                r, g, b = edef.color
                child.setForeground(0, QColor(r, g, b))

    def _apply_filter(self, text: str) -> None:
        self._populate_tree(text)

    def _on_select(self, current: QTreeWidgetItem | None,
                   previous: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        eid = current.data(0, Qt.ItemDataRole.UserRole)
        if eid and self._tool:
            self._tool.current_type = eid

    def refresh(self) -> None:
        """Update the selected entity inspector from tool state."""
        if not self._tool:
            return
        uid = self._tool.selected_uid
        if uid is None:
            self._sel_type_label.setText("Type: —")
            self._sel_uid_label.setText("UID: —")
            self._pos_x.setValue(0)
            self._pos_y.setValue(0)
            self._angle_spin.setValue(0)
            return

        ent = self._tool._entity_by_uid(uid)
        if ent is None:
            self._sel_type_label.setText("Type: —")
            self._sel_uid_label.setText("UID: —")
            return

        import math
        self._sel_type_label.setText(f"Type: {ent.type}")
        self._sel_uid_label.setText(f"UID: {ent.uid}")
        self._pos_x.setValue(ent.x)
        self._pos_y.setValue(ent.y)
        self._angle_spin.setValue(math.degrees(ent.angle))
