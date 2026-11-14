import io
import unittest

from PIL import Image

from retrieve_owner_image import image_url_from_html, is_google_https_url, retrieve_image


class OwnerImageRetrieval(unittest.TestCase):
    def test_google_url_allowlist_rejects_non_google_and_non_https_urls(self):
        self.assertTrue(is_google_https_url("https://photos.app.goo.gl/example"))
        self.assertTrue(is_google_https_url("https://lh3.googleusercontent.com/image"))
        self.assertFalse(is_google_https_url("http://photos.app.goo.gl/example"))
        self.assertFalse(is_google_https_url("https://photos.app.goo.gl.example.com/image"))
        self.assertFalse(is_google_https_url("https://example.com/image"))

    def test_html_preview_must_resolve_to_an_allowed_google_image_url(self):
        page = b'<meta property="og:image" content="https://lh3.googleusercontent.com/image">'
        self.assertEqual(
            image_url_from_html(page, "https://photos.google.com/share/example"),
            "https://lh3.googleusercontent.com/image",
        )
        with self.assertRaisesRegex(ValueError, "outside the allowed"):
            image_url_from_html(
                b'<meta property="og:image" content="https://example.com/image">',
                "https://photos.google.com/share/example",
            )

    def test_retrieval_preserves_transparent_png_bytes_and_checks_dimensions(self):
        source = io.BytesIO()
        Image.new("RGBA", (600, 700), (20, 40, 60, 0)).save(source, format="PNG")
        original = source.getvalue()

        def fake_fetch(url, _user_agent):
            return original, "image/png", "https://lh3.googleusercontent.com/image"

        result = retrieve_image("https://photos.app.goo.gl/example", "test-agent", fake_fetch)
        self.assertEqual(result["content"], original)
        self.assertEqual((result["width"], result["height"]), (600, 700))
        self.assertTrue(result["has_transparency"])
        self.assertEqual(result["format"], "PNG")

    def test_retrieval_rejects_small_images(self):
        source = io.BytesIO()
        Image.new("RGB", (499, 700), "white").save(source, format="JPEG")

        def fake_fetch(url, _user_agent):
            return source.getvalue(), "image/jpeg", "https://lh3.googleusercontent.com/image"

        with self.assertRaisesRegex(ValueError, "shortest image side"):
            retrieve_image("https://photos.app.goo.gl/example", "test-agent", fake_fetch)


if __name__ == "__main__":
    unittest.main()
