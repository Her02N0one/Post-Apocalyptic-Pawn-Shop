#!/usr/bin/env python3
"""zone_editor.py - Thin entry-point for the standalone Zone Editor.

The implementation lives in `editor/app/` (split into focused modules).
This file exists so the original `python zone_editor.py` invocation
still works.

    python zone_editor.py [zone_name]
"""
from __future__ import annotations
import sys

from editor.app import ZoneEditorApp


def main() -> None:
    zone = sys.argv[1] if len(sys.argv) > 1 else ""
    ZoneEditorApp(zone).run()


if __name__ == "__main__":
    main()

