# MCP Server for Confluence Search

MCP (Model Context Protocol) сервер для поиска по внутренней документации Confluence. Поддерживает **SSE** и **streamable-http** транспорты, **Basic Auth**.

## Быстрый старт

```bash
cp .env.example .env          # скопировать шаблон
# заполнить .env (минимум: CONFLUENCE_BASE_URL, CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN)
docker compose up -d --build  # собрать и запустить
```

Сервер доступен по адресу `http://localhost:8003/sse`.

## Конфигурация (.env)

Все настройки — в одном файле `.env`. Скопируйте `.env.example` и заполните:

```bash
cp .env.example .env
```

### Обязательные

| Переменная | Описание |
|---|---|
| `CONFLUENCE_BASE_URL` | URL Confluence (локальный или Cloud) |
| `CONFLUENCE_USERNAME` | Логин (для Cloud — email) |
| `CONFLUENCE_API_TOKEN` | Пароль (для Cloud — API token) |

### Опциональные

| Переменная | По умолч. | Описание |
|---|---|---|
| `MCP_PORT` | `8003` | Порт сервера |
| `CONFLUENCE_TIMEOUT` | `30` | Таймаут HTTP-запросов к Confluence (секунды, минимум 5) |
| `SCORE_MERGE_MAX_VARIANTS` | `12` | Макс. число вариантов запроса при score-based поиске (4–24) |
| `LLM_REWRITE_ENDPOINT` | _(пусто)_ | URL OpenAI-совместимого API для переформулировки запросов |
| `LLM_REWRITE_MODEL` | _(пусто)_ | Имя модели (например `qwen2.5`) |
| `LLM_REWRITE_API_KEY` | _(пусто)_ | API-ключ (если не нужен — оставить пустым) |
| `LLM_REWRITE_TIMEOUT` | `5` | Таймаут LLM-запроса (секунды) |

### Как получить credentials

**Локальный Confluence (on-premise):** используйте логин и пароль от учётной записи.

**Atlassian Cloud:**
1. Перейдите https://id.atlassian.com/manage-profile/security/api-tokens
2. Создайте API token
3. В качестве `CONFLUENCE_USERNAME` укажите email, в качестве `CONFLUENCE_API_TOKEN` — созданный token

## Инструменты (Tools)

### `search_content`

Поиск страниц по ключевым словам. По умолчанию (`multi_pass=true`) сервер:
- извлекает `pageId` из Confluence-ссылок в запросе
- генерирует несколько вариантов поиска (полная фраза, токены с `_`, длинные слова)
- выполняет CQL-запросы по каждому варианту и объединяет результаты без дубликатов

**Параметры:**

| Параметр | Тип | По умолч. | Описание |
|---|---|---|---|
| `query` | string | _(обязательный)_ | Поисковый запрос |
| `space_key` | string | `null` | Ключ пространства или несколько через запятую (`DEV, HR`) |
| `space_keys` | string[] | `null` | Список ключей пространств (предпочтительно для нескольких) |
| `content_type` | string | `"page"` | Тип: `page`, `blogpost`, `comment`, `attachment`, `space`, `all` |
| `limit` | int | `10` | Макс. результатов (до 100) |
| `multi_pass` | bool | `true` | Расширенный поиск по нескольким вариантам |
| `score_merge` | bool | `false` | Ранжирование по score (см. ниже) |
| `score_merge_max_variants` | int | `0` | Лимит вариантов (0 = из конфига, `SCORE_MERGE_MAX_VARIANTS`) |
| `llm_rewrite` | bool | `false` | Переформулировать запрос через LLM перед поиском |

```json
search_content(query="оформить звонок директорат", score_merge=true)
```

### `search_by_cql`

Поиск по произвольной CQL-строке.

| Параметр | Тип | По умолч. | Описание |
|---|---|---|---|
| `cql` | string | _(обязательный)_ | CQL-запрос |
| `limit` | int | `10` | Макс. результатов |
| `expand` | string[] | `["space","version"]` | Дополнительные поля |

### `get_page_content`

Полное содержимое страницы по ID. Возвращает HTML (`body.view`), пространство, версию, цепочку родителей (`ancestors`) и дочерние страницы (`children.page`).

### `get_page_children`

Список дочерних страниц (id, title, version) для заданного page_id.

### `list_spaces`

Список всех пространств Confluence.

### `confluence_health`

Проверка доступности Confluence и учётных данных. Возвращает имя пользователя и git-хэш сборки.

## Умный поиск

### Проблема

Запрос «КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ» не находит статью со словом «принять», потому что:
- «оформить» и «принять» — лексически разные слова, Confluence не связывает их
- общий вариант «ЗВОНОК ДИРЕКТОРАТ» существует в обоих контекстах, но ранние варианты заполняют `limit` раньше

Решение — три независимых улучшения, каждое решает свою часть проблемы:

### Улучшение 1: Score-based merging (`score_merge=true`)

**Идея:** запустить ВСЕ варианты запроса, собрать все совпадения, ранжировать по числу вариантов, которые нашли страницу.

Без score_merge сервер останавливается, когда набрал `limit` результатов — первые варианты забивают выдачу. Со score_merge все варианты выполняются до конца, и страница, найденная 5 вариантами, получит более высокий рейтинг, чем страница, найденная одним.

**Веса вариантов:**

| Тип варианта | Вес | Пример |
|---|---|---|
| Полная фраза (исходный запрос) | 3.0 | «КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ» |
| 2–3 слова | 2.0–2.5 | «ОФОРМИТЬ ЗВОНОК» |
| Одно слово | 1.0 | «ДИРЕКТОРАТ» |

Количество вариантов ограничено `SCORE_MERGE_MAX_VARIANTS` (по умолчанию 12, диапазон 4–24).

```json
search_content(query="оформить звонок директорат", score_merge=true)
```

### Улучшение 2: Noun-only проход (автоматически)

**Идея:** pymorphy3 определяет части речи. Из запроса выделяются только существительные — получается «чистый» вариант без глаголов и предлогов.

```
"КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ"  →  "ЗВОНОК ДИРЕКТОРАТ"
"ПОРЯДОК СОГЛАСОВАНИЯ ДОКУМЕНТОВ"    →  "ПОРЯДОК СОГЛАСОВАНИЕ ДОКУМЕНТ"
```

Существительные — самые информативные слова в поисковом запросе. Убрав глаголы и предлоги, вариант точнее попадает в заголовки и текст статей. Работает всегда, флагов не требует, внешних зависимостей нет.

### Улучшение 3: LLM-переформулировка (`llm_rewrite=true`)

**Идея:** LLM получает исходный запрос и генерирует 3–5 альтернативных формулировок, используя синонимы и перефразирование.

```
"КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ"
  → "принять звонок директорат"
  → "перевести вызов в директорат"
  → "маршрутизация звонков директорат"
```

Это единственный механизм, который понимает синонимы («оформить» = «принять» = «перевести»). Требует настроенных переменных `LLM_REWRITE_*` в `.env`. При ошибке (таймаут, LLM недоступен) тихо откатывается к обычному поиску.

```json
search_content(query="оформить звонок директорат", llm_rewrite=true)
```

Можно комбинировать оба флага: `score_merge=true, llm_rewrite=true`.

### Сравнение подходов

| Подход | Зависимости | Покрытие синонимов |
|---|---|---|
| **Score merging** | нет | ~40% — ловит через пересечения вариантов |
| **Noun-only** | pymorphy3 (встроен) | ~60% — убирает глагольный шум |
| **LLM rewrite** | внешний LLM API | ~90% — понимает синонимы и перефразирование |

### Как это работает вместе

```
Запрос: "КАК ОФОРМИТЬ ЗВОНОК В ДИРЕКТОРАТ"
                    │
    ┌───────────────┼───────────────┐
    │               │               │
 Полная фраза   Noun-only       LLM варианты
 "КАК ОФОРМИТЬ  "ЗВОНОК        "принять звонок
  ЗВОНОК В       ДИРЕКТОРАТ"    директорат"
  ДИРЕКТОРАТ"                   "перевести вызов
    │               │            в директорат"
    │               │               │
    └───────────────┼───────────────┘
                    │
            Каждый вариант →
            CQL-запрос к Confluence
                    │
                    ▼
          Score-based ранжирование
          (страница, найдённая 3+
          вариантами, будет первой)
                    │
                    ▼
              Результаты
```

## Интеграция

### Claude Desktop

Добавьте в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "confluence": {
      "url": "http://localhost:8003/sse",
      "transport": "sse"
    }
  }
}
```

### Claude Code (CLI)

Добавьте в `~/.claude/mcp_config.json`:

```json
{
  "mcpServers": {
    "confluence": {
      "url": "http://localhost:8003/sse",
      "transport": "sse"
    }
  }
}
```

### MCP SuperAssistant Proxy

```json
{
  "mcpServers": {
    "confluence": {
      "type": "streamable-http",
      "url": "http://localhost:8003/mcp",
      "timeout": 30
    }
  }
}
```

## Endpoints

| Endpoint | Метод | Описание |
|---|---|---|
| `/sse` | GET | SSE endpoint (Claude Desktop, Claude Code) |
| `/messages/` | POST | SSE JSON-RPC |
| `/mcp` | GET/POST | Streamable-HTTP (SuperAssistant Proxy) |
| `/health` | GET | Статус сервера и Confluence (браузер, curl) |

### Проверка curl

```bash
# Статус
curl http://localhost:8003/health

# Инициализация MCP
curl -X POST http://localhost:8003/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

## Локальная установка (без Docker)

```bash
pip install -r requirements.txt
cp .env.example .env          # заполнить credentials
python -m confluence_mcp.server
```

## Структура проекта

```
src/confluence_mcp/
├── server.py            # MCP сервер (SSE + streamable-http), инструменты
├── confluence_client.py # REST-клиент Confluence (Basic Auth)
├── config.py            # Конфигурация из .env
├── cql_escape.py        # Экранирование CQL-строк
├── query_expand.py      # Генерация вариантов поискового запроса
├── scoring.py           # Score-based ранжирование результатов
├── noun_extract.py      # Выделение существительных (pymorphy3)
└── llm_rewrite.py       # LLM-переформулировка запросов

tests/
└── test_cql_escape.py   # python tests/test_cql_escape.py -v
```

## Требования

- Python 3.10+
- Docker (рекомендуется)
- Confluence (локальный или Cloud) с Basic Auth
