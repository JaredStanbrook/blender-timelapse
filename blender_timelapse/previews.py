# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview thumbnails for the panel (icons, not Image datablocks): camera test capture and look preview."""

import bpy.utils.previews

_pcoll = None
_KEY = "camera_preview"


def show(path, key=_KEY):
    if _pcoll is None:
        return
    if key in _pcoll:  # load() refuses existing keys; del releases the old preview
        del _pcoll[key]
    _pcoll.load(key, str(path), "IMAGE", force_reload=True)


def icon_id(key=_KEY):
    if _pcoll is None or key not in _pcoll:
        return 0
    return _pcoll[key].icon_id


def register():
    global _pcoll
    _pcoll = bpy.utils.previews.new()


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None
