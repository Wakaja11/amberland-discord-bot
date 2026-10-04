import unittest

from content_filter import detect_prohibited_content


class ContentFilterTests(unittest.TestCase):
    def test_does_not_join_normal_words_into_slur(self) -> None:
        harmless_messages = (
            "да у нас короче галерея",
            "да у нас арт появился NSFW",
            "да у нас всё готово",
            "когда у нас встреча",
            "вода у нас холодная",
            "он уродился красивым",
            "жидкость уже остыла",
            "я хачу домой",
            "заказал хачапури",
            "приготовили хачипури",
            "попробовал хачупури",
            "hachu est",
            "hachapuri",
        )
        for message in harmless_messages:
            with self.subTest(message=message):
                self.assertIsNone(detect_prohibited_content(message))

    def test_detects_actual_slur_and_deliberate_masking(self) -> None:
        for message in ("даун", "д а у н", "д.а.у.н"):
            with self.subTest(message=message):
                detection = detect_prohibited_content(message)
                self.assertIsNotNone(detection)
                self.assertEqual(detection.level, "obvious")

    def test_detects_other_masked_sequences_without_joining_words(self) -> None:
        for message in ("k.y.s", "k y s", "н.и.г.г.е.р", "н и г г е р"):
            with self.subTest(message=message):
                self.assertIsNotNone(detect_prohibited_content(message))

    def test_hach_exceptions_do_not_disable_the_slur_filter(self) -> None:
        for message in ("хач", "хачи", "хачур", "hach"):
            with self.subTest(message=message):
                detection = detect_prohibited_content(message)
                self.assertIsNotNone(detection)
                self.assertEqual(detection.level, "obvious")


if __name__ == "__main__":
    unittest.main()
