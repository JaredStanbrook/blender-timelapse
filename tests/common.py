"""Shared helpers for the Blender Timelapse test scripts (run inside Blender)."""

import json
import sys
import traceback
from pathlib import Path

import bpy

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" -- " + str(detail) if detail else ""))
    return cond


def run(name, fn):
    try:
        fn()
    except Exception as ex:
        traceback.print_exc()
        check(name + " (raised)", False, repr(ex))


def finish(report_path):
    failed = [r for r in RESULTS if not r[1]]
    Path(report_path).write_text(json.dumps(
        [{"test": n, "passed": ok, "detail": str(d)} for n, ok, d in RESULTS], indent=2))
    print("\n=== %d passed, %d failed ===" % (len(RESULTS) - len(failed), len(failed)))
    for n, _ok, d in failed:
        print("FAILED:", n, d)
    return 1 if failed else 0


def addon():
    """Return the installed add-on package (bl_ext.user_default.blender_timelapse)."""
    for name, mod in sys.modules.items():
        if name.endswith(".blender_timelapse") and hasattr(mod, "recorder"):
            return mod
    raise RuntimeError("Blender Timelapse is not enabled")


def addon_key():
    return next(k for k in bpy.context.preferences.addons.keys() if k.endswith("blender_timelapse"))


def build_scene():
    """Fresh scene: one cube, one camera looking at it, a light."""
    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.render.resolution_x, scene.render.resolution_y = 320, 240
    scene.render.resolution_percentage = 100
    mesh = bpy.data.meshes.new("Cube")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(mesh)
    bm.free()
    cube = bpy.data.objects.new("Cube", mesh)
    scene.collection.objects.link(cube)
    cam = bpy.data.objects.new("RecCam", bpy.data.cameras.new("RecCam"))
    cam.location = (7, -7, 5)
    cam.rotation_euler = (1.1, 0, 0.785)
    scene.collection.objects.link(cam)
    light = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    scene.collection.objects.link(light)
    other = bpy.data.objects.new("OtherCam", bpy.data.cameras.new("OtherCam"))
    other.location = (0, 0, 20)
    scene.collection.objects.link(other)
    scene.camera = other  # deliberately a different camera: must be preserved
    return scene, cube, cam


def render_state(scene):
    """Everything a capture must leave untouched."""
    r, im = scene.render, scene.render.image_settings
    vl = bpy.context.view_layer
    return {
        "camera": scene.camera.name if scene.camera else None,
        "engine": r.engine, "res": (r.resolution_x, r.resolution_y, r.resolution_percentage),
        "media": im.media_type, "format": im.file_format, "color": im.color_mode, "depth": im.color_depth,
        "quality": im.quality, "compression": im.compression, "filepath": r.filepath,
        "seq": r.use_sequencer, "comp": r.use_compositing, "border": r.use_border,
        "eevee_samples": scene.eevee.taa_render_samples,
        "cycles_samples": scene.cycles.samples if hasattr(scene, "cycles") else None,
        "frame": scene.frame_current,
        "active": vl.objects.active.name if vl.objects.active else None,
        "selected": sorted(o.name for o in scene.objects if o.select_get()),
        "scenes": sorted(s.name for s in bpy.data.scenes),
        "window_scene": bpy.context.window.scene.name if bpy.context.window else None,
        "workspace": bpy.context.window.workspace.name if bpy.context.window else None,
        "cam_transform": (tuple(scene.objects["RecCam"].location), tuple(scene.objects["RecCam"].rotation_euler))
        if "RecCam" in scene.objects else None,
        "lens": scene.objects["RecCam"].data.lens if "RecCam" in scene.objects else None,
    }


def pixels(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        return tuple(img.size), list(img.pixels)
    finally:
        bpy.data.images.remove(img)


def diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))
