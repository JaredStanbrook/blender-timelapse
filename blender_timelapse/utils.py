# SPDX-License-Identifier: GPL-3.0-or-later
"""Small helpers with no recording state: paths, metadata, formatting, redraw."""

import json
import os
import re
import shutil
import tomllib
from pathlib import Path

import bpy

ROOT_FOLDER_NAME = "BlenderTimelapse"
FRAMES_FOLDER_NAME = "Frames"
METADATA_NAME = "session_info.json"
FRAME_PREFIX = "Frame_"
FRAME_DIGITS = 6
MIN_FREE_BYTES = 64 * 1024 * 1024
ADDON_VERSION = tomllib.loads((Path(__file__).parent / "blender_manifest.toml").read_text("utf-8"))["version"]

_FRAME_RE = re.compile(r"^%s(\d+)\.(png|jpg)$" % FRAME_PREFIX, re.IGNORECASE)
_SESSION_RE = re.compile(r"^Session_(\d+)$")


class TimelapseError(Exception):
    """An expected, user-facing problem (bad path, no camera, disk full...)."""


def format_duration(seconds):
    seconds = max(0, int(seconds))
    return "%02d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60)


def safe_name(name, fallback="Untitled"):
    """Make a string safe to use as a folder name on every platform."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or fallback


def project_name(settings):
    if settings.project_name.strip():
        return safe_name(settings.project_name)
    return safe_name(Path(bpy.data.filepath).stem) if bpy.data.filepath else "Untitled"


def output_root(settings):
    """Absolute root folder. Empty setting means ~/BlenderTimelapse."""
    raw = settings.output_dir.strip()
    if not raw:
        return Path.home() / ROOT_FOLDER_NAME
    if raw.startswith("//") and not bpy.data.filepath:
        raise TimelapseError("Output folder is relative ('//') but the .blend file is not saved yet")
    return Path(bpy.path.abspath(raw)).expanduser().resolve()


def frame_path(frames_dir, index, ext):
    return Path(frames_dir) / ("%s%0*d.%s" % (FRAME_PREFIX, FRAME_DIGITS, index, ext))


def list_frames(frames_dir):
    """Sorted [(index, Path)] of captured frames in a folder."""
    try:
        entries = os.listdir(frames_dir)
    except OSError:
        return []
    found = []
    for name in entries:
        m = _FRAME_RE.match(name)
        if m:
            found.append((int(m.group(1)), Path(frames_dir) / name))
    return sorted(found)


def check_writable(folder):
    """Raise TimelapseError unless we can create and write files in folder."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".bt_write_test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as ex:
        raise TimelapseError("Cannot write to '%s': %s" % (folder, ex.strerror or ex)) from ex
    check_free_space(folder)


def check_free_space(folder):
    try:
        free = shutil.disk_usage(folder).free
    except OSError as ex:
        raise TimelapseError("Output storage unavailable: %s" % (ex.strerror or ex)) from ex
    if free < MIN_FREE_BYTES:
        raise TimelapseError("Less than %d MB free on the output drive" % (MIN_FREE_BYTES // 2**20))


def create_session_dir(root, project):
    """Create root/project/Session_NNN/Frames with NNN one above the highest existing."""
    project_dir = Path(root) / project
    check_writable(project_dir)
    existing = [int(m.group(1)) for n in os.listdir(project_dir) if (m := _SESSION_RE.match(n))]
    number = max(existing, default=0) + 1
    while True:  # exist_ok=False guarantees we never reuse a folder, even if one appears meanwhile
        session_dir = project_dir / ("Session_%03d" % number)
        try:
            session_dir.mkdir()
            break
        except FileExistsError:
            number += 1
    (session_dir / FRAMES_FOLDER_NAME).mkdir()
    return session_dir


def unique_path(path):
    """Return path, or path with _2, _3... appended to the stem if it already exists."""
    path = Path(path)
    n = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name("%s_%d%s" % (path.stem, n, path.suffix))
        n += 1
    return candidate


def write_json_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def find_scene(session_uid):
    """Look a scene up by session_uid (survives renames and undo, unlike a Python reference)."""
    for scene in bpy.data.scenes:
        if scene.session_uid == session_uid:
            return scene
    return None


def redraw_viewports():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def any_window():
    wm = bpy.context.window_manager
    return bpy.context.window or (wm.windows[0] if wm and wm.windows else None)
