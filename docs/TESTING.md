# Testing Report: Blender Timelapse 1.1.0

**Result: all 168 automated checks pass.** 129 run in background mode, 38 in the interactive GUI, and 1 checks quitting mid-recording. The whole suite was run twice in a row on the final code and both runs passed. Nothing failed and no check was skipped.

Version 1.1.0 added the export and capture changes from the implementation brief. Their acceptance criteria are covered in the next section, and the original 1.0.0 scenarios further down still pass unchanged.

## 1.1.0 acceptance criteria

| Criterion | Result | How it was checked |
|---|---|---|
| Captures use the selected fixed-angle camera | ✅ | The `render_pre` probe still sees the recording camera on every capture. The 1.0.0 navigation test still produces pixel-identical frames. |
| Images are saved in chronological order | ✅ | Files are `Frame_000001…000006` in capture order, and their modification times never decrease. |
| Each image is repeated for the configured duration | ✅ | Four flat-grey photos at 15 frames per photo: the picture changes on exactly frames 15, 30 and 45 (60 frames in all), with both the ffmpeg and the built-in encoder. |
| FPS determines the number of frames per second | ✅ | ffprobe reports a frame rate of 24/1, 30/1 or 60/1, matching the setting. |
| Video duration = photos × duration per photo | ✅ | 6 photos at 1 s / 30 FPS: 180 frames and 6.0 s. At 2 s / 30 FPS: 360 frames and 12.0 s. At 0.5 s / 24 FPS: 72 frames and 3.0 s. At 2 s / 60 FPS (built-in encoder): 720 frames and 12.0 s. The panel's `video.plan` gives the same totals. |
| Settings remain editable after stopping | ✅ | Duration and FPS were changed between exports and after them. The Export panel never disables them. |
| Users can export repeatedly with different settings | ✅ | Five exports of one session, each with different settings and each to a new file (`video`, `video_2`, …). |
| Original captures are preserved across every export | ✅ | The SHA-256 hash and modification time of every photo were identical after each of the five exports. |
| Completed sessions can be reopened and exported | ✅ | After **Reset Session**, **Open Session** on the session's `Frames` folder selected the session, and an export at 0.25 s / 24 FPS gave 36 frames. A folder with no photos is refused. An older session can be exported while a new one is recording. The session being recorded can't be exported. |
| Existing session and capture functionality still works | ✅ | All 1.0.0 checks still pass. |
| Manual capture with a button and a shortcut | ✅ | In **Manual** mode there are no automatic captures and Capture Now adds a photo. Capture Now also works while paused. Switching to automatic mid-session resumes scheduling. Without a session, Capture Now explains that you need to start one. The Ctrl+Shift+F12 shortcut is registered in the global Screen keymap and removed when the add-on is disabled. This was checked against Blender 5.2's default keymap: the combination wasn't already used. |


## Test environment

- **Blender:** 5.2.3 LTS (hash `e13b728c6880`, official Linux x64 build, bundled Python 3.13.13)
- **OS:** Linux x64 (container) with the Xvfb virtual display. GPU: none. Mesa llvmpipe software OpenGL on 4 CPU cores.
- **FFmpeg:** 6.1.1 (system) for external encoding; Blender's bundled FFmpeg for the built-in path.
- **Install path tested:** `blender --command extension build` produces the ZIP, then `extension install-file -r user_default -e` installs it into a clean, isolated user profile. The tests use the installed extension, not the source folder.

Reproduce with:

```
tests/run_tests.sh /path/to/blender      # needs xvfb-run on Linux; exits non-zero on any failure
```

| Script | Mode | What it does |
|---|---|---|
| `tests/test_background.py` | `blender -b` | Drives the recorder API directly. Covers formats, resolutions, engines, paths, video, file reload and add-on disable. |
| `tests/test_gui.py` | Full UI, real event loop | A scripted user session: real `bpy.app.timers`, the real UI operators, and real `view3d.view_orbit` / `view_pan` / `zoom`, Edit Mode, Sculpt Mode, undo and redo, then disabling the add-on mid-recording. |
| `tests/test_quit.py` | Full UI | Quits Blender during a recording. The runner then checks that `session_info.json` was closed. |
| `tests/screenshots.py` | Full UI | Produces `docs/images/*.png` (not a test). |

## Required tests

| # | Requirement | Result | Evidence (check names) |
|---|---|---|---|
| 1 | Add-on installation | ✅ | Installed from the built ZIP into a clean profile: `01 add-on installed` |
| 2 | Add-on enablement | ✅ | `02 add-on enabled`, `02b panels registered` |
| 3 | Camera selection | ✅ | The camera pointer accepts cameras and rejects meshes; orthographic cameras work: `03 …` |
| 4 | Starting a recording | ✅ | Session folder and timer created; a second start is rejected by the API and by the operator poll: `04 …`, `start operator`, `duplicate start blocked by poll` |
| 5 | Capturing multiple frames | ✅ | `05 multiple frames`, `06 frames captured while navigating` |
| 6 | Viewport movement while recording | ✅ | About 30 rounds of orbit, pan and zoom during capture. **All frames are pixel-identical** (mean diff < 1e-6). The viewport is never put in camera view and keeps the user's navigated view: `06 …`, `viewport keeps the user's navigated view` |
| 7 | Editing geometry while recording | ✅ | Edits in Edit Mode (resize, subdivide, translate) show in frames, including while still in Edit Mode; direct data edits show too: `07 …` |
| 8 | Pause and resume | ✅ | No frames for 3 s while paused, elapsed time frozen, same session and numbering after resume: `08 …` |
| 9 | Manual capture | ✅ | `09 manual capture`, `09 capture-now operator` |
| 10 | Stopping a recording | ✅ | Final frame, `STOPPED` state, metadata, no captures afterwards: `10 …` |
| 11 | Changing capture intervals | ✅ | Changing the interval during recording applies to the next countdown, from 1 s to 2 s and to a custom 7 s: `11 …` |
| 12 | PNG and JPEG output | ✅ | Both formats at every resolution, with the extension and decoded size checked: `12/13 …` |
| 13 | Different resolution settings | ✅ | 25, 50, 75 and 100 % plus Custom 200×100, with exact pixel sizes checked |
| 14 | Invalid output directories | ✅ | A file used as the folder, an unwritable path, and `//` in an unsaved file are each rejected with a message and no session: `14 …` |
| 15 | Existing session directories | ✅ | With `Session_001` and `Session_007` present, the next session is `Session_008`. Old files are byte-for-byte untouched: `15 …` |
| 16 | Video generation | ✅ | External ffmpeg and the built-in encoder each produce H.264 at the right fps with 12/12 frames (checked with ffprobe). A gapped sequence and an existing file name (`_2`) are handled. No scenes or images leak. Frames are kept: `16 …` |
| 17 | Add-on disablement during a session | ✅ | In background mode and in the GUI: captures stop, metadata reads `stopped / add-on disabled`, classes unregister, and re-enabling works: `17 …` |
| 18 | Timer cleanup | ✅ | No timer after stop, file load or disable: `18 …` |
| 19 | Reopening a saved .blend | ✅ | Loading a file during recording closes the session. Settings (camera, format, quality) persist in the .blend, the file isn't dirtied, and recording works after reopening: `19 …` |
| 20 | Repeated sessions | ✅ | Each new session goes to a new `Session_NNN`: `20 …` |

Additional checks:

- **Render-state restoration:** after every capture, every engine, every format and resolution, and a whole GUI session, these are compared with a snapshot taken beforehand:
  - scene camera, engine, resolution and percentage
  - media type, format, colour mode, depth, quality and compression
  - filepath, sequencer, compositor, border, samples
  - active object, selection, scenes, window scene, workspace
  - the recording camera's transform and lens
- **Correct camera and engine actually used:** a `render_pre` probe confirms each capture rendered through the recording camera, even though `scene.camera` was a different camera, with the chosen engine (Workbench, EEVEE, Cycles or Scene).
- **Timing:** at a 1 s interval with a real event loop, start-to-start gaps were 1.00–1.14 s and never under 0.95 s.
- **Robustness:**
  - Deleting the session folder mid-recording auto-pauses with an error, and stopping afterwards is clean.
  - Renaming the scene mid-session is handled.
  - Undo and redo during recording are handled, including undoing past the moment the camera was chosen.
  - Renaming the recording camera keeps the recording going.
  - Deleting the recording camera is reported as an error and auto-pauses the recording without crashing.
  - Quitting Blender during recording closes `session_info.json`.

## Capture timing measured in the test environment

These numbers come from CPU-only software rendering. A real GPU is much faster, especially for Workbench and EEVEE. Scene: default scene plus a Suzanne with Subdivision level 2, 1920×1080 base, samples override 16.

| Engine | 50 % | 100 % |
|---|---|---|
| Workbench | 0.3–0.6 s | 0.8–0.9 s |
| EEVEE | 6 s (9 s the first time, shader compile) | 9 s |
| Cycles (16 spp) | 3.4 s | 13.5 s |

## Not tested
- **The Ctrl+Shift+F12 key press itself.** The test checks that the shortcut is registered, and calls the operator it runs, but no physical key press was simulated.

- **Windows and macOS.** Only Linux was available. The code uses only cross-platform APIs: `pathlib`, `os.replace`, `shutil.disk_usage`, `subprocess` with `CREATE_NO_WINDOW` on Windows, and `wm.path_open`. It still needs a run on those systems.
- **Real GPUs and real input devices.** Navigation was driven by the same operators that the mouse and keyboard call, under Xvfb with software OpenGL. Hand-held mouse orbiting and timing on a GPU were not exercised.
- **Brush strokes in Sculpt Mode.** The test changed mesh data while in Sculpt Mode, and captures continued. Real brush strokes, and Multires or Dyntopo, were not tested.
- **Physically removing storage** (unplugging a USB drive). This was simulated by deleting the session folder.
- **Blender crashes** (as opposed to a clean quit). They can't be tested meaningfully; frames already on disk are unaffected.
- **Clicking through the N-panel UI by hand.** The panels are drawn in screenshots (`docs/images`) and every operator is invoked through `bpy.ops`, but not by mouse clicks on the buttons. The confirmation dialog of **Reset Session** was not exercised.

## Bugs found and fixed during testing

1. **The scheduler was too slow at short intervals.** A fixed 1 s minimum idle time plus a 0.25 s tick gave 1.26–1.40 s gaps at a 1 s interval. The idle time is now 0.5 s and the tick wakes exactly when a frame is due, giving 1.00–1.14 s.
2. **A metadata write error could hide the real capture error.** When the storage was removed, "Could not write session info" replaced the capture error. Now the first error is kept.
3. **The manifest failed validation.** `permissions.files` was over 64 characters. It was shortened.
4. **A speculative "frame-range suffix" fallback in the built-in encoder was dead code.** Blender 5.2 writes the exact file name, so the fallback was removed.
5. **Undo could stop a recording.** Undoing past the step where the camera was picked cleared `settings.camera`, so captures failed and the recording auto-paused. The session now holds the camera by `session_uid`, which is fixed at Start and survives undo and renames. The GUI test reproduces this deterministically.
6. **A test-harness issue, not an add-on bug.** The tests held a `Scene` reference across undo. This confirmed the add-on's design choice to look scenes up by `session_uid`.

### Fixed in 1.1.0 testing
7. **Two test waits were too short, not add-on bugs.** One test assumed 60 FPS where 30 FPS was intended. The wait for the first capture after an undo was raised from 1.3 s to 5 s, because that capture rebuilds the depsgraph and can take longer.

