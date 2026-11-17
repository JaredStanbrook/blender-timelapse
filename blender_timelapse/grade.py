# SPDX-License-Identifier: GPL-3.0-or-later
"""Export-time colour look: exposure, contrast, saturation and an optional .cube LUT.

Applied only while a video is made; captured photos are never changed. The same maths
is implemented twice and cross-checked by the tests:
* `ffmpeg_filters` for the external FFmpeg encoder (runs in that process),
* `apply` (numpy) for Blender's built-in encoder and the panel preview.

Order, on display-encoded sRGB values in 0..1:
  1. exposure  - convert to linear light, multiply by 2**stops, clip, re-encode
  2. contrast  - (v - 0.5) * contrast + 0.5
  3. saturation - mix with Rec.709 luma: luma + (v - luma) * saturation
  4. LUT       - 3D .cube lookup, trilinear interpolation
"""

from pathlib import Path

from .utils import TimelapseError

LUMA = (0.2126, 0.7152, 0.0722)
_lut_cache = {}


class Look:
    def __init__(self, exposure=0.0, contrast=1.0, saturation=1.0, lut_path=""):
        self.exposure, self.contrast, self.saturation = exposure, contrast, saturation
        self.lut_path = Path(lut_path) if lut_path else None
        if self.lut_path:
            load_lut(self.lut_path)  # validate early, with a clear message

    @property
    def is_identity(self):
        return self.exposure == 0 and self.contrast == 1 and self.saturation == 1 and self.lut_path is None


def look_from(settings):
    """The Look configured in the panel, or None when off / neutral."""
    if not settings.use_look:
        return None
    import bpy
    look = Look(settings.look_exposure, settings.look_contrast, settings.look_saturation,
                bpy.path.abspath(settings.look_lut_path) if settings.look_lut_path else "")
    return None if look.is_identity else look


# -- .cube LUTs -----------------------------------------------------------------

def load_lut(path):
    """Parse a 3D .cube file -> (size, domain_min, domain_max, table[b][g][r][3]); cached on mtime."""
    import numpy as np
    path = Path(path)
    try:
        key = (path, path.stat().st_mtime_ns)
    except OSError as ex:
        raise TimelapseError("LUT not found: %s" % path) from ex
    if key in _lut_cache:
        return _lut_cache[key]
    size, lo, hi, rows = None, [0.0] * 3, [1.0] * 3, []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if not parts or parts[0].startswith("#") or parts[0] == "TITLE":
                continue
            if parts[0] == "LUT_1D_SIZE":
                raise TimelapseError("'%s' is a 1D LUT; only 3D .cube LUTs are supported" % path.name)
            if parts[0] == "LUT_3D_SIZE":
                size = int(parts[1])
            elif parts[0] == "DOMAIN_MIN":
                lo = [float(v) for v in parts[1:4]]
            elif parts[0] == "DOMAIN_MAX":
                hi = [float(v) for v in parts[1:4]]
            elif parts[0][0].isdigit() or parts[0][0] in "-.":
                rows.append([float(v) for v in parts[:3]])
    except (ValueError, IndexError) as ex:
        raise TimelapseError("'%s' is not a valid .cube LUT" % path.name) from ex
    if not size or len(rows) != size ** 3:
        raise TimelapseError("'%s' is not a valid 3D .cube LUT" % path.name)
    # .cube order: red changes fastest, so index the table as [b][g][r].
    table = np.asarray(rows, dtype=np.float32).reshape(size, size, size, 3)
    _lut_cache[key] = (size, np.asarray(lo, np.float32), np.asarray(hi, np.float32), table)
    return _lut_cache[key]


# -- numpy implementation --------------------------------------------------------

def _to_linear(v):
    import numpy as np
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _to_srgb(v):
    import numpy as np
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def _apply_lut(rgb, lut):
    import numpy as np
    size, lo, hi, table = lut
    pos = np.clip((rgb - lo) / (hi - lo), 0, 1) * (size - 1)
    i0 = np.minimum(pos.astype(np.int32), size - 2) if size > 1 else np.zeros_like(pos, np.int32)
    f = pos - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = 0
    for db, wb in ((0, 1 - fb), (1, fb)):
        for dg, wg in ((0, 1 - fg), (1, fg)):
            for dr, wr in ((0, 1 - fr), (1, fr)):
                out = out + table[b0 + db, g0 + dg, r0 + dr] * (wr * wg * wb)
    return out


def apply(rgb, look):
    """Grade an (..., 3) float array of display-encoded values in 0..1."""
    import numpy as np
    v = rgb.astype(np.float32)
    if look.exposure:
        v = _to_srgb(np.clip(_to_linear(v) * 2.0 ** look.exposure, 0, 1))
    if look.contrast != 1:
        v = np.clip((v - 0.5) * look.contrast + 0.5, 0, 1)
    if look.saturation != 1:
        luma = (v * np.asarray(LUMA, np.float32)).sum(axis=-1, keepdims=True)
        v = np.clip(luma + (v - luma) * look.saturation, 0, 1)
    if look.lut_path:
        v = np.clip(_apply_lut(v, load_lut(look.lut_path)), 0, 1)
    return v


def grade_file(src, dst, look):
    """Write a graded copy of image src to dst (PNG). src is only read."""
    import bpy
    import numpy as np
    img = bpy.data.images.load(str(src), check_existing=False)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        px[:, :3] = apply(px[:, :3], look)
        img.pixels.foreach_set(px.ravel())
        img.filepath_raw = str(dst)
        img.file_format = "PNG"
        img.save()
    finally:
        bpy.data.images.remove(img)


# -- FFmpeg implementation ----------------------------------------------------------

def _ffmpeg_path(path):
    """Escape a path for use inside an ffmpeg filter argument (also works on Windows)."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def ffmpeg_filters(look):
    """Filter chain (list of strings) implementing `apply`, to put before scaling/encoding."""
    if look is None:
        return []
    chain = ["format=rgb24"]
    x = "(val/255)"
    if look.exposure:
        lin = "if(lte(%s,0.04045),%s/12.92,pow((%s+0.055)/1.055,2.4))" % (x, x, x)
        e = "min(1,%s*%r)" % (lin, 2.0 ** look.exposure)
        x = "(if(lte(%s,0.0031308),%s*12.92,1.055*pow(%s,1/2.4)-0.055))" % (e, e, e)
    if look.contrast != 1:
        x = "(clip((%s-0.5)*%r+0.5,0,1))" % (x, look.contrast)
    if x != "(val/255)":
        expr = "clip(255*%s,0,255)" % x
        chain.append("lutrgb=r='%s':g='%s':b='%s'" % (expr, expr, expr))
    if look.saturation != 1:
        s = look.saturation
        rows = []
        for out_ch in range(3):
            rows += ["%.6f" % ((1 - s) * LUMA[in_ch] + (s if in_ch == out_ch else 0)) for in_ch in range(3)]
        names = [o + i for o in "rgb" for i in "rgb"]
        chain.append("colorchannelmixer=" + ":".join("%s=%s" % kv for kv in zip(names, rows)))
    if look.lut_path:
        chain.append("lut3d=file='%s':interp=trilinear" % _ffmpeg_path(look.lut_path))
    return chain
