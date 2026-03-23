"""editor2/dialogs.py — Modal dialogs used by the zone editor.

Each dialog is a self-contained ``QDialog`` subclass.  They receive
data in their constructor and expose results via accessor methods
(e.g. ``zone_size()``, ``values()``).

Dialogs
-------
- ``NewZoneDialog``       — pick width × height for a new zone.
- ``OpenZoneDialog``      — pick from existing ``.zone`` files.
- ``ResizeZoneDialog``    — enter new W×H for current zone.
- ``FindReplaceDialog``   — two text inputs for texture find/replace.
- ``ZoneSettingsDialog``  — first_person, skybox, sky_color, anchor.
- ``HelpDialog``          — read-only keyboard shortcut reference.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
    QSpinBox, QVBoxLayout, QWidget,
)


# ── NewZoneDialog ─────────────────────────────────────────────────

class NewZoneDialog(QDialog):
    """Simple dialog to pick width × height for a new zone."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Zone")
        layout = QFormLayout(self)

        self._w_spin = QSpinBox()
        self._w_spin.setRange(4, 128)
        self._w_spin.setValue(20)
        layout.addRow("Width:", self._w_spin)

        self._h_spin = QSpinBox()
        self._h_spin.setRange(4, 128)
        self._h_spin.setValue(20)
        layout.addRow("Height:", self._h_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def zone_size(self) -> tuple[int, int]:
        return self._w_spin.value(), self._h_spin.value()


# ── OpenZoneDialog ────────────────────────────────────────────────

class OpenZoneDialog(QDialog):
    """Dialog listing all available .zone files to pick from."""

    def __init__(self, zones: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Zone")
        self.resize(300, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select a zone to open:"))

        self._list = QListWidget()
        for name in zones:
            self._list.addItem(QListWidgetItem(name))
        self._list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_zone(self) -> str | None:
        item = self._list.currentItem()
        return item.text() if item else None


# ── ResizeZoneDialog ──────────────────────────────────────────────

class ResizeZoneDialog(QDialog):
    """Dialog to resize the current zone."""

    def __init__(self, cur_w: int, cur_h: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize Zone")
        layout = QFormLayout(self)

        layout.addRow(QLabel(f"Current size: {cur_w} × {cur_h}"))

        self._w_spin = QSpinBox()
        self._w_spin.setRange(4, 128)
        self._w_spin.setValue(cur_w)
        layout.addRow("New Width:", self._w_spin)

        self._h_spin = QSpinBox()
        self._h_spin.setRange(4, 128)
        self._h_spin.setValue(cur_h)
        layout.addRow("New Height:", self._h_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def zone_size(self) -> tuple[int, int]:
        return self._w_spin.value(), self._h_spin.value()


# ── FindReplaceDialog ─────────────────────────────────────────────

class FindReplaceDialog(QDialog):
    """Dialog with two text inputs to find and replace texture names."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find / Replace Texture")
        layout = QFormLayout(self)

        self._find_edit = QLineEdit()
        self._find_edit.setPlaceholderText("e.g. grass")
        layout.addRow("Find:", self._find_edit)

        self._replace_edit = QLineEdit()
        self._replace_edit.setPlaceholderText("e.g. dirt")
        layout.addRow("Replace:", self._replace_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, str]:
        return self._find_edit.text().strip(), self._replace_edit.text().strip()


# ── ZoneSettingsDialog ────────────────────────────────────────────

class ZoneSettingsDialog(QDialog):
    """Edit zone-level settings: first_person, skybox, sky_color, anchor."""

    def __init__(self, zone, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zone Settings")
        layout = QFormLayout(self)

        from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox

        self._fp_check = QCheckBox()
        self._fp_check.setChecked(zone.first_person)
        layout.addRow("First Person:", self._fp_check)

        self._skybox_edit = QLineEdit()
        self._skybox_edit.setText(zone.skybox if zone.skybox else "")
        self._skybox_edit.setPlaceholderText("(empty = procedural gradient)")
        layout.addRow("Skybox:", self._skybox_edit)

        sky = zone.sky_color if zone.sky_color else (0, 0, 0)
        self._sky_r = QSpinBox()
        self._sky_r.setRange(0, 255)
        self._sky_r.setValue(sky[0] if len(sky) >= 1 else 0)
        self._sky_g = QSpinBox()
        self._sky_g.setRange(0, 255)
        self._sky_g.setValue(sky[1] if len(sky) >= 2 else 0)
        self._sky_b = QSpinBox()
        self._sky_b.setRange(0, 255)
        self._sky_b.setValue(sky[2] if len(sky) >= 3 else 0)
        sky_row = QWidget()
        sky_layout = QHBoxLayout(sky_row)
        sky_layout.setContentsMargins(0, 0, 0, 0)
        sky_layout.addWidget(QLabel("R"))
        sky_layout.addWidget(self._sky_r)
        sky_layout.addWidget(QLabel("G"))
        sky_layout.addWidget(self._sky_g)
        sky_layout.addWidget(QLabel("B"))
        sky_layout.addWidget(self._sky_b)
        layout.addRow("Sky Color:", sky_row)

        anchor = zone.anchor if zone.anchor else (0.0, 0.0)
        self._anchor_r = QDoubleSpinBox()
        self._anchor_r.setRange(0.0, zone.height - 1)
        self._anchor_r.setDecimals(2)
        self._anchor_r.setValue(anchor[0] if len(anchor) >= 1 else 0.0)
        self._anchor_c = QDoubleSpinBox()
        self._anchor_c.setRange(0.0, zone.width - 1)
        self._anchor_c.setDecimals(2)
        self._anchor_c.setValue(anchor[1] if len(anchor) >= 2 else 0.0)
        anchor_row = QWidget()
        anchor_layout = QHBoxLayout(anchor_row)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        anchor_layout.addWidget(QLabel("Row"))
        anchor_layout.addWidget(self._anchor_r)
        anchor_layout.addWidget(QLabel("Col"))
        anchor_layout.addWidget(self._anchor_c)
        layout.addRow("Spawn Anchor:", anchor_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> dict:
        sky = (self._sky_r.value(), self._sky_g.value(), self._sky_b.value())
        if sky == (0, 0, 0):
            sky = ()
        return {
            "first_person": self._fp_check.isChecked(),
            "skybox": self._skybox_edit.text().strip(),
            "sky_color": sky,
            "anchor": (self._anchor_r.value(), self._anchor_c.value()),
        }


# ── HelpDialog ────────────────────────────────────────────────────

SHORTCUTS_TEXT = """\
─── General ───────────────────────────
1              Paint tool
2              Sculpt tool
3              Select tool
4              Erase tool
5              Tile Type tool
6              Entity tool
7              Light tool
Ctrl+Z         Undo
Ctrl+Y / Ctrl+Shift+Z   Redo
Ctrl+S         Save
Ctrl+Shift+S   Save As
Ctrl+N         New Zone
Ctrl+O         Open Zone
Ctrl+F         Find / Replace Texture
Ctrl+A         Select all cells
Ctrl+C         Copy selection
Ctrl+V         Paste at hovered cell
Escape         Release camera / clear selection
Home           Reset Camera
Tab            Toggle 2.5D raycaster preview

─── Camera ────────────────────────────
Right-click hold   Look / orbit (release to exit)
Enter          Toggle free-fly camera mode
W / A / S / D  Move (while in camera)
Q / E          Yaw left / right
Space          Move up
Ctrl / C       Move down
Shift          Sprint
Scroll wheel   Zoom in / out
Shift+1..9     Save camera bookmark
Alt+1..9       Recall camera bookmark

Note: tool shortcuts are paused while
camera is active. Release right-click
or press Escape to use tool keys.

─── Paint Tool ────────────────────────
Click          Paint face
Shift+Click    Paint all faces of cell
Ctrl+Click     Flood fill
Middle-click   Eyedropper (pick texture)

─── Sculpt Tool ───────────────────────
Click + drag   Raise (floor) / Lower (ceiling)
Shift+Click    Lower (floor) / Raise (ceiling)
G              Cycle snap grid
H              Make cell a wall
Shift+H        Make cell open (grass)
T              Toggle ceiling (sky / closed)
R              Reset floor or ceiling height
U              Raise upper wall height
Shift+U        Lower upper wall height
Ctrl+U         Reset upper wall height
Delete         Clear cell (all defaults)

─── Select Tool ───────────────────────
Click          Set rectangle corners (2-click)
Ctrl+Click     Toggle individual cell
Shift+Click    Select line (Bresenham)
Scroll wheel   Raise / lower selected heights
X              Toggle floor / ceiling mode
Delete         Reset selected cells
H              Make selected cells walls
Shift+H        Make selected cells open

─── Entity Tool ───────────────────────
Click          Place / select entity
Shift+Click    Always place (ignore existing)
X / Delete     Delete selected entity
R              Rotate selected 90°
Shift+Scroll   Rotate selected 15° steps
M              Move selected to hovered cell
[ / ]          Prev / next entity type
F              Quick search entity types
S              Cycle snap mode

─── Light Tool ─────────────────────────
Click + drag   Increase light level
Shift+Click    Decrease light level
[ / ]          Decrease / increase step size
Middle-click   Sample light level

─── Erase Tool ────────────────────────
Click          Full cell reset
Shift+Click    Clear textures only
Ctrl+Click     Reset height only

─── View ──────────────────────────────
Ctrl+1         Toggle walls visibility
Ctrl+2         Toggle floors visibility
Ctrl+3         Toggle ceilings visibility
Ctrl+4         Toggle entities visibility
Ctrl+5         Toggle wireframe
G              Toggle grid / cycle snap (sculpt)
F3             Toggle performance overlay
F4             Dump stats

─── Raycaster Preview ─────────────────
Tab            Return to 3D editor
Click          Enter FPS mode
W / A / S / D  Move
Shift          Sprint
Escape         Release mouse
"""


class HelpDialog(QDialog):
    """Dialog showing all keyboard shortcuts."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(480, 520)
        layout = QVBoxLayout(self)

        text = QPlainTextEdit()
        text.setPlainText(SHORTCUTS_TEXT)
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 10))
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
