"""editor/panels.py — Backward-compatible shim.

All panel classes have been split into ``editor/panels_pkg/`` for cleaner
separation of concerns.  This file re-exports every public name so
existing ``from editor.panels import …`` statements work unmodified.
"""

from editor.panels_pkg import (       # noqa: F401
    MenuBar,
    ZoneNav,
    TilePalette,
    ZonePanel,
    EntityPanel,
    TextureBrowserPanel,
    PortalPanel,
    RoomTemplatePanel,
    Minimap,
    StatusBar,
    PanelSplitter,
    Sidebar,
    Toolbar,
)
