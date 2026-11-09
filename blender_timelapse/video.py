# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn a session's frames into an MP4. Source frames are never modified or deleted.

Two encoders:
* External FFmpeg (preferred): runs as a separate process, polled by a timer,
  so Blender stays responsive. Progress is read from a file (works on Windows).
* Blender's built-in FFmpeg: a temporary VSE scene renders the frames to H.264.
  Blocks the UI while it runs; the temporary scene is always removed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import bpy

from .utils import TimelapseError, frame_path, list_frames, redraw_viewports, safe_name, unique_path

POLL = 0.5


class Job:
    def __init__(self):
        self.state = "IDLE"  # IDLE, RUNNING, DONE, FAILED
        self.message = ""
        self.output = None
        self.total = 0
        self.done_frames = 0
        self.proc = None
        self.progress_file = None
        self.log = None

    @property
    def progress(self):
        return min(1.0, self.done_frames / self.total) if self.total else 0.0


job = Job()


def find_ffmpeg(prefs_path=""):
    if prefs_path:
        path = Path(bpy.path.abspath(prefs_path))
        return str(path) if path.is_file() else None
    return shutil.which("ffmpeg")


def output_path(session_folder, name):
    name = safe_name(Path(name).stem if name.lower().endswith(".mp4") else name, "timelapse")
    return unique_path(Path(session_folder) / (name + ".mp4"))


def _contiguous(frames):
    return all(idx == frames[0][0] + i for i, (idx, _p) in enumerate(frames))


def start(session_folder, fps, name, ffmpeg_exe):
    """Encode; returns immediately for external FFmpeg, blocks for the built-in path."""
    if job.state == "RUNNING":
        raise TimelapseError("A video is already being generated")
    frames_dir = Path(session_folder) / "Frames"
    frames = list_frames(frames_dir)
    if len(frames) < 2:
        raise TimelapseError("Need at least 2 captured frames to make a video")
    if len({p.suffix.lower() for _i, p in frames}) > 1:
        raise TimelapseError("Frames folder mixes PNG and JPEG files")
    out = output_path(session_folder, name)

    job.__init__()
    job.total = len(frames)
    job.output = out
    if ffmpeg_exe and _contiguous(frames):
        _start_external(ffmpeg_exe, frames, frames_dir, fps, out)
    else:
        _encode_builtin(frames, fps, out)


def _start_external(exe, frames, frames_dir, fps, out):
    first = frames[0][0]
    pattern = str(frame_path(frames_dir, 0, frames[0][1].suffix[1:])).replace("000000", "%06d")
    job.progress_file = out.with_suffix(".progress.txt")
    log_path = out.with_suffix(".ffmpeg.log")
    cmd = [
        exe, "-hide_banner", "-nostdin", "-n",
        "-framerate", str(fps), "-start_number", str(first), "-i", pattern,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-movflags", "+faststart",
        "-progress", str(job.progress_file), "-nostats",
        str(out),
    ]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        job.log = open(log_path, "w", encoding="utf-8")
        job.proc = subprocess.Popen(cmd, stdout=job.log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, creationflags=flags)
    except OSError as ex:
        if job.log:
            job.log.close()
        job.state = "FAILED"
        raise TimelapseError("Could not run FFmpeg: %s" % (ex.strerror or ex)) from ex
    job.state = "RUNNING"
    job.message = "Encoding with FFmpeg..."
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=POLL, persistent=True)


def _read_progress():
    try:
        text = job.progress_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in reversed(text.splitlines()):
        if line.startswith("frame="):
            try:
                job.done_frames = int(line[6:])
            except ValueError:
                pass
            return


def _cleanup_external():
    if job.log:
        job.log.close()
        job.log = None
    if job.progress_file:
        try:
            job.progress_file.unlink()
        except OSError:
            pass


def _poll():
    if job.proc is None:
        return None
    _read_progress()
    code = job.proc.poll()
    if code is None:
        redraw_viewports()
        return POLL
    _cleanup_external()
    if code == 0 and job.output.is_file():
        job.state, job.done_frames = "DONE", job.total
        job.message = "Saved %s" % job.output.name
        try:
            job.output.with_suffix(".ffmpeg.log").unlink()
        except OSError:
            pass
    else:
        job.state = "FAILED"
        job.message = "FFmpeg failed (code %s), see %s" % (code, job.output.with_suffix(".ffmpeg.log").name)
    job.proc = None
    redraw_viewports()
    return None


def cancel():
    """Stop an external encode and remove its partial output."""
    if job.proc and job.proc.poll() is None:
        job.proc.terminate()
        try:
            job.proc.wait(5)
        except subprocess.TimeoutExpired:
            job.proc.kill()
        _cleanup_external()
        try:
            job.output.unlink()
        except OSError:
            pass
        job.state, job.message, job.proc = "FAILED", "Cancelled", None
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)


def _image_size(path):
    """Read width/height without creating a datablock that could end up in the user's file."""
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        return tuple(img.size)
    finally:
        bpy.data.images.remove(img)


def _encode_builtin(frames, fps, out):
    width, height = _image_size(frames[0][1])
    scene = bpy.data.scenes.new("Blender Timelapse Encode")
    try:
        r = scene.render
        r.resolution_x, r.resolution_y = max(2, width // 2 * 2), max(2, height // 2 * 2)
        r.resolution_percentage = 100
        r.fps, r.fps_base = fps, 1.0
        r.use_sequencer, r.use_compositing = True, False
        r.image_settings.media_type = "VIDEO"
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        r.ffmpeg.constant_rate_factor = "HIGH"
        r.ffmpeg.ffmpeg_preset = "GOOD"
        r.ffmpeg.audio_codec = "NONE"
        r.use_file_extension = False
        r.filepath = str(out)
        # Frames are already display-referred; pass them through untouched.
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.frame_start, scene.frame_end = 1, len(frames)

        strip = scene.sequence_editor_create().strips.new_image(
            "Frames", str(frames[0][1]), 1, 1, fit_method="FIT")
        for _idx, path in frames[1:]:
            strip.elements.append(path.name)
        strip.frame_final_duration = len(frames)

        job.state, job.message = "RUNNING", "Encoding with Blender..."
        with bpy.context.temp_override(scene=scene):
            bpy.ops.render.render(animation=True, scene=scene.name)
    except RuntimeError as ex:
        job.state, job.message = "FAILED", "Encoding failed: %s" % ex
        raise TimelapseError(job.message) from ex
    finally:
        bpy.data.scenes.remove(scene)

    if not out.is_file():
        job.state, job.message = "FAILED", "Encoder produced no file"
        raise TimelapseError(job.message)
    job.state, job.done_frames, job.message = "DONE", job.total, "Saved %s" % out.name
