#!/usr/bin/env python
"""Launch the standalone Map Editor.

Usage::

    python editor_main.py                # opens first zone or blank
    python editor_main.py playground     # opens specific zone
"""

import sys
from pathlib import Path

# Ensure project root is importable
_root = str(Path(__file__).resolve().parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from editor.app import EditorApp


def main():
    zone = sys.argv[1] if len(sys.argv) > 1 else ""
    EditorApp(zone).run()


if __name__ == "__main__":
    main()
