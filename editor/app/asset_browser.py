"""editor/app/asset_browser.py — Texture browser panel for zone editor.

Provides a floating ImGui window to browse, preview, and manage
texture files (tiles, skyboxes, billboards) from the project's
``assets/`` directory tree.

Exposed as :class:`AssetBrowserMixin` which is mixed into the
:class:`ZoneEditorApp`.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import imgui
import pygame
import OpenGL.GL as gl

from core.paths import (
    ASSETS_DIR,
    TEXTURES_DIR,
    TILE_TEX_DIR,
    SKYBOXES_DIR,
    BILLBOARDS_DIR,
)

# Image extensions recognised by the browser.
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga"}

# Maximum thumbnail dimension uploaded to GL.
_THUMB_SIZE = 64

# ── Asset category definitions ────────────────────────────────────

ASSET_CATEGORIES = (
    ("Tiles",      TILE_TEX_DIR),
    ("Skyboxes",   SKYBOXES_DIR),
    ("Billboards", BILLBOARDS_DIR),
    ("Other",      TEXTURES_DIR),
)


def _list_images(directory: Path) -> list[Path]:
    """Return sorted image file paths in *directory* (non-recursive)."""
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _IMG_EXTS
    )


class AssetBrowserMixin:
    """Floating texture browser window for the zone editor."""

    # ── State ─────────────────────────────────────────────────────

    show_texture_browser: bool = False

    # Immutable class defaults (scalars are fine as class attrs)
    _ab_cat_idx: int = 0
    _ab_selected: str = ""
    _ab_import_path: str = ""
    _ab_refresh: int = 0

    def _ab_init(self) -> None:
        """Initialise mutable asset-browser state (call from __init__)."""
        # Thumbnail GL texture cache:  path → (gl_tex_id, w, h)
        self._ab_thumb_cache: dict[str, tuple[int, int, int]] = {}
        # Cached directory listing:  (cat_idx, refresh_id) → list[Path]
        self._ab_dir_cache: dict[tuple[int, int], list[Path]] = {}

    # ── Thumbnail helpers ─────────────────────────────────────────

    @staticmethod
    def _ab_upload_thumbnail(path: Path) -> tuple[int, int, int]:
        """Load *path* as a pygame Surface, upload to GL, return (tex_id, w, h)."""
        try:
            surf = pygame.image.load(str(path))
        except Exception:
            # Unloadable image — return a 1×1 magenta placeholder.
            logging.getLogger(__name__).debug("Cannot load thumbnail: %s", path)
            tex_id = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexImage2D(
                gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 1, 1, 0,
                gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, b"\xff\x00\xff\xff",
            )
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            return tex_id, 1, 1

        # Scale to thumbnail size while preserving aspect ratio.
        ow, oh = surf.get_size()
        scale = min(_THUMB_SIZE / ow, _THUMB_SIZE / oh, 1.0)
        tw, th = max(1, int(ow * scale)), max(1, int(oh * scale))
        thumb = pygame.transform.smoothscale(surf, (tw, th))
        thumb = thumb.convert_alpha()

        # Upload to GL texture.
        raw = pygame.image.tobytes(thumb, "RGBA", False)
        tex_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, tw, th, 0,
            gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, raw,
        )
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        return tex_id, tw, th

    def _ab_get_thumb(self, path: Path) -> tuple[int, int, int]:
        """Cached thumbnail texture.  Returns ``(gl_tex_id, w, h)``."""
        key = str(path)
        if key not in self._ab_thumb_cache:
            self._ab_thumb_cache[key] = self._ab_upload_thumbnail(path)
        return self._ab_thumb_cache[key]

    def _ab_invalidate_thumbs(self) -> None:
        """Delete all cached GL textures and force rescan."""
        for tex_id, _, _ in self._ab_thumb_cache.values():
            try:
                gl.glDeleteTextures([tex_id])
            except Exception:
                logging.getLogger(__name__).debug("GL texture cleanup failed", exc_info=True)
        self._ab_thumb_cache.clear()
        self._ab_dir_cache.clear()
        self._ab_refresh += 1

    # ── Directory listing (cached) ────────────────────────────────

    def _ab_list_files(self, cat_idx: int) -> list[Path]:
        """Return image files for the given category, cached per refresh."""
        key = (cat_idx, self._ab_refresh)
        if key not in self._ab_dir_cache:
            _, directory = ASSET_CATEGORIES[cat_idx]
            files = _list_images(directory)
            # For "Other" category, exclude files that belong to sub-categories.
            if cat_idx == len(ASSET_CATEGORIES) - 1:
                sub_dirs = {d for _, d in ASSET_CATEGORIES[:-1]}
                files = [f for f in files if f.parent.resolve() not in
                         {d.resolve() for d in sub_dirs}]
            self._ab_dir_cache[key] = files
        return self._ab_dir_cache[key]

    # ── Main draw entry point ─────────────────────────────────────

    def _draw_texture_browser(self) -> None:
        """Draw the floating texture browser window."""
        if not self.show_texture_browser:
            return

        win_w, win_h = self.win_size
        imgui.set_next_window_size(520, 420, imgui.ONCE)
        imgui.set_next_window_position(
            win_w * 0.5 - 260, win_h * 0.5 - 210, imgui.ONCE)

        expanded, opened = imgui.begin("Texture Browser", True)
        if not opened:
            self.show_texture_browser = False
            imgui.end()
            return

        # ── Category tabs ─────────────────────────────────────────
        for ci, (cat_name, _) in enumerate(ASSET_CATEGORIES):
            if ci > 0:
                imgui.same_line()
            is_active_cat = ci == self._ab_cat_idx
            if is_active_cat:
                imgui.push_style_color(imgui.COLOR_BUTTON, 0.25, 0.45, 0.65, 1.0)
                imgui.push_style_color(
                    imgui.COLOR_BUTTON_HOVERED, 0.30, 0.55, 0.75, 1.0)
            if imgui.button(f"{cat_name}##abcat{ci}"):
                self._ab_cat_idx = ci
                self._ab_selected = ""
            if is_active_cat:
                imgui.pop_style_color(2)

        imgui.same_line(imgui.get_window_width() - 80)
        if imgui.button("\u21bb Refresh##abrefresh"):
            self._ab_invalidate_thumbs()

        imgui.separator()

        # ── File grid ─────────────────────────────────────────────
        files = self._ab_list_files(self._ab_cat_idx)
        cat_name, cat_dir = ASSET_CATEGORIES[self._ab_cat_idx]

        if not files:
            imgui.text_colored(
                f"No images in {cat_dir.relative_to(ASSETS_DIR.parent)}",
                0.5, 0.5, 0.5, 1.0)
        else:
            # Compute grid columns.
            avail_w = imgui.get_content_region_available()[0]
            cell_size = _THUMB_SIZE + 12  # thumb + padding
            cols = max(1, int(avail_w / cell_size))

            grid_h = max(180, imgui.get_content_region_available()[1] - 100)
            imgui.begin_child("##ab_grid", 0, grid_h, border=True)

            for fi, fpath in enumerate(files):
                if fi % cols != 0:
                    imgui.same_line()

                is_sel = str(fpath) == self._ab_selected
                tex_id, tw, th = self._ab_get_thumb(fpath)

                # Draw thumbnail button.
                if is_sel:
                    imgui.push_style_color(
                        imgui.COLOR_BUTTON, 0.35, 0.55, 0.75, 1.0)
                    imgui.push_style_color(
                        imgui.COLOR_BUTTON_HOVERED, 0.40, 0.60, 0.80, 1.0)

                imgui.push_id(f"abt_{fi}")
                # ImGui.image_button:  (texture_id, width, height)
                if imgui.image_button(tex_id, _THUMB_SIZE, _THUMB_SIZE):
                    self._ab_selected = str(fpath)
                imgui.pop_id()

                if is_sel:
                    imgui.pop_style_color(2)

                # Tooltip on hover.
                if imgui.is_item_hovered():
                    imgui.begin_tooltip()
                    imgui.text(fpath.name)
                    imgui.text_disabled(f"{tw}x{th} px")
                    imgui.end_tooltip()

            imgui.end_child()

        # ── Detail / actions bar ──────────────────────────────────
        imgui.separator()

        if self._ab_selected:
            sel_path = Path(self._ab_selected)
            imgui.text_colored(sel_path.name, 0.9, 0.85, 0.6, 1.0)
            imgui.same_line()
            imgui.text_disabled(
                str(sel_path.relative_to(ASSETS_DIR.parent)))

            imgui.same_line(imgui.get_window_width() - 150)

            # Apply as skybox (only for Skyboxes category)
            if self._ab_cat_idx == 1 and self.zone:  # Skyboxes
                if imgui.button("Apply Skybox##ab_apply_sky"):
                    self.zone.skybox = sel_path.name
                    self.dirty = True
                imgui.same_line()

            # Delete button.
            imgui.push_style_color(imgui.COLOR_BUTTON, 0.65, 0.15, 0.15, 0.9)
            imgui.push_style_color(
                imgui.COLOR_BUTTON_HOVERED, 0.80, 0.25, 0.25, 1.0)
            if imgui.button("\u2716 Delete##ab_del"):
                try:
                    sel_path.unlink()
                    self._ab_selected = ""
                    self._ab_invalidate_thumbs()
                except Exception:
                    logging.getLogger(__name__).warning("Failed to delete %s", sel_path, exc_info=True)
            imgui.pop_style_color(2)

        else:
            imgui.text_disabled("Select a file to see details")

        # ── Import bar ────────────────────────────────────────────
        imgui.spacing()
        imgui.text_disabled("Import:")
        imgui.same_line()
        _, self._ab_import_path = imgui.input_text(
            "##ab_import", self._ab_import_path, 512)
        imgui.same_line()
        if imgui.button("Import##ab_do_import"):
            self._ab_do_import()

        imgui.end()

    # ── Import logic ──────────────────────────────────────────────

    def _ab_do_import(self) -> None:
        """Copy the file at ``_ab_import_path`` into the current category dir."""
        src = Path(self._ab_import_path.strip())
        if not src.exists():
            return
        if src.suffix.lower() not in _IMG_EXTS:
            return

        _, dest_dir = ASSET_CATEGORIES[self._ab_cat_idx]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        # Avoid overwrite — append suffix.
        n = 1
        while dest.exists():
            dest = dest_dir / f"{src.stem}_{n}{src.suffix}"
            n += 1

        try:
            shutil.copy2(str(src), str(dest))
        except Exception:
            logging.getLogger(__name__).warning("Import failed: %s", src, exc_info=True)
            return

        self._ab_import_path = ""
        self._ab_invalidate_thumbs()
        self._ab_selected = str(dest)
