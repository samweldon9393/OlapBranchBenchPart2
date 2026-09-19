"""Snowflake's side of the macrobenchmark.

Branching is simulated exactly as part 1 does it: a branch is a zero-copy database clone, created
with CREATE DATABASE ... CLONE and dropped with DROP DATABASE, on the same connection part 1 opens.
Nothing about those two primitives differs between the parts, so the numbers stay comparable.

What has no Snowflake equivalent is merging. A clone is a whole database, not a set of commits, so
publishing a branch means copying its tables back over the parent's — see merge_branch.

Running a build and reading a branch are shared with Databricks, in backends/sql.py; everything this
platform does differently is the DIALECT below.
"""

import re
import uuid
from collections.abc import Mapping, Sequence

# The connector ships no usable types, which is why part 1's Protocols exist; the error class is
# imported here rather than lazily because it is what tells a failed build from a broken connection
from snowflake.connector.errors import Error as SnowflakeError

from src.branch.snowflake import connect as open_connection
from src.branch.snowflake import list_tables
from src.branch.sql import Connection, Cursor, ident
from src.macrobench.backends import sql
from src.macrobench.backends.refs import pack_ref, unpack_ref
from src.macrobench.experiment import Action, Outcome

# The schema the TPC-H tables live in on this backend, used when a run does not name one.
# Snowflake folds unquoted identifiers to upper case, so this is spelled the way it is stored.
DEFAULT_NAMESPACE = "TPCH_SF1"


def _use(cursor: Cursor, branch: str, namespace: str) -> None:
    """Point the session at a branch's copy of the workload's schema.

    Scripts and checks are written against unqualified table names, the same way Bauplan models
    read unqualified names inside a namespace, so the session context is what makes a statement
    land on the right branch.
    """
    cursor.execute(f"USE DATABASE {ident(branch)}")
    cursor.execute(f"USE SCHEMA {ident(namespace)}")


def _set_cache(cursor: Cursor, cache: bool) -> None:
    """Snowflake's spelling of the caching flag.

    Left alone, a repeated query is served from the result cache and times a lookup instead of the
    work, and how warm the cache was would depend on what had already been run on the account.
    """
    cursor.execute(f"ALTER SESSION SET USE_CACHED_RESULT = {'TRUE' if cache else 'FALSE'}")


def _qualify(branch: str, namespace: str, table: str) -> str:
    """Name a table on a branch the session is not pointed at."""
    return f"{ident(branch)}.{ident(namespace)}.{ident(table)}"


def _list_tables(cursor: Cursor, branch: str, namespace: str) -> frozenset[str]:
    """The base tables in the branch's copy of the namespace, lower-cased."""
    return frozenset(
        table.lower() for schema, table in list_tables(cursor, branch) if schema.upper() == namespace.upper()
    )


DIALECT = sql.Dialect(
    failure=SnowflakeError,
    use=_use,
    qualify=_qualify,
    list_tables=_list_tables,
    set_cache=_set_cache,
)


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
    """Clone the base database into the run's root and return its name."""
    return create_branch(client, f"MACROBENCH_ROOT_{uuid.uuid4().hex.upper()}", base_branch)


def create_branch(client: Connection, branch: str, from_ref: str) -> str:
    """Zero-copy clone the source database into a new one; return its name to branch from.

    Exactly part 1's create: one statement covering the whole database. From a snapshot the clone is
    taken by Time Travel instead, as the database stood right before that statement ran.
    """
    source, statement = unpack_ref(from_ref)
    at = f" BEFORE(STATEMENT => '{_query_id(statement)}')" if statement else ""
    client.cursor().execute(f"CREATE DATABASE {ident(branch)} CLONE {ident(source)}{at}")
    return branch


def _query_id(value: str) -> str:
    """Validate a query id before it is interpolated into a clone, the way ident() does a name."""
    if not re.fullmatch(r"[0-9a-f-]+", value):
        raise ValueError(f"not a Snowflake query id: {value}")
    return value


def snapshot(client: Connection, branch: str) -> str:
    """The database as it stands now, as somewhere create_branch can clone from.

    Snowflake has no commits to name, only points in time, so this makes one: a trivial statement
    whose query id is the reference. Cloning BEFORE it gives the state right after every change made
    until then, and Time Travel keeps that reachable for the retention period, a day by default.
    """
    cursor = client.cursor()
    cursor.execute("SELECT 1")
    cursor.execute("SELECT LAST_QUERY_ID()")
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"no query id to snapshot {branch} by")
    return pack_ref(branch, _query_id(str(row[0])))


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
    tables_to_copy = [(str(schema), str(table)) for schema, table in cursor.fetchall()]

    for schema, table in tables_to_copy:
        destination = f"{ident(into_branch)}.{ident(schema)}.{ident(table)}"
        source = f"{ident(source_ref)}.{ident(schema)}.{ident(table)}"
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {ident(into_branch)}.{ident(schema)}")
        cursor.execute(f"CREATE OR REPLACE TABLE {destination} CLONE {source}")


def overwrite_branch(client: Connection, source_ref: str, into_branch: str, namespace: str) -> None:
    """Publish a branch by overwriting the destination's tables with its own.

    That is already what merge_branch does here: it clones every table the branch holds over the
    destination's, which covers the ones the branch rewrote whatever it was cut from.
    """
    merge_branch(client, source_ref, into_branch)


def tables(client: Connection, branch: str, namespace: str) -> frozenset[str]:
    """The tables the branch holds."""
    return sql.tables(client, DIALECT, branch, namespace)


def run(
    client: Connection, branch: str, namespace: str, action: Action, checks: Mapping[str, str], cache: bool = False
) -> Outcome:
    """Build the action on the branch by running its scripts, then run its checks."""
    return sql.run(client, DIALECT, branch, namespace, action, checks, cache)


def query(client: Connection, branch: str, namespace: str, statement: str, cache: bool = False) -> list[dict]:
    """Read the branch."""
    return sql.query(client, DIALECT, branch, namespace, statement, cache)


def read_across(
    client: Connection, branches: Sequence[str], namespace: str, table: str, cache: bool = False
) -> dict[str, list[dict]]:
    """Read one table off many branches in a single statement."""
    return sql.read_across(client, DIALECT, branches, namespace, table, cache)
