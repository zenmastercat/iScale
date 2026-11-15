"""Four phone screens of the location feature side by side (f19_location_phone.png).
Run: uv run --with pillow python docs/build/location_figs.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SHOT, FIG = ROOT / "docs" / "screenshots", Path(__file__).resolve().parent / "fig"
items = [("location-agreement-phone.png", "1  Agreement"), ("location-agreement-phone-th.png", "2  The same in Thai"),
         ("pin-where-i-am-phone.png", "3  Pin where I am"), ("record-drive-phone.png", "4  Record a drive")]
ims = [Image.open(SHOT / f).convert("RGB") for f, _ in items]
h = 1400
ims = [im.resize((round(im.width * h / im.height), h), Image.LANCZOS) for im in ims]
gap, top = 48, 90
W = sum(i.width for i in ims) + gap * (len(ims) + 1)
canvas = Image.new("RGB", (W, h + top + gap), "white")
d = ImageDraw.Draw(canvas)
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
except OSError:
    font = ImageFont.load_default(44)
x = gap
for im, (_, label) in zip(ims, items):
    d.text((x, 22), label, fill=(29, 38, 34), font=font)
    canvas.paste(im, (x, top))
    d.rectangle([x - 1, top - 1, x + im.width, top + im.height], outline=(217, 223, 219), width=2)
    x += im.width + gap
FIG.mkdir(exist_ok=True)
canvas.save(FIG / "f19_location_phone.png", optimize=True)
print(FIG / "f19_location_phone.png", canvas.size)
