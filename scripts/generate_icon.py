from pathlib import Path

from PIL import Image, ImageDraw


APP = Path(__file__).resolve().parents[1] / "app"
SIZE = 1024
BLUE = (35, 87, 217, 255)
WHITE = (255, 255, 255, 255)
SOFT_WHITE = (255, 255, 255, 210)


def draw_mark(canvas: Image.Image, *, scale: float = 1.0, offset: tuple[int, int] = (0, 0)) -> None:
    draw = ImageDraw.Draw(canvas)
    ox, oy = offset
    cx = int(445 * scale) + ox
    cy = int(420 * scale) + oy
    radius = int(220 * scale)
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=WHITE,
        width=max(1, int(72 * scale)),
    )
    for inner, width in ((145, 28), (78, 22)):
        inner = int(inner * scale)
        draw.ellipse(
            (cx - inner, cy - inner, cx + inner, cy + inner),
            outline=SOFT_WHITE,
            width=max(1, int(width * scale)),
        )
    draw.line(
        (
            int(610 * scale) + ox,
            int(585 * scale) + oy,
            int(825 * scale) + ox,
            int(800 * scale) + oy,
        ),
        fill=WHITE,
        width=max(1, int(86 * scale)),
    )
    draw.ellipse(
        (
            int(785 * scale) + ox,
            int(760 * scale) + oy,
            int(865 * scale) + ox,
            int(840 * scale) + oy,
        ),
        fill=WHITE,
    )


# Master / legacy icon.
img = Image.new("RGBA", (SIZE, SIZE), BLUE)
draw_mark(img)
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
res = APP / "android" / "app" / "src" / "main" / "res"
for folder, pixels in android_sizes.items():
    target = res / folder
    if target.parent.exists():
        target.mkdir(parents=True, exist_ok=True)
        img.resize((pixels, pixels), Image.Resampling.LANCZOS).save(target / "ic_launcher.png")

# Modern Android adaptive icon. Keep the white mark well inside the adaptive
# safe zone so circular/squircle launchers (including Honor MagicOS) do not cut
# the magnifier handle.
if res.exists():
    foreground = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    draw_mark(foreground, scale=0.52, offset=(-95, -88))
    drawable = res / "drawable-nodpi"
    drawable.mkdir(parents=True, exist_ok=True)
    foreground.save(drawable / "ic_launcher_foreground.png", optimize=True)

    values = res / "values"
    values.mkdir(parents=True, exist_ok=True)
    (values / "ic_launcher_colors.xml").write_text(
        """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<resources>
    <color name=\"ic_launcher_background\">#2357D9</color>
</resources>
""",
        encoding="utf-8",
    )

    adaptive = res / "mipmap-anydpi-v26"
    adaptive.mkdir(parents=True, exist_ok=True)
    adaptive_xml = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<adaptive-icon xmlns:android=\"http://schemas.android.com/apk/res/android\">
    <background android:drawable=\"@color/ic_launcher_background\" />
    <foreground android:drawable=\"@drawable/ic_launcher_foreground\" />
</adaptive-icon>
"""
    (adaptive / "ic_launcher.xml").write_text(adaptive_xml, encoding="utf-8")
    (adaptive / "ic_launcher_round.xml").write_text(adaptive_xml, encoding="utf-8")

    # Reference the round icon only after the resource exists. This keeps
    # prepare_platforms.py safe for builds that do not run icon generation.
    manifest = APP / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8")
        if "android:roundIcon=" not in text:
            text = text.replace(
                'android:icon="@mipmap/ic_launcher"',
                'android:icon="@mipmap/ic_launcher"\n        android:roundIcon="@mipmap/ic_launcher_round"',
                1,
            )
        manifest.write_text(text, encoding="utf-8")

# Windows executable icon uses the same identity.
win = APP / "windows" / "runner" / "resources"
if win.parent.exists():
    win.mkdir(parents=True, exist_ok=True)
    img.save(
        win / "app_icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
