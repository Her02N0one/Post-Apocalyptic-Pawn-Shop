"""editor/panels_pkg — Split panel modules.

Re-exports every public class so existing ``from editor.panels import …``
statements continue to work unchanged.
"""

from editor.panels_pkg.base import PanelBase, PanelRegion  # noqa: F401
from editor.panels_pkg.chrome import EditorChrome          # noqa: F401
from editor.panels_pkg.menu_bar import MenuBar          # noqa: F401
from editor.panels_pkg.zone_nav import ZoneNav          # noqa: F401
from editor.panels_pkg.tile_palette import TilePalette  # noqa: F401
from editor.panels_pkg.zone_panel import ZonePanel      # noqa: F401
from editor.panels_pkg.entity_panel import EntityPanel  # noqa: F401
from editor.panels_pkg.texture_panel import TextureBrowserPanel  # noqa: F401
from editor.panels_pkg.portal_panel import PortalPanel  # noqa: F401
from editor.panels_pkg.template_panel import RoomTemplatePanel  # noqa: F401
from editor.panels_pkg.minimap import Minimap           # noqa: F401
from editor.panels_pkg.status_bar import StatusBar      # noqa: F401
from editor.panels_pkg.splitter import PanelSplitter    # noqa: F401
from editor.panels_pkg.panel_tabs import PanelTabs      # noqa: F401
from editor.panels_pkg.toolbar import Toolbar            # noqa: F401
from editor.panels_pkg.surface_panel import SurfacePanel  # noqa: F401


