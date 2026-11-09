"""Quit Blender mid-recording; tests/run_tests.sh then checks session_info.json was closed."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from common import addon  # noqa: E402

OUT = Path(sys.argv[sys.argv.index("--") + 1])
bt = addon()


def go():
    scene = bpy.context.scene
    st = scene.blender_timelapse
    st.camera, st.output_dir, st.project_name, st.interval_preset = scene.objects["Camera"], str(OUT), "Quit", "1"
    bt.recorder.start(scene)
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=2.5)


bpy.app.timers.register(go, first_interval=1.0)
