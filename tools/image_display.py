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
    image = background.convert("RGB")
    if organic:
        badge_input = io.BytesIO()
        image.save(badge_input, format="PNG")
        with Image.open(io.BytesIO(render_watermark(badge_input.getvalue()))) as marked:
            image = marked.convert("RGB")
    result = io.BytesIO()
    image.save(result, format="JPEG", quality=90, optimize=True, progressive=True)
    return result.getvalue()
