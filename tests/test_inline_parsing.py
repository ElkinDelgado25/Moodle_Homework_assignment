import unittest

from moodle_tasks import document_model
from moodle_tasks.document_model import parse_inline, reference_key


class InlineParsingTests(unittest.TestCase):
    text = "Un **texto en negrita** con [enlace](https://ejemplo.test/a) y *cursiva*."

    def test_segments_keep_their_format_and_links(self):
        self.assertEqual(parse_inline(self.text), [
            {"text": "Un ", "bold": False, "italic": False, "link": None},
            {"text": "texto en negrita", "bold": True, "italic": False, "link": None},
            {"text": " con ", "bold": False, "italic": False, "link": None},
            {"text": "enlace", "bold": False, "italic": False, "link": "https://ejemplo.test/a"},
            {"text": " y ", "bold": False, "italic": False, "link": None},
            {"text": "cursiva", "bold": False, "italic": True, "link": None},
            {"text": ".", "bold": False, "italic": False, "link": None},
        ])

    def test_the_same_text_is_parsed_only_once(self):
        document_model._parse_inline.cache_clear()
        for _ in range(3):
            parse_inline(self.text)
        reference_key(self.text)
        info = document_model._parse_inline.cache_info()
        # Se analiza el texto completo y, dentro, los dos fragmentos con énfasis; las otras tres llamadas salen del caché.
        self.assertEqual(info.misses, 3)
        self.assertGreaterEqual(info.hits, 3)

    def test_changing_a_result_never_changes_the_next_one(self):
        first = parse_inline(self.text)
        first[0]["text"] = "otro"
        first[0]["bold"] = True
        first.append({"text": "extra", "bold": False, "italic": False, "link": None})
        second = parse_inline(self.text)
        self.assertEqual(second[0], {"text": "Un ", "bold": False, "italic": False, "link": None})
        self.assertEqual(len(second), 7)

    def test_an_invalid_link_fails_every_time_and_is_not_cached(self):
        for _ in range(2):
            with self.assertRaises(ValueError):
                parse_inline("[GitHub](https://github.com/a/b)")


if __name__ == "__main__":
    unittest.main()
