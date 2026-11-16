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
    bt.video.start(s.folder, 24, 1, "timelapse", exe)
    job = bt.video.job
    job.proc.wait(60)
    bt.video._poll()
    check("16 external ffmpeg video", job.state == "DONE" and (s.folder / "timelapse.mp4").is_file(), job.message)
    check("16 frames kept after export", len(frames(s)) == 12)
    scenes_before = len(bpy.data.scenes)
    images_before = len(bpy.data.images)
    bt.video.start(s.folder, 30, 1, "timelapse", None)
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
    bt.video.start(s.folder, 24, 1, "gappy.mp4", exe)
    check("16 gapped sequence encodes (built-in fallback)", job.state == "DONE" and (s.folder / "gappy.mp4").is_file())
    try:
        empty_scene, _c, _cam, st2 = setup(project="Empty", capture_on_stop=False)
        s3 = rec.start(empty_scene)
        rec.stop()
        bt.video.start(s3.folder, 24, 1, "x", exe)
        check("video with no photos refused", False)
    except bt.utils.TimelapseError:
        check("video with no photos refused", True)


def probe(path):
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames,r_frame_rate:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    info = json.loads(r.stdout)
    return int(info["streams"][0]["nb_read_frames"]), info["streams"][0]["r_frame_rate"], float(info["format"]["duration"])


def photo_changes(path):
    """Video frame numbers where the picture changes (per-frame mean luma jumps)."""
    import re
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    means = [int(m) for m in re.findall(r"mean:\[(\d+)", r.stderr)]
    return [i for i in range(1, len(means)) if abs(means[i] - means[i - 1]) > 4]


def export(st, exe=True):
    """Export the selected session through the real operator; wait for external ffmpeg."""
    prefs = bpy.context.preferences.addons[addon_key_saved].preferences
    prefs.ffmpeg_path = "" if exe else "/nonexistent/ffmpeg"  # missing path forces the built-in encoder
    result = bpy.ops.blender_timelapse.generate_video()
    job = bt.video.job
    if job.proc:
        job.proc.wait(120)
        bt.video._poll()
    prefs.ffmpeg_path = ""
    return result, job


def digest(folder):
    import hashlib
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for _i, p in bt.utils.list_frames(Path(folder) / "Frames")}


def t_photo_duration_export():
    """Brief acceptance criteria: duration per photo x FPS, repeatable export, originals untouched."""
    scene, cube, cam, st = setup(project="Durations", capture_on_stop=False)
    s = rec.start(scene)
    check("new session becomes the export session", bt.utils.session_dir(st.export_folder) == s.folder)
    check("export refused while that session records", not bpy.ops.blender_timelapse.generate_video.poll())
    for i in range(6):
        cube.rotation_euler.z = i * 0.25
        tick_capture()
    rec.stop()
    names = [p.name for _i, p in frames(s)]
    times = [p.stat().st_mtime_ns for _i, p in frames(s)]
    check("photos saved sequentially in chronological order",
          names == ["Frame_%06d.png" % i for i in range(1, 7)] and times == sorted(times), names)
    original = digest(s.folder)

    def case(label, duration, fps_preset, fps, exe, want_frames, want_seconds):
        st.photo_duration, st.fps_preset = duration, fps_preset
        st.video_name = "video"
        r, job = export(st, exe)
        out = job.output
        n, rate, secs = probe(out) if out and out.is_file() else (None, None, None)
        check("%s: %d frames, %g s @%d fps" % (label, want_frames, want_seconds, fps),
              r == {"FINISHED"} and job.state == "DONE" and n == want_frames and rate == "%d/1" % fps
              and abs(secs - want_seconds) < 0.05, (r, job.message, n, rate, secs))
        check("%s: UI plan matches" % label, bt.video.plan(6, st.fps, st.frames_per_photo) == (want_frames,
              want_seconds))
        check("%s: originals unchanged" % label, digest(s.folder) == original)
        return out

    outs = [case("1 s/photo 30 fps (ffmpeg)", 1.0, "30", 30, True, 180, 6.0),
            case("2 s/photo 30 fps re-export (ffmpeg)", 2.0, "30", 30, True, 360, 12.0),
            case("0.5 s/photo 24 fps (ffmpeg)", 0.5, "24", 24, True, 72, 3.0),
            case("1 s/photo 30 fps (built-in)", 1.0, "30", 30, False, 180, 6.0),
            case("2 s/photo 60 fps (built-in)", 2.0, "60", 60, False, 720, 12.0)]
    check("every export is a new file, none overwritten", len({o.name for o in outs}) == len(outs)
          and all(o.is_file() for o in outs), [o.name for o in outs])
    check("settings stay editable after export", (st.photo_duration, st.fps) == (2.0, 60))
    st.fps_preset, st.photo_duration = "30", 1 / 30 + 0.001
    check("frames per photo rounds and is at least 1", st.frames_per_photo == 1 and
          bt.properties.frames_per_photo(0.001, 24) == 1 and bt.properties.frames_per_photo(1.5, 24) == 36)

    # reopen the finished session after the recorder forgot it
    rec.reset()
    st.export_folder = ""
    check("export disabled without a session", not bpy.ops.blender_timelapse.generate_video.poll())
    r = bpy.ops.blender_timelapse.open_session(directory=str(s.folder / "Frames"))
    check("reopen session (picking its Frames folder works too)", r == {"FINISHED"}
          and bt.utils.session_dir(st.export_folder) == s.folder)
    st.photo_duration, st.fps_preset, st.video_name = 0.25, "24", "reopened"
    r, job = export(st)
    check("reopened session exports with latest settings (6 frames per photo)",
          job.state == "DONE" and probe(job.output)[0] == 36, job.message)
    try:
        bpy.ops.blender_timelapse.open_session(directory=str(OUT))
        check("opening a folder without photos refused", False)
    except RuntimeError:
        check("opening a folder without photos refused", True)

    # older session stays exportable while a new one records
    s2 = rec.start(scene)
    tick_capture()
    bpy.ops.blender_timelapse.open_session(directory=str(s.folder))
    check("an earlier session can be exported while recording another",
          bpy.ops.blender_timelapse.generate_video.poll())
    rec.stop()


def t_hold_exact_frames():
    """Each photo is held exactly frames-per-photo frames, by both encoders."""
    import subprocess
    folder = OUT / "Holds" / "Session_001"
    (folder / "Frames").mkdir(parents=True)
    for i, grey in enumerate((20, 90, 160, 230), start=1):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x%02x%02x%02x:s=64x48" %
                        (grey, grey, grey), "-frames:v", "1", str(folder / "Frames" / ("Frame_%06d.png" % i))],
                       check=True)
    for exe, label in ((bt.video.find_ffmpeg(""), "ffmpeg"), (None, "built-in")):
        bt.video.start(folder, 30, 15, "hold_" + label, exe)
        job = bt.video.job
        if job.proc:
            job.proc.wait(60)
            bt.video._poll()
        check("%s: photo changes exactly every 15 frames" % label,
              photo_changes(job.output) == [15, 30, 45] and probe(job.output)[0] == 60,
              (photo_changes(job.output), probe(job.output)))
    single = OUT / "Holds" / "Session_002"
    (single / "Frames").mkdir(parents=True)
    (folder / "Frames" / "Frame_000001.png").rename(single / "Frames" / "Frame_000001.png")
    bt.video.start(single, 30, 60, "one", bt.video.find_ffmpeg(""))
    bt.video.job.proc.wait(60)
    bt.video._poll()
    check("a single photo exports as a still video (2 s)", probe(bt.video.job.output)[0] == 60)


def loudness(path, start=None, duration=None):
    """Mean volume (dB) of a file's audio, optionally of a time window. -91 means silence / no audio."""
    import re
    import subprocess
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", str(start), "-t", str(duration)]
    cmd += ["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"]
    m = re.search(r"mean_volume: (-?[\d.]+) dB", subprocess.run(cmd, capture_output=True, text=True).stderr)
    return float(m.group(1)) if m else -91.0


def stream_seconds(path, kind):
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind + ":0", "-show_entries",
                        "stream=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def t_soundtrack():
    """Music under the video: chosen start point, cut to the video length, faded out, both encoders."""
    import subprocess
    folder = OUT / "Music" / "Session_001"
    (folder / "Frames").mkdir(parents=True)
    for i in range(1, 7):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x%02x%02x%02x:s=64x48"
                        % ((i * 35,) * 3), "-frames:v", "1", str(folder / "Frames" / ("Frame_%06d.png" % i))],
                       check=True)
    music = OUT / "music.mp3"  # 5 s of silence, then 20 s of loud tone: position in the file is audible
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=20:sample_rate=44100",
                    "-filter_complex", "[1]volume=0.8,aformat=channel_layouts=stereo[t];[0][t]concat=n=2:v=0:a=1",
                    str(music)], check=True)
    bt.video._audio_cache.clear()
    check("track length read without datablocks", abs(bt.video.audio_length(music) - 25.0) < 0.1
          and not any(snd.filepath.endswith("music.mp3") for snd in bpy.data.sounds))
    exe = bt.video.find_ffmpeg("")
    sounds, actions = len(bpy.data.sounds), len(bpy.data.actions)
    for label, ffmpeg in (("ffmpeg", exe), ("built-in", None)):
        def run(name, start, fade):
            bt.video.start(folder, 30, 30, "%s_%s" % (label, name), ffmpeg, bt.video.Soundtrack(music, start, fade))
            job = bt.video.job
            if job.proc:
                job.proc.wait(120)
                bt.video._poll()
            return job.output if job.state == "DONE" else None

        # 6 photos x 1 s = 6 s video. Start at 5 s -> loud tone throughout, cut at 6 s.
        out = run("from5", 5.0, 0.0)
        check("%s: video still 180 frames with music" % label, out and probe(out)[0] == 180, out)
        check("%s: music cut to video length (6 s)" % label, abs(stream_seconds(out, "a") - 6.0) < 0.1,
              stream_seconds(out, "a"))
        check("%s: plays from the chosen point (5 s -> tone)" % label, loudness(out) > -35, loudness(out))
        out0 = run("from0", 0.0, 0.0)
        check("%s: start 0 plays the silent intro first" % label,
              loudness(out0, 0, 4.5) < -60 and loudness(out0, 5.2, 0.6) > -35,
              (loudness(out0, 0, 4.5), loudness(out0, 5.2, 0.6)))
        outf = run("fade", 5.0, 2.0)
        check("%s: fade out at the end" % label,
              loudness(outf, 1, 2) > -35 and loudness(outf, 5.6, 0.35) < loudness(outf, 1, 2) - 12,
              (loudness(outf, 1, 2), loudness(outf, 5.6, 0.35)))
        outs = run("short", 22.0, 0.0)  # only 3 s of music left for a 6 s video
        check("%s: short track ends early, video keeps full length" % label,
              probe(outs)[0] == 180 and 2.8 < stream_seconds(outs, "a") <= 3.2 or
              (probe(outs)[0] == 180 and loudness(outs, 3.5, 2) < -60),
              (probe(outs)[0], stream_seconds(outs, "a"), loudness(outs, 3.5, 2)))
    check("built-in encoder leaves no sound/action datablocks",
          (len(bpy.data.sounds), len(bpy.data.actions)) == (sounds, actions))

    # panel settings + operator path
    scene, cube, cam, st = setup(project="MusicUI")
    st.export_folder = str(folder)
    st.use_soundtrack = True
    check("soundtrack on without a file blocks export", not bpy.ops.blender_timelapse.generate_video.poll())
    st.soundtrack_path = str(OUT / "missing.mp3")
    check("missing music file blocks export", not bpy.ops.blender_timelapse.generate_video.poll())
    st.soundtrack_path = str(music)
    st.soundtrack_start = 30.0
    check("Start At past the end blocks export", not bpy.ops.blender_timelapse.generate_video.poll())
    st.soundtrack_start, st.photo_duration, st.fps_preset, st.video_name = 5.0, 0.5, "24", "ui_music"
    r, job = export(st)
    check("operator exports with music from panel settings", r == {"FINISHED"} and job.state == "DONE"
          and probe(job.output)[0] == 72 and abs(stream_seconds(job.output, "a") - 3.0) < 0.1, job.message)
    st.use_soundtrack = False
    st.video_name = "ui_silent"
    r, job = export(st)
    check("turning the soundtrack off exports silent video", stream_seconds(job.output, "a") == 0
          and loudness(job.output) == -91.0)


def t_manual_mode():
    scene, cube, cam, st = setup(project="Manual", interval_preset="MANUAL", capture_on_stop=False)
    check("interval None in manual mode", st.interval is None)
    s = rec.start(scene)
    for _ in range(5):
        tick_capture()
    check("manual mode: no automatic captures", s.frames == 0 and s.countdown() is None, s.frames)
    r = bpy.ops.blender_timelapse.capture_now()
    check("manual mode: Capture Now adds a photo", r == {"FINISHED"} and s.frames == 1)
    rec._tick()
    check("manual mode: still no automatic capture after manual one", s.frames == 1)
    rec.pause()
    bpy.ops.blender_timelapse.capture_now()
    check("Capture Now works while paused", s.frames == 2)
    rec.resume()
    st.interval_preset = "1"
    rec._tick()
    check("switch to automatic mid-session schedules next capture", 0 < s.countdown() <= 1.0, s.countdown())
    tick_capture()
    check("automatic captures after switching", s.frames == 3)
    rec.stop()
    try:
        bpy.ops.blender_timelapse.capture_now()
        check("Capture Now without a session explains why", False)
    except RuntimeError as ex:
        check("Capture Now without a session explains why", "Start a recording first" in str(ex), ex)


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
