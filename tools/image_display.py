"""Render approved produce images at a consistent display size."""
import io

from PIL import Image, ImageOps

from organic_watermarks import render_watermark

DISPLAY_SIZE = (500, 500)


def display_image(content, organic=False):
    with Image.open(io.BytesIO(content)) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
    image.thumbnail(DISPLAY_SIZE, Image.Resampling.LANCZOS)
    background = Image.new("RGBA", DISPLAY_SIZE, "white")
    background.alpha_composite(
        image, ((DISPLAY_SIZE[0] - image.width) // 2, (DISPLAY_SIZE[1] - image.height) // 2))
    result = io.BytesIO()
    background.convert("RGB").save(result, format="PNG")
    content = result.getvalue()
    return render_watermark(content) if organic else content
