"""Unit tests for CQL string escaping."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confluence_mcp.cql_escape import escape_cql_string  # noqa: E402


class TestEscapeCqlString(unittest.TestCase):
    def test_plain(self) -> None:
        self.assertEqual(escape_cql_string("hello"), "hello")

    def test_double_quotes(self) -> None:
        self.assertEqual(escape_cql_string('say "hi"'), 'say \\"hi\\"')

    def test_backslash_then_quote(self) -> None:
        self.assertEqual(escape_cql_string('\\"'), '\\\\\\"')

    def test_order_backslash_first(self) -> None:
        s = 'a\\b"c'
        out = escape_cql_string(s)
        self.assertIn('\\\\', out)
        self.assertIn('\\"', out)


if __name__ == "__main__":
    unittest.main()
