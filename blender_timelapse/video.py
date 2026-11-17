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
import tempfile
from pathlib import Path

import bpy

from . import grade
from .utils import TimelapseError, frame_path, list_frames, redraw_viewports, safe_name, unique_path

POLL = 0.5
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".aif", ".aiff", ".wma")

_audio_cache = {}


class Soundtrack:
    """Music laid under the video: played from `start` seconds into the file, cut at the video's end."""

    def __init__(self, path, start=0.0, fade=0.0):
        self.path, self.start, self.fade = Path(path), max(0.0, start), max(0.0, fade)

    def window(self, video_seconds):
        """(seconds of music actually heard, second at which the fade-out begins)."""
        heard = max(0.0, min(video_seconds, audio_length(self.path) - self.start))
        return heard, max(0.0, heard - self.fade)


def audio_length(path):
    """Length of an audio file in seconds, read with Blender's audio library (no datablock is created)."""
    path = Path(path)
    try:
        key = (path, path.stat().st_mtime_ns)
    except OSError as ex:
        raise TimelapseError("Soundtrack not found: %s" % path) from ex
    if key not in _audio_cache:
        import aud
        try:
            sound = aud.Sound(str(path))
            _audio_cache[key] = sound.length / sound.specs[0]
        except Exception as ex:  # aud raises plain Exception for unreadable files
            raise TimelapseError("Can't read soundtrack '%s': %s" % (path.name, ex)) from ex
    return _audio_cache[key]


def soundtrack_from(settings):
    """The Soundtrack configured in the panel, or None. Raises TimelapseError if it can't be used."""
    if not settings.use_soundtrack:
        return None
    if not settings.soundtrack_path:
        raise TimelapseError("Choose a music file, or turn the soundtrack off")
    track = Soundtrack(bpy.path.abspath(settings.soundtrack_path), settings.soundtrack_start,
                       settings.soundtrack_fade)
    length = audio_length(track.path)
    if track.start >= length:
        raise TimelapseError("Start At is past the end of the track (%.1f s long)" % length)
    return track


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


def plan(photos, fps, per_photo):
    """(total video frames, video seconds) for an export: each photo is held for per_photo frames."""
    total = photos * per_photo
    return total, total / fps


def start(session_folder, fps, per_photo, name, ffmpeg_exe, soundtrack=None, look=None):
    """Encode every photo held for per_photo frames at fps, with optional music.

    Reads the photos only; they are never modified. Returns immediately for external
    FFmpeg, blocks for the built-in path.
    """
    if job.state == "RUNNING":
        raise TimelapseError("A video is already being generated")
    frames_dir = Path(session_folder) / "Frames"
    frames = list_frames(frames_dir)
    if not frames:
        raise TimelapseError("No captured photos in '%s'" % frames_dir)
    if len({p.suffix.lower() for _i, p in frames}) > 1:
        raise TimelapseError("Frames folder mixes PNG and JPEG files")
    out = output_path(session_folder, name)

    job.__init__()
    job.total = plan(len(frames), fps, per_photo)[0]
    job.output = out
    if ffmpeg_exe and _contiguous(frames):
        _start_external(ffmpeg_exe, frames, frames_dir, fps, per_photo, out, soundtrack, look)
    else:
        _encode_builtin(frames, fps, per_photo, out, soundtrack, look)


def _audio_args(track, fps):
    """Extra ffmpeg arguments that lay the soundtrack under the video, cut to the video length."""
    seconds = job.total / fps
    heard, fade_at = track.window(seconds)
    args = ["-ss", "%.3f" % track.start, "-i", str(track.path), "-map", "0:v:0", "-map", "1:a:0",
            "-c:a", "aac", "-b:a", "192k", "-t", "%.3f" % seconds]
    if track.fade > 0 and heard > 0:
        args += ["-af", "afade=t=out:st=%.3f:d=%.3f" % (fade_at, heard - fade_at)]
    return args


def _start_external(exe, frames, frames_dir, fps, per_photo, out, soundtrack=None, look=None):
    first = frames[0][0]
    pattern = str(frame_path(frames_dir, 0, frames[0][1].suffix[1:])).replace("000000", "%06d")
    job.progress_file = out.with_suffix(".progress.txt")
    log_path = out.with_suffix(".ffmpeg.log")
    cmd = [
        exe, "-hide_banner", "-nostdin", "-n",
        # Photos are read at fps/per_photo and resampled to fps, so each is repeated per_photo times.
        "-framerate", "%d/%d" % (fps, per_photo), "-start_number", str(first), "-i", pattern,
        *(_audio_args(soundtrack, fps) if soundtrack else []),
        "-vf", ",".join(grade.ffmpeg_filters(look) + ["scale=trunc(iw/2)*2:trunc(ih/2)*2", "fps=%d" % fps,
                                                       "format=yuv420p"]), "-r", str(fps),
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


def _add_builtin_audio(scene, track, fps):
    """Sound strip shifted so frame 1 plays `start` seconds into the file; volume fades to 0 at the end."""
    heard, fade_at = track.window(job.total / fps)
    if heard <= 0:
        return
    r = scene.render
    r.ffmpeg.audio_codec = "AAC"
    r.ffmpeg.audio_bitrate = 192
    r.ffmpeg.audio_channels = "STEREO"
    r.ffmpeg.audio_mixrate = 48000
    strip = scene.sequence_editor.strips.new_sound("Soundtrack", str(track.path), 2, 1 - round(track.start * fps))
    end = 1 + round(heard * fps)  # never past the video or the music
    strip.frame_final_start, strip.frame_final_end = 1, end
    if track.fade > 0:
        strip.volume = 1.0
        strip.keyframe_insert("volume", frame=1 + round(fade_at * fps))
        strip.volume = 0.0
        strip.keyframe_insert("volume", frame=end)


def _graded_copies(frames, look, folder):
    """Graded PNG copies of the photos in a temporary folder; the originals are only read."""
    wm = bpy.context.window_manager
    if wm:
        wm.progress_begin(0, len(frames))
    try:
        graded = []
        for n, (idx, path) in enumerate(frames):
            dst = Path(folder) / (path.stem + ".png")
            grade.grade_file(path, dst, look)
            graded.append((idx, dst))
            if wm:
                wm.progress_update(n)
        return graded
    finally:
        if wm:
            wm.progress_end()


def _encode_builtin(frames, fps, per_photo, out, soundtrack=None, look=None):
    if look is not None:
        with tempfile.TemporaryDirectory(prefix="blender_timelapse_") as tmp:
            job.message = "Applying look..."
            return _encode_builtin(_graded_copies(frames, look, tmp), fps, per_photo, out, soundtrack)
    width, height = _image_size(frames[0][1])
    sounds_before, actions_before = set(bpy.data.sounds), set(bpy.data.actions)
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
        scene.frame_start, scene.frame_end = 1, job.total

        strip = scene.sequence_editor_create().strips.new_image(
            "Frames", str(frames[0][1]), 1, 1, fit_method="FIT")
        # Each photo appears per_photo times in a row: element i is shown on frame i.
        for _ in range(per_photo - 1):
            strip.elements.append(frames[0][1].name)
        for _idx, path in frames[1:]:
            for _ in range(per_photo):
                strip.elements.append(path.name)
        strip.frame_final_duration = job.total
        if soundtrack:
            _add_builtin_audio(scene, soundtrack, fps)

        job.state, job.message = "RUNNING", "Encoding with Blender..."
        with bpy.context.temp_override(scene=scene):
            bpy.ops.render.render(animation=True, scene=scene.name)
    except RuntimeError as ex:
        job.state, job.message = "FAILED", "Encoding failed: %s" % ex
        raise TimelapseError(job.message) from ex
    finally:
        bpy.data.scenes.remove(scene)
        # The sound strip and fade keyframes create datablocks; never leave them in the user's file.
        for sound in set(bpy.data.sounds) - sounds_before:
            bpy.data.sounds.remove(sound)
        for action in set(bpy.data.actions) - actions_before:
            bpy.data.actions.remove(action)

    if not out.is_file():
        job.state, job.message = "FAILED", "Encoder produced no file"
        raise TimelapseError(job.message)
    job.state, job.done_frames, job.message = "DONE", job.total, "Saved %s" % out.name
