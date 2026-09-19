"""Databricks' side of the macrobenchmark.

Branching is simulated as part 1 does it: Databricks has no database-level clone, so a branch is a
new schema into which every table of the parent is SHALLOW CLONE'd, and deleting one is DROP SCHEMA
CASCADE. A branch name here carries its catalog — `catalog.schema` — because the catalog is the only
place the schema can live and nothing else in the run would otherwise know it.

Two things follow from a limitation Databricks genuinely has: a shallow clone cannot itself be
shallow-cloned.

The root is a DEEP clone rather than a shallow one. That is setup, not measurement, and it leaves
the root holding real tables so that every timed step branch is a true SHALLOW CLONE — the same
operation part 1 times. A shallow root would make every step a nested clone and put the backend out
of the running entirely rather than only for the workloads that genuinely need depth.

Anything deeper than one level is simply not available. A workload that branches off a branch — the
data engineering chain — fails on its second step, and that is a fact about Databricks rather than
something for this adapter to work around.

Running a build and reading a branch are shared with Snowflake, in backends/sql.py; everything this
platform does differently is the DIALECT below.
"""

import uuid
from collections.abc import Mapping, Sequence

# Imported here rather than lazily because it is what tells a failed build from a broken connection
from databricks.sql.exc import Error as DatabricksError

from src.branch.databricks import connect as open_connection
from src.branch.databricks import list_tables, split_namespace
from src.branch.sql import Connection, Cursor, ident
from src.macrobench.backends import sql
from src.macrobench.backends.refs import pack_ref, unpack_ref
from src.macrobench.experiment import Action, Outcome

# A branch is itself a schema here, so the namespace is fixed by the branch rather than named
# separately. This is the schema of the usual base, kept only so the protocol has an answer.
DEFAULT_NAMESPACE = "tpch"


def _schema(branch: str) -> tuple[str, str]:
    """The catalog and schema a branch names, both quoted."""
    return split_namespace(branch)


def _use(cursor: Cursor, branch: str, namespace: str) -> None:
    """Point the session at a branch.

    Scripts and checks are written against unqualified table names, so the session context is what
    makes a statement land on the right branch. The namespace the driver passes is ignored: on this
    backend the branch *is* the schema, so there is nothing left for it to select.
    """
    catalog, schema = _schema(branch)
    cursor.execute(f"USE CATALOG {catalog}")
    cursor.execute(f"USE SCHEMA {schema}")


def _set_cache(cursor: Cursor, cache: bool) -> None:
    """Databricks' spelling of the caching flag, passed explicitly on every step."""
    cursor.execute(f"SET use_cached_result = {'true' if cache else 'false'}")


def _qualify(branch: str, namespace: str, table: str) -> str:
    """Name a table on a branch the session is not pointed at."""
    catalog, schema = _schema(branch)
    return f"{catalog}.{schema}.{ident(table)}"


def _list_tables(cursor: Cursor, branch: str, namespace: str) -> frozenset[str]:
    """The tables the branch's schema holds, lower-cased."""
    catalog, schema = _schema(branch)
    return frozenset(name.lower() for name in list_tables(cursor, catalog, schema))


DIALECT = sql.Dialect(
    failure=DatabricksError,
    use=_use,
    qualify=_qualify,
    list_tables=_list_tables,
    set_cache=_set_cache,
)


def connect() -> Connection:
    """Open a Databricks SQL warehouse connection, warmed up.

    The warmup keeps the warehouse resume out of the first measurement, the same way part 1 does it.
    """
    connection = open_connection()
    warmup = connection.cursor()
    warmup.execute("SELECT 1")
    warmup.fetchall()
    return connection


def close(client: Connection) -> None:
    """Close the warehouse connection.

    A run opens one per worker; left to the garbage collector they are still being closed as the
    interpreter shuts down, by which point the connector's transport can already be gone.
    """
    client.close()


def _clone_tables(
    cursor: Cursor, source: str, destination: str, deep: bool, versions: Mapping[str, int] | None = None
) -> None:
    """Clone every table of one schema into another.

    Given the versions a snapshot recorded, each table is cloned as it stood at its version instead,
    and a table the snapshot does not name did not exist yet, so it is left out.
    """
    source_catalog, source_schema = _schema(source)
    target_catalog, target_schema = _schema(destination)
    kind = "DEEP" if deep else "SHALLOW"
    for table in list_tables(cursor, source_catalog, source_schema):
        if versions is None:
            at = ""
        elif table in versions:
            at = f" VERSION AS OF {versions[table]}"
        else:
            continue
        cursor.execute(
            f"CREATE TABLE {target_catalog}.{target_schema}.{table} "
            f"{kind} CLONE {source_catalog}.{source_schema}.{table}{at}"
        )


def _version(cursor: Cursor, table: str) -> int:
    """The latest version in a table's Delta history."""
    cursor.execute(f"DESCRIBE HISTORY {table} LIMIT 1")
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"{table} has no history")
    return int(str(row[0]))


def create_root_branch(client: Connection, base_branch: str) -> str:
    """Deep clone the base schema into the run's root and return its catalog.schema.

    Deep rather than shallow so the root holds real tables: a shallow clone cannot be shallow-cloned,
    and every timed step branches off this one. Copying the data here is untimed setup, and it is
    what keeps the measured operation a true shallow clone.
    """
    catalog, _ = _schema(base_branch)
    root_branch = f"{catalog}.macrobench_root_{uuid.uuid4().hex}"
    cursor = client.cursor()
    cursor.execute(f"CREATE SCHEMA {_schema(root_branch)[0]}.{_schema(root_branch)[1]}")
    _clone_tables(cursor, base_branch, root_branch, deep=True)
    return root_branch


def create_branch(client: Connection, branch: str, from_ref: str) -> str:
    """Shallow clone every table of the parent schema into a new one. Exactly part 1's create.

    From a snapshot each table is cloned at its recorded version instead. Those are still clones of
    the source's own tables, so the branch is one level deep like any other.
    """
    source, at = unpack_ref(from_ref)
    versions = {ident(table): int(version) for table, version in (p.split("=") for p in at.split(","))} if at else None
    catalog, schema = _schema(branch)
    cursor = client.cursor()
    cursor.execute(f"CREATE SCHEMA {catalog}.{schema}")
    try:
        _clone_tables(cursor, source, branch, deep=False, versions=versions)
    except Exception:
        # The driver only learns a branch exists once this returns, so a schema left behind by a
        # clone that failed — a nested shallow clone, say — is one teardown would never find
        cursor.execute(f"DROP SCHEMA IF EXISTS {catalog}.{schema} CASCADE")
        raise
    return branch


def snapshot(client: Connection, branch: str) -> str:
    """The schema as it stands now: the version of every table in it.

    Delta keeps history per table rather than per schema, so no single point names the whole branch;
    the latest version of every table, taken together, is the ref.
    """
    catalog, schema = _schema(branch)
    cursor = client.cursor()
    versions = [
        (table, _version(cursor, f"{catalog}.{schema}.{table}")) for table in list_tables(cursor, catalog, schema)
    ]
    return pack_ref(branch, ",".join(f"{table}={version}" for table, version in versions))


def delete_branch(client: Connection, branch: str) -> None:
    """Drop the branch schema and everything in it. Exactly part 1's delete."""
    catalog, schema = _schema(branch)
    client.cursor().execute(f"DROP SCHEMA IF EXISTS {catalog}.{schema} CASCADE")


def merge_branch(client: Connection, source_ref: str, into_branch: str) -> None:
    """Publish a branch by deep-cloning the tables it added or rewrote onto the destination.

    Databricks has no merge, and two of its properties decide how this has to be emulated. A shallow
    clone would break as soon as the branch is dropped, since the clone points at the branch's
    files, so what lands has to be a real copy. And only the tables the branch changed are copied:
    deep-cloning everything would copy the whole dataset on every publish, and the tables a branch
    inherited untouched are the ones the destination already has.

    A table's own history says whether the branch changed it. A clone's history starts at the clone,
    version 0, so anything past that was written on the branch; a table the destination lacks was
    added. Reading the history costs a statement per table, which is part of what publishing costs.
    """
    cursor = client.cursor()
    source_catalog, source_schema = _schema(source_ref)
    target_catalog, target_schema = _schema(into_branch)

    source_tables = list_tables(cursor, source_catalog, source_schema)
    added = set(source_tables) - set(list_tables(cursor, target_catalog, target_schema))
    rewritten = {table for table in source_tables if _version(cursor, f"{source_catalog}.{source_schema}.{table}") > 0}
    for table in sorted(added | rewritten):
        cursor.execute(
            f"CREATE OR REPLACE TABLE {target_catalog}.{target_schema}.{table} "
            f"DEEP CLONE {source_catalog}.{source_schema}.{table}"
        )


def overwrite_branch(client: Connection, source_ref: str, into_branch: str, namespace: str) -> None:
    """Publish a branch by overwriting the destination's tables with the ones it rewrote.

    That is already what merge_branch does here; the namespace is the branch itself on this backend.
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
