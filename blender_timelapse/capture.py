# SPDX-License-Identifier: GPL-3.0-or-later
"""Render one frame from the recording camera without leaving any trace on the scene.

Every setting we touch is recorded by `TemporaryOverrides` and put back in a
`finally`, so the scene is restored even when rendering or saving raises.
The viewport, selection, active object and workspace are never touched:
`bpy.ops.render.render` in EXEC mode renders off-screen from `scene.camera`.
"""

from pathlib import Path

import bpy

from .properties import ENGINE_IDS
from .utils import TimelapseError, any_window

_busy = False  # guards against re-entrant captures (timer + button at once)


def is_busy():
    return _busy


class TemporaryOverrides:
    """Set attributes now, restore all of them (in reverse) on exit."""

    def __init__(self):
        self._saved = []

    def set(self, owner, attr, value):
        old = getattr(owner, attr)
        self._saved.append((owner, attr, old))
        if old != value:
            setattr(owner, attr, value)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        errors = []
        for owner, attr, old in reversed(self._saved):
            try:
                if getattr(owner, attr) != old:
                    setattr(owner, attr, old)
            except Exception as ex:  # keep restoring the rest no matter what
                errors.append("%s: %s" % (attr, ex))
        self._saved.clear()
        if errors:
            print("Blender Timelapse: could not restore", errors)
        return False


def snapshot(settings):
    """Freeze the capture settings so one session's frames stay consistent."""
    return {
        "engine": settings.engine,
        "resolution": settings.resolution_preset,
        "width": settings.custom_width,
        "height": settings.custom_height,
        "format": settings.image_format,
        "jpeg_quality": settings.jpeg_quality,
        "samples": settings.samples,
        "use_compositor": settings.use_compositor,
    }


def extension(snap):
    return "jpg" if snap["format"] == "JPEG" else "png"


def validate_camera(camera):
    if camera is None:
        raise TimelapseError("No recording camera selected")
    if camera.type != "CAMERA":
        raise TimelapseError("'%s' is not a camera" % camera.name)
    return camera


def _apply(ov, scene, camera, snap):
    r = scene.render
    ov.set(scene, "camera", camera)

    engine = ENGINE_IDS.get(snap["engine"])
    if engine:
        ov.set(r, "engine", engine)

    if snap["resolution"] == "CUSTOM":
        ov.set(r, "resolution_x", snap["width"])
        ov.set(r, "resolution_y", snap["height"])
        ov.set(r, "resolution_percentage", 100)
    else:
        ov.set(r, "resolution_percentage", int(snap["resolution"]))
    ov.set(r, "use_border", False)

    im = r.image_settings
    ov.set(im, "media_type", "IMAGE")  # must precede file_format in Blender 5.x
    ov.set(im, "file_format", snap["format"])
    ov.set(im, "color_mode", "RGB")
    if snap["format"] == "JPEG":
        ov.set(im, "quality", snap["jpeg_quality"])
    else:
        ov.set(im, "color_depth", "8")
        ov.set(im, "compression", 15)  # fast; PNG is lossless at any level

    ov.set(r, "use_sequencer", False)  # VSE strips would replace the 3D render
    ov.set(r, "use_compositing", snap["use_compositor"])

    if snap["samples"] > 0:
        if r.engine == "BLENDER_EEVEE":
            ov.set(scene.eevee, "taa_render_samples", snap["samples"])
        elif r.engine == "CYCLES" and hasattr(scene, "cycles"):
            ov.set(scene.cycles, "samples", snap["samples"])


def _render_result():
    for image in bpy.data.images:
        if image.type == "RENDER_RESULT":
            return image
    return None


def render_frame(scene, camera, snap, filepath, view_layer=None):
    """Render scene through camera and write it to filepath. Returns (width, height)."""
    global _busy
    if _busy:
        raise TimelapseError("A capture is already in progress")
    validate_camera(camera)
    if bpy.app.is_job_running("RENDER"):
        raise TimelapseError("Another render is running")

    filepath = Path(filepath)
    if filepath.exists():
        raise TimelapseError("Refusing to overwrite '%s'" % filepath)

    _busy = True
    try:
        with TemporaryOverrides() as ov:
            _apply(ov, scene, camera, snap)
            r = scene.render
            size = (r.resolution_x * r.resolution_percentage // 100, r.resolution_y * r.resolution_percentage // 100)

            layer = "" if snap["use_compositor"] else (view_layer or scene.view_layers[0]).name
            override = {"scene": scene}
            window = any_window()
            if window is not None:
                override["window"] = window
            with bpy.context.temp_override(**override):
                result = bpy.ops.render.render(write_still=False, layer=layer, scene=scene.name)
            if "FINISHED" not in result:
                raise TimelapseError("Render was cancelled")

            image = _render_result()
            if image is None:
                raise TimelapseError("Render produced no image")
            # save_render applies the scene's colour management and image settings (still overridden here).
            image.save_render(filepath=str(filepath), scene=scene)
    except RuntimeError as ex:  # bpy raises RuntimeError for operator / IO errors
        raise TimelapseError(str(ex).replace("Error: ", "").strip()) from ex
    finally:
        _busy = False

    if not filepath.is_file():
        raise TimelapseError("Frame was not written to '%s'" % filepath)
    return size
