import unittest

from content_filter import detect_prohibited_content


class ContentFilterTests(unittest.TestCase):
    def test_does_not_join_normal_words_into_slur(self) -> None:
        self.assertIsNone(detect_prohibited_content("да у нас короче галерея"))
        self.assertIsNone(detect_prohibited_content("да у нас арт появился NSFW"))

    def test_detects_actual_slur_and_deliberate_masking(self) -> None:
        for message in ("даун", "д а у н", "д.а.у.н"):
            with self.subTest(message=message):
                detection = detect_prohibited_content(message)
                self.assertIsNotNone(detection)
                self.assertEqual(detection.level, "obvious")


if __name__ == "__main__":
    unittest.main()
