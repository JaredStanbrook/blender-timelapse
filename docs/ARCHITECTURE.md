# Architecture

```
blender_timelapse/
  __init__.py            register / unregister, load_pre handler (closes session on file change)
  blender_manifest.toml  Extension Platform manifest (id, version, license, permissions)
  properties.py          BT_Settings (per-scene PropertyGroup, saved in .blend) + AddonPreferences (ffmpeg path)
  capture.py             render ONE frame from a camera with guaranteed restore (TemporaryOverrides)
  recorder.py            Session object + scheduler timer: start / pause / resume / stop / capture_now / reset
  video.py               MP4 export: external ffmpeg subprocess (polled) or built-in VSE encoder
  operators.py           thin UI operators; turn TimelapseError into a report
  ui.py                  N-panel (main + Camera/Recording/Settings/Advanced/Session/Export) + header REC badge
  previews.py            camera preview thumbnail (bpy.utils.previews, no Image datablock)
  utils.py               paths, session folders, metadata, formatting, redraw helpers
```

## Data flow

```
Start ─▶ recorder.start(scene)
           ├─ validate camera / output folder (writable, ≥64 MB free)
           ├─ utils.create_session_dir → Project/Session_NNN/Frames   (mkdir exist_ok=False ⇒ never reused)
           ├─ Session(snapshot of capture settings)                    (plain Python, no bpy refs)
           └─ bpy.app.timers.register(_tick)                           (only if not already registered)

_tick (main thread, every ≤0.25 s)
   ├─ scene, camera = find by session_uid (survive rename + undo)
   ├─ due? ─ busy (render job / bake / modal tool ≤3 s)? → defer
   │        └─ _capture → capture.render_frame(scene, camera, snapshot, Frame_N)
   │              with TemporaryOverrides:            ← every change recorded
   │                 scene.camera, engine, resolution, image format, samples, sequencer, compositor
   │                 bpy.ops.render.render(write_still=False, layer=active, scene=…)   (off-screen, EXEC)
   │                 Render Result.save_render(path)
   │              finally: restore in reverse order, clear busy flag
   ├─ next = max(start + interval, end + 0.5 s)    ← never faster than interval, never back-to-back
   ├─ 3 consecutive failures → auto-pause with error
   └─ tag VIEW_3D redraw (countdown)

Stop ─▶ optional final frame → state STOPPED → session_info.json → timer removed
```

## Key decisions

| Decision | Why |
|---|---|
| Render through `bpy.ops.render.render` in EXEC mode | This is the only API that gives an accurate render from a specific camera: correct lens, sensor fit, ortho scale, materials and colour management. EXEC mode opens no render window and never touches the viewport. |
| Temporary overrides plus `finally`, not a duplicate scene | A linked duplicate scene would differ in world, colour management and view layers, and it adds datablocks to the user's file. Overriding a handful of attributes and restoring them in reverse order is smaller and verifiable: the tests compare a before/after snapshot of every setting. |
| `Image.save_render` from the Render Result | `write_still=True` would require changing `render.filepath`, and Blender would append frame numbers to it. `save_render` writes exactly to our path, using the scene's (overridden) format and colour management. |
| Look up the scene and camera by `session_uid` on each tick | Python references to IDs become invalid after undo or a file load. `session_uid` stays the same across undo and renames. The camera is fixed at Start, so undoing past the moment it was chosen does not stop the recording. The GUI test runs undo and redo during a recording. |
| A single timer, with no threads | Blender's data API is not thread-safe. Video encoding runs in an external *process*, and a timer polls its progress file, so no Python thread is involved. |
| Snapshot of the capture settings at Start | Every frame in a sequence has the same size, format and engine. Only the interval stays live. |
| Workbench as the default engine | It is the fastest by far, so you can keep working while it records (see the timings in the testing report). |
| Defer while modal operators run (up to 3 s) | This avoids a hitch in the middle of a drag or orbit. The 3 s cap stops a permanently running modal add-on from blocking captures. |
| `load_pre` handler and `unregister` call `shutdown()` | Changing files, disabling the add-on or quitting (Blender unregisters add-ons on quit) always closes `session_info.json`. `atexit` is a last resort. |

# Research notes

## SimpleTimelapser (Jorhlok, MIT, Blender 2.80–3.0)

I read the source (one 290-line `__init__.py`).

- **Approach:** an interval timer calls `bpy.ops.render.render(write_still=True)` for each camera that is enabled for rendering. It swaps `scene.camera` and `scene.render.filepath` for each camera. It also has a window screenshot mode and a viewport (`render.opengl`) mode.
- **Useful ideas:**
  - Render from cameras rather than the viewport.
  - Workbench and JPEG are recommended to reduce hitches.
  - Each camera gets its own output subdirectory.
  - The frame counter continues from existing files.
  - Recording stops on `load_pre`.
- **Problems I avoided:**
  - The camera and path are not restored if the render raises an exception.
  - The add-on uses whatever render settings the user has (format, resolution), so a recording can break their F12 setup or produce mismatched frames.
  - There is no protection against overlapping captures or slow renders ("unknown behavior if renders take longer than interval").
  - The `load_pre` handler has the wrong signature.
  - State is kept in globals that hold `bpy.context.scene`.
  - It cannot pause.
  - It has no video export.
  - The README notes that viewport capture does not update in sculpt mode. Blender Timelapse renders from the camera, so this does not apply to it.

## TIMELAPSE Tool (Fwiller, paid, closed source)

I read the documentation site and the itch.io page only. No code was available.

- **Features:**
  - Window screenshots at a fixed interval (set in minutes).
  - Camera capture, including animated and multiple cameras.
  - "Lock Shading".
  - Image-sequence settings: path, images, and an ID that can be regenerated.
  - A video build from the image sequence.
- **Takeaways:**
  - Users want a session ID or folder for each recording. Blender Timelapse uses `Session_NNN`.
  - Video creation should be a single click.
  - Camera capture matters more than screenshots for a polished result.
  - Multi-camera and animated cameras were deliberately left out of scope.

## Blender 5.2.3 API checks

Each of these was verified against the real 5.2.3 build, not taken from the docs alone.

- `ImageFormatSettings.media_type` (`IMAGE` / `VIDEO` / …) must be set before `file_format`. This is new in 5.x.
- The engine identifiers are `BLENDER_WORKBENCH`, `BLENDER_EEVEE` (the `_NEXT` suffix is gone) and `CYCLES`.
- `SequenceEditor.strips.new_image(..., fit_method=...)`: the collection is now called `strips`, no longer `sequences`.
- `Image.save_render(filepath, scene, quality)`, `Window.modal_operators` and `bpy.app.is_job_running(...)`.
- `render.render` accepts `layer`, `scene` and `use_sequencer_scene`.
- `Region.active_panel_category` is read-only.
- Extension manifest: `permissions.files` must be 64 characters or fewer, and the ID is accessed through `__package__`.
- `blender --command extension validate/build/install-file` validates, builds and installs the package.
