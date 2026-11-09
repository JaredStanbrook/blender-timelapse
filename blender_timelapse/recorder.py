# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording session state and the capture scheduler.

There is at most one `Session` (module global `_session`). It holds plain Python
data only, never bpy references, so it can't dangle after undo or a file load.
A single `bpy.app.timers` callback (`_tick`) drives everything on the main
thread; no background threads ever touch Blender data.
"""

import atexit
import time
import traceback
from datetime import datetime

import bpy

from . import capture
from .utils import (
    ADDON_VERSION,
    METADATA_NAME,
    TimelapseError,
    any_window,
    check_free_space,
    create_session_dir,
    find_scene,
    format_duration,
    frame_path,
    output_root,
    project_name,
    redraw_viewports,
    write_json_atomic,
)

IDLE, RECORDING, PAUSED, STOPPED = "IDLE", "RECORDING", "PAUSED", "STOPPED"

TICK = 0.25           # scheduler resolution (seconds)
MIN_IDLE = 0.5        # always give the user this long between back-to-back captures
MAX_DEFER = 3.0       # longest we wait for a modal tool before capturing anyway
MAX_FAILURES = 3      # consecutive capture failures before auto-pausing


def _now():
    return time.monotonic()


class Session:
    def __init__(self, scene, settings, folder):
        self.scene_uid = scene.session_uid
        self.scene_name = scene.name
        self.folder = folder
        self.frames_dir = folder / "Frames"
        self.snap = capture.snapshot(settings)
        self.ext = capture.extension(self.snap)
        self.camera_name = settings.camera.name
        self.camera_uid = settings.camera.session_uid  # fixed for the session; survives undo and renames
        self.state = RECORDING
        self.frames = 0
        self.next_index = 1
        self.started = datetime.now().astimezone()
        self.ended = None
        self.active_seconds = 0.0
        self.resumed_at = _now()
        self.next_capture_at = _now()  # first frame straight away
        self.deferred_since = None
        self.last_duration = 0.0
        self.slow = False
        self.last_error = ""
        self.failures = 0
        self.pauses = 0
        self.resolution = None
        self.end_reason = ""
        self.blender_version = bpy.app.version_string
        self.blend_file = bpy.data.filepath or None

    # -- derived --------------------------------------------------------
    def elapsed(self):
        extra = _now() - self.resumed_at if self.state == RECORDING else 0.0
        return self.active_seconds + extra

    def countdown(self):
        return max(0.0, self.next_capture_at - _now()) if self.state == RECORDING else None

    def metadata(self):
        return {
            "addon": "Blender Timelapse",
            "addon_version": ADDON_VERSION,
            "blender_version": self.blender_version,
            "blend_file": self.blend_file,
            "scene": self.scene_name,
            "camera": self.camera_name,
            "status": self.state.lower(),
            "end_reason": self.end_reason or None,
            "started": self.started.isoformat(timespec="seconds"),
            "ended": self.ended.isoformat(timespec="seconds") if self.ended else None,
            "recorded_seconds": round(self.elapsed(), 2),
            "frames": self.frames,
            "pauses": self.pauses,
            "frame_pattern": "Frames/Frame_%06d." + self.ext,
            "resolution": list(self.resolution) if self.resolution else None,
            "capture": dict(self.snap),
            "last_error": self.last_error or None,
        }

    def save_metadata(self):
        try:
            write_json_atomic(self.folder / METADATA_NAME, self.metadata())
        except OSError as ex:
            self.last_error = self.last_error or "Could not write session info: %s" % (ex.strerror or ex)


_session = None


def get():
    return _session


def is_active():
    return _session is not None and _session.state in (RECORDING, PAUSED)


def _settings(scene):
    return scene.blender_timelapse


def _view_layer(scene):
    window = any_window()
    if window is not None and window.scene == scene:
        return window.view_layer
    return next((vl for vl in scene.view_layers if vl.use), scene.view_layers[0])


# -- controls --------------------------------------------------------------

def start(scene):
    """Begin a new session in a fresh, unique folder."""
    global _session
    if is_active():
        raise TimelapseError("A recording is already running")
    settings = _settings(scene)
    capture.validate_camera(settings.camera)
    if settings.camera.name not in scene.objects:
        raise TimelapseError("Camera '%s' is not in scene '%s'" % (settings.camera.name, scene.name))
    folder = create_session_dir(output_root(settings), project_name(settings))
    _session = Session(scene, settings, folder)
    _session.save_metadata()
    _ensure_timer()
    return _session


def pause():
    s = _session
    if s and s.state == RECORDING:
        s.active_seconds = s.elapsed()
        s.state = PAUSED
        s.pauses += 1
        s.save_metadata()


def resume():
    s = _session
    if s and s.state == PAUSED:
        s.state = RECORDING
        s.resumed_at = _now()
        s.failures = 0
        scene = find_scene(s.scene_uid)
        s.next_capture_at = _now() + (_settings(scene).interval if scene else MIN_IDLE)
        _ensure_timer()


def stop(reason="", final_capture=None):
    """Close the session. Safe to call any time, including during shutdown."""
    s = _session
    if not s or s.state not in (RECORDING, PAUSED):
        return
    scene = find_scene(s.scene_uid)
    if final_capture is None:
        final_capture = bool(scene) and _settings(scene).capture_on_stop and s.state == RECORDING
    if final_capture and scene:
        _capture(s, scene, manual=True)
    if s.state == RECORDING:
        s.active_seconds = s.elapsed()
    s.state = STOPPED
    s.ended = datetime.now().astimezone()
    s.end_reason = reason
    s.save_metadata()
    _remove_timer()
    redraw_viewports()


def reset():
    """Forget the current/last session (files on disk are kept)."""
    global _session
    stop("reset", final_capture=False)
    _session = None
    redraw_viewports()


def capture_now():
    s = _session
    if not is_active():
        raise TimelapseError("Start a recording first")
    scene = find_scene(s.scene_uid)
    if scene is None:
        raise TimelapseError("The recorded scene no longer exists")
    if not _capture(s, scene, manual=True):
        raise TimelapseError(s.last_error or "Capture failed")


def shutdown(reason):
    """Stop without rendering: used for file loads, disabling the add-on and quitting."""
    try:
        stop(reason, final_capture=False)
    finally:
        _remove_timer()


# -- scheduler ---------------------------------------------------------------

def _ensure_timer():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=TICK)


def _remove_timer():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)


def _user_busy():
    wm = bpy.context.window_manager
    return bool(wm) and any(len(w.modal_operators) for w in wm.windows)


def _tick():
    s = _session
    if s is None or s.state not in (RECORDING, PAUSED):
        return None
    try:
        scene = find_scene(s.scene_uid)
        if scene is None:
            stop("scene removed", final_capture=False)
            return None
        if s.state == RECORDING and _now() >= s.next_capture_at:
            if _should_defer(s, scene):
                s.next_capture_at = _now() + TICK
            else:
                _capture(s, scene)
        redraw_viewports()
    except Exception as ex:  # never let the timer die silently with a running session
        traceback.print_exc()
        s.last_error = "Unexpected error: %s" % ex
        pause()
    if s.state == RECORDING:  # wake exactly when the next frame is due
        return min(TICK, max(0.01, s.next_capture_at - _now()))
    return TICK


def _should_defer(s, scene):
    busy = bpy.app.is_job_running("RENDER") or bpy.app.is_job_running("OBJECT_BAKE")
    if not busy and _settings(scene).defer_while_busy and _user_busy():
        if s.deferred_since is None:
            s.deferred_since = _now()
        busy = _now() - s.deferred_since < MAX_DEFER
    if not busy:
        s.deferred_since = None
    return busy


def _capture(s, scene, manual=False):
    """Render one frame into the session. Returns True on success."""
    if capture.is_busy():
        return False
    started = _now()
    ok = False
    try:
        check_free_space(s.frames_dir)
        camera = next((o for o in scene.objects if o.session_uid == s.camera_uid), None)
        if camera is None:
            raise TimelapseError("Recording camera '%s' was deleted" % s.camera_name)
        path = frame_path(s.frames_dir, s.next_index, s.ext)
        while path.exists():  # never overwrite, even if files were copied in meanwhile
            s.next_index += 1
            path = frame_path(s.frames_dir, s.next_index, s.ext)
        s.resolution = capture.render_frame(scene, camera, s.snap, path, _view_layer(scene))
        s.camera_name = camera.name
        s.frames += 1
        s.next_index += 1
        s.failures = 0
        s.last_error = ""
        ok = True
    except TimelapseError as ex:
        s.failures += 1
        s.last_error = str(ex)
    except Exception as ex:
        traceback.print_exc()
        s.failures += 1
        s.last_error = "Capture failed: %s" % ex
    finally:
        finished = _now()
        s.last_duration = finished - started
        interval = _settings(scene).interval
        s.slow = s.last_duration > interval
        # Never start-to-start faster than the interval, and always leave the user breathing room.
        earliest = max(started + interval, finished + MIN_IDLE)
        s.next_capture_at = max(s.next_capture_at, earliest) if manual else earliest
        if s.failures >= MAX_FAILURES and s.state == RECORDING:
            s.last_error += " (recording paused)"
            pause()
        s.save_metadata()
    return ok


# -- status for the UI ---------------------------------------------------------

def status_text(s):
    if s is None:
        return "Ready"
    if s.state == RECORDING:
        return "Recording"
    if s.state == PAUSED:
        return "Paused"
    return "Stopped"


def elapsed_text(s):
    return format_duration(s.elapsed()) if s else format_duration(0)


@atexit.register
def _on_exit():
    """Blender is quitting: bpy may already be torn down, so only write plain metadata."""
    s = _session
    if s and s.state in (RECORDING, PAUSED):
        if s.state == RECORDING:
            s.active_seconds += _now() - s.resumed_at
        s.state = STOPPED
        s.ended = datetime.now().astimezone()
        s.end_reason = "blender closed"
        s.save_metadata()
