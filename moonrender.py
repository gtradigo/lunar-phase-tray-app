"""Moon image rendering: small tray icons (cairo) and an offline
high-resolution fallback picture (numpy + PIL) used when the NASA
image cannot be fetched."""

from __future__ import annotations

import math

import cairo


def render_icon(path: str, elongation: float, size: int = 64, south: bool = False) -> None:
    """Draw a phase icon: lit part bright, dark part faintly visible."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surf)
    c = size / 2.0
    r = size / 2.0 - max(1.0, size / 32.0)

    # Dark (earthshine) disc
    cr.arc(c, c, r, 0, 2 * math.pi)
    cr.set_source_rgba(0.35, 0.37, 0.42, 0.55)
    cr.fill_preserve()
    cr.set_source_rgba(0.85, 0.85, 0.9, 0.6)
    cr.set_line_width(max(1.0, size / 40.0))
    cr.stroke()

    _lit_path(cr, c, c, r, elongation, south)
    grad = cairo.RadialGradient(c - r * 0.3, c - r * 0.3, r * 0.1, c, c, r * 1.05)
    grad.add_color_stop_rgb(0, 1.0, 0.99, 0.93)
    grad.add_color_stop_rgb(1, 0.86, 0.84, 0.74)
    cr.set_source(grad)
    cr.fill()
    surf.write_to_png(path)


def _lit_path(cr, cx, cy, r, elongation, south):
    """Build the path of the illuminated region.

    The lit region is bounded by the bright limb (a semicircle) and the
    terminator, which projects to a half-ellipse with x-radius r*|cos(e)|.
    Northern-hemisphere view: waxing moon is lit on the right.
    """
    e = math.radians(elongation % 360.0)
    waxing = elongation % 360.0 < 180.0
    lit_right = waxing != south
    k = math.cos(e)  # +1 new, -1 full
    cr.save()
    cr.translate(cx, cy)
    if not lit_right:
        cr.scale(-1, 1)
    # Limb: right semicircle from top to bottom
    cr.arc(0, 0, r, -math.pi / 2, math.pi / 2)
    # Terminator: from bottom back to top along half-ellipse.
    # k>0 (crescent): terminator bulges right; k<0 (gibbous): bulges left.
    rx = abs(k) * r
    cr.save()
    if rx < 1e-3:
        cr.restore()
        cr.line_to(0, -r)
    else:
        cr.scale(rx / r, 1.0)
        if k > 0:
            cr.arc_negative(0, 0, r, math.pi / 2, -math.pi / 2)
        else:
            cr.arc(0, 0, r, math.pi / 2, 3 * math.pi / 2)
        cr.restore()
    cr.close_path()
    cr.restore()


# Rough positions of the major maria on the near side, as
# (x, y, radius_x, radius_y, darkness) in units of the disc radius,
# x to the right (east on sky = west lunar), y downward, north up.
_MARIA = [
    (-0.30, -0.42, 0.28, 0.22, 0.30),  # Imbrium
    (-0.62, -0.05, 0.30, 0.45, 0.28),  # Procellarum
    (0.18, -0.38, 0.16, 0.15, 0.32),   # Serenitatis
    (0.35, -0.12, 0.20, 0.17, 0.30),   # Tranquillitatis
    (0.70, -0.30, 0.11, 0.12, 0.34),   # Crisium
    (0.58, 0.18, 0.13, 0.20, 0.25),    # Fecunditatis
    (0.32, 0.25, 0.12, 0.10, 0.22),    # Nectaris
    (-0.20, 0.35, 0.18, 0.15, 0.24),   # Nubium
    (-0.45, 0.30, 0.13, 0.11, 0.25),   # Humorum
    (0.05, -0.68, 0.38, 0.07, 0.22),   # Frigoris
    (-0.02, 0.05, 0.12, 0.12, 0.15),   # Vaporum/Medii
]


def render_fallback_picture(path: str, elongation: float, size: int = 730, south: bool = False) -> None:
    """Procedurally render a shaded moon (used offline)."""
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(42)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    r = size * 0.47
    x = (xs - size / 2) / r
    y = (ys - size / 2) / r
    rr = x * x + y * y
    inside = rr <= 1.0
    z = np.sqrt(np.clip(1 - rr, 0, 1))

    albedo = np.full((size, size), 0.78, np.float32)
    for mx, my, ax, ay, dark in _MARIA:
        d = ((x - mx) / ax) ** 2 + ((y - my) / ay) ** 2
        albedo -= dark * np.exp(-d ** 2 * 1.5)
    # Crater-ish speckle
    noise = rng.normal(0, 1, (size // 8 + 1, size // 8 + 1)).astype(np.float32)
    noise = np.array(Image.fromarray(noise).resize((size, size), Image.BICUBIC))
    albedo += noise * 0.035
    fine = rng.normal(0, 0.02, (size, size)).astype(np.float32)
    albedo += fine
    # Tycho-ish bright spot with rays
    ty = ((x + 0.12) ** 2 + (y - 0.70) ** 2)
    albedo += 0.18 * np.exp(-ty / 0.002)
    albedo = np.clip(albedo, 0.15, 1.0)

    e = math.radians(elongation % 360.0)
    sx = math.sin(e)
    sz = -math.cos(e)
    lambert = np.clip(x * sx + z * sz, 0, None)
    # Lommel-Seeliger-ish: flatter brightness, sharp terminator
    shade = np.where(lambert > 0, (lambert / (lambert + np.maximum(z, 1e-3))) * 2, 0)
    shade = np.clip(shade, 0, 1) ** 0.6
    earthshine = 0.04
    img = albedo * np.maximum(shade, earthshine)
    if south:
        img = img[::-1, ::-1]
        inside_s = inside[::-1, ::-1]
    else:
        inside_s = inside
    img = np.where(inside_s, img, 0.0)
    # Slight soft edge
    rgb = np.stack([img * 0.98, img * 0.97, img * 0.93], axis=-1)
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(path, quality=92)
