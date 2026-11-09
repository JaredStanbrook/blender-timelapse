# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera preview thumbnail for the panel (an icon, not an Image datablock)."""

import bpy.utils.previews

_pcoll = None
_KEY = "camera_preview"


def show(path):
    if _pcoll is None:
        return
    _pcoll.load(_KEY, str(path), "IMAGE", force_reload=True)


def icon_id():
    if _pcoll is None or _KEY not in _pcoll:
        return 0
    return _pcoll[_KEY].icon_id


def register():
    global _pcoll
    _pcoll = bpy.utils.previews.new()


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
