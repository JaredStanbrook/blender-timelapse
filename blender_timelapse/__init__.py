# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender Timelapse: record fixed-camera timelapses while you model freely."""

import bpy
from bpy.app.handlers import persistent

from . import operators, previews, properties, recorder, ui, video

_modules = (properties, previews, operators, ui)


@persistent
def _on_load_pre(*_args):
    # A different .blend is about to replace all data: close the session cleanly first.
    recorder.shutdown("file changed")


def register():
    for m in _modules:
        m.register()
    bpy.app.handlers.load_pre.append(_on_load_pre)


def unregister():
    # Stop first so no timer can fire into half-unregistered classes.
    recorder.shutdown("add-on disabled")
    video.cancel()
    if _on_load_pre in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load_pre)
    for m in reversed(_modules):
        m.unregister()
