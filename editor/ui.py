"""editor/ui.py — Lightweight retained-mode widget toolkit for Pygame.

Provides reusable UI primitives: buttons, text fields, dropdowns,
checkboxes, number inputs, color pickers, and scrollable containers.

All widgets follow the same pattern:
    widget.draw(surface, font)
    result = widget.handle_event(event)

Widgets store their own rects and values.  ``UIContext`` tracks which
widget has keyboard focus.
"""

from __future__ import annotations

import pygame
from typing import Any, Callable

# ── Theme ───────────────────────────────────────────────────────────

class Theme:
    BG          = (30, 30, 34)
    PANEL       = (42, 42, 48)
    PANEL_LITE  = (58, 58, 66)
    FIELD_BG    = (22, 22, 26)
    TEXT        = (220, 220, 220)
    TEXT_DIM    = (140, 140, 150)
    ACCENT      = (80, 160, 255)
    ACCENT2     = (255, 180, 60)
    DANGER      = (255, 80, 80)
    SUCCESS     = (80, 220, 120)
    PORTAL      = (200, 60, 220)
    ANCHOR      = (60, 200, 240)
    ENTITY      = (100, 220, 160)
    GRID        = (60, 60, 66)
    HIGHLIGHT   = (70, 70, 80)
    SELECTED    = (50, 70, 100)
    BORDER      = (80, 80, 90)
    BTN_HOVER   = (65, 65, 75)
    BTN_ACTIVE  = (45, 55, 80)
    SCROLLBAR   = (70, 70, 80)
    SCROLLTHUMB = (120, 120, 135)


# ── Focus management ────────────────────────────────────────────────

class UIContext:
    """Manages keyboard focus and shared state for all widgets."""

    def __init__(self):
        self.focused_id: int | None = None
        self._next_id = 0

    def alloc_id(self) -> int:
        uid = self._next_id
        self._next_id += 1
        return uid

    def has_focus(self, uid: int) -> bool:
        return self.focused_id == uid

    def take_focus(self, uid: int):
        self.focused_id = uid

    def release_focus(self, uid: int | None = None):
        if uid is None or self.focused_id == uid:
            self.focused_id = None

    def any_focused(self) -> bool:
        return self.focused_id is not None


# ── Helper ──────────────────────────────────────────────────────────

def _clamp(v, lo, hi):
    return max(lo, min(v, hi))


def draw_text(surface: pygame.Surface, text: str, x: int, y: int,
              color=Theme.TEXT, font: pygame.font.Font | None = None):
    """Quick text draw helper."""
    if font is None:
        return
    img = font.render(str(text), True, color)
    surface.blit(img, (x, y))
    return img.get_width()


def draw_text_centered(surface: pygame.Surface, text: str,
                       rect: pygame.Rect, color=Theme.TEXT,
                       font: pygame.font.Font | None = None):
    if font is None:
        return
    img = font.render(str(text), True, color)
    x = rect.x + (rect.w - img.get_width()) // 2
    y = rect.y + (rect.h - img.get_height()) // 2
    surface.blit(img, (x, y))


# ── Button ──────────────────────────────────────────────────────────

class Button:
    def __init__(self, rect: pygame.Rect, label: str,
                 color=Theme.PANEL_LITE, text_color=Theme.TEXT,
                 hover_color=Theme.BTN_HOVER, border_color=Theme.BORDER,
                 active_color=Theme.BTN_ACTIVE, tooltip: str = ""):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color
        self.text_color = text_color
        self.hover_color = hover_color
        self.border_color = border_color
        self.active_color = active_color
        self.tooltip = tooltip
        self._hovered = False
        self._pressed = False

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        bg = self.active_color if self._pressed else (
            self.hover_color if self._hovered else self.color)
        pygame.draw.rect(surface, bg, self.rect, border_radius=4)
        pygame.draw.rect(surface, self.border_color, self.rect, 1, border_radius=4)
        draw_text_centered(surface, self.label, self.rect, self.text_color, font)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Returns True when button is clicked."""
        if event.type == pygame.MOUSEMOTION:
            self._hovered = self.rect.collidepoint(event.pos)
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._pressed = True
                return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was = self._pressed
            self._pressed = False
            if was and self.rect.collidepoint(event.pos):
                return True
        return False


# ── ToggleButton ────────────────────────────────────────────────────

class ToggleButton(Button):
    def __init__(self, rect: pygame.Rect, label: str, active: bool = False,
                 **kwargs):
        super().__init__(rect, label, **kwargs)
        self.active = active
        self.active_border = Theme.ACCENT

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        bg = self.active_color if self.active else (
            self.hover_color if self._hovered else self.color)
        pygame.draw.rect(surface, bg, self.rect, border_radius=4)
        border = self.active_border if self.active else self.border_color
        pygame.draw.rect(surface, border, self.rect, 2 if self.active else 1,
                         border_radius=4)
        draw_text_centered(surface, self.label, self.rect, self.text_color, font)

    def handle_event(self, event: pygame.event.Event) -> bool:
        clicked = super().handle_event(event)
        if clicked:
            self.active = not self.active
        return clicked


# ── TextField ───────────────────────────────────────────────────────

class TextField:
    def __init__(self, rect: pygame.Rect, ctx: UIContext,
                 value: str = "", placeholder: str = "",
                 on_change: Callable[[str], None] | None = None,
                 on_submit: Callable[[str], None] | None = None):
        self.rect = pygame.Rect(rect)
        self.uid = ctx.alloc_id()
        self.ctx = ctx
        self.value = value
        self.placeholder = placeholder
        self.on_change = on_change
        self.on_submit = on_submit
        self._cursor_pos = len(value)
        self._cursor_blink = 0.0

    @property
    def focused(self) -> bool:
        return self.ctx.has_focus(self.uid)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             dt: float = 0.016):
        bg = Theme.FIELD_BG
        border = Theme.ACCENT if self.focused else Theme.BORDER
        pygame.draw.rect(surface, bg, self.rect, border_radius=3)
        pygame.draw.rect(surface, border, self.rect, 1, border_radius=3)

        text = self.value if self.value else self.placeholder
        color = Theme.TEXT if self.value else Theme.TEXT_DIM
        clip = self.rect.inflate(-8, -4)

        # Simple text rendering — clip to field
        img = font.render(text, True, color)
        area = pygame.Rect(0, 0, clip.w, img.get_height())
        # Scroll if text wider than field
        if self.focused:
            cursor_x = font.size(self.value[:self._cursor_pos])[0]
            if cursor_x > clip.w - 8:
                area.x = cursor_x - clip.w + 8
        surface.blit(img, (clip.x, clip.y + (clip.h - img.get_height()) // 2),
                     area)

        # Cursor
        if self.focused:
            self._cursor_blink += dt
            if int(self._cursor_blink * 2) % 2 == 0:
                cx = clip.x + font.size(self.value[:self._cursor_pos])[0] - area.x
                cy = clip.y + 2
                pygame.draw.line(surface, Theme.TEXT, (cx, cy),
                                 (cx, cy + clip.h - 4), 1)

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Returns True when value changes."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.ctx.take_focus(self.uid)
                self._cursor_blink = 0.0
                return False
            elif self.focused:
                self.ctx.release_focus(self.uid)
                return False

        if not self.focused:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                if self.on_submit:
                    self.on_submit(self.value)
                self.ctx.release_focus(self.uid)
                return True
            elif event.key == pygame.K_ESCAPE:
                self.ctx.release_focus(self.uid)
                return False
            elif event.key == pygame.K_BACKSPACE:
                if self._cursor_pos > 0:
                    self.value = (self.value[:self._cursor_pos - 1]
                                  + self.value[self._cursor_pos:])
                    self._cursor_pos -= 1
                    if self.on_change:
                        self.on_change(self.value)
                    return True
            elif event.key == pygame.K_DELETE:
                if self._cursor_pos < len(self.value):
                    self.value = (self.value[:self._cursor_pos]
                                  + self.value[self._cursor_pos + 1:])
                    if self.on_change:
                        self.on_change(self.value)
                    return True
            elif event.key == pygame.K_LEFT:
                self._cursor_pos = max(0, self._cursor_pos - 1)
            elif event.key == pygame.K_RIGHT:
                self._cursor_pos = min(len(self.value), self._cursor_pos + 1)
            elif event.key == pygame.K_HOME:
                self._cursor_pos = 0
            elif event.key == pygame.K_END:
                self._cursor_pos = len(self.value)
            elif event.key == pygame.K_a and event.mod & pygame.KMOD_CTRL:
                self._cursor_pos = len(self.value)
            else:
                ch = event.unicode
                if ch and ch.isprintable():
                    self.value = (self.value[:self._cursor_pos] + ch
                                  + self.value[self._cursor_pos:])
                    self._cursor_pos += 1
                    if self.on_change:
                        self.on_change(self.value)
                    return True
        return False


# ── NumberField ─────────────────────────────────────────────────────

class NumberField:
    def __init__(self, rect: pygame.Rect, ctx: UIContext,
                 value: float = 0.0, min_val: float = -9999,
                 max_val: float = 9999, step: float = 1.0,
                 decimals: int = 1, is_int: bool = False,
                 on_change: Callable[[float], None] | None = None):
        self.rect = pygame.Rect(rect)
        self.ctx = ctx
        self.value = value
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.decimals = decimals
        self.is_int = is_int
        self.on_change = on_change
        fmt = f"{int(value)}" if is_int else f"{value:.{decimals}f}"
        self._text = TextField(
            pygame.Rect(rect.x, rect.y, rect.w - 40, rect.h),
            ctx, value=fmt)
        self._btn_up = pygame.Rect(rect.right - 38, rect.y, 18, rect.h)
        self._btn_dn = pygame.Rect(rect.right - 18, rect.y, 18, rect.h)

    def _format(self):
        if self.is_int:
            return str(int(self.value))
        return f"{self.value:.{self.decimals}f}"

    def _apply_text(self):
        try:
            v = float(self._text.value)
            self.value = _clamp(v, self.min_val, self.max_val)
            if self.on_change:
                self.on_change(self.value)
        except ValueError:
            pass
        self._text.value = self._format()
        self._text._cursor_pos = len(self._text.value)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             dt: float = 0.016):
        self._text.draw(surface, font, dt)
        # Up/Down buttons
        for btn_rect, label in [(self._btn_up, "+"), (self._btn_dn, "-")]:
            hov = btn_rect.collidepoint(pygame.mouse.get_pos())
            bg = Theme.BTN_HOVER if hov else Theme.PANEL_LITE
            pygame.draw.rect(surface, bg, btn_rect, border_radius=2)
            pygame.draw.rect(surface, Theme.BORDER, btn_rect, 1, border_radius=2)
            draw_text_centered(surface, label, btn_rect, Theme.TEXT, font)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if self._text.handle_event(event):
            self._apply_text()
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._btn_up.collidepoint(event.pos):
                self.value = _clamp(self.value + self.step,
                                    self.min_val, self.max_val)
                self._text.value = self._format()
                self._text._cursor_pos = len(self._text.value)
                if self.on_change:
                    self.on_change(self.value)
                return True
            if self._btn_dn.collidepoint(event.pos):
                self.value = _clamp(self.value - self.step,
                                    self.min_val, self.max_val)
                self._text.value = self._format()
                self._text._cursor_pos = len(self._text.value)
                if self.on_change:
                    self.on_change(self.value)
                return True
        return False

    def set_value(self, v: float):
        self.value = _clamp(v, self.min_val, self.max_val)
        self._text.value = self._format()
        self._text._cursor_pos = len(self._text.value)


# ── Checkbox ────────────────────────────────────────────────────────

class Checkbox:
    def __init__(self, rect: pygame.Rect, label: str, checked: bool = False,
                 on_change: Callable[[bool], None] | None = None):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.checked = checked
        self.on_change = on_change

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        from editor.layout import Layout
        sz = max(12, Layout.s(14))
        box = pygame.Rect(self.rect.x, self.rect.y + Layout.pad_sm,
                          sz, sz)
        br = max(1, Layout.border_r - 1)
        pygame.draw.rect(surface, Theme.FIELD_BG, box, border_radius=br)
        pygame.draw.rect(surface, Theme.BORDER, box, 1, border_radius=br)
        if self.checked:
            inner = box.inflate(-6, -6)
            pygame.draw.rect(surface, Theme.ACCENT, inner, border_radius=1)
        draw_text(surface, self.label, box.right + Layout.pad_md,
                  self.rect.y + Layout.pad_sm, Theme.TEXT, font)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.checked = not self.checked
                if self.on_change:
                    self.on_change(self.checked)
                return True
        return False


# ── Dropdown ────────────────────────────────────────────────────────

class Dropdown:
    def __init__(self, rect: pygame.Rect, options: list[str],
                 selected: int = 0,
                 on_change: Callable[[int, str], None] | None = None):
        self.rect = pygame.Rect(rect)
        self.options = options
        self.selected = selected
        self.on_change = on_change
        self._open = False
        self._hovered_idx = -1

    @property
    def value(self) -> str:
        if 0 <= self.selected < len(self.options):
            return self.options[self.selected]
        return ""

    def draw(self, surface: pygame.Surface, font: pygame.font.Font):
        # Main button
        hov = self.rect.collidepoint(pygame.mouse.get_pos())
        bg = Theme.BTN_HOVER if hov or self._open else Theme.PANEL_LITE
        pygame.draw.rect(surface, bg, self.rect, border_radius=3)
        pygame.draw.rect(surface, Theme.ACCENT if self._open else Theme.BORDER,
                         self.rect, 1, border_radius=3)
        from editor.layout import Layout
        txt = self.value if self.value else "(none)"
        fh = font.get_height()
        ty = self.rect.y + max(1, (self.rect.h - fh) // 2)
        draw_text(surface, txt, self.rect.x + Layout.pad_md, ty,
                  Theme.TEXT, font)
        # Arrow
        ax = self.rect.right - 14
        ay = self.rect.centery
        pygame.draw.polygon(surface, Theme.TEXT_DIM,
                            [(ax - 4, ay - 2), (ax + 4, ay - 2), (ax, ay + 4)])

    def draw_dropdown(self, surface: pygame.Surface, font: pygame.font.Font):
        """Draw the dropdown list (call AFTER other widgets)."""
        if not self._open or not self.options:
            return
        from editor.layout import Layout
        item_h = Layout.item_h
        total_h = min(len(self.options), 8) * item_h
        br = Layout.border_r
        dr = pygame.Rect(self.rect.x, self.rect.bottom + 2,
                         self.rect.w, total_h)
        pygame.draw.rect(surface, Theme.PANEL, dr, border_radius=br)
        pygame.draw.rect(surface, Theme.BORDER, dr, 1, border_radius=br)

        fh = font.get_height()
        text_y_off = max(1, (item_h - fh) // 2)
        mx, my = pygame.mouse.get_pos()
        for i, opt in enumerate(self.options[:8]):
            iy = dr.y + i * item_h
            ir = pygame.Rect(dr.x + 2, iy, dr.w - 4, item_h)
            is_hov = ir.collidepoint(mx, my)
            is_sel = (i == self.selected)
            if is_hov:
                pygame.draw.rect(surface, Theme.HIGHLIGHT, ir, border_radius=2)
            elif is_sel:
                pygame.draw.rect(surface, Theme.SELECTED, ir, border_radius=2)
            color = Theme.ACCENT if is_sel else Theme.TEXT
            draw_text(surface, opt, ir.x + Layout.pad_md,
                      ir.y + text_y_off, color, font)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._open:
                from editor.layout import Layout
                item_h = Layout.item_h
                dr = pygame.Rect(self.rect.x, self.rect.bottom + 2,
                                 self.rect.w,
                                 min(len(self.options), 8) * item_h)
                if dr.collidepoint(event.pos):
                    idx = (event.pos[1] - dr.y) // item_h
                    if 0 <= idx < len(self.options):
                        self.selected = idx
                        self._open = False
                        if self.on_change:
                            self.on_change(idx, self.options[idx])
                        return True
                self._open = False
                return False
            elif self.rect.collidepoint(event.pos):
                self._open = True
                return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self._open:
                self._open = False
                return True
        return False

    @property
    def is_open(self) -> bool:
        return self._open


# ── ColorField ──────────────────────────────────────────────────────

class ColorField:
    """Three number fields (R, G, B) with a color preview swatch."""

    def __init__(self, rect: pygame.Rect, ctx: UIContext,
                 color: tuple[int, int, int] = (200, 200, 200),
                 on_change: Callable[[tuple[int, int, int]], None] | None = None):
        self.rect = pygame.Rect(rect)
        self.ctx = ctx
        self.color = color
        self.on_change = on_change
        w_each = (rect.w - 30) // 3
        self._r = NumberField(
            pygame.Rect(rect.x + 20, rect.y, w_each, rect.h), ctx,
            value=color[0], min_val=0, max_val=255, step=5, is_int=True)
        self._g = NumberField(
            pygame.Rect(rect.x + 22 + w_each, rect.y, w_each, rect.h), ctx,
            value=color[1], min_val=0, max_val=255, step=5, is_int=True)
        self._b = NumberField(
            pygame.Rect(rect.x + 24 + 2 * w_each, rect.y, w_each, rect.h),
            ctx, value=color[2], min_val=0, max_val=255, step=5, is_int=True)

    def draw(self, surface: pygame.Surface, font: pygame.font.Font,
             dt: float = 0.016):
        # Swatch
        sw = pygame.Rect(self.rect.x, self.rect.y + 2, 16, self.rect.h - 4)
        pygame.draw.rect(surface, self.color, sw, border_radius=2)
        pygame.draw.rect(surface, Theme.BORDER, sw, 1, border_radius=2)
        self._r.draw(surface, font, dt)
        self._g.draw(surface, font, dt)
        self._b.draw(surface, font, dt)

    def handle_event(self, event: pygame.event.Event) -> bool:
        changed = False
        if self._r.handle_event(event):
            changed = True
        if self._g.handle_event(event):
            changed = True
        if self._b.handle_event(event):
            changed = True
        if changed:
            self.color = (int(self._r.value), int(self._g.value),
                          int(self._b.value))
            if self.on_change:
                self.on_change(self.color)
        return changed

    def set_color(self, c: tuple[int, int, int]):
        self.color = c
        self._r.set_value(c[0])
        self._g.set_value(c[1])
        self._b.set_value(c[2])


# ── ScrollPanel ─────────────────────────────────────────────────────

class ScrollPanel:
    """A scrollable vertical region. Content is drawn via a callback."""

    def __init__(self, rect: pygame.Rect, content_height: int = 0):
        self.rect = pygame.Rect(rect)
        self.content_height = content_height
        self.scroll_y: float = 0.0
        self._dragging_thumb = False
        self._drag_offset = 0

    @property
    def max_scroll(self) -> float:
        return max(0, self.content_height - self.rect.h)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_y = _clamp(
                    self.scroll_y - event.y * 30, 0, self.max_scroll)
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            thumb = self._thumb_rect()
            if thumb and thumb.collidepoint(event.pos):
                self._dragging_thumb = True
                self._drag_offset = event.pos[1] - thumb.y
                return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging_thumb = False
        if event.type == pygame.MOUSEMOTION and self._dragging_thumb:
            track = self.rect.h
            thumb_h = self._thumb_height()
            track_range = track - thumb_h
            if track_range > 0:
                rel = (event.pos[1] - self._drag_offset - self.rect.y) / track_range
                self.scroll_y = _clamp(rel * self.max_scroll, 0, self.max_scroll)
            return True
        return False

    def _thumb_height(self) -> int:
        if self.content_height <= self.rect.h:
            return self.rect.h
        return max(20, int(self.rect.h * self.rect.h / self.content_height))

    def _thumb_rect(self) -> pygame.Rect | None:
        if self.content_height <= self.rect.h:
            return None
        th = self._thumb_height()
        track = self.rect.h - th
        if self.max_scroll > 0:
            y = self.rect.y + int(track * self.scroll_y / self.max_scroll)
        else:
            y = self.rect.y
        return pygame.Rect(self.rect.right - 8, y, 8, th)

    def draw_scrollbar(self, surface: pygame.Surface):
        if self.content_height <= self.rect.h:
            return
        # Track
        track = pygame.Rect(self.rect.right - 8, self.rect.y, 8, self.rect.h)
        pygame.draw.rect(surface, Theme.SCROLLBAR, track, border_radius=4)
        # Thumb
        thumb = self._thumb_rect()
        if thumb:
            pygame.draw.rect(surface, Theme.SCROLLTHUMB, thumb, border_radius=4)

    def begin_clip(self, surface: pygame.Surface):
        surface.set_clip(self.rect)

    def end_clip(self, surface: pygame.Surface):
        surface.set_clip(None)


# ── Convenience: section header ─────────────────────────────────────

def draw_section_header(surface: pygame.Surface, text: str,
                        x: int, y: int, width: int,
                        font: pygame.font.Font):
    """Draw a labeled divider for inspector sections.

    Layout:  ``text``  at *y*, horizontal rule below at ``y + fh + gap``.
    Returns the y position after the header (ready for the next widget).
    """
    from editor.layout import Layout
    fh = font.get_height()
    gap = max(2, Layout.pad_sm)
    # Text sits at the top; line underneath
    tw = draw_text(surface, text, x + Layout.pad_sm, y, Theme.ACCENT, font) or 0
    line_y = y + fh + gap
    pygame.draw.line(surface, Theme.BORDER, (x, line_y),
                     (x + width, line_y), 1)
    return line_y + gap


# ── KeyValue row ────────────────────────────────────────────────────

def draw_label(surface: pygame.Surface, label: str,
               x: int, y: int, font: pygame.font.Font, width: int = 80):
    """Draw a dim label at *(x, y)*.  Vertically offset by ``pad_sm``."""
    from editor.layout import Layout
    draw_text(surface, label, x, y + Layout.pad_sm, Theme.TEXT_DIM, font)


# ── Panel rendering helpers ─────────────────────────────────────────

def draw_panel_bg(surface: pygame.Surface, left: int, top: int,
                  pw: int, panel_h: int):
    """Draw the standard semi-transparent panel background + right border."""
    panel_surf = pygame.Surface((pw, panel_h), pygame.SRCALPHA)
    panel_surf.fill((*Theme.PANEL, 230))
    surface.blit(panel_surf, (left, top))
    pygame.draw.line(surface, Theme.BORDER,
                     (left + pw - 1, top),
                     (left + pw - 1, top + panel_h))


def draw_item_row(surface: pygame.Surface, rect: pygame.Rect, *,
                  hovered: bool = False, selected: bool = False,
                  border: bool = False, accent_border: bool = False,
                  br: int = 0):
    """Draw a standard list-item background.

    *selected* — ``Theme.SELECTED`` fill; optionally an ``ACCENT`` outline
    if *accent_border* is set.
    *hovered*  — ``Theme.HIGHLIGHT`` fill.
    *border*   — always draw a ``Theme.BORDER`` outline (e.g. portal rows).
    """
    if selected:
        pygame.draw.rect(surface, Theme.SELECTED, rect, border_radius=br)
        if accent_border:
            pygame.draw.rect(surface, Theme.ACCENT, rect, 1, border_radius=br)
    elif hovered:
        pygame.draw.rect(surface, Theme.HIGHLIGHT, rect, border_radius=br)
    if border:
        pygame.draw.rect(surface, Theme.BORDER, rect, 1, border_radius=br)


def draw_empty_hint(surface: pygame.Surface, lines: list[str],
                    x: int, y: int, font: pygame.font.Font) -> int:
    """Draw greyed-out placeholder text for an empty list.

    Returns the y position after the last line.
    """
    fh = font.get_height()
    for line in lines:
        draw_text(surface, line, x, y, Theme.TEXT_DIM, font)
        y += fh + 2
    return y


def clamp_scroll(scroll_y: float, total_h: float,
                 visible_h: float) -> float:
    """Clamp scroll offset so content cannot scroll past the end."""
    max_scroll = max(0.0, total_h - visible_h)
    return min(scroll_y, max_scroll)


def two_line_offsets(item_h: int, font_h: int,
                     gap: int = 2) -> tuple[int, int]:
    """Return ``(line1_y_offset, line2_y_offset)`` for a two-line list item.

    Offsets are relative to the item-rect top.  Text is vertically centred
    within ``item_h - 2`` pixels (leaving a 2 px row gap at the bottom).
    The second offset is clamped so that text never extends below the row.
    """
    usable = item_h - 2
    block = font_h * 2 + gap
    top_pad = max(1, (usable - block) // 2)
    return top_pad, min(top_pad + font_h + gap, max(0, usable - font_h))


def draw_scrollbar(surface: pygame.Surface, x: int, top: int,
                   height: int, total_h: float, scroll_y: float,
                   bar_w: int = 4, br: int = 2):
    """Draw a thin scrollbar track + thumb.

    Does nothing when *total_h* fits within *height*.
    """
    if total_h <= height or height <= 0:
        return
    thumb_h = max(16, int(height * height / max(1, total_h)))
    thumb_y = top + int(scroll_y / max(1, total_h) * height)
    thumb_y = min(thumb_y, top + height - thumb_h)
    pygame.draw.rect(surface, Theme.SCROLLBAR,
                     (x, top, bar_w, height), border_radius=br)
    pygame.draw.rect(surface, Theme.SCROLLTHUMB,
                     (x, thumb_y, bar_w, thumb_h), border_radius=br)
