"""Interactive-mode tests: real window, real bpy.app.timers, real viewport navigation.

Runs Blender with a UI (under Xvfb in CI) and drives a scripted user session from a
timer-stepped generator, then quits. See tests/run_tests.sh.
"""

import json
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from common import addon, addon_key, check, diff, finish, pixels, render_state  # noqa: E402

OUT = Path(sys.argv[sys.argv.index("--") + 1])
REPORT = sys.argv[sys.argv.index("--") + 2]
SHOTS = Path(__file__).resolve().parent.parent / "docs" / "images"


def view3d():
    win = bpy.context.window_manager.windows[0]
    area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
    region = next(r for r in area.regions if r.type == "WINDOW")
    return win, area, region, area.spaces.active


def op(fn, **kw):
    win, area, region, _space = view3d()
    with bpy.context.temp_override(window=win, area=area, region=region):
        return fn(**kw)


def view_matrix():
    rv3d = view3d()[3].region_3d
    return [round(v, 5) for row in rv3d.view_matrix for v in row], rv3d.view_perspective


def wait(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        yield 0.1


def frames(s):
    return bt.utils.list_frames(s.folder / "Frames")


def scenario():
    yield 1.0  # let the UI settle
    win, area, region, space = view3d()
    space.show_region_ui = True
    scene = bpy.context.scene
    st = scene.blender_timelapse
    st.camera = scene.objects["Camera"]
    st.output_dir = str(OUT)
    st.project_name = "GUI"
    st.engine = "WORKBENCH"
    st.interval_preset = "1"
    st.resolution_preset = "50"
    st.capture_on_stop = False
    rv3d = space.region_3d
    check("viewport starts in free view", rv3d.view_perspective != "CAMERA")
    bpy.ops.object.select_all(action="DESELECT")
    scene.objects["Cube"].select_set(True)
    bpy.context.view_layer.objects.active = scene.objects["Cube"]
    before = render_state(scene)

    # -- test capture + preview
    r = op(bpy.ops.blender_timelapse.test_capture)
    check("camera test capture operator", r == {"FINISHED"})
    yield from wait(1.0)
    check("camera preview thumbnail available", bt.previews.icon_id() != 0)

    # -- start via the real operator
    check("start operator", op(bpy.ops.blender_timelapse.start) == {"FINISHED"})
    s = bt.recorder.get()
    check("duplicate start blocked by poll", not bpy.ops.blender_timelapse.start.poll())

    # -- phase A: navigate heavily, model static -> frames must be identical
    t_end = time.monotonic() + 5.5
    nav = 0
    while time.monotonic() < t_end:
        op(bpy.ops.view3d.view_orbit, angle=0.3, type="ORBITLEFT")
        op(bpy.ops.view3d.view_orbit, angle=0.1, type="ORBITUP")
        op(bpy.ops.view3d.view_pan, type="PANRIGHT")
        op(bpy.ops.view3d.zoom, delta=1 if nav % 2 else -1)
        nav += 1
        yield 0.15
    yield from wait(0.5)
    nav_view = view_matrix()
    a_frames = frames(s)
    check("06 frames captured while navigating", len(a_frames) >= 4, len(a_frames))
    ref = pixels(a_frames[0][1])[1]
    worst = max(diff(ref, pixels(p)[1]) for _i, p in a_frames[1:])
    check("06 orbit/pan/zoom never changes captured angle (pixel-identical)", worst < 1e-6, worst)
    check("06 viewport not forced into camera view", rv3d.view_perspective != "CAMERA")
    times = [p.stat().st_mtime for _i, p in a_frames]
    gaps = [b - a for a, b in zip(times, times[1:])]
    check("never captures faster than interval (1 s)", min(gaps) >= 0.95, ["%.2f" % g for g in gaps])

    SHOTS.mkdir(parents=True, exist_ok=True)
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=str(SHOTS / "panel_recording.png"))

    # -- phase B: edit geometry in Edit Mode while recording
    n0 = len(frames(s))
    op(bpy.ops.object.mode_set, mode="EDIT")
    op(bpy.ops.mesh.select_all, action="SELECT")
    op(bpy.ops.transform.resize, value=(1.8, 0.6, 1.0))
    yield from wait(1.6)
    op(bpy.ops.mesh.subdivide, number_cuts=2)
    op(bpy.ops.transform.translate, value=(0, 0, 1.2))
    yield from wait(1.6)
    op(bpy.ops.object.mode_set, mode="OBJECT")
    yield from wait(1.6)
    b_frames = frames(s)[n0 - 1:]
    d_edit = diff(pixels(b_frames[0][1])[1], pixels(b_frames[-1][1])[1])
    check("07 edits made in Edit Mode appear in frames", d_edit > 1e-3, d_edit)
    edit_frames = [p for i, p in frames(s) if i > n0][:2]
    if edit_frames:
        check("07 edit visible while still in Edit Mode",
              diff(pixels(b_frames[0][1])[1], pixels(edit_frames[0])[1]) > 1e-3)

    # -- undo / redo while recording (ID pointers are rebuilt by undo)
    n_u = len(frames(s))
    for _ in range(3):
        op(bpy.ops.transform.translate, value=(0.5, 0, 0))
        op(bpy.ops.ed.undo_push, message="move")
        yield 0.4
    for _ in range(3):  # the last undo goes back past the moment the camera was chosen
        op(bpy.ops.ed.undo)
        yield 0.4
    check("undo went past camera selection", bpy.context.scene.blender_timelapse.camera is None)
    n_u2 = len(frames(s))
    yield from wait(1.3)
    check("undo past camera choice keeps recording from the same camera", len(frames(s)) > n_u2 and not s.last_error,
          s.last_error)
    op(bpy.ops.ed.redo)
    yield from wait(1.2)
    check("undo/redo during recording keeps capturing", len(frames(s)) > n_u and not s.last_error, s.last_error)
    scene = bpy.context.scene  # undo invalidates Python references to IDs
    st = scene.blender_timelapse
    rv3d = view3d()[3].region_3d

    # -- sculpt mode
    n1 = len(frames(s))
    op(bpy.ops.object.mode_set, mode="SCULPT")
    mesh = scene.objects["Cube"].data
    mesh.vertices[0].co.z += 2.0  # direct data change while in sculpt mode
    mesh.update()
    for _ in range(50):  # the capture after undo/redo can be slow, so allow up to 5 s
        if len(frames(s)) > n1:
            break
        yield 0.1
    op(bpy.ops.object.mode_set, mode="OBJECT")
    check("captures keep running in Sculpt Mode", len(frames(s)) > n1,
          (s.state, s.last_error, s.deferred_since, s.countdown(), [len(w.modal_operators) for w in
                                                                    bpy.context.window_manager.windows]))

    # -- pause / resume through operators
    check("pause operator", op(bpy.ops.blender_timelapse.pause) == {"FINISHED"})
    n2 = len(frames(s))
    el = s.elapsed()
    yield from wait(3.0)
    check("08 no captures while paused (3 s)", len(frames(s)) == n2)
    check("08 elapsed frozen while paused", abs(s.elapsed() - el) < 1e-6)
    check("resume operator", op(bpy.ops.blender_timelapse.resume) == {"FINISHED"})
    yield from wait(2.6)
    check("08 captures resume in same session", len(frames(s)) > n2 and bt.recorder.get() is s)

    # -- interval change mid-session
    st.interval_preset = "2"
    yield from wait(1.2)
    n3 = len(frames(s))
    yield from wait(4.4)
    got = len(frames(s)) - n3
    check("11 interval change to 2 s takes effect", 1 <= got <= 3, got)

    # -- manual + stop
    n4 = len(frames(s))
    check("09 capture-now operator", op(bpy.ops.blender_timelapse.capture_now) == {"FINISHED"}
          and len(frames(s)) == n4 + 1)
    check("10 stop operator", op(bpy.ops.blender_timelapse.stop) == {"FINISHED"})
    n5 = len(frames(s))
    yield from wait(2.0)
    check("18 no captures after stop / timer gone", len(frames(s)) == n5
          and not bpy.app.timers.is_registered(bt.recorder._tick))
    idx = [i for i, _p in frames(s)]
    check("sequential numbering without gaps", idx == list(range(1, len(idx) + 1)), idx[-3:])

    after = render_state(scene)
    keys = ("camera", "engine", "res", "media", "format", "color", "depth", "quality", "compression", "filepath",
            "seq", "comp", "border", "eevee_samples", "active", "selected", "scenes", "window_scene", "workspace",
            "cam_transform", "lens")
    changed = {k: (before[k], after[k]) for k in keys if before[k] != after[k]}
    # selection legitimately changes only because Edit Mode subdivide keeps Cube selected; nothing else may move
    check("render/scene/selection/workspace state preserved", not changed, changed)
    check("viewport keeps the user's navigated view", view_matrix() == nav_view)
    check(".blend never saved by add-on", bpy.data.filepath == "")

    # -- video from the UI operator (external ffmpeg, non-blocking)
    st.fps_preset = "24"
    check("generate video operator", op(bpy.ops.blender_timelapse.generate_video) == {"FINISHED"})
    for _ in range(300):
        if bt.video.job.state != "RUNNING":
            break
        yield 0.1
    check("16 video generated while UI stays live", bt.video.job.state == "DONE"
          and (s.folder / "timelapse.mp4").is_file(), bt.video.job.message)
    with bpy.context.temp_override(window=win):
        bpy.ops.screen.screenshot(filepath=str(SHOTS / "panel_stopped.png"))

    # -- repeated session, then disable add-on mid-recording
    check("20 second session starts", op(bpy.ops.blender_timelapse.start) == {"FINISHED"})
    s2 = bt.recorder.get()
    check("20 new folder for repeat", s2.folder != s.folder, s2.folder.name)
    yield from wait(2.5)
    bpy.ops.preferences.addon_disable(module=KEY)
    n6 = len(bt.utils.list_frames(s2.folder / "Frames"))
    yield from wait(2.5)
    check("17 disabling mid-recording stops captures", len(bt.utils.list_frames(s2.folder / "Frames")) == n6
          and n6 >= 1, n6)
    meta = json.loads((s2.folder / "session_info.json").read_text())
    check("17 session closed with metadata", meta["status"] == "stopped", meta["end_reason"])
    check("18 no add-on timer left", not bpy.app.timers.is_registered(bt.recorder._tick))
    bpy.ops.preferences.addon_enable(module=KEY)
    check("re-enable after disable", hasattr(bpy.types, "BT_PT_main"))


bt = addon()
KEY = addon_key()
_gen = scenario()
_exit = [0]


def _step():
    try:
        return next(_gen)
    except StopIteration:
        pass
    except Exception as ex:
        import traceback
        traceback.print_exc()
        check("scenario crashed", False, repr(ex))
    _exit[0] = finish(REPORT)
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.2)
    return None


bpy.app.timers.register(_step, first_interval=1.0)
