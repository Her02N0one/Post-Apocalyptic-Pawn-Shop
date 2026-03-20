"""editor2/viewport.py — QOpenGLWidget that renders zone geometry."""

from __future__ import annotations

import collections
import logging
import time
from typing import TYPE_CHECKING, Callable

import numpy as np
from OpenGL import GL as gl

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QLabel
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from core.zones import Zone
from editor2.atlas import TileAtlas
from editor2.camera import Camera, MOVE_SPEED, SPRINT_MULT, MOUSE_SENS
from editor2.mesh import build_zone_mesh

if TYPE_CHECKING:
    from editor2.tools import Overlay, Tool

log = logging.getLogger(__name__)

COL_BG = (15, 15, 20)

# ── Main scene shaders ────────────────────────────────────────────

VERT_SRC = """
#version 330 core
layout(location = 0) in vec3 a_pos;
layout(location = 1) in vec3 a_color;
layout(location = 2) in vec2 a_uv;
layout(location = 3) in float a_texLayer;

uniform mat4 u_vp;

out vec3 v_color;
out vec2 v_uv;
flat out float v_texLayer;

void main() {
    v_color = a_color;
    v_uv = a_uv;
    v_texLayer = a_texLayer;
    gl_Position = u_vp * vec4(a_pos, 1.0);
}
"""

FRAG_SRC = """
#version 330 core
uniform sampler2DArray u_atlas;

in vec3 v_color;
in vec2 v_uv;
flat in float v_texLayer;

out vec4 frag_color;

void main() {
    vec4 tex = texture(u_atlas, vec3(v_uv, v_texLayer));
    frag_color = vec4(tex.rgb * v_color, tex.a);
}
"""

# ── Overlay shaders (flat colour, alpha blend) ────────────────────

OVERLAY_VERT = """
#version 330 core
layout(location = 0) in vec3 a_pos;
uniform mat4 u_vp;
void main() {
    gl_Position = u_vp * vec4(a_pos, 1.0);
}
"""

OVERLAY_FRAG = """
#version 330 core
uniform vec4 u_color;
out vec4 frag_color;
void main() {
    frag_color = u_color;
}
"""


class ZoneViewport(QOpenGLWidget):
    """QOpenGLWidget that renders zone geometry with face shading."""

    def __init__(self, zone: Zone, atlas: TileAtlas,
                 parent=None) -> None:
        super().__init__(parent)
        self.zone = zone
        self.camera = Camera()
        self._vao = 0
        self._vbo = 0
        self._program = 0
        self._vp_loc = -1
        self._atlas_loc = -1
        self._vertex_count = 0
        self._atlas = atlas

        # Overlay GL state
        self._ovl_program = 0
        self._ovl_vp_loc = -1
        self._ovl_color_loc = -1
        self._ovl_vao = 0
        self._ovl_vbo = 0
        self._ovl_vbo_size = 0

        # Active tool (set externally)
        self._tool: Tool | None = None
        self.on_hover: Callable[[], None] | None = None
        self._on_scroll: Callable[[int], bool] | None = None
        self.extra_overlays: Callable[[], list] | None = None
        self.on_eyedrop: Callable[[int, int, int], None] | None = None

        # Display options
        self._show_grid = True
        self._wireframe = False
        self._show_walls = True

        # HUD overlay label (QLabel sitting on top of the GL surface)
        self._hud_label = QLabel(self)
        self._hud_label.setStyleSheet(
            "background: rgba(0,0,0,140); color: #ccc;"
            " font: 10pt 'Consolas'; padding: 6px;"
            " border: none;"
        )
        self._hud_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hud_label.move(6, 6)
        self._hud_label.hide()
        self._show_floors = True
        self._show_ceilings = True

        # Input state
        self._keys: set[int] = set()
        self._mouse_captured = False
        self._last_time = time.monotonic()

        # Perf counters
        self._frame_times: collections.deque[float] = collections.deque(maxlen=120)
        self._last_rebuild_ms: float = 0.0
        self._show_perf = False
        self._mesh_dirty = False
        self._in_paint_gl = False

        # Centre camera on zone
        self.camera.x = zone.width * 0.5
        self.camera.z = zone.height * 0.5
        self.camera.y = 1.5

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # 60 FPS update
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ── Perf helpers ──────────────────────────────────────────────

    @property
    def show_perf(self) -> bool:
        return self._show_perf

    @show_perf.setter
    def show_perf(self, v: bool) -> None:
        self._show_perf = v

    @property
    def avg_frame_ms(self) -> float:
        if not self._frame_times:
            return 0.0
        return sum(self._frame_times) / len(self._frame_times)

    @property
    def fps(self) -> float:
        avg = self.avg_frame_ms
        return 1000.0 / avg if avg > 0 else 0.0

    @property
    def last_rebuild_ms(self) -> float:
        return self._last_rebuild_ms

    @property
    def show_grid(self) -> bool:
        return self._show_grid

    @show_grid.setter
    def show_grid(self, v: bool) -> None:
        self._show_grid = v

    @property
    def wireframe(self) -> bool:
        return self._wireframe

    @wireframe.setter
    def wireframe(self, v: bool) -> None:
        self._wireframe = v

    def set_layer_vis(self, layer: str, on: bool) -> None:
        """Toggle visibility of a mesh layer ('walls', 'floors', 'ceilings')."""
        attr = f"_show_{layer}"
        if getattr(self, attr, None) == on:
            return
        setattr(self, attr, on)
        self.mark_mesh_dirty()

    # ── GL Lifecycle ──────────────────────────────────────────────

    @property
    def tool(self) -> Tool | None:
        return self._tool

    @tool.setter
    def tool(self, t: Tool | None) -> None:
        self._tool = t

    def initializeGL(self) -> None:
        gl.glClearColor(COL_BG[0] / 255, COL_BG[1] / 255, COL_BG[2] / 255, 1.0)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        gl.glFrontFace(gl.GL_CW)

        self._build_shader()
        self._build_overlay_shader()
        self._atlas.upload()
        self._build_mesh()

    def _build_shader(self) -> None:
        vs = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        gl.glShaderSource(vs, VERT_SRC)
        gl.glCompileShader(vs)
        if not gl.glGetShaderiv(vs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(vs).decode()
            raise RuntimeError(f"Vertex shader error:\n{log}")

        fs = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)
        gl.glShaderSource(fs, FRAG_SRC)
        gl.glCompileShader(fs)
        if not gl.glGetShaderiv(fs, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(fs).decode()
            raise RuntimeError(f"Fragment shader error:\n{log}")

        prog = gl.glCreateProgram()
        gl.glAttachShader(prog, vs)
        gl.glAttachShader(prog, fs)
        gl.glLinkProgram(prog)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            log = gl.glGetProgramInfoLog(prog).decode()
            raise RuntimeError(f"Shader link error:\n{log}")

        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)

        self._program = prog
        self._vp_loc = gl.glGetUniformLocation(prog, "u_vp")
        self._atlas_loc = gl.glGetUniformLocation(prog, "u_atlas")

    def _build_overlay_shader(self) -> None:
        vs = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        gl.glShaderSource(vs, OVERLAY_VERT)
        gl.glCompileShader(vs)
        if not gl.glGetShaderiv(vs, gl.GL_COMPILE_STATUS):
            raise RuntimeError(gl.glGetShaderInfoLog(vs).decode())

        fs = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)
        gl.glShaderSource(fs, OVERLAY_FRAG)
        gl.glCompileShader(fs)
        if not gl.glGetShaderiv(fs, gl.GL_COMPILE_STATUS):
            raise RuntimeError(gl.glGetShaderInfoLog(fs).decode())

        prog = gl.glCreateProgram()
        gl.glAttachShader(prog, vs)
        gl.glAttachShader(prog, fs)
        gl.glLinkProgram(prog)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            raise RuntimeError(gl.glGetProgramInfoLog(prog).decode())
        gl.glDeleteShader(vs)
        gl.glDeleteShader(fs)

        self._ovl_program = prog
        self._ovl_vp_loc = gl.glGetUniformLocation(prog, "u_vp")
        self._ovl_color_loc = gl.glGetUniformLocation(prog, "u_color")

        # Overlay VAO + VBO (initial size, grows dynamically)
        self._ovl_vao = int(gl.glGenVertexArrays(1))
        gl.glBindVertexArray(self._ovl_vao)
        self._ovl_vbo = int(gl.glGenBuffers(1))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._ovl_vbo)
        self._ovl_vbo_size = 6 * 3 * 4  # 6 verts × 3 floats × 4 bytes
        gl.glBufferData(gl.GL_ARRAY_BUFFER, self._ovl_vbo_size, None,
                        gl.GL_DYNAMIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12,
                                 gl.ctypes.c_void_p(0))
        gl.glBindVertexArray(0)

    def _build_mesh(self) -> None:
        data, count = build_zone_mesh(
            self.zone, self._atlas,
            show_walls=self._show_walls,
            show_floors=self._show_floors,
            show_ceilings=self._show_ceilings,
        )
        self._vertex_count = count

        self._vao = int(gl.glGenVertexArrays(1))
        gl.glBindVertexArray(self._vao)

        self._vbo = int(gl.glGenBuffers(1))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)

        stride = 9 * 4  # 9 floats × 4 bytes
        # pos3
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 gl.ctypes.c_void_p(0))
        # color3
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 gl.ctypes.c_void_p(12))
        # uv2
        gl.glEnableVertexAttribArray(2)
        gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 gl.ctypes.c_void_p(24))
        # texLayer1
        gl.glEnableVertexAttribArray(3)
        gl.glVertexAttribPointer(3, 1, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 gl.ctypes.c_void_p(32))

        gl.glBindVertexArray(0)

        print(f"  Mesh: {count:,} vertices, {count // 3:,} triangles")

    def resizeGL(self, w: int, h: int) -> None:
        gl.glViewport(0, 0, w, h)

    def mark_mesh_dirty(self) -> None:
        """Schedule a mesh rebuild before the next frame."""
        self._mesh_dirty = True
        self.update()

    def rebuild_mesh(self) -> None:
        """Rebuild the zone mesh after zone data changes.

        Safe to call both from paintGL (context already current) and
        outside paintGL (will acquire context).
        """
        self._mesh_dirty = False
        t0 = time.perf_counter()
        in_paint = self._in_paint_gl
        if not in_paint:
            self.makeCurrent()
        data, count = build_zone_mesh(
            self.zone, self._atlas,
            show_walls=self._show_walls,
            show_floors=self._show_floors,
            show_ceilings=self._show_ceilings,
        )
        self._vertex_count = count
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        if not in_paint:
            self.doneCurrent()
        elapsed = (time.perf_counter() - t0) * 1000
        self._last_rebuild_ms = elapsed
        log.debug("rebuild_mesh: %d verts, %.1f ms", count, elapsed)
        self.update()

    def paintGL(self) -> None:
        self._in_paint_gl = True
        if self._mesh_dirty:
            self.rebuild_mesh()

        t0 = time.perf_counter()

        # Re-establish GL state
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        gl.glFrontFace(gl.GL_CW)
        gl.glDisable(gl.GL_BLEND)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        gl.glClear(int(gl.GL_COLOR_BUFFER_BIT) | int(gl.GL_DEPTH_BUFFER_BIT))

        w, h = self.width(), self.height()
        aspect = w / h if h > 0 else 1.0

        proj = self.camera.projection_matrix(aspect)
        view = self.camera.view_matrix()
        vp = (view.reshape(4, 4) @ proj.reshape(4, 4)).flatten()

        # ── Scene ──
        gl.glUseProgram(self._program)
        gl.glUniformMatrix4fv(self._vp_loc, 1, gl.GL_FALSE, vp)

        self._atlas.bind(0)
        gl.glUniform1i(self._atlas_loc, 0)

        if self._wireframe:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)

        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self._vertex_count)
        gl.glBindVertexArray(0)

        if self._wireframe:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        # ── Grid ──
        if self._show_grid:
            self._draw_grid(vp)

        # ── Overlays ──
        if self._tool:
            self._draw_overlays(vp)

        # ── Crosshair (FPS mode) ──
        if self._mouse_captured:
            self._draw_crosshair()

        # ── Perf tracking ──
        frame_ms = (time.perf_counter() - t0) * 1000
        self._frame_times.append(frame_ms)
        self._in_paint_gl = False

    def _draw_grid(self, vp: np.ndarray) -> None:
        """Draw a floor-level cell grid over the zone."""
        W, H = self.zone.width, self.zone.height
        y = 0.005  # slightly above Y=0 to avoid z-fighting

        lines: list[float] = []
        # Vertical lines (X direction)
        for c in range(W + 1):
            lines.extend([float(c), y, 0.0, float(c), y, float(H)])
        # Horizontal lines (Z direction)
        for r in range(H + 1):
            lines.extend([0.0, y, float(r), float(W), y, float(r)])

        buf = np.array(lines, dtype=np.float32)
        n_verts = len(lines) // 3

        gl.glUseProgram(self._ovl_program)
        gl.glUniformMatrix4fv(self._ovl_vp_loc, 1, gl.GL_FALSE, vp)
        gl.glUniform4f(self._ovl_color_loc, 1.0, 1.0, 1.0, 0.12)

        gl.glBindVertexArray(self._ovl_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._ovl_vbo)
        needed = buf.nbytes
        if needed > self._ovl_vbo_size:
            gl.glBufferData(gl.GL_ARRAY_BUFFER, needed, buf,
                            gl.GL_DYNAMIC_DRAW)
            self._ovl_vbo_size = needed
        else:
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, needed, buf)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDrawArrays(gl.GL_LINES, 0, n_verts)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_BLEND)
        gl.glBindVertexArray(0)

    def _draw_overlays(self, vp: np.ndarray) -> None:
        """Draw tool overlay primitives with alpha blending."""
        items: list[Overlay] = self._tool.overlays() if self._tool else []
        if self.extra_overlays:
            items = items + self.extra_overlays()
        if not items:
            return

        from editor2.tools import OverlayMode

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_CULL_FACE)
        # Push overlays slightly toward camera to prevent z-fighting
        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(-1.0, -1.0)

        gl.glUseProgram(self._ovl_program)
        gl.glUniformMatrix4fv(self._ovl_vp_loc, 1, gl.GL_FALSE, vp)
        gl.glBindVertexArray(self._ovl_vao)

        _MODE_MAP = {
            OverlayMode.TRIS: gl.GL_TRIANGLES,
            OverlayMode.LINES: gl.GL_LINES,
            OverlayMode.LINE_STRIP: gl.GL_LINE_STRIP,
        }

        for ovl in items:
            n = len(ovl.verts)
            if n == 0:
                continue
            flat = []
            for v in ovl.verts:
                flat.extend(v)
            buf = np.array(flat, dtype=np.float32)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._ovl_vbo)
            # Resize VBO if needed (orphan + realloc)
            needed = buf.nbytes
            if needed > self._ovl_vbo_size:
                gl.glBufferData(gl.GL_ARRAY_BUFFER, needed, buf,
                                gl.GL_DYNAMIC_DRAW)
                self._ovl_vbo_size = needed
            else:
                gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, needed, buf)
            gl.glUniform4f(self._ovl_color_loc, *ovl.color)
            gl_mode = _MODE_MAP.get(ovl.mode, gl.GL_TRIANGLES)
            gl.glDrawArrays(gl_mode, 0, n)

        gl.glBindVertexArray(0)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glEnable(gl.GL_CULL_FACE)

    def _draw_crosshair(self) -> None:
        """Draw a small crosshair at screen centre using thin quads."""
        gl.glUseProgram(self._ovl_program)
        # Identity VP → draw in NDC directly
        identity = np.eye(4, dtype=np.float32).flatten()
        gl.glUniformMatrix4fv(self._ovl_vp_loc, 1, gl.GL_FALSE, identity)
        gl.glUniform4f(self._ovl_color_loc, 1.0, 1.0, 1.0, 0.7)

        # Crosshair arms in NDC (~12px at 1280 wide, ~2px thick)
        L = 0.015   # half-length
        T = 0.002   # half-thickness
        # Two quads (horizontal + vertical), each as 2 triangles = 12 verts
        verts = np.array([
            # horizontal bar
            -L, -T, 0,   L, -T, 0,   L,  T, 0,
            -L, -T, 0,   L,  T, 0,  -L,  T, 0,
            # vertical bar
            -T, -L, 0,   T, -L, 0,   T,  L, 0,
            -T, -L, 0,   T,  L, 0,  -T,  L, 0,
        ], dtype=np.float32)

        gl.glBindVertexArray(self._ovl_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._ovl_vbo)
        needed = verts.nbytes
        if needed > self._ovl_vbo_size:
            gl.glBufferData(gl.GL_ARRAY_BUFFER, needed, verts,
                            gl.GL_DYNAMIC_DRAW)
            self._ovl_vbo_size = needed
        else:
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, needed, verts)

        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 12)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_BLEND)
        gl.glBindVertexArray(0)

    @property
    def hud_lines(self) -> list[tuple[str, tuple[int, int, int]]]:
        return []

    @hud_lines.setter
    def hud_lines(self, v: list[tuple[str, tuple[int, int, int]]]) -> None:
        lines = [(t, c) for t, c in v if t]
        if not lines:
            self._hud_label.hide()
            return
        parts: list[str] = []
        for text, color in lines:
            r, g, b = color
            parts.append(f'<span style="color:rgb({r},{g},{b})">{text}</span>')
        self._hud_label.setText("<br>".join(parts))
        self._hud_label.adjustSize()
        self._hud_label.show()

    # ── Input ─────────────────────────────────────────────────────

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last_time, 0.05)
        self._last_time = now

        # While captured, keep tool hover locked to screen centre
        if self._mouse_captured and self._tool:
            cx = self.width() * 0.5
            cy = self.height() * 0.5
            self._tool.on_mouse_move(cx, cy, self.width(), self.height())
            if self.on_hover:
                self.on_hover()

        if not self._mouse_captured:
            return

        speed = MOVE_SPEED
        if Qt.Key.Key_Shift in self._keys:
            speed *= SPRINT_MULT

        cam = self.camera
        fx, fy, fz = cam.forward()
        rx, _, rz = cam.right()
        v = speed * dt

        if Qt.Key.Key_W in self._keys:
            cam.x += fx * v; cam.y += fy * v; cam.z += fz * v
        if Qt.Key.Key_S in self._keys:
            cam.x -= fx * v; cam.y -= fy * v; cam.z -= fz * v
        if Qt.Key.Key_A in self._keys:
            cam.x -= rx * v; cam.z -= rz * v
        if Qt.Key.Key_D in self._keys:
            cam.x += rx * v; cam.z += rz * v
        if Qt.Key.Key_Space in self._keys:
            cam.y += v
        if Qt.Key.Key_Control in self._keys or Qt.Key.Key_C in self._keys:
            cam.y -= v

        turn = 2.5 * dt
        if Qt.Key.Key_Q in self._keys or Qt.Key.Key_Left in self._keys:
            cam.yaw -= turn
        if Qt.Key.Key_E in self._keys or Qt.Key.Key_Right in self._keys:
            cam.yaw += turn

        self.update()

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        self._keys.add(key)
        if key == Qt.Key.Key_Escape:
            if self._mouse_captured:
                self._release_mouse()
            else:
                self.window().close()
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if not self._mouse_captured:
                self._capture_mouse()
        ev.accept()

    def keyReleaseEvent(self, ev) -> None:
        self._keys.discard(ev.key())
        ev.accept()

    def mousePressEvent(self, ev) -> None:
        if not self._mouse_captured:
            # Middle-click eyedropper (global, before tool)
            if ev.button() == Qt.MouseButton.MiddleButton and self.on_eyedrop:
                pos = ev.position()
                self.on_eyedrop(pos.x(), pos.y(), self.width(), self.height())
                ev.accept()
                return
            # Right-click captures mouse for FPS camera
            if ev.button() == Qt.MouseButton.RightButton:
                self._capture_mouse()
            elif self._tool:
                if ev.button() == Qt.MouseButton.LeftButton:
                    btn = 1
                elif ev.button() == Qt.MouseButton.MiddleButton:
                    btn = 3
                else:
                    btn = 2
                pos = ev.position()
                self._tool.on_mouse_press(
                    pos.x(), pos.y(), self.width(), self.height(), btn)
        else:
            cx = self.width() * 0.5
            cy = self.height() * 0.5
            if self._tool:
                if ev.button() == Qt.MouseButton.LeftButton:
                    self._tool.on_mouse_press(
                        cx, cy, self.width(), self.height(), 1)
                elif ev.button() == Qt.MouseButton.MiddleButton:
                    self._tool.on_mouse_press(
                        cx, cy, self.width(), self.height(), 3)
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if not self._mouse_captured:
            if self._tool:
                pos = ev.position()
                self._tool.on_mouse_move(
                    pos.x(), pos.y(), self.width(), self.height())
                if self.on_hover:
                    self.on_hover()
                self.update()  # repaint for overlay
            return
        centre = self.rect().center()
        dx = ev.position().x() - centre.x()
        dy = ev.position().y() - centre.y()
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return
        self.camera.yaw += dx * MOUSE_SENS
        self.camera.pitch -= dy * MOUSE_SENS
        self.camera.pitch = max(-1.4, min(1.4, self.camera.pitch))
        from PySide6.QtGui import QCursor
        QCursor.setPos(self.mapToGlobal(centre))
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if self._tool:
            btn = 1 if ev.button() == Qt.MouseButton.LeftButton else 2
            if self._mouse_captured:
                cx = self.width() * 0.5
                cy = self.height() * 0.5
                self._tool.on_mouse_release(
                    cx, cy, self.width(), self.height(), btn)
            else:
                pos = ev.position()
                self._tool.on_mouse_release(
                    pos.x(), pos.y(), self.width(), self.height(), btn)
        ev.accept()

    def wheelEvent(self, ev) -> None:
        """Scroll wheel: zoom camera forward/back when not in FPS mode.
        
        If an on_scroll callback is set and returns True, the scroll is consumed.
        """
        delta = ev.angleDelta().y()
        if delta == 0:
            ev.ignore()
            return
        # Let the main window intercept scroll (e.g. for selection raise/lower)
        if self._on_scroll is not None:
            direction = 1 if delta > 0 else -1
            if self._on_scroll(direction):
                ev.accept()
                return
        cam = self.camera
        fx, fy, fz = cam.forward()
        step = 0.5 if delta > 0 else -0.5
        cam.x += fx * step
        cam.y += fy * step
        cam.z += fz * step
        self.update()
        ev.accept()

    def focusOutEvent(self, ev) -> None:
        if self._mouse_captured:
            self._release_mouse()
        self._keys.clear()
        super().focusOutEvent(ev)

    def _capture_mouse(self) -> None:
        self._mouse_captured = True
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.grabMouse()
        self.setFocus()

    def _release_mouse(self) -> None:
        self._mouse_captured = False
        self.releaseMouse()
        self.setCursor(Qt.CursorShape.ArrowCursor)
