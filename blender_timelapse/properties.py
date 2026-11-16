# SPDX-License-Identifier: GPL-3.0-or-later
"""User settings, stored per scene in the .blend file. Runtime state lives in recorder.py."""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

INTERVAL_PRESETS = ("1", "2", "5", "10", "30", "60")
ENGINE_IDS = {"WORKBENCH": "BLENDER_WORKBENCH", "EEVEE": "BLENDER_EEVEE", "CYCLES": "CYCLES"}


def _is_camera(_self, obj):
    return obj.type == "CAMERA"


class BT_Settings(bpy.types.PropertyGroup):
    camera: PointerProperty(
        name="Recording Camera",
        type=bpy.types.Object,
        poll=_is_camera,
        description="Camera every timelapse frame is rendered from. Your viewport is never changed",
    )

    interval_preset: EnumProperty(
        name="Interval",
        description="Time between captures",
        items=[(p, "%ss" % p, "Capture every %s second%s" % (p, "" if p == "1" else "s")) for p in INTERVAL_PRESETS]
        + [("CUSTOM", "Custom", "Use a custom interval"),
           ("MANUAL", "Manual", "No automatic captures: only Capture Now (Ctrl Shift F12) adds photos")],
        default="5",
    )
    interval_custom: FloatProperty(
        name="Seconds", description="Custom time between captures",
        default=15.0, min=0.5, max=3600.0, soft_max=600.0, unit="TIME_ABSOLUTE",
    )

    resolution_preset: EnumProperty(
        name="Resolution",
        description="Capture size relative to the scene's render resolution",
        items=[
            ("25", "25%", "Quarter of the scene resolution (fastest)"),
            ("50", "50%", "Half of the scene resolution"),
            ("75", "75%", "Three quarters of the scene resolution"),
            ("100", "100%", "Full scene resolution"),
            ("CUSTOM", "Custom", "Explicit width and height"),
        ],
        default="50",
    )
    custom_width: IntProperty(name="Width", default=1920, min=16, max=16384, subtype="PIXEL")
    custom_height: IntProperty(name="Height", default=1080, min=16, max=16384, subtype="PIXEL")

    image_format: EnumProperty(
        name="Format",
        items=[("PNG", "PNG", "Lossless, larger files"), ("JPEG", "JPEG", "Lossy, small files")],
        default="PNG",
    )
    jpeg_quality: IntProperty(name="Quality", default=90, min=1, max=100, subtype="PERCENTAGE")

    engine: EnumProperty(
        name="Engine",
        description="Render engine used for captures only; the scene's engine is restored afterwards",
        items=[
            ("WORKBENCH", "Workbench", "Fast solid shading. Best for working while recording"),
            ("EEVEE", "EEVEE", "Real-time materials and lighting"),
            ("CYCLES", "Cycles", "Path traced. Slow; lower samples in Advanced"),
            ("SCENE", "Scene Engine", "Use whatever engine the scene is set to"),
        ],
        default="WORKBENCH",
    )

    output_dir: StringProperty(
        name="Output Folder",
        description="Root folder for recordings. Empty uses ~/BlenderTimelapse",
        subtype="DIR_PATH",
        default="",
    )
    project_name: StringProperty(
        name="Project Name", description="Sub-folder name. Empty uses the .blend file name", default="",
    )

    # Advanced
    samples: IntProperty(
        name="Samples Override",
        description="EEVEE / Cycles samples used for captures. 0 keeps the scene's value",
        default=16, min=0, soft_max=512,
    )
    use_compositor: BoolProperty(
        name="Use Compositor",
        description="Run the scene compositor on captures (slower). Off renders only the active view layer",
        default=False,
    )
    capture_on_stop: BoolProperty(
        name="Capture Final Frame on Stop", description="Take one last frame when recording stops", default=True,
    )
    defer_while_busy: BoolProperty(
        name="Wait While Interacting",
        description="Delay a capture (up to 3 s) while you are dragging, orbiting or using another modal tool",
        default=True,
    )
    show_look: BoolProperty(name="Show Look", default=False, options={"HIDDEN"})
    show_soundtrack: BoolProperty(name="Show Soundtrack", default=False, options={"HIDDEN"})

    # Export
    fps_preset: EnumProperty(
        name="FPS",
        items=[("24", "24", ""), ("30", "30", ""), ("60", "60", ""), ("CUSTOM", "Custom", "")],
        default="30",
    )
    fps_custom: IntProperty(name="Custom FPS", default=12, min=1, max=240)
    photo_duration: FloatProperty(
        name="Duration per Photo",
        description="How long each captured photo stays on screen in the video. Change it and export again any time",
        default=1.0, min=0.01, soft_min=0.04, max=600.0, soft_max=10.0, step=10, precision=2, unit="TIME_ABSOLUTE",
    )
    use_soundtrack: BoolProperty(name="Soundtrack", description="Add music to the exported video", default=False)
    soundtrack_path: StringProperty(
        name="Music", description="Audio file to play under the video (MP3, WAV, OGG, FLAC, M4A...)",
        subtype="FILE_PATH", default="",
    )
    soundtrack_start: FloatProperty(
        name="Start At", description="Where in the music file playback begins. The music is cut when the video ends",
        default=0.0, min=0.0, soft_max=600.0, unit="TIME_ABSOLUTE",
    )
    soundtrack_fade: FloatProperty(
        name="Fade Out", description="Fade the music out over the last seconds of the video. 0 cuts it hard",
        default=2.0, min=0.0, max=30.0, unit="TIME_ABSOLUTE",
    )
    use_look: BoolProperty(name="Look", description="Colour-grade the exported video (photos are not changed)",
                           default=False)
    look_exposure: FloatProperty(name="Exposure", description="Brightness in stops (+1 doubles the light)",
                                 default=0.0, min=-4.0, max=4.0, soft_min=-2.0, soft_max=2.0, step=10)
    look_contrast: FloatProperty(name="Contrast", description="1 is unchanged, below 1 flatter, above 1 punchier",
                                 default=1.0, min=0.0, max=3.0, soft_max=2.0, step=5)
    look_saturation: FloatProperty(name="Saturation", description="1 is unchanged, 0 is black and white",
                                   default=1.0, min=0.0, max=3.0, soft_max=2.0, step=5)
    look_lut_path: StringProperty(
        name="LUT", description="Optional 3D .cube LUT applied after the sliders (e.g. a film emulation look)",
        subtype="FILE_PATH", default="",
    )
    video_name: StringProperty(name="File Name", default="timelapse", description="Video file name, without extension")
    export_folder: StringProperty(
        name="Session",
        description="Session folder to export. Set automatically when you record; pick any earlier session to re-export it",
        subtype="DIR_PATH",
        default="",
    )

    @property
    def interval(self):
        """Seconds between automatic captures, or None for manual-only sessions."""
        if self.interval_preset == "MANUAL":
            return None
        return self.interval_custom if self.interval_preset == "CUSTOM" else float(self.interval_preset)

    @property
    def fps(self):
        return self.fps_custom if self.fps_preset == "CUSTOM" else int(self.fps_preset)

    @property
    def frames_per_photo(self):
        """Frames per photo = Duration per photo × FPS (rounded to whole frames, at least 1)."""
        return frames_per_photo(self.photo_duration, self.fps)


def frames_per_photo(duration, fps):
    return max(1, round(duration * fps))


class BT_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    ffmpeg_path: StringProperty(
        name="FFmpeg Executable",
        description="Optional path to an ffmpeg executable. Empty searches the system PATH, "
        "then falls back to Blender's built-in encoder",
        subtype="FILE_PATH",
        default="",
    )

    def draw(self, _context):
        self.layout.prop(self, "ffmpeg_path")


classes = (BT_Settings, BT_Preferences)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blender_timelapse = PointerProperty(type=BT_Settings)


def unregister():
    del bpy.types.Scene.blender_timelapse
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
