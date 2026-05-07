"""Tests for LLM query rewriting."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confluence_mcp.llm_rewrite import is_llm_rewrite_enabled, rewrite_query


class TestLLMRewrite(unittest.TestCase):
    def test_not_configured_returns_empty(self) -> None:
        with patch.dict("os.environ", {"LLM_REWRITE_ENDPOINT": ""}, clear=False):
            self.assertEqual(rewrite_query("тест"), [])

    def test_is_enabled_check(self) -> None:
        with patch.dict("os.environ", {"LLM_REWRITE_ENDPOINT": ""}, clear=False):
            self.assertFalse(is_llm_rewrite_enabled())
        with patch.dict("os.environ", {"LLM_REWRITE_ENDPOINT": "http://localhost:11434/v1/chat/completions"}, clear=False):
            self.assertTrue(is_llm_rewrite_enabled())

    def test_successful_rewrite(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [
                                "как принять звонок в директорат",
                                "порядок регистрации звонка в директорат",
                                "инструкция по обработке звонка",
                            ]
                        )
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(
            "os.environ",
            {
                "LLM_REWRITE_ENDPOINT": "http://localhost:11434/v1/chat/completions",
                "LLM_REWRITE_MODEL": "test",
                "LLM_REWRITE_API_KEY": "",
            },
            clear=False,
        ):
            with patch("confluence_mcp.llm_rewrite.requests.post", return_value=mock_resp):
                result = rewrite_query("КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ")
                self.assertEqual(len(result), 3)
                self.assertIn("как принять звонок в директорат", result)

    def test_handles_markdown_fences(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '```json\n["альтернатива 1", "альтернатива 2"]\n```'
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(
            "os.environ",
            {"LLM_REWRITE_ENDPOINT": "http://test", "LLM_REWRITE_MODEL": "m"},
            clear=False,
        ):
            with patch("confluence_mcp.llm_rewrite.requests.post", return_value=mock_resp):
                result = rewrite_query("тест")
                self.assertEqual(len(result), 2)

    def test_timeout_returns_empty(self) -> None:
        import requests as req

        with patch.dict(
            "os.environ",
            {"LLM_REWRITE_ENDPOINT": "http://test", "LLM_REWRITE_MODEL": "m"},
            clear=False,
        ):
            with patch("confluence_mcp.llm_rewrite.requests.post", side_effect=req.Timeout("timeout")):
                result = rewrite_query("тест")
                self.assertEqual(result, [])

    def test_bad_json_returns_empty(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "not json at all"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(
            "os.environ",
            {"LLM_REWRITE_ENDPOINT": "http://test", "LLM_REWRITE_MODEL": "m"},
            clear=False,
        ):
            with patch("confluence_mcp.llm_rewrite.requests.post", return_value=mock_resp):
                result = rewrite_query("тест")
                self.assertEqual(result, [])

    def test_filters_short_strings(self) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(["ab", "нормальная фраза", "x" * 300])
                    }
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(
            "os.environ",
            {"LLM_REWRITE_ENDPOINT": "http://test", "LLM_REWRITE_MODEL": "m"},
            clear=False,
        ):
            with patch("confluence_mcp.llm_rewrite.requests.post", return_value=mock_resp):
                result = rewrite_query("тест")
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0], "нормальная фраза")


if __name__ == "__main__":
    unittest.main()
