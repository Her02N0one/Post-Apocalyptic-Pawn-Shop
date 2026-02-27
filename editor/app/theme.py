"""editor/app/theme.py — ImGui dark theme for the zone editor."""

from __future__ import annotations

import imgui


def setup_theme() -> None:
    """Apply the zone-editor dark theme to the current ImGui context."""
    style = imgui.get_style()
    style.window_rounding = 6.0
    style.frame_rounding = 4.0
    style.scrollbar_rounding = 6.0
    style.grab_rounding = 4.0
    style.tab_rounding = 4.0
    style.window_border_size = 1.0
    style.frame_border_size = 0.0
    style.window_padding = (10, 8)
    style.frame_padding = (6, 4)
    style.item_spacing = (8, 5)
    style.item_inner_spacing = (6, 4)
    style.scrollbar_size = 12.0
    imgui.style_colors_dark(style)
    c = style.colors
    # Panel backgrounds
    c[imgui.COLOR_WINDOW_BACKGROUND]           = (0.08, 0.08, 0.10, 0.95)
    c[imgui.COLOR_CHILD_BACKGROUND]            = (0.06, 0.06, 0.08, 1.00)
    c[imgui.COLOR_BORDER]                      = (0.20, 0.22, 0.28, 0.45)
    # Input frames
    c[imgui.COLOR_FRAME_BACKGROUND]            = (0.12, 0.12, 0.16, 1.00)
    c[imgui.COLOR_FRAME_BACKGROUND_HOVERED]    = (0.18, 0.18, 0.24, 1.00)
    c[imgui.COLOR_FRAME_BACKGROUND_ACTIVE]     = (0.25, 0.25, 0.32, 1.00)
    # Title bars
    c[imgui.COLOR_TITLE_BACKGROUND]            = (0.08, 0.08, 0.10, 1.00)
    c[imgui.COLOR_TITLE_BACKGROUND_ACTIVE]     = (0.12, 0.14, 0.18, 1.00)
    # Buttons — warm accent
    c[imgui.COLOR_BUTTON]                      = (0.18, 0.17, 0.22, 1.00)
    c[imgui.COLOR_BUTTON_HOVERED]              = (0.28, 0.26, 0.34, 1.00)
    c[imgui.COLOR_BUTTON_ACTIVE]               = (0.35, 0.32, 0.42, 1.00)
    # Headers / collapsing sections — tinted blue
    c[imgui.COLOR_HEADER]                      = (0.14, 0.16, 0.24, 1.00)
    c[imgui.COLOR_HEADER_HOVERED]              = (0.20, 0.24, 0.36, 1.00)
    c[imgui.COLOR_HEADER_ACTIVE]               = (0.26, 0.30, 0.44, 1.00)
    # Separator
    c[imgui.COLOR_SEPARATOR]                   = (0.24, 0.26, 0.34, 0.80)
    # Scrollbar
    c[imgui.COLOR_SCROLLBAR_BACKGROUND]        = (0.05, 0.05, 0.07, 1.00)
    c[imgui.COLOR_SCROLLBAR_GRAB]              = (0.24, 0.24, 0.32, 1.00)
    c[imgui.COLOR_SCROLLBAR_GRAB_HOVERED]      = (0.34, 0.34, 0.42, 1.00)
    c[imgui.COLOR_SCROLLBAR_GRAB_ACTIVE]       = (0.42, 0.42, 0.52, 1.00)
    # Tabs
    c[imgui.COLOR_TAB]                         = (0.12, 0.14, 0.18, 1.00)
    c[imgui.COLOR_TAB_HOVERED]                 = (0.22, 0.26, 0.36, 1.00)
    # Widgets
    c[imgui.COLOR_CHECK_MARK]                  = (0.40, 0.75, 1.00, 1.00)
    c[imgui.COLOR_SLIDER_GRAB]                 = (0.40, 0.60, 0.95, 1.00)
    c[imgui.COLOR_SLIDER_GRAB_ACTIVE]          = (0.50, 0.70, 1.00, 1.00)
    # Menu bar
    c[imgui.COLOR_MENUBAR_BACKGROUND]          = (0.10, 0.10, 0.13, 1.00)
    c[imgui.COLOR_POPUP_BACKGROUND]            = (0.09, 0.09, 0.12, 0.97)
    # Text
    c[imgui.COLOR_TEXT]                         = (0.92, 0.92, 0.94, 1.00)
    c[imgui.COLOR_TEXT_DISABLED]                = (0.42, 0.42, 0.48, 1.00)
    # Selection highlight
    c[imgui.COLOR_HEADER]                      = (0.18, 0.22, 0.35, 0.70)
