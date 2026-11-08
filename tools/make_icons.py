"""Draws the app icons (cardamom pod + peppercorns + rising line). Run once: python tools/make_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "site" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG = (26, 77, 46)          # deep cardamom green
POD = (156, 204, 101)      # light pod green
POD_LINE = (104, 159, 56)
PEPPER = (33, 33, 33)
PEPPER_HI = (90, 90, 90)
LINE = (255, 213, 79)      # warm turmeric yellow trend line


def draw(size, padding=0.0, rounded=True):
    s = 4  # draw big then shrink, for smooth edges
    W = size * s
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, W - 1, W - 1], radius=int(W * 0.22), fill=BG)
    else:
        d.rectangle([0, 0, W, W], fill=BG)
    p = W * padding
    inner = W - 2 * p
    u = lambda v: p + v * inner  # 0..1 -> pixels inside the safe area

    # cardamom pod: rotated ellipse built from a separate layer
    pod = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pod)
    pd.ellipse([u(0.26), u(0.18), u(0.58), u(0.70)], fill=POD)
    pd.line([u(0.42), u(0.21), u(0.42), u(0.67)], fill=POD_LINE, width=max(2, int(inner * 0.018)))
    pod = pod.rotate(-28, center=(u(0.42), u(0.44)), resample=Image.BICUBIC)
    img.alpha_composite(pod)

    # peppercorns
    for cx, cy, r in ((0.70, 0.46, 0.085), (0.82, 0.58, 0.07), (0.66, 0.62, 0.065)):
        d.ellipse([u(cx - r), u(cy - r), u(cx + r), u(cy + r)], fill=PEPPER)
        d.ellipse([u(cx - r * 0.45), u(cy - r * 0.55), u(cx - r * 0.05), u(cy - r * 0.15)], fill=PEPPER_HI)

    # rising price line
    pts = [(u(0.14), u(0.88)), (u(0.36), u(0.81)), (u(0.52), u(0.85)), (u(0.86), u(0.74))]
    d.line(pts, fill=LINE, width=int(inner * 0.045), joint="curve")
    r = inner * 0.035
    x, y = pts[-1]
    d.ellipse([x - r, y - r, x + r, y + r], fill=LINE)
    return img.resize((size, size), Image.LANCZOS)


draw(192).save(OUT / "icon-192.png")
draw(512).save(OUT / "icon-512.png")
draw(512, padding=0.12, rounded=False).save(OUT / "icon-maskable-512.png")   # Android adaptive icons
draw(180, rounded=False).convert("RGB").save(OUT / "apple-touch-icon.png")   # iPhone home screen
draw(32).save(OUT / "favicon-32.png")
print("Icons written to", OUT)
