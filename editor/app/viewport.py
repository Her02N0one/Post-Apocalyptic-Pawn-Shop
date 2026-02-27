"""editor/app/viewport.py — ViewportMixin: GL surface rendering."""

from __future__ import annotations

import pygame
import OpenGL.GL as gl


def upload_surface(surface: pygame.Surface, tex_id: int = 0) -> int:
    """Upload a pygame Surface to an OpenGL texture.  Returns texture ID."""
    w, h = surface.get_size()
    data = pygame.image.tostring(surface, "RGBA", False)

    if tex_id == 0:
        tex_id = int(gl.glGenTextures(1))
    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
    gl.glTexImage2D(
        gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, w, h, 0,
        gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data,
    )
    return tex_id


class ViewportMixin:
    """OpenGL viewport rendering mixin for :class:`ZoneEditorApp`."""

    def _render_frame(self) -> None:
        import imgui

        win_w, win_h = self.win_size
        gl.glViewport(0, 0, win_w, win_h)
        gl.glClearColor(0.06, 0.06, 0.08, 1.0)
        gl.glClear(int(gl.GL_COLOR_BUFFER_BIT))

        # 1. Render viewport to full-window surface → fullscreen GL quad
        self._vp_size = (win_w, win_h)
        if self.zone:
            self._render_viewport()
            if self._vp_tex:
                self._draw_fullscreen_quad()

        # 2. ImGui overlay panels on top
        io = imgui.get_io()
        io.display_size = (win_w, win_h)
        self.imgui_impl.process_inputs()
        imgui.new_frame()
        self._build_ui()
        imgui.render()
        self.imgui_impl.render(imgui.get_draw_data())

    def _get_vp_surface(self, w: int, h: int) -> pygame.Surface:
        if self._vp_surface is None or self._vp_surface.get_size() != (w, h):
            self._vp_surface = pygame.Surface((w, h))
        return self._vp_surface

    def _render_viewport(self) -> None:
        vw, vh = self._vp_size
        if vw < 16 or vh < 16:
            return

        surf = self._get_vp_surface(vw, vh)

        if self.view_mode == "3d" and self.editor_3d:
            self.editor_3d.draw(surf)
        elif self.view_mode == "2d" and self.renderer:
            frame = self.renderer.render(self.px, self.py, self.angle,
                                          self.cam_h, self.pitch)
            self.renderer.render_entities(self.px, self.py, self.angle)
            scaled = pygame.transform.scale(frame, (vw, vh))
            surf.blit(scaled, (0, 0))

        self._vp_tex = upload_surface(surf, self._vp_tex)

    def _draw_fullscreen_quad(self) -> None:
        """Draw the viewport texture as a fullscreen GL quad (behind imgui)."""
        try:
            gl.glUseProgram(0)
        except Exception:
            pass

        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glOrtho(-1, 1, -1, 1, -1, 1)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()

        gl.glDisable(gl.GL_BLEND)

        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._vp_tex)
        gl.glTexEnvi(gl.GL_TEXTURE_ENV, gl.GL_TEXTURE_ENV_MODE, gl.GL_REPLACE)
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)

        gl.glBegin(gl.GL_QUADS)
        gl.glTexCoord2f(0, 1); gl.glVertex2f(-1, -1)
        gl.glTexCoord2f(1, 1); gl.glVertex2f( 1, -1)
        gl.glTexCoord2f(1, 0); gl.glVertex2f( 1,  1)
        gl.glTexCoord2f(0, 0); gl.glVertex2f(-1,  1)
        gl.glEnd()

        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPopMatrix()
