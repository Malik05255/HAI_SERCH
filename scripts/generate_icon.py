from pathlib import Path

from PIL import Image, ImageDraw


APP = Path(__file__).resolve().parents[1] / "app"
SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (35, 87, 217, 255))
draw = ImageDraw.Draw(img)

cx, cy, radius = 445, 420, 220
draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline="white", width=72)
for inner, width in ((145, 28), (78, 22)):
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=(255, 255, 255, 210), width=width)
draw.line((610, 585, 825, 800), fill="white", width=86)
draw.ellipse((785, 760, 865, 840), fill="white")

assets = APP / "assets"
assets.mkdir(parents=True, exist_ok=True)
img.save(assets / "icon.png", optimize=True)

android_sizes = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}
for folder, pixels in android_sizes.items():
    target = APP / "android" / "app" / "src" / "main" / "res" / folder
    if target.parent.exists():
        target.mkdir(parents=True, exist_ok=True)
        img.resize((pixels, pixels), Image.Resampling.LANCZOS).save(target / "ic_launcher.png")

win = APP / "windows" / "runner" / "resources"
if win.parent.exists():
    win.mkdir(parents=True, exist_ok=True)
    img.save(win / "app_icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
