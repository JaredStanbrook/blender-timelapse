"""Capture documentation screenshots of the panel (Xvfb + --enable-event-simulate)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from common import addon  # noqa: E402

OUT = Path(sys.argv[sys.argv.index("--") + 1])
SHOTS = Path(__file__).resolve().parent.parent / "docs" / "images"
bt = addon()


def ui_region():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    return win, area, next(r for r in area.regions if r.type == "UI")


def grab(name):
    win, area, region = ui_region()
    SHOTS.mkdir(parents=True, exist_ok=True)
    full = SHOTS / ("_full_%s.png" % name)
    subprocess.run(["import", "-display", os.environ["DISPLAY"], "-window", "root", str(full)], check=True)
    # crop: whole viewport + panel (X origin is top-left, Blender's is bottom-left)
    y = win.height - (area.y + area.height)
    subprocess.run(["convert", str(full), "-crop", "%dx%d+%d+%d" % (area.width, area.height, area.x, y),
                    str(SHOTS / ("%s.png" % name))], check=True)
    full.unlink()


def steps():
    yield 1.0
    win, area, region = ui_region()
    area.spaces.active.show_region_ui = True
    yield 0.5
    win, area, region = ui_region()
    win.event_simulate("MOUSEMOVE", "NOTHING", x=area.x + 200, y=area.y + 200)
    win.event_simulate("ESC", "PRESS")  # dismiss the splash screen
    win.event_simulate("ESC", "RELEASE")
    yield 0.3
    # Tabs run down the region's right edge; click until ours is active.
    tx = region.x + region.width - 6
    for ty in range(region.y + region.height - 20, region.y, -15):
        if region.active_panel_category == "Blender Timelapse":
            break
        win.event_simulate("MOUSEMOVE", "NOTHING", x=tx, y=ty)
        win.event_simulate("LEFTMOUSE", "PRESS", x=tx, y=ty)
        win.event_simulate("LEFTMOUSE", "RELEASE", x=tx, y=ty)
        yield 0.05
    win.event_simulate("MOUSEMOVE", "NOTHING", x=area.x + 300, y=area.y + 300)
    print("ACTIVE TAB", region.active_panel_category)
    scene = bpy.context.scene
    st = scene.blender_timelapse
    st.camera = scene.objects["Camera"]
    st.output_dir = str(OUT)
    st.project_name = "Screenshots"
    st.interval_preset = "2"
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.blender_timelapse.test_capture()
    yield 1.5
    grab("panel_idle")
    with bpy.context.temp_override(window=win, area=area):
        bpy.ops.blender_timelapse.start()
    for i in range(10):
        scene.objects["Cube"].rotation_euler.z += 0.1
        yield 0.5
    grab("panel_recording")
    bt.recorder.stop("user")
    yield 0.5
    grab("panel_stopped")


_g = steps()


def _step():
    try:
        return next(_g)
    except StopIteration:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.2)
    return None


bpy.app.timers.register(_step, first_interval=1.0)
