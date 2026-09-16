"""What the two SQL backends share: the scripts a build runs, and how a step reads and writes.

Snowflake and Databricks build a step by running the same dialect-neutral script and read a branch
with the same statements. What differs is how a session names a branch, which errors mean "that did
not build", and how caching is turned off. That difference is a `Dialect` — data each backend states
once, rather than a base class whose behaviour has to be reassembled from two files.

Branching itself is not here: cloning a database, cloning a schema table by table, and what a
snapshot means are exactly where the two platforms are not alike, and each backend says so itself.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from src.branch.sql import Connection, Cursor
from src.macrobench.experiment import Action

# The SQL a build runs, named after it and grouped under the workload it belongs to. A build with one
# implementation is `<name>.sql`; one with several is `<name>.<variant>.sql`. Script names are unique
# across the groups, so one index over all of them finds any script without the backend having to be
# told which workload is running.
SQL_ROOT = Path(__file__).parents[1] / "workloads" / "sql"
SCRIPTS = {script.name: script for script in SQL_ROOT.glob("*/*.sql")}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Dialect:
    """What one SQL platform does differently. Everything else about running a step is shared."""

    # What a statement raises when it does not work, which is how a build reports that it did not
    failure: type[BaseException]
    # Point the session at a branch's copy of the workload's tables
    use: Callable[[Cursor, str, str], None]
    # Name a table on a branch the session is not pointed at
    qualify: Callable[[str, str, str], str]
    # The tables a branch holds, lower-cased
    list_tables: Callable[[Cursor, str, str], frozenset[str]]
    # This platform's spelling of the caching flag, passed explicitly on every step
    set_cache: Callable[[Cursor, bool], None]


def script(build: str, variant: str = "") -> Path:
    """The SQL script a build runs, for the variant asked for or the only one there is."""
    filename = f"{build}.{variant}.sql" if variant else f"{build}.sql"
    try:
        return SCRIPTS[filename]
    except KeyError:
        raise RuntimeError(f"no sql script {filename} under {SQL_ROOT}") from None


def statements(path: Path, params: Mapping[str, str]) -> list[str]:
    """The statements in a script, in order, with the parameters filled in.

    Only the names the caller passed are substituted, so a script can hold braces of its own — the
    Python inside a Snowpark procedure, say — without having to double them.

    Splitting is the Snowflake connector's own, used by both backends: it is a plain tokenizer that
    knows a semicolon inside a comment or a string literal does not end a statement, and splitting by
    hand looks like it works right up until a comment contains one. Both backends splitting the
    shared scripts the same way is itself worth having.
    """
    from snowflake.connector.util_text import split_statements

    sql = _PLACEHOLDER.sub(lambda match: params.get(match.group(1), match.group(0)), path.read_text())
    return [statement for statement, _is_put_or_get in split_statements(StringIO(sql)) if statement.strip()]


def _cursor(client: Connection, dialect: Dialect, branch: str, namespace: str, cache: bool) -> Cursor:
    """A cursor pointed at the branch, with caching set explicitly."""
    cursor = client.cursor()
    dialect.set_cache(cursor, cache)
    dialect.use(cursor, branch, namespace)
    return cursor


def _rows(cursor: Cursor) -> list[dict]:
    """Whatever the cursor holds, as dicts with lower-cased column names."""
    columns = [str(column[0]).lower() for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def run(
    client: Connection, dialect: Dialect, branch: str, namespace: str, action: Action, cache: bool = False
) -> bool:
    """Build the action on the branch by running its script."""
    try:
        cursor = _cursor(client, dialect, branch, namespace, cache)
        for statement in statements(script(action.build, action.variant), dict(action.params)):
            cursor.execute(statement)
    except dialect.failure:
        return False
    return True


def query(
    client: Connection, dialect: Dialect, branch: str, namespace: str, sql: str, cache: bool = False
) -> list[dict]:
    """Read the branch."""
    cursor = _cursor(client, dialect, branch, namespace, cache)
    cursor.execute(sql)
    return _rows(cursor)


def tables(client: Connection, dialect: Dialect, branch: str, namespace: str) -> frozenset[str]:
    """The tables the branch holds."""
    return dialect.list_tables(client.cursor(), branch, namespace)


def read_across(
    client: Connection,
    dialect: Dialect,
    branches: Sequence[str],
    namespace: str,
    table: str,
    cache: bool = False,
) -> dict[str, list[dict]]:
    """Read one table off many branches in a single statement.

    A branch is a database or a schema here, so their copies of a table can be unioned directly. A
    branch that never wrote the table would fail the whole union, so that case falls back to reading
    the branches one at a time — which costs nothing on the normal path and keeps a run from dying
    inside the timed region over a branch that has nothing to say.
    """
    readings: dict[str, list[dict]] = {branch: [] for branch in branches}
    if not branches:
        return readings

    cursor = client.cursor()
    dialect.set_cache(cursor, cache)
    try:
        cursor.execute(
            " UNION ALL ".join(
                f"SELECT '{branch}' AS branch_name__, * FROM {dialect.qualify(branch, namespace, table)}"
                for branch in branches
            )
        )
    except dialect.failure:
        for branch in branches:
            try:
                readings[branch] = query(client, dialect, branch, namespace, f"SELECT * FROM {table}", cache)
            except dialect.failure:
                readings[branch] = []
        return readings

    for record in _rows(cursor):
        readings[str(record.pop("branch_name__"))].append(record)
    return readings
