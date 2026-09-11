"""Snowflake's side of the macrobenchmark.

Branching is simulated exactly as part 1 does it: a branch is a zero-copy database clone, created
with CREATE DATABASE ... CLONE and dropped with DROP DATABASE, on the same connection part 1 opens.
Nothing about those two primitives differs between the parts, so the numbers stay comparable.

What has no Snowflake equivalent is merging. A clone is a whole database, not a set of commits, so
publishing a branch means copying its tables back over the parent's — see merge_branch.

Where Bauplan does the work of a step by running a project, Snowflake runs SQL, so each fixture and
each target has a script here rather than a project directory.
"""

import uuid
from collections.abc import Mapping
from io import StringIO
from pathlib import Path

from src.branch.snowflake import connect as open_connection
from src.branch.sql import Connection, Cursor, ident
from src.macrobench.experiment import Action, Fixture

# The schema the TPC-H tables live in on this backend, used when a run does not name one.
# Snowflake folds unquoted identifiers to upper case, so this is spelled the way it is stored.
DEFAULT_NAMESPACE = "TPCH_SF1"

# The SQL a fixture or a target is built by, named after it and grouped under the workload it
# belongs to. A fixture is `<name>.sql`; a target has one script per variant, `<name>.correct.sql`
# and `<name>.broken.sql`, mirroring the way a Bauplan project takes the variant as a run parameter.
# Script names are unique across the groups, so one index over all of them is enough to find any
# script without the backend having to be told which workload is running.
SQL_ROOT = Path(__file__).parents[1] / "workloads" / "sql"
SCRIPTS = {script.name: script for script in SQL_ROOT.glob("*/*.sql")}


def _script(name: str, variant: str | None = None) -> Path:
    """The SQL script that builds a named fixture or target."""
    filename = f"{name}.{variant}.sql" if variant else f"{name}.sql"
    try:
        return SCRIPTS[filename]
    except KeyError:
        raise RuntimeError(f"no snowflake script {filename} under {SQL_ROOT}") from None


def _statements(script: Path, params: Mapping[str, str]) -> list[str]:
    """The statements in a script, in order.

    Splitting is the connector's own, which knows that a semicolon inside a comment or a string
    literal does not end a statement. Splitting on semicolons by hand looks like it works right up
    until a comment contains one, at which point the script quietly becomes two broken fragments.
    """
    from snowflake.connector.util_text import split_statements

    sql = script.read_text()
    if params:
        sql = sql.format(**params)
    return [statement for statement, _is_put_or_get in split_statements(StringIO(sql)) if statement.strip()]


def _use(cursor: Cursor, branch: str, namespace: str) -> None:
    """Point the session at a branch's copy of the workload's schema.

    Scripts and checks are written against unqualified table names, the same way Bauplan models
    read unqualified names inside a namespace, so the session context is what makes a statement
    land on the right branch.
    """
    cursor.execute(f"USE DATABASE {ident(branch)}")
    cursor.execute(f"USE SCHEMA {ident(namespace)}")


def _set_cache(cursor: Cursor, cache: bool) -> None:
    """Snowflake's equivalent of the caching flag, passed explicitly on every step.

    Left alone, a repeated query is served from the result cache and times a lookup instead of the
    work, and how warm the cache was would depend on what had already been run on the account.
    """
    cursor.execute(f"ALTER SESSION SET USE_CACHED_RESULT = {'TRUE' if cache else 'FALSE'}")


def connect() -> Connection:
    """Open a Snowflake connection from the environment, warmed up.

    The connection rather than a cursor, since a step runs several statements and wants a fresh
    cursor for each. The warmup keeps cold-connection latency out of the first measurement, the
    same way part 1 does it.
    """
    connection = open_connection()
    warmup = connection.cursor()
    warmup.execute("SELECT 1")
    warmup.fetchone()
    return connection


def close(client: Connection) -> None:
    """Close the warehouse connection.

    A run opens one per worker; left to the garbage collector they are still being closed as the
    interpreter shuts down, by which point the connector's transport can already be gone.
    """
    client.close()


def create_root_branch(client: Connection, base_branch: str) -> str:
    """Clone the base database into the run's root and return its name.

    The root carries only what the base database already had; materialize_fixture puts the
    workload's tables on top of it.
    """
    root_branch = f"MACROBENCH_ROOT_{uuid.uuid4().hex.upper()}"
    return create_branch(client, root_branch, base_branch)


def materialize_fixture(
    client: Connection, branch: str, namespace: str, fixture: Fixture, cache: bool = False
) -> None:
    """Build the workload's fixture on the branch.

    This is setup, not measurement: once it has run, the branch holds whatever the workload needs
    to start from, so every timed step can clone it and inherit the lot without rebuilding
    anything. The fixture names the tables it owes, and they are checked here so a fixture that
    half-built fails now rather than as a workload that can never finish.
    """
    cursor = client.cursor()
    _set_cache(cursor, cache)
    _use(cursor, branch, namespace)
    for statement in _statements(_script(fixture.name), {}):
        cursor.execute(statement)

    materialized = {str(row[0]).lower() for row in _tables(cursor, branch, namespace)}
    missing = {table for table in fixture.tables if table.lower() not in materialized}
    if missing:
        raise RuntimeError(f"fixture run left {branch}.{namespace} without: {', '.join(sorted(missing))}")


def _tables(cursor: Cursor, database: str, namespace: str) -> list[tuple[object, ...]]:
    """The base tables in one schema of a database."""
    cursor.execute(
        f"SELECT table_name FROM {ident(database)}.INFORMATION_SCHEMA.TABLES "
        f"WHERE table_type = 'BASE TABLE' AND table_schema = '{ident(namespace).upper()}'"
    )
    return cursor.fetchall()


def create_branch(client: Connection, branch: str, from_ref: str) -> str:
    """Zero-copy clone the source database into a new one; return its name to branch from.

    Exactly part 1's create: one statement covering the whole database.
    """
    client.cursor().execute(f"CREATE DATABASE {ident(branch)} CLONE {ident(from_ref)}")
    return branch


def delete_branch(client: Connection, branch: str) -> None:
    """Drop the cloned database. Exactly part 1's delete."""
    client.cursor().execute(f"DROP DATABASE IF EXISTS {ident(branch)}")


def merge_branch(client: Connection, source_ref: str, into_branch: str) -> None:
    """Publish a branch by cloning each of its tables over the destination's copy.

    Snowflake has no merge: a clone is a whole database rather than a set of commits, so there is
    nothing to replay. The closest honest equivalent is to zero-copy clone every table the branch
    holds back over the destination, which is cheap per table but costs a statement each.

    Table by table rather than ALTER DATABASE ... SWAP WITH, which would be a single statement but
    is not safe when several branches publish at once: a branch cloned before a sibling published
    would swap the sibling's work straight back out again. Cloning only the tables the branch
    actually holds leaves anything published in the meantime alone.
    """
    cursor = client.cursor()
    cursor.execute(
        f"SELECT table_schema, table_name FROM {ident(source_ref)}.INFORMATION_SCHEMA.TABLES "
        "WHERE table_type = 'BASE TABLE'"
    )
    tables = [(str(schema), str(table)) for schema, table in cursor.fetchall()]

    for schema, table in tables:
        destination = f"{ident(into_branch)}.{ident(schema)}.{ident(table)}"
        source = f"{ident(source_ref)}.{ident(schema)}.{ident(table)}"
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {ident(into_branch)}.{ident(schema)}")
        cursor.execute(f"CREATE OR REPLACE TABLE {destination} CLONE {source}")


def run(client: Connection, branch: str, namespace: str, action: Action, cache: bool = False) -> bool:
    """Apply the action's rewrite on the branch by running the target's script.

    A script that fails is not an error the benchmark should stop for: writing something that does
    not build is one of the ways an attempt can be wrong, and such a step gets pruned like any
    other dead end. Only Snowflake's own errors are swallowed, so a broken connection or bad
    credentials still surface instead of looking like a very unlucky agent.
    """
    from snowflake.connector.errors import Error as SnowflakeError

    try:
        cursor = client.cursor()
        _set_cache(cursor, cache)
        _use(cursor, branch, namespace)
        for statement in _statements(_script(action.target, action.variant), dict(action.params)):
            cursor.execute(statement)
    except SnowflakeError:
        return False
    return True


def evaluate(
    client: Connection, branch: str, namespace: str, checks: Mapping[str, str], cache: bool = False
) -> frozenset[str]:
    """Run each target's check on the branch and return the ones that pass.

    The workload supplies the SQL and this only reads the boolean it returns, so what counts as
    correct never has to be known here. A target that never materialized, or whose check will not
    typecheck against what it built, raises out of the query; that counts as not passing rather
    than as a benchmark failure.
    """
    from snowflake.connector.errors import Error as SnowflakeError

    cursor = client.cursor()
    _set_cache(cursor, cache)
    _use(cursor, branch, namespace)

    passing = set()
    for target, sql in checks.items():
        try:
            cursor.execute(sql)
            row = cursor.fetchone()
        except SnowflakeError as error:
            print(f"check for {target} on {branch} failed: {error}")
            continue
        if row is not None and row[0]:
            passing.add(target)
    return frozenset(passing)
