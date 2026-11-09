"""Functional tests that drive the recorder directly (background mode, no event loop).

Run via tests/run_tests.sh, which installs the built ZIP into an isolated user profile.
"""

import json
import os
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
from common import addon, addon_key, build_scene, check, diff, finish, pixels, render_state, run  # noqa: E402

OUT = Path(sys.argv[sys.argv.index("--") + 1])
REPORT = sys.argv[sys.argv.index("--") + 2]
bt = addon()
rec = bt.recorder


def setup(**kw):
    scene, cube, cam = build_scene()
    st = scene.blender_timelapse
    st.camera = cam
    st.output_dir = str(OUT)
    st.project_name = kw.pop("project", "BG")
    st.engine = kw.pop("engine", "WORKBENCH")
    st.interval_preset = "1"
    for k, v in kw.items():
        setattr(st, k, v)
    return scene, cube, cam, st


SEEN = []


@bpy.app.handlers.persistent
def _probe(scene, *_a):
    SEEN.append((scene.camera.name if scene.camera else None, scene.render.engine))


bpy.app.handlers.render_pre.append(_probe)


def tick_capture():
    """Make the next scheduled capture due now and run one scheduler tick."""
    s = rec.get()
    s.next_capture_at = 0
    s.deferred_since = None
    rec._tick()


def frames(s):
    return bt.utils.list_frames(s.folder / "Frames")


def t_install():
    check("01 add-on installed", "blender_timelapse" in addon_key())
    check("02 add-on enabled", hasattr(bpy.ops, "blender_timelapse") and hasattr(bpy.types.Scene, "blender_timelapse"))
    check("02b panels registered", hasattr(bpy.types, "BT_PT_main"))


def t_camera_selection():
    scene, cube, cam, st = setup()
    check("03 camera poll accepts camera", bt.properties._is_camera(None, cam))
    check("03 camera poll rejects mesh", not bt.properties._is_camera(None, cube))
    cam.data.type = "ORTHO"
    st.camera = cam
    check("03 ortho camera selectable", st.camera == cam)


def t_record_cycle():
    scene, cube, cam, st = setup(capture_on_stop=True)
    before = render_state(scene)
    s = rec.start(scene)
    check("04 start creates session folder", s.folder.is_dir() and (s.folder / "Frames").is_dir(), s.folder)
    check("04 timer registered", bpy.app.timers.is_registered(rec._tick))
    try:
        rec.start(scene)
        check("04 second start rejected", False)
    except bt.utils.TimelapseError:
        check("04 second start rejected", True)

    tick_capture()
    check("05 first frame captured", s.frames == 1 and frames(s)[0][1].name == "Frame_000001.png", frames(s))
    check("render settings restored after capture", render_state(scene) == before,
          {k: (before[k], v) for k, v in render_state(scene).items() if before[k] != v})

    # geometry edit between frames must show up
    cube.data.vertices[0].co.z += 3.0
    cube.data.update()
    tick_capture()
    cube.location.x += 1.5
    tick_capture()
    check("05 multiple frames", s.frames == 3, s.frames)
    f = frames(s)
    _sz, p1 = pixels(f[0][1])
    _sz, p2 = pixels(f[1][1])
    _sz, p3 = pixels(f[2][1])
    check("07 geometry edit visible in frames", diff(p1, p2) > 1e-4 and diff(p2, p3) > 1e-4, (diff(p1, p2), diff(p2, p3)))

    # not due yet -> no capture (never faster than interval)
    rec._tick()
    check("never captures before interval", s.frames == 3)

    rec.pause()
    check("08 paused state", s.state == rec.PAUSED)
    e1 = s.elapsed()
    tick_capture()
    time.sleep(0.3)
    check("08 pause prevents captures", s.frames == 3)
    check("08 elapsed frozen while paused", abs(s.elapsed() - e1) < 1e-6)
    rec.resume()
    check("08 resume continues same session", s.state == rec.RECORDING and rec.get() is s)
    check("08 resume waits one interval", s.countdown() > 0.5, s.countdown())
    tick_capture()
    check("08 capture after resume continues numbering", frames(s)[-1][1].name == "Frame_000004.png")

    rec.capture_now()
    check("09 manual capture", s.frames == 5)

    st.interval_preset = "CUSTOM"
    st.interval_custom = 7.0
    tick_capture()
    check("11 interval change applies live", 6.0 < s.countdown() <= 7.0, s.countdown())

    rec.stop("test")
    check("10 stop captures final frame", s.frames == 7, s.frames)
    check("10 stop sets STOPPED", s.state == rec.STOPPED)
    check("18 timer removed on stop", not bpy.app.timers.is_registered(rec._tick))
    meta = json.loads((s.folder / "session_info.json").read_text())
    check("metadata written", meta["frames"] == 7 and meta["status"] == "stopped" and meta["camera"] == "RecCam", meta)
    check("render settings restored after session", render_state(scene) == before)
    check("camera object untouched", render_state(scene)["cam_transform"] == before["cam_transform"])
    try:
        rec.capture_now()
        check("capture_now refused after stop", False)
    except bt.utils.TimelapseError:
        check("capture_now refused after stop", True)


def t_formats_and_resolutions():
    for fmt, ext in (("PNG", "png"), ("JPEG", "jpg")):
        for res, expect in (("25", (80, 60)), ("50", (160, 120)), ("75", (240, 180)), ("100", (320, 240)),
                            ("CUSTOM", (200, 100))):
            scene, cube, cam, st = setup(image_format=fmt, resolution_preset=res, custom_width=200,
                                         custom_height=100, capture_on_stop=False, jpeg_quality=50)
            s = rec.start(scene)
            tick_capture()
            rec.stop()
            f = frames(s)
            size = pixels(f[0][1])[0] if f else None
            check("12/13 %s %s%%" % (fmt, res), f and f[0][1].suffix == "." + ext and size == expect, (f, size))
            check("12/13 %s %s restored" % (fmt, res),
                  (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
                   scene.render.image_settings.file_format) == (320, 240, 100, "PNG"))


def t_engines():
    for engine in ("WORKBENCH", "EEVEE", "CYCLES", "SCENE"):
        scene, cube, cam, st = setup(engine=engine, capture_on_stop=False, samples=4)
        scene.render.engine = "BLENDER_EEVEE"
        before = render_state(scene)
        s = rec.start(scene)
        t0 = time.time()
        tick_capture()
        rec.stop()
        check("engine %s captures" % engine, s.frames == 1, s.last_error)
        want = {"WORKBENCH": "BLENDER_WORKBENCH", "EEVEE": "BLENDER_EEVEE", "CYCLES": "CYCLES",
                "SCENE": "BLENDER_EEVEE"}[engine]
        check("engine %s used for render, via RecCam" % engine, SEEN[-1] == ("RecCam", want), SEEN[-1])
        check("engine %s restores settings" % engine, render_state(scene) == before)
        print("   %s capture took %.2fs" % (engine, time.time() - t0))


def t_invalid_paths():
    scene, cube, cam, st = setup()
    blocker = OUT / "not_a_folder"
    blocker.write_text("x")
    for label, path in (("file as folder", str(blocker)), ("unwritable", "/proc/bt_nope"),
                        ("relative unsaved", "//renders")):
        st.output_dir = path
        try:
            rec.start(scene)
            check("14 invalid dir rejected: " + label, False)
            rec.reset()
        except bt.utils.TimelapseError as ex:
            check("14 invalid dir rejected: " + label, not rec.is_active(), ex)
    st.camera = None
    try:
        rec.start(scene)
        check("no camera rejected", False)
    except bt.utils.TimelapseError:
        check("no camera rejected", True)


def t_existing_sessions():
    scene, cube, cam, st = setup(project="Existing", capture_on_stop=False)
    proj = OUT / "Existing"
    (proj / "Session_001" / "Frames").mkdir(parents=True)
    keep = proj / "Session_001" / "Frames" / "Frame_000001.png"
    keep.write_bytes(b"precious")
    (proj / "Session_007").mkdir()
    s = rec.start(scene)
    tick_capture()
    rec.stop()
    check("15 new session after highest existing", s.folder.name == "Session_008", s.folder)
    check("15 previous session preserved", keep.read_bytes() == b"precious")
    s2 = rec.start(scene)
    rec.stop()
    check("20 repeated session gets new folder", s2.folder.name == "Session_009")


def t_disk_failure():
    scene, cube, cam, st = setup(capture_on_stop=False)
    s = rec.start(scene)
    tick_capture()
    import shutil
    shutil.rmtree(s.folder)  # storage vanishes mid-session
    for _ in range(3):
        tick_capture()
    check("storage loss pauses with error", s.state == rec.PAUSED and s.last_error, s.last_error)
    rec.stop()
    check("stop after storage loss is clean", s.state == rec.STOPPED)


def t_video():
    scene, cube, cam, st = setup(project="Video", capture_on_stop=False)
    s = rec.start(scene)
    for i in range(12):
        cube.rotation_euler.z = i * 0.2
        tick_capture()
    rec.stop()
    exe = bt.video.find_ffmpeg("")
    check("ffmpeg found on PATH", exe)
    bt.video.start(s.folder, 24, "timelapse", exe)
    job = bt.video.job
    job.proc.wait(60)
    bt.video._poll()
    check("16 external ffmpeg video", job.state == "DONE" and (s.folder / "timelapse.mp4").is_file(), job.message)
    check("16 frames kept after export", len(frames(s)) == 12)
    scenes_before = len(bpy.data.scenes)
    images_before = len(bpy.data.images)
    bt.video.start(s.folder, 30, "timelapse", None)
    out2 = s.folder / "timelapse_2.mp4"
    check("16 built-in encoder video, no overwrite", job.state == "DONE" and out2.is_file(), job.message)
    check("16 built-in encoder leaves no scene/images", len(bpy.data.scenes) == scenes_before
          and len(bpy.data.images) == images_before)
    import subprocess
    for out, fps in ((s.folder / "timelapse.mp4", 24), (out2, 30)):
        probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                "stream=nb_read_frames,r_frame_rate,width,height,codec_name", "-of", "json", str(out)],
                               capture_output=True, text=True)
        info = json.loads(probe.stdout)["streams"][0]
        check("16 %s: 12 frames @%d fps h264" % (out.name, fps),
              int(info["nb_read_frames"]) == 12 and info["r_frame_rate"] == "%d/1" % fps
              and info["codec_name"] == "h264", info)
    # gap in numbering -> built-in path handles explicit list
    frames(s)[5][1].unlink()
    bt.video.start(s.folder, 24, "gappy.mp4", exe)
    check("16 gapped sequence encodes (built-in fallback)", job.state == "DONE" and (s.folder / "gappy.mp4").is_file())
    try:
        empty_scene, _c, _cam, st2 = setup(project="Empty", capture_on_stop=False)
        s3 = rec.start(empty_scene)
        rec.stop()
        bt.video.start(s3.folder, 24, "x", exe)
        check("video with <2 frames refused", False)
    except bt.utils.TimelapseError:
        check("video with <2 frames refused", True)


def t_reopen_blend():
    scene, cube, cam, st = setup(project="Reopen", image_format="JPEG", jpeg_quality=77)
    blend = OUT / "saved.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    s = rec.start(scene)
    tick_capture()
    bpy.ops.wm.open_mainfile(filepath=str(blend))  # file change mid-session
    check("file load stops session", s.state == rec.STOPPED and s.end_reason == "file changed")
    check("file load removes timer", not bpy.app.timers.is_registered(rec._tick))
    st = bpy.context.scene.blender_timelapse
    check("19 settings persist in .blend", st.camera and st.camera.name == "RecCam" and st.jpeg_quality == 77
          and st.image_format == "JPEG")
    check("19 .blend not modified by recording", not bpy.data.is_dirty)
    s2 = rec.start(bpy.context.scene)
    tick_capture()
    rec.stop()
    check("19 recording works after reopen", s2.frames == 2 and s2.folder.name == "Session_002", s2.folder)


def t_rename_and_camera_changes():
    scene, cube, cam, st = setup(capture_on_stop=False)
    s = rec.start(scene)
    scene.name = "Renamed"
    tick_capture()
    check("scene rename does not break session", s.frames == 1)
    cam.name = "RenamedCam"
    st.camera = None  # e.g. undo past the moment the camera was picked
    tick_capture()
    check("camera rename / cleared pointer: same camera keeps recording", s.frames == 2 and SEEN[-1][0] == "RenamedCam",
          (s.last_error, SEEN[-1]))
    bpy.data.objects.remove(cam)
    tick_capture()
    check("deleted camera reported, no crash", s.frames == 2 and "deleted" in s.last_error, s.last_error)
    tick_capture()
    tick_capture()
    check("repeated failures auto-pause", s.state == rec.PAUSED)
    rec.stop()


def t_disable_during_session():
    scene, cube, cam, st = setup(capture_on_stop=False)
    s = rec.start(scene)
    tick_capture()
    folder = s.folder
    import addon_utils
    addon_utils.disable(addon_key(), default_set=True)
    meta = json.loads((folder / "session_info.json").read_text())
    check("17 disable stops session", meta["status"] == "stopped" and meta["end_reason"] == "add-on disabled", meta)
    check("17/18 no timers left after disable", not bpy.app.timers.is_registered(rec._tick))
    check("17 UI classes unregistered", not hasattr(bpy.types, "BT_PT_main"))
    addon_utils.enable(addon_key_saved, default_set=True)
    check("re-enable works", hasattr(bpy.ops.blender_timelapse, "start") and hasattr(bpy.types, "BT_PT_main"))


addon_key_saved = addon_key()
for name, fn in list(globals().items()):
    if name.startswith("t_"):
        print("\n---", name)
        run(name, fn)
        if rec.is_active():
            rec.reset()

sys.exit(finish(REPORT))
