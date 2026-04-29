"""Placeholder to satisfy test discovery on empty test suite."""
import unittest


class PlaceholderTest(unittest.TestCase):
    def test_package_importable(self) -> None:
        """Verify the src package and entrypoint are importable."""
        import src  # noqa: F401
        import gh_readme_pipeline  # noqa: F401
        self.assertTrue(True)
