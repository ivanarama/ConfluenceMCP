"""CQL string literal escaping for Confluence search."""


def escape_cql_string(value: str) -> str:
    """Escape backslashes and double quotes for use inside a CQL double-quoted string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
