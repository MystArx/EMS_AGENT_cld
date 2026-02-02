import re
import logging

logger = logging.getLogger("sql_refiner")

# -------------------------------------------------
# Utilities
# -------------------------------------------------

IDENT = r"(?:`?[a-zA-Z_][a-zA-Z0-9_]*`?)"

# -------------------------------------------------
# Rule 0 — Enforce backticks on hyphenated schemas
# -------------------------------------------------

_SCHEMA_WITH_HYPHEN_RE = re.compile(
    r"""
    (?<!`)
    (?P<schema>[a-zA-Z_][a-zA-Z0-9_-]*-[a-zA-Z0-9_-]*)
    \.
    (?P<table>`?[a-zA-Z_][a-zA-Z0-9_]*`?)
    """,
    flags=re.VERBOSE,
)


def _fix_hyphenated_schema_names(sql: str) -> str:
    def repl(match: re.Match) -> str:
        schema = match.group("schema")
        table = match.group("table")
        return f"`{schema}`.{table}"

    sql, count = _SCHEMA_WITH_HYPHEN_RE.subn(repl, sql)

    if count:
        logger.info(
            "SQL Refiner: fixed %d unquoted hyphenated schema name(s)",
            count,
        )

    return sql


# -------------------------------------------------
# Rule 1 — SAFE quick_code_master JOIN fix
# -------------------------------------------------

_QUICK_CODE_ALIAS_RE = re.compile(
    rf"""
    (?:FROM|JOIN)\s+
    `?quick_code_master`?
    (?:\s+AS)?\s+
    (?P<alias>{IDENT})
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

_JOIN_ON_RE_TEMPLATE = rf"""
ON\s+
(?P<lhs>[^=]+?)\s*=\s*
(?P<rhs>{IDENT}\.\w+)
"""


def _find_quick_code_aliases(sql: str) -> set[str]:
    return {
        m.group("alias").strip("`")
        for m in _QUICK_CODE_ALIAS_RE.finditer(sql)
    }


def _fix_quick_code_joins(sql: str) -> str:
    aliases = _find_quick_code_aliases(sql)
    if not aliases:
        return sql

    total_fixes = 0

    for alias in aliases:
        join_on_re = re.compile(
            _JOIN_ON_RE_TEMPLATE.replace("{IDENT}", alias),
            flags=re.IGNORECASE | re.VERBOSE,
        )

        def repl(match: re.Match) -> str:
            lhs = match.group("lhs").strip()
            return f"ON {lhs} = {alias}.id"

        sql, count = join_on_re.subn(repl, sql)
        total_fixes += count

    if total_fixes:
        logger.info(
            "SQL Refiner: fixed %d quick_code_master JOIN condition(s)",
            total_fixes,
        )

    return sql


# -------------------------------------------------
# Rule 2 — HARD invariant: account_name MUST be fuzzy
# -------------------------------------------------

_ACCOUNT_NAME_EQ_RE = re.compile(
    rf"""
    (?:
        (?P<qualified>{IDENT}\.account_name)
        |
        (?P<unqualified>\baccount_name\b)
    )
    \s*=\s*
    '(?P<val>[^']+)'
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def _enforce_account_name_like(sql: str) -> str:
    def repl(match: re.Match) -> str:
        col = match.group("qualified") or "account_name"
        val = match.group("val")
        return f"{col} LIKE '%%{val}%%'"

    sql, count = _ACCOUNT_NAME_EQ_RE.subn(repl, sql)

    if count:
        logger.info(
            "SQL Refiner: enforced LIKE for account_name (%d occurrence(s))",
            count,
        )

    return sql


# -------------------------------------------------
# Rule 3 — HARD invariant: region / city / warehouse fuzzy
# -------------------------------------------------

_FUZZY_NAME_COLUMNS = {
    "warehouse_name",
    "name",          # quick_code_master.name (city / region)
    "region_name",   # future-proofing
}

_OTHER_NAME_EQ_RE = re.compile(
    rf"""
    (?P<col>{IDENT}\.(?:{'|'.join(_FUZZY_NAME_COLUMNS)}))
    \s*=\s*
    '(?P<val>[^']+)'
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)


def _apply_fuzzy_name_like(sql: str) -> str:
    def repl(match: re.Match) -> str:
        col = match.group("col")
        val = match.group("val")
        return f"{col} LIKE '%%{val}%%'"

    sql, count = _OTHER_NAME_EQ_RE.subn(repl, sql)

    if count:
        logger.info(
            "SQL Refiner: enforced LIKE for business name (%d occurrence(s))",
            count,
        )

    return sql


# -------------------------------------------------
# PUBLIC API
# -------------------------------------------------

def refine_sql(sql: str) -> str:
    """
    Deterministic, scoped SQL fixes.
    Order matters.
    """
    original = sql

    sql = _fix_hyphenated_schema_names(sql)  # 🔒 MUST BE FIRST
    sql = _fix_quick_code_joins(sql)
    sql = _enforce_account_name_like(sql)
    sql = _apply_fuzzy_name_like(sql)

    if sql != original:
        logger.debug("SQL Refiner modified SQL")

    return sql
