# Changelog

All notable changes to Blender Timelapse. Format: [Keep a Changelog](https://keepachangelog.com/), versioning: [SemVer](https://semver.org/).

## [1.1.0] - 2026-11-16

### Added
- **Duration per photo** export setting. Each photo is held for `Duration per photo × FPS` frames, and the video lasts `photos × Duration per photo` seconds. The Export panel shows frames per photo, total frames and video length before you export.
- Re-export any session as often as you like with the current settings. Each export writes a new file, and the captured photos are never touched.
- Reopen earlier sessions for export: the Export panel's **Session** menu lists the project's sessions, and **Browse…** opens a session folder from anywhere.
- **Manual** interval mode: the session only captures when you press Capture Now.
- **Ctrl Shift F12** keyboard shortcut for Capture Now, active in any editor.

### Changed
- Export now uses the session selected in the Export panel, not only the session that was just recorded. Starting a recording selects its new session automatically.
- A video can now be made from a single photo.

## [1.0.0] - 2026-11-09

First release, targeting Blender 5.2.3 LTS.

### Added
- Recording from a dedicated camera, completely independent of the working viewport.
- Start, Pause/Resume, Stop, Capture Now and Reset Session controls, plus a REC badge in the 3D Viewport header.
- Capture intervals of 1, 2, 5, 10, 30 or 60 s, or custom (0.5–3600 s). The interval can be changed during recording.
- Workbench, EEVEE, Cycles or Scene engine for captures, with a samples override.
- Resolutions of 25 / 50 / 75 / 100 % or a custom width × height. PNG or JPEG output with adjustable quality.
- Automatic `Project/Session_NNN/Frames/Frame_000001.png` layout and `session_info.json` metadata.
- Test Capture with a thumbnail preview, View Last Capture, and New Camera from View.
- MP4 export through an external FFmpeg (non-blocking, with progress) or Blender's built-in encoder.
- Render-state preservation: every temporary override is restored in a `finally` step.
- Safe shutdown on file load, add-on disable and quit.
