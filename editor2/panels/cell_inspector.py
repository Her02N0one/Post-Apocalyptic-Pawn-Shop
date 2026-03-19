"""editor2/panels/cell_inspector.py — Read-only cell data inspector."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout,
)

from core.zones import Zone


class CellInspector(QWidget):
    """Dock panel showing full data for the hovered cell."""

    def __init__(self, zone: Zone, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zone = zone

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Coordinates ──
        self._lbl_cell = QLabel("Cell: —")
        layout.addWidget(self._lbl_cell)

        # ── Heights ──
        heights_box = QGroupBox("Heights")
        h_lay = QFormLayout(heights_box)
        self._lbl_floor_h = QLabel("—")
        self._lbl_ceil_h = QLabel("—")
        h_lay.addRow("Floor:", self._lbl_floor_h)
        h_lay.addRow("Ceiling:", self._lbl_ceil_h)
        layout.addWidget(heights_box)

        # ── Textures ──
        tex_box = QGroupBox("Textures")
        t_lay = QFormLayout(tex_box)
        self._lbl_tile = QLabel("—")
        self._lbl_floor_tex = QLabel("—")
        self._lbl_ceil_tex = QLabel("—")
        self._lbl_wall_tex = QLabel("—")
        self._lbl_face_n = QLabel("—")
        self._lbl_face_s = QLabel("—")
        self._lbl_face_e = QLabel("—")
        self._lbl_face_w = QLabel("—")
        t_lay.addRow("Tile:", self._lbl_tile)
        t_lay.addRow("Floor:", self._lbl_floor_tex)
        t_lay.addRow("Ceil:", self._lbl_ceil_tex)
        t_lay.addRow("Wall:", self._lbl_wall_tex)
        t_lay.addRow("N:", self._lbl_face_n)
        t_lay.addRow("S:", self._lbl_face_s)
        t_lay.addRow("E:", self._lbl_face_e)
        t_lay.addRow("W:", self._lbl_face_w)
        layout.addWidget(tex_box)

        # ── Properties ──
        props_box = QGroupBox("Properties")
        p_lay = QFormLayout(props_box)
        self._lbl_light = QLabel("—")
        self._lbl_rotation = QLabel("—")
        p_lay.addRow("Light:", self._lbl_light)
        p_lay.addRow("Rotation:", self._lbl_rotation)
        layout.addWidget(props_box)

        layout.addStretch()

    def set_zone(self, zone: Zone) -> None:
        self._zone = zone

    def update_cell(self, row: int | None, col: int | None) -> None:
        """Update display for the given cell coordinates."""
        if row is None or col is None:
            self._lbl_cell.setText("Cell: —")
            for lbl in (self._lbl_floor_h, self._lbl_ceil_h,
                        self._lbl_tile, self._lbl_floor_tex,
                        self._lbl_ceil_tex, self._lbl_wall_tex,
                        self._lbl_face_n, self._lbl_face_s,
                        self._lbl_face_e, self._lbl_face_w,
                        self._lbl_light, self._lbl_rotation):
                lbl.setText("—")
            return

        z = self._zone
        self._lbl_cell.setText(f"Cell: ({col}, {row})")

        # Heights
        fh = z.floor_heights[row][col] if z.floor_heights else 0.0
        ch = z.ceil_heights[row][col] if z.ceil_heights else 10.0
        self._lbl_floor_h.setText(f"{fh:.3f}")
        self._lbl_ceil_h.setText(f"{ch:.3f}")

        # Textures
        self._lbl_tile.setText(z.tiles[row][col])
        ft = z.floor_textures[row][col] if z.floor_textures else ""
        ct = z.ceil_textures[row][col] if z.ceil_textures else ""
        wt = z.wall_textures[row][col] if z.wall_textures else ""
        self._lbl_floor_tex.setText(ft or "(default)")
        self._lbl_ceil_tex.setText(ct or "(default)")
        self._lbl_wall_tex.setText(wt or "(default)")

        # Per-face textures
        if z.face_textures and z.face_textures[row][col]:
            faces = z.face_textures[row][col]
            self._lbl_face_n.setText(faces[0] or "(default)")
            self._lbl_face_s.setText(faces[1] or "(default)")
            self._lbl_face_e.setText(faces[2] or "(default)")
            self._lbl_face_w.setText(faces[3] or "(default)")
        else:
            for lbl in (self._lbl_face_n, self._lbl_face_s,
                        self._lbl_face_e, self._lbl_face_w):
                lbl.setText("(default)")

        # Properties
        ll = z.light_levels[row][col] if z.light_levels else 1.0
        rot = z.rotations[row][col] if z.rotations else 0
        self._lbl_light.setText(f"{ll:.2f}")
        self._lbl_rotation.setText(str(rot))
