# Blender Timelapse

Record fixed-camera timelapses of your modelling while you keep working normally.

Pick a camera, press **Start Recording**, then model as usual. You can orbit, zoom, pan, edit, sculpt and undo. Every few seconds Blender Timelapse renders one frame from that camera in the background. Your viewport, selection and render settings are never changed. When you stop, you have a numbered image sequence, and one click turns it into an MP4.

- Version 1.0.0. Needs Blender 5.2 or newer; tested on 5.2.3 LTS.
- License: GPL-3.0-or-later.

---

## Installation

1. Download `blender_timelapse-1.0.0.zip`. Don't unzip it.
2. In Blender, open **Edit › Preferences › Get Extensions**.
3. Open the **⌄** menu in the top right and choose **Install from Disk…**, then pick the ZIP.
4. The extension is enabled straight away. Open a 3D Viewport, press **N**, and click the **Blender Timelapse** tab.

You can also drag the ZIP onto the Blender window, or install from the command line:

```
blender --command extension install-file -r user_default -e blender_timelapse-1.0.0.zip
```

## Quick start

1. **Set up a camera.** Use any perspective or orthographic camera. In the **Camera** section, the **+** button creates one that matches your current view.
2. **Check the framing.** **Test Capture** renders one frame with your settings and shows a thumbnail. The image button beside it opens the full render.
3. **Press Start Recording** and work. A red **REC** badge with the elapsed time and frame count appears in every 3D Viewport header.
4. **Pause**, **Resume** or **Capture Now** whenever you like.
5. **Stop Recording.** By default one last frame is taken.
6. In **Export**, choose the FPS and press **Generate Video**.

## Panel reference

| Section | Controls |
|---|---|
| **Camera** | The recording camera, **+** (new camera from view), camera type and lens, preview thumbnail, **Test Capture**, **View Last Capture** |
| **Recording** | **Start Recording**, **Pause / Resume**, **Stop Recording**, **Capture Now**, **Reset Session** (↺). Also shows the next-capture countdown and any errors. |
| **Settings** | **Interval** (1, 2, 5, 10, 30, 60 s or Custom), **Engine**, **Resolution** (25 / 50 / 75 / 100 % or Custom W×H), **Format** (PNG / JPEG + quality), **Folder**, **Project** |
| **Settings › Advanced** | **Samples Override** (EEVEE/Cycles, default 16), **Use Compositor**, **Capture Final Frame on Stop**, **Wait While Interacting** |
| **Session** | Status, elapsed time, frames, interval, image size, session folder, **Open Folder** |
| **Export** | **FPS** (24 / 30 / 60 / Custom), **File Name**, **Generate Video**, progress and result |

Settings are saved per scene in your .blend file.

**What you can change while recording:** only the interval. It takes effect from the next capture. Engine, resolution, format and folder are locked during a session, so every frame in a sequence matches.

### Choosing an engine

| Engine | Speed | Use when |
|---|---|---|
| **Workbench** (default) | Fastest | You want to keep modelling with no noticeable hitch. It uses the scene's *Render › Lighting / Color* settings, not your viewport's. |
| **EEVEE** | Medium; the first capture also compiles shaders | You want materials and lighting. |
| **Cycles** | Slow | You want the final look. Lower **Samples Override** to keep it practical. |
| **Scene Engine** | Depends on the scene | You want exactly what F12 would give you. |

## Output

```
<Folder>/                     (default: ~/BlenderTimelapse)
  <Project>/                  (default: the .blend file name, or "Untitled")
    Session_001/
      Frames/
        Frame_000001.png
        Frame_000002.png
        ...
      session_info.json       (camera, settings, frame count, times, status)
      timelapse.mp4           (after Generate Video)
    Session_002/
```

- Each **Start Recording** creates the next free `Session_NNN` folder. Existing sessions and files are never overwritten.
- If the folder can't be created or written, if the drive has less than 64 MB free, or if `//` is used in an unsaved file, recording refuses to start and tells you why.
- If the drive becomes unavailable during recording, recording pauses after 3 failed captures and shows the error.

## Video export

**Generate Video** writes `<File Name>.mp4` (H.264, yuv420p) into the session folder. If that file already exists, it writes `_2`, `_3` and so on. Frames are never deleted.

- If an `ffmpeg` executable is on your PATH, or set in **Preferences › Add-ons › Blender Timelapse › FFmpeg Executable**, it runs as a separate process. Blender stays responsive and a progress bar is shown.
- Otherwise Blender's built-in encoder is used, through a temporary scene that is deleted afterwards. Blender is busy until encoding finishes.

**Using another editor:** import `Frames/Frame_000001.png` as an image sequence. That works in Blender's Video Sequencer, DaVinci Resolve, Premiere, After Effects, Kdenlive and others. With ffmpeg:

```
ffmpeg -framerate 30 -i Frames/Frame_%06d.png -c:v libx264 -pix_fmt yuv420p -crf 18 timelapse.mp4
```

## How it stays out of your way

- Frames are rendered off-screen from the recording camera with `bpy.ops.render.render`. The viewport is never switched to camera view, and its view is never read or changed.
- To render, the add-on briefly overrides `scene.camera`, the engine, resolution, image format, samples, sequencer and compositor. All of these are restored in a guaranteed cleanup step, even if the render fails. Your camera, objects, selection, active object, workspace and frame are never touched.
- Captures never overlap and never happen more often than the interval. If a render takes longer than the interval, the next one waits until at least 0.5 s after it finishes.
- If you are dragging, orbiting or running another modal tool, the capture waits up to 3 s. You can turn this off with **Wait While Interacting**.
- The add-on never saves your .blend file. Opening another file, disabling the add-on or quitting Blender closes the session cleanly and writes its metadata.

## Known limitations

- **Captures briefly pause Blender.** Rendering has to happen on Blender's main thread, so each capture freezes the UI for as long as the render takes. Workbench at 25–50 % is barely noticeable on a normal GPU; EEVEE and Cycles cause a visible pause. Measured times are in the testing report.
- **Workbench captures use the scene's Render shading settings, not the viewport's.** Set them under *Render Properties › Lighting / Color*.
- **Objects hidden from render are not captured** (the camera icon in the Outliner), the same as with F12.
- **No compositor or VSE by default.** Only the active view layer is rendered and the Video Sequencer is ignored. Enable **Use Compositor** in Advanced if you need compositor effects.
- **The viewport cannot show the recording camera's view.** There is no reliable way to do this without changing your viewport. Use **Test Capture** / **View Last Capture**, or a second 3D Viewport with *View › Cameras › Active Camera*.
- **Sculpting with Multires or Dyntopo** may not show up in renders until you leave Sculpt Mode. This is a Blender behaviour.
- **The built-in encoder blocks Blender** while it runs. Install ffmpeg for non-blocking export.
- **The live session is lost if Blender crashes,** but all frames written so far stay on disk and `session_info.json` holds the last saved state.
- **One recording at a time,** from one camera (this is by design).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
