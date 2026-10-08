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
            "хачапурная открылась рядом",
            "заказал khachapuri",
            "гуляли по даунтауну",
            "the task looks daunting",
            "жидкий азот и жидкость",
            "обсуждали шизофрению",
            "оформляется инвалидность",
            "фамилия Москалёв",
            "ребенок уродился здоровым",
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

    def test_all_immediate_discriminatory_words_still_match(self) -> None:
        prohibited_words = (
            "черножопый", "черномазый", "чурка", "хач", "жид", "жидяра",
            "хохол", "кацап", "москаль", "русня", "пидор", "пидарас",
            "гомик", "трансуха", "даун", "аутист", "шизофреник", "инвалид",
        )
        for word in prohibited_words:
            with self.subTest(word=word):
                detection = detect_prohibited_content(word)
                self.assertIsNotNone(detection)
                self.assertEqual(detection.level, "obvious")

        self.assertIsNone(detect_prohibited_content("укроп"))

    def test_detects_other_masked_sequences_without_joining_words(self) -> None:
        for message in ("k.y.s", "k y s", "н.и.г.г.е.р", "н и г г е р"):
            with self.subTest(message=message):
                self.assertIsNotNone(detect_prohibited_content(message))

    def test_hach_exceptions_do_not_disable_the_slur_filter(self) -> None:
        for message in ("хач", "хачи", "хачур", "hach", "х.а.ч", "х-а-ч-и"):
            with self.subTest(message=message):
                detection = detect_prohibited_content(message)
                self.assertIsNotNone(detection)
                self.assertEqual(detection.level, "obvious")

    def test_safe_similar_word_before_violation_does_not_hide_violation(self) -> None:
        detection = detect_prohibited_content("хачапури — это еда, а хач — оскорбление")
        self.assertIsNotNone(detection)
        self.assertEqual(detection.matched, "хач")


if __name__ == "__main__":
    unittest.main()
