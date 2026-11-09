# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
from pathlib import Path

import bpy

from . import capture, previews, recorder, video
from .utils import TimelapseError


def _settings(context):
    return context.scene.blender_timelapse


class _Base:
    """Turn TimelapseError into a clean report instead of a traceback."""

    def execute(self, context):
        try:
            return self.run(context) or {"FINISHED"}
        except TimelapseError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}


class BT_OT_start(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.start"
    bl_label = "Start Recording"
    bl_description = "Start a new timelapse session in a new folder"

    @classmethod
    def poll(cls, context):
        return not recorder.is_active() and _settings(context).camera is not None

    def run(self, context):
        s = recorder.start(context.scene)
        self.report({"INFO"}, "Recording to %s" % s.folder)


class BT_OT_pause(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.pause"
    bl_label = "Pause"
    bl_description = "Pause captures. Elapsed time stops too"

    @classmethod
    def poll(cls, _context):
        s = recorder.get()
        return s is not None and s.state == recorder.RECORDING

    def run(self, _context):
        recorder.pause()


class BT_OT_resume(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.resume"
    bl_label = "Resume"
    bl_description = "Continue the paused session"

    @classmethod
    def poll(cls, _context):
        s = recorder.get()
        return s is not None and s.state == recorder.PAUSED

    def run(self, _context):
        recorder.resume()


class BT_OT_stop(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.stop"
    bl_label = "Stop Recording"
    bl_description = "Finish the session and write its metadata"

    @classmethod
    def poll(cls, _context):
        return recorder.is_active()

    def run(self, _context):
        recorder.stop("user")
        s = recorder.get()
        self.report({"INFO"}, "Recorded %d frames" % s.frames)


class BT_OT_capture_now(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.capture_now"
    bl_label = "Capture Now"
    bl_description = "Add one frame to the session immediately"

    @classmethod
    def poll(cls, _context):
        return recorder.is_active() and not capture.is_busy()

    def run(self, _context):
        recorder.capture_now()


class BT_OT_reset(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.reset"
    bl_label = "Reset Session"
    bl_description = "Stop and clear the session from the panel. Recorded files are kept"

    @classmethod
    def poll(cls, _context):
        return recorder.get() is not None

    def invoke(self, context, event):
        if recorder.is_active():
            return context.window_manager.invoke_confirm(self, event, message="Stop recording and reset?")
        return self.execute(context)

    def run(self, _context):
        recorder.reset()


class BT_OT_test_capture(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.test_capture"
    bl_label = "Test Capture"
    bl_description = "Render one preview frame with the current settings (not saved to a session)"

    @classmethod
    def poll(cls, context):
        return not recorder.is_active() and _settings(context).camera is not None and not capture.is_busy()

    def run(self, context):
        settings = _settings(context)
        snap = capture.snapshot(settings)
        folder = Path(tempfile.gettempdir()) / "blender_timelapse"
        folder.mkdir(exist_ok=True)
        path = folder / ("preview.%s" % capture.extension(snap))
        path.unlink(missing_ok=True)
        w, h = capture.render_frame(context.scene, settings.camera, snap, path, context.view_layer)
        previews.show(path)
        self.report({"INFO"}, "Test capture %d x %d" % (w, h))


class BT_OT_show_render(bpy.types.Operator):
    bl_idname = "blender_timelapse.show_render"
    bl_label = "View Last Capture"
    bl_description = "Show the last captured image in Blender's render view"

    def execute(self, _context):
        return bpy.ops.render.view_show("INVOKE_DEFAULT")


class BT_OT_camera_from_view(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.camera_from_view"
    bl_label = "New Camera from View"
    bl_description = "Add a camera matching this viewport and use it for recording. Your view is not changed"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.region_data is not None and not recorder.is_active()

    def run(self, context):
        rv3d = context.region_data
        data = bpy.data.cameras.new("Timelapse Camera")
        data.lens = context.space_data.lens
        if not rv3d.is_perspective:
            data.type = "ORTHO"
            data.ortho_scale = rv3d.view_distance * 2.0
        cam = bpy.data.objects.new("Timelapse Camera", data)
        cam.matrix_world = rv3d.view_matrix.inverted()
        context.scene.collection.objects.link(cam)
        _settings(context).camera = cam


class BT_OT_open_folder(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.open_folder"
    bl_label = "Open Folder"
    bl_description = "Open the session folder in the system file browser"

    @classmethod
    def poll(cls, _context):
        return recorder.get() is not None

    def run(self, _context):
        bpy.ops.wm.path_open(filepath=str(recorder.get().folder))


class BT_OT_generate_video(_Base, bpy.types.Operator):
    bl_idname = "blender_timelapse.generate_video"
    bl_label = "Generate Video"
    bl_description = "Encode the session's frames to MP4. Frames are kept"

    @classmethod
    def poll(cls, _context):
        s = recorder.get()
        return s is not None and s.state == recorder.STOPPED and video.job.state != "RUNNING"

    def run(self, context):
        settings = _settings(context)
        prefs = context.preferences.addons[__package__].preferences
        exe = video.find_ffmpeg(prefs.ffmpeg_path)
        if prefs.ffmpeg_path and exe is None:
            self.report({"WARNING"}, "FFmpeg path not found; using Blender's encoder")
        video.start(recorder.get().folder, settings.fps, settings.video_name, exe)
        if video.job.state == "DONE":
            self.report({"INFO"}, video.job.message)


class BT_OT_cancel_video(bpy.types.Operator):
    bl_idname = "blender_timelapse.cancel_video"
    bl_label = "Cancel"
    bl_description = "Stop encoding and delete the partial video"

    def execute(self, _context):
        video.cancel()
        return {"FINISHED"}


classes = (
    BT_OT_start, BT_OT_pause, BT_OT_resume, BT_OT_stop, BT_OT_capture_now, BT_OT_reset,
    BT_OT_test_capture, BT_OT_show_render, BT_OT_camera_from_view, BT_OT_open_folder,
    BT_OT_generate_video, BT_OT_cancel_video,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
