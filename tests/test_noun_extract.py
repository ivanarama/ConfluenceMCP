"""Tests for noun extraction."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confluence_mcp.noun_extract import extract_nouns, has_pymorphy3, noun_phrase


class TestNounExtract(unittest.TestCase):
    @unittest.skipUnless(has_pymorphy3(), "pymorphy3 not installed")
    def test_extracts_nouns_from_russian(self) -> None:
        nouns = extract_nouns("КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ")
        nouns_lower = [n.lower() for n in nouns]
        self.assertIn("звонок", nouns_lower)
        self.assertIn("директорат", nouns_lower)

    @unittest.skipUnless(has_pymorphy3(), "pymorphy3 not installed")
    def test_skips_verbs(self) -> None:
        nouns = extract_nouns("как оформить звонок")
        nouns_lower = [n.lower() for n in nouns]
        self.assertIn("звонок", nouns_lower)
        self.assertNotIn("оформить", nouns_lower)

    @unittest.skipUnless(has_pymorphy3(), "pymorphy3 not installed")
    def test_noun_phrase_two_nouns(self) -> None:
        result = noun_phrase("КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ")
        self.assertIsNotNone(result)
        self.assertIn("звонок", result.lower())
        self.assertIn("директорат", result.lower())

    @unittest.skipUnless(has_pymorphy3(), "pymorphy3 not installed")
    def test_noun_phrase_single_noun(self) -> None:
        result = noun_phrase("как быстро оформить")
        self.assertIsNotNone(result)

    @unittest.skipUnless(has_pymorphy3(), "pymorphy3 not installed")
    def test_mixed_russian_english(self) -> None:
        nouns = extract_nouns("CRM звонок")
        nouns_lower = [n.lower() for n in nouns]
        self.assertIn("звонок", nouns_lower)

    def test_empty_input(self) -> None:
        self.assertEqual(extract_nouns(""), [])

    @unittest.skipUnless(has_pymorphy3(), "pymorphy3 not installed")
    def test_dedup(self) -> None:
        nouns = extract_nouns("звонок звонок")
        self.assertEqual(len(nouns), 1)


class TestNounExtractFallback(unittest.TestCase):
    def test_graceful_no_pymorphy3(self) -> None:
        with patch("confluence_mcp.noun_extract._HAS_MORPH", False):
            self.assertEqual(extract_nouns("звонок директорат"), [])
            self.assertIsNone(noun_phrase("звонок директорат"))


if __name__ == "__main__":
    unittest.main()
