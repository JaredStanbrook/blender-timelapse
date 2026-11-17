# Blender Timelapse

Record fixed-camera timelapses of your modelling while you keep working normally.

Pick a camera, press **Start Recording**, then model as usual. You can orbit, zoom, pan, edit, sculpt and undo. Every few seconds Blender Timelapse renders one frame from that camera in the background. Your viewport, selection and render settings are never changed. When you stop, you have a numbered image sequence, and one click turns it into an MP4.

- Version 1.1.0. Needs Blender 5.2 or newer; tested on 5.2.3 LTS.
- License: GPL-3.0-or-later.

---

## Installation

1. Download `blender_timelapse-1.0.0.zip`. Don't unzip it.
2. In Blender, open **Edit › Preferences › Get Extensions**.
3. Open the **⌄** menu in the top right and choose **Install from Disk…**, then pick the ZIP.
4. The extension is enabled straight away. Open a 3D Viewport, press **N**, and click the **Blender Timelapse** tab.

You can also drag the ZIP onto the Blender window, or install from the command line:

```
blender --command extension install-file -r user_default -e blender_timelapse-1.1.0.zip
```

## Quick start

1. **Set up a camera.** Use any perspective or orthographic camera. In the **Camera** section, the **+** button creates one that matches your current view.
2. **Check the framing.** **Test Capture** renders one frame with your settings and shows a thumbnail. The image button beside it opens the full render.
3. **Press Start Recording** and work. A red **REC** badge with the elapsed time and frame count appears in every 3D Viewport header.
4. **Pause**, **Resume** or **Capture Now** whenever you like. Capture Now's shortcut is **Ctrl Shift F12**, and it works in any editor.
5. **Stop Recording.** By default one last frame is taken.
6. In **Export**, set **Per Photo** (how long each photo is shown) and **FPS**, then press **Generate Video**. You can change either setting and export again as often as you like.

**Only want photos you take yourself?** Set **Interval** to **Manual**. The session then captures nothing on its own, and only **Capture Now** (or Ctrl Shift F12) adds a photo. This suits step-by-step builds, for example a piece of furniture photographed after each stage.

## Panel reference

| Section | Controls |
|---|---|
| **Camera** | The recording camera, **+** (new camera from view), camera type and lens, preview thumbnail, **Test Capture**, **View Last Capture** |
| **Recording** | **Start Recording**, **Pause / Resume**, **Stop Recording**, **Capture Now** (Ctrl Shift F12), **Reset Session** (↺). Also shows the next-capture countdown (or "Manual") and any errors. |
| **Settings** | **Interval** (1, 2, 5, 10, 30, 60 s, Custom, or Manual), **Engine**, **Resolution** (25 / 50 / 75 / 100 % or Custom W×H), **Format** (PNG / JPEG + quality), **Folder**, **Project** |
| **Settings › Advanced** | **Samples Override** (EEVEE/Cycles, default 16), **Use Compositor**, **Capture Final Frame on Stop**, **Wait While Interacting** |
| **Session** | Status, elapsed time, frames, interval, image size, session folder, **Open Folder** |
| **Export** | **Session** (the latest one by default, ⌄ to reopen any earlier session), **Per Photo** (seconds each photo is shown), **FPS** (24 / 30 / 60 / Custom), **File Name**; a summary of photos, frames per photo, total frames and **Video Length**; **Generate Video**, progress and result |

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

Two settings control the video, and neither is ever locked:

- **Per Photo**: how many seconds each captured photo stays on screen.
- **FPS**: frames per second of the video.

Each photo is repeated for **Per Photo × FPS** frames (rounded to whole frames, at least 1). The video is **photos × Per Photo** seconds long, and the Export panel shows the result before you export.

| Photos | Per Photo | FPS | Frames per photo | Total frames | Video length |
|---|---|---|---|---|---|
| 60 | 1 s | 30 | 30 | 1,800 | 1:00 |
| 60 | 2 s | 30 | 60 | 3,600 | 2:00 |
| 600 | 0.1 s | 30 | 3 | 1,800 | 1:00 (a fast timelapse) |

**Export again as often as you like.**
- Every export reads the photos with the settings as they are at that moment, and writes a new file.
- `<File Name>.mp4` becomes `_2`, `_3` and so on, so earlier videos are kept.
- The captured photos are only ever read, never modified, moved or deleted, so you never need to recapture.

**Look (colour grading).** Tick **Look** in Export to grade the video as it's made. The settings are:

| Setting | Effect |
|---|---|
| **Exposure** | Brightness in stops. +1 doubles the light, −1 halves it. |
| **Contrast** | 1 is unchanged, below 1 is flatter, above 1 is punchier. Mid-grey stays put. |
| **Saturation** | 1 is unchanged, 0 is black and white, above 1 is more vivid. |
| **LUT** | An optional 3D `.cube` file, applied after the sliders. Use one for a ready-made look such as film emulation or teal-orange. DaVinci Resolve, Photoshop, Affinity and many free packs export `.cube` files. |

- **Preview Look** shows the middle photo of the selected session with the look applied, so you can check it without exporting.
- **↺** resets everything to neutral.
- Like the other export settings, the look is applied only to the video and never to your photos. Change it and export again whenever you like.
- With the external ffmpeg, grading happens inside ffmpeg and Blender stays responsive.
- With Blender's built-in encoder, each photo is graded once into a temporary folder, which is deleted afterwards, and a progress indicator shows on the cursor.
- Both encoders use the same maths and give the same result.

**Want more than that?** For colour wheels, curves, masks or a different grade per shot, import `Frames/` as an image sequence into Blender's Video Sequencer or DaVinci Resolve.

**Grade the captures themselves instead?** *Render Properties › Color Management* (exposure, gamma, look, curves) also affects captures, because they render like F12. That is baked into the photos when they're taken, though, so the Look section is usually the better place.

**Soundtrack.** Tick **Soundtrack** in Export and pick a music file (MP3, WAV, OGG, FLAC, M4A, …).

- **Start At** chooses where in the music file playback begins, so you can skip an intro.
- The music always stops when the video ends. If the track runs out first, the rest of the video is silent, and the panel warns you before you export.
- **Fade Out** (default 2 s, 0 for a hard cut) fades the music out over the end of whatever part plays.
- The panel shows the track length and exactly which part will be heard, for example "Plays 0:30 – 1:30".
- The music file is only read, never changed. Each export is a new file, so you can try different tracks or start points freely.

**Re-exporting an older session.** The **Session** row in Export points to the session you recorded most recently. Its ⌄ menu lists every session in the current project with its photo count, and **Browse…** opens any session folder, or its `Frames` folder, from anywhere. You can export an earlier session even while a new one is recording; only the session currently being recorded can't be exported.

- If an `ffmpeg` executable is on your PATH, or set in **Preferences › Add-ons › Blender Timelapse › FFmpeg Executable**, it runs as a separate process. Blender stays responsive and a progress bar is shown.
- Otherwise Blender's built-in encoder is used, through a temporary scene that is deleted afterwards. Blender is busy until encoding finishes.

**Using another editor:** import `Frames/Frame_000001.png` as an image sequence. That works in Blender's Video Sequencer, DaVinci Resolve, Premiere, After Effects, Kdenlive and others. With ffmpeg:

```
# 1 s per photo at 30 FPS:  -framerate = FPS / frames-per-photo
ffmpeg -framerate 30/30 -i Frames/Frame_%06d.png -vf fps=30 -c:v libx264 -pix_fmt yuv420p -crf 18 timelapse.mp4
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
