"""Тесты разбиения запроса для поиска Confluence."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confluence_mcp.query_expand import (  # noqa: E402
    expand_abbrev,
    extract_page_ids_from_text,
    search_query_variants,
    significant_words,
)


class TestExtractPageIds(unittest.TestCase):
    def test_viewpage_query(self) -> None:
        u = "http://confluence.example/pages/viewpage.action?pageId=1076789578"
        self.assertEqual(extract_page_ids_from_text(u), ["1076789578"])

    def test_rest_content_path(self) -> None:
        u = "https://c/wiki/rest/api/content/12345?expand=body"
        self.assertEqual(extract_page_ids_from_text(u), ["12345"])

    def test_dedupe(self) -> None:
        t = "pageId=1 and pageId=1"
        self.assertEqual(extract_page_ids_from_text(t), ["1"])


class TestSearchVariants(unittest.TestCase):
    def test_underscore_token(self) -> None:
        q = "CRM Messenger_av_ОбновлениеСообщенийВСервисе дата"
        v = search_query_variants(q)
        self.assertIn(q, v)
        self.assertTrue(any("Messenger_av_" in x for x in v))

    def test_camelcase_from_underscore_identifier(self) -> None:
        """CamelCase-части идентификатора с «_» должны быть в вариантах до скользящих фраз."""
        q = "CRM Messenger_av_ОбновлениеСообщенийВСервисе Дата последнего регл. задания 13.01.2026"
        v = search_query_variants(q, max_variants=24)
        # Целый токен после «_»
        self.assertIn("ОбновлениеСообщенийВСервисе", v)
        # CamelCase-слова из токена
        self.assertIn("Обновление", v)
        self.assertIn("Сообщений", v)
        self.assertIn("Сервисе", v)
        # Дата не должна попадать в скользящие фразы (загрязняет поиск)
        date_phrases = [x for x in v if "13.01.2026" in x and x != q]
        self.assertEqual(date_phrases, [], msg=f"Дата попала в подфразы: {date_phrases}")

    def test_camelcase_priority_over_sliding(self) -> None:
        """Специфичные варианты (идентификатор, фраза) идут до одиночных CamelCase-слов."""
        q = "CRM Messenger_av_ОбновлениеСообщенийВСервисе Дата последнего регл. задания 13.01.2026"
        v = search_query_variants(q, max_variants=24)
        # Идентификатор целиком и CamelCase-токен — в начале
        self.assertIn("ОбновлениеСообщенийВСервисе", v[:8])
        # Слово запроса «регл» появляется ДО одиночных CamelCase-слов («Обновление»)
        if "регл" in v and "Обновление" in v:
            self.assertLess(v.index("регл"), v.index("Обновление"),
                            msg="«регл» должен идти до общего слова «Обновление»")

    def test_russian_short_words_in_variants(self) -> None:
        q = "делаем замену ручки питы ?"
        v = search_query_variants(q)
        self.assertIn("ручки", v)
        self.assertIn("питы", v)
        self.assertIn("замену", v)

    def test_significant_words(self) -> None:
        w = significant_words("делаем замену ручки питы", min_len=4)
        self.assertIn("замену", w)
        self.assertIn("ручки", w)
        self.assertIn("питы", w)

    def test_natural_language_question_stopwords_filtered(self) -> None:
        """Стоп-слова (как, который, надо, это) не должны попадать в поисковые варианты."""
        q = "Дата последнего регл. задания 13.01.2026 надо выключить регламент который отправляет это сообщение как это сделать ?"
        v = search_query_variants(q, max_variants=24)
        stopwords_found = [x for x in v if x.lower() in {"как", "который", "надо", "это"}]
        self.assertEqual(stopwords_found, [], msg=f"Стоп-слова в вариантах: {stopwords_found}")

    def test_abbrev_expansion_regl(self) -> None:
        """«регл» расширяется в полные формы слова «регламент»."""
        expansions = expand_abbrev("регл")
        self.assertIn("регламент", expansions)
        self.assertIn("регламентного", expansions)
        self.assertIn("регл", expansions)  # исходный токен тоже сохраняется

    def test_abbrev_expansion_in_search(self) -> None:
        """При поиске с «регл.» в вариантах должна быть полная форма «регламент»."""
        q = "Дата последнего регл. задания надо выключить"
        v = search_query_variants(q, max_variants=24)
        self.assertIn("регламент", v)

    def test_empty(self) -> None:
        self.assertEqual(search_query_variants(""), [])
        self.assertEqual(search_query_variants("   "), [])


if __name__ == "__main__":
    unittest.main()
