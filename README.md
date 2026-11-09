# Blender Timelapse

Blender Timelapse is a Blender 5.2 extension that records fixed-camera timelapses of your modelling while you keep working normally.

Pick a camera and press **Start Recording**. You can then orbit, zoom, edit, sculpt and undo as usual. Every few seconds, Blender Timelapse renders one frame from that camera in the background. Your viewport, selection and render settings are never changed. When you stop, **Generate Video** turns the frames into an MP4.

![Panel while recording](docs/images/panel_recording.png)

## Download and install

- **Installable package:** [`dist/blender_timelapse-1.0.0.zip`](dist/blender_timelapse-1.0.0.zip)
- In Blender, go to **Edit › Preferences › Get Extensions › ⌄ › Install from Disk…** and pick the ZIP. You can also drag the ZIP onto the Blender window.
- Open a 3D Viewport, press **N**, and click the **Blender Timelapse** tab.

## Documentation

| | |
|---|---|
| [User guide, installation, limitations](blender_timelapse/README.md) | How to use the add-on, its output layout, video export and known limitations |
| [Changelog](blender_timelapse/CHANGELOG.md) | |
| [Architecture and research notes](docs/ARCHITECTURE.md) | Module layout, the capture pipeline, design decisions and research on the reference add-ons |
| [Testing report](docs/TESTING.md) | Results for the 20 required scenarios and 129 automated checks run on Blender 5.2.3 LTS |

## Repository layout

```
blender_timelapse/   the extension (manifest, Python modules, README, CHANGELOG, LICENSE)
dist/                built, installable ZIP
tests/               Blender test scripts + run_tests.sh
docs/                architecture, testing report, screenshots, raw test results
```

## Build and test

```
blender --command extension build --source-dir blender_timelapse --output-dir dist
tests/run_tests.sh /path/to/blender     # Linux, needs xvfb-run
```

## License

GPL-3.0-or-later. See [blender_timelapse/LICENSE](blender_timelapse/LICENSE).
