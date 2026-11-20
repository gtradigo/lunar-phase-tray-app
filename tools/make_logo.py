"""Build assets/logo.png from a NASA SVS Dial-A-Moon image (public domain).

Usage: python3 tools/make_logo.py ~/.cache/lunar-phase-tray/nasa-n-<hour>.jpg assets/logo.png
The current logo uses the waxing gibbous Moon of 2026-11-20 11:00 UTC.
"""
import sys, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

src, out = sys.argv[1], sys.argv[2]
N = 512
moon = Image.open(src).convert("RGB")
a = np.asarray(moon).astype(np.float32)
# find the disc bounding box (pixels brighter than the black sky; include dark side faintly lit)
mask = a.max(axis=2) > 12
ys, xs = np.nonzero(mask)
cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
r = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2
moon = moon.crop((int(cx - r), int(cy - r), int(cx + r), int(cy + r)))

D = int(N * 0.66)
moon = moon.resize((D, D), Image.LANCZOS)
lum = np.asarray(moon.convert("L")).astype(np.float32) / 255
# alpha: lit part opaque, dark limb as a faint earthshine silhouette
yy, xx = np.mgrid[0:D, 0:D]
inside = ((xx - D / 2 + .5) ** 2 + (yy - D / 2 + .5) ** 2) <= (D / 2 - 1) ** 2
alpha = np.clip(lum * 4, 0, 1)
alpha = np.where(inside, np.maximum(alpha, 0.0), 0)
moon_rgba = moon.convert("RGBA")
moon_rgba.putalpha(Image.fromarray((alpha * 255).astype(np.uint8)))

# background badge: radial night-sky gradient in a circle
yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
d = np.hypot(xx - N * 0.42, yy - N * 0.38) / N
top = np.array([38, 52, 102]); bot = np.array([8, 12, 32])
t = np.clip(d / 0.75, 0, 1)[..., None]
bg = (top * (1 - t) + bot * t)
badge = np.hypot(xx - N / 2 + .5, yy - N / 2 + .5) <= N / 2 - 2
img = Image.fromarray(np.dstack([bg, badge * 255]).astype(np.uint8), "RGBA")

# stars on the dark (left) side
rnd = random.Random(7)
draw = ImageDraw.Draw(img)
for _ in range(60):
    x, y = rnd.uniform(0, N), rnd.uniform(0, N)
    if math.hypot(x - N / 2, y - N / 2) > N / 2 - 14: continue
    if math.hypot(x - N / 2, y - N / 2) < D / 2 + 10: continue
    s = rnd.choice([1, 1, 1, 1.5, 2])
    c = rnd.randint(150, 255)
    draw.ellipse((x - s, y - s, x + s, y + s), fill=(c, c, min(255, c + 20), 255))
for (x, y, s) in [(N * 0.2, N * 0.27, 7), (N * 0.8, N * 0.79, 5)]:  # two twinkles
    draw.polygon([(x, y - s * 2.2), (x + s * .35, y - s * .35), (x + s * 2.2, y), (x + s * .35, y + s * .35),
                  (x, y + s * 2.2), (x - s * .35, y + s * .35), (x - s * 2.2, y), (x - s * .35, y - s * .35)],
                 fill=(255, 250, 225, 255))

# glow behind the moon
glow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
o = (N - D) // 2
gd.ellipse((o - 6, o - 6, o + D + 6, o + D + 6), fill=(255, 240, 200, 90))
glow = glow.filter(ImageFilter.GaussianBlur(22))
img = Image.alpha_composite(img, glow)
# faint earthshine disc so the full circle reads
es = Image.new("RGBA", (N, N), (0, 0, 0, 0))
ImageDraw.Draw(es).ellipse((o, o, o + D, o + D), fill=(70, 85, 130, 80))
img = Image.alpha_composite(img, es)
img.alpha_composite(moon_rgba, (o, o))
# re-apply badge mask (glow must not leak outside)
final_alpha = np.minimum(np.asarray(img)[..., 3], badge * 255).astype(np.uint8)
img.putalpha(Image.fromarray(final_alpha))
img.save(out, optimize=True)

