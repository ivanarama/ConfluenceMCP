"""Tests for score-based merging."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confluence_mcp.scoring import score_results, variant_weight


def _page(pid: str, title: str = "") -> dict:
    return {"id": pid, "title": title}


class TestScoreResults(unittest.TestCase):
    def test_single_variant(self) -> None:
        hits = [[_page("1", "A"), _page("2", "B"), _page("3", "C")]]
        result = score_results(hits, limit=10)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].item["id"], "1")

    def test_multi_variant_overlap(self) -> None:
        page_a = _page("1", "A")
        page_b = _page("2", "B")
        result = score_results(
            [[page_a, page_b], [page_a]],
            limit=10,
        )
        self.assertEqual(result[0].item["id"], "1")
        self.assertGreater(result[0].score, result[1].score)

    def test_weights_applied(self) -> None:
        result = score_results(
            [[_page("1", "A")], [_page("2", "B")]],
            weights=[3.0, 1.0],
            limit=10,
        )
        self.assertEqual(result[0].item["id"], "1")
        self.assertAlmostEqual(result[0].score, 3.0)

    def test_dedup_by_id(self) -> None:
        page = _page("1", "A")
        result = score_results([[page, page], [page]], limit=10)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].matched_variants, 3)

    def test_limit_respected(self) -> None:
        hits = [[_page(str(i)) for i in range(20)]]
        result = score_results(hits, limit=5)
        self.assertEqual(len(result), 5)

    def test_empty_input(self) -> None:
        result = score_results([], limit=10)
        self.assertEqual(result, [])

    def test_mixed_valid_invalid(self) -> None:
        hits = [[_page("1"), "not_a_dict", _page("2"), {"no_id": True}]]
        result = score_results(hits, limit=10)
        self.assertEqual(len(result), 2)


class TestVariantWeight(unittest.TestCase):
    def test_full_phrase(self) -> None:
        self.assertEqual(variant_weight("как принять звонок", "как принять звонок"), 3.0)

    def test_three_words(self) -> None:
        self.assertEqual(variant_weight("принять звонок директорат", "как принять звонок"), 2.5)

    def test_two_words(self) -> None:
        self.assertEqual(variant_weight("звонок директорат", "как принять звонок"), 2.0)

    def test_single_word(self) -> None:
        self.assertEqual(variant_weight("директорат", "как принять звонок"), 1.0)


if __name__ == "__main__":
    unittest.main()
