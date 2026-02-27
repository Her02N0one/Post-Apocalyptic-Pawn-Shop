"""editor.app — Zone editor application package.

Decomposes the monolithic zone_editor into focused modules:

  constants.py        -- window/panel/raycaster configuration
  theme.py            -- imgui dark theme colours
  events.py           -- EventsMixin: input routing, escape chains
  viewport.py         -- ViewportMixin: GL quad, surface upload
  raycaster.py        -- RaycasterMixin: 2D preview camera/movement
  panels.py           -- PanelsMixin: toolbox, inspector, status bar
  dialogs.py          -- DialogsMixin: new zone, save-as, unsaved guard
  app.py              -- ZoneEditorApp: init, run loop, zone management
"""

from editor.app.app import ZoneEditorApp  # noqa: F401

__all__ = ["ZoneEditorApp"]
