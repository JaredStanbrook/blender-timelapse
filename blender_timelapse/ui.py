# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from . import capture, previews, recorder, video
from .utils import output_root, project_name, TimelapseError

CATEGORY = "Blender Timelapse"


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


def _row(layout, label, value, icon="NONE"):
    split = layout.split(factor=0.42)
    split.label(text=label)
    split.label(text=value, icon=icon)


class BT_PT_main(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_main"
    bl_label = "Blender Timelapse"

    def draw_header(self, _context):
        s = recorder.get()
        if s and s.state == recorder.RECORDING:
            self.layout.label(icon="REC")

    def draw(self, context):
        s = recorder.get()
        row = self.layout.row()
        row.alert = s is not None and s.state == recorder.RECORDING
        text = recorder.status_text(s)
        if s:
            text += "  %s  ·  %d frames" % (recorder.elapsed_text(s), s.frames)
        row.label(text=text, icon={"Recording": "REC", "Paused": "PAUSE", "Stopped": "CHECKMARK"}.get(
            recorder.status_text(s), "INFO"))


class BT_PT_camera(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_camera"
    bl_label = "Camera"
    bl_parent_id = "BT_PT_main"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blender_timelapse
        active = recorder.is_active()

        row = layout.row(align=True)
        row.enabled = not active
        row.prop(settings, "camera", text="")
        row.operator("blender_timelapse.camera_from_view", text="", icon="ADD")

        cam = settings.camera
        if cam is None:
            layout.label(text="Pick a camera to record from", icon="ERROR")
        elif cam.name not in context.scene.objects:
            layout.label(text="Camera is not in this scene", icon="ERROR")
        else:
            data = cam.data
            kind = "Orthographic %.2f" % data.ortho_scale if data.type == "ORTHO" else "%s %.0f mm" % (
                data.type.title(), data.lens)
            layout.label(text=kind, icon="OUTLINER_DATA_CAMERA")

        icon = previews.icon_id()
        if icon:
            layout.template_icon(icon_value=icon, scale=7.0)
        row = layout.row(align=True)
        row.operator("blender_timelapse.test_capture", icon="RENDER_STILL")
        row.operator("blender_timelapse.show_render", text="", icon="IMAGE_DATA")


class BT_PT_recording(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_recording"
    bl_label = "Recording"
    bl_parent_id = "BT_PT_main"

    def draw(self, context):
        layout = self.layout
        s = recorder.get()
        state = s.state if s else recorder.IDLE

        if state in (recorder.RECORDING, recorder.PAUSED):
            row = layout.row(align=True)
            row.scale_y = 1.6
            if state == recorder.RECORDING:
                row.operator("blender_timelapse.pause", icon="PAUSE")
            else:
                row.operator("blender_timelapse.resume", icon="PLAY")
            row.operator("blender_timelapse.stop", icon="SNAP_FACE")
            row = layout.row(align=True)
            row.operator("blender_timelapse.capture_now", icon="RENDER_STILL")
            row.operator("blender_timelapse.reset", text="", icon="LOOP_BACK")
        else:
            col = layout.column()
            col.scale_y = 2.0
            col.alert = True
            col.operator("blender_timelapse.start", icon="REC")
            if s:
                layout.operator("blender_timelapse.reset", icon="LOOP_BACK")

        if s is None:
            return
        if s.last_error:
            box = layout.box()
            box.alert = True
            box.label(text=s.last_error, icon="ERROR")
        if state == recorder.RECORDING:
            cd = s.countdown()
            if capture.is_busy():
                layout.label(text="Capturing...", icon="RENDER_STILL")
            elif s.deferred_since is not None:
                layout.label(text="Waiting for you to finish...", icon="TIME")
            else:
                layout.label(text="Next capture in %.0f s" % max(cd, 0), icon="TIME")
            if s.slow:
                layout.label(text="Capture took %.1f s (> interval)" % s.last_duration, icon="INFO")


class BT_PT_settings(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_settings"
    bl_label = "Settings"
    bl_parent_id = "BT_PT_main"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.blender_timelapse
        locked = recorder.is_active()

        col = layout.column()  # interval may change mid-session
        col.prop(settings, "interval_preset")
        if settings.interval_preset == "CUSTOM":
            col.prop(settings, "interval_custom")

        col = layout.column()
        col.enabled = not locked  # keep one session's frames consistent
        col.prop(settings, "engine")
        col.prop(settings, "resolution_preset")
        if settings.resolution_preset == "CUSTOM":
            sub = col.column(align=True)
            sub.prop(settings, "custom_width")
            sub.prop(settings, "custom_height")
        else:
            r = context.scene.render
            pct = int(settings.resolution_preset)
            col.label(text="%d x %d px" % (r.resolution_x * pct // 100, r.resolution_y * pct // 100))
        col.prop(settings, "image_format")
        if settings.image_format == "JPEG":
            col.prop(settings, "jpeg_quality")
        col.prop(settings, "output_dir", text="Folder")
        col.prop(settings, "project_name", text="Project", placeholder=bpy.path.display_name_from_filepath(bpy.data.filepath) or "Untitled")
        if locked:
            col.label(text="Locked while recording", icon="LOCKED")


class BT_PT_advanced(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_advanced"
    bl_label = "Advanced"
    bl_parent_id = "BT_PT_settings"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.blender_timelapse
        col = layout.column()
        col.enabled = not recorder.is_active()
        col.prop(settings, "samples")
        col.prop(settings, "use_compositor")
        layout.prop(settings, "capture_on_stop")
        layout.prop(settings, "defer_while_busy")


class BT_PT_session(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_session"
    bl_label = "Session"
    bl_parent_id = "BT_PT_main"

    def draw(self, context):
        layout = self.layout
        s = recorder.get()
        if s is None:
            try:
                root = output_root(context.scene.blender_timelapse)
                layout.label(text=str(root / project_name(context.scene.blender_timelapse)), icon="FILE_FOLDER")
            except TimelapseError as ex:
                layout.label(text=str(ex), icon="ERROR")
            return
        col = layout.column(align=True)
        _row(col, "Status", recorder.status_text(s))
        _row(col, "Elapsed", recorder.elapsed_text(s))
        _row(col, "Frames", str(s.frames))
        _row(col, "Interval", "%g s" % context.scene.blender_timelapse.interval)
        if s.resolution:
            _row(col, "Size", "%d x %d %s" % (*s.resolution, s.ext.upper()))
        _row(col, "Folder", s.folder.name)
        layout.label(text=str(s.folder.parent), icon="FILE_FOLDER")
        layout.operator("blender_timelapse.open_folder", icon="FOLDER_REDIRECT")


class BT_PT_export(_Panel, bpy.types.Panel):
    bl_idname = "BT_PT_export"
    bl_label = "Export"
    bl_parent_id = "BT_PT_main"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.blender_timelapse
        col = layout.column()
        col.prop(settings, "fps_preset")
        if settings.fps_preset == "CUSTOM":
            col.prop(settings, "fps_custom")
        col.prop(settings, "video_name")

        s = recorder.get()
        if s and s.frames:
            layout.label(text="%d frames → %.1f s of video" % (s.frames, s.frames / settings.fps), icon="TIME")

        job = video.job
        if job.state == "RUNNING":
            row = layout.row(align=True)
            row.progress(factor=job.progress, text=job.message)
            row.operator("blender_timelapse.cancel_video", text="", icon="X")
        else:
            row = layout.row()
            row.scale_y = 1.4
            row.operator("blender_timelapse.generate_video", icon="FILE_MOVIE")
            if s and s.state != recorder.STOPPED:
                layout.label(text="Stop recording to export", icon="INFO")
            if job.message:
                layout.label(text=job.message, icon="CHECKMARK" if job.state == "DONE" else "ERROR")


def draw_header_indicator(self, _context):
    """Small REC badge in every 3D Viewport header, so the state is visible with the N-panel closed."""
    s = recorder.get()
    if s is None or s.state not in (recorder.RECORDING, recorder.PAUSED):
        return
    row = self.layout.row(align=True)
    row.alert = s.state == recorder.RECORDING
    row.label(text="%s %s · %d" % ("REC" if row.alert else "PAUSED", recorder.elapsed_text(s), s.frames),
              icon="REC" if row.alert else "PAUSE")


classes = (BT_PT_main, BT_PT_camera, BT_PT_recording, BT_PT_settings, BT_PT_advanced, BT_PT_session, BT_PT_export)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_HT_header.append(draw_header_indicator)


def unregister():
    bpy.types.VIEW3D_HT_header.remove(draw_header_indicator)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
