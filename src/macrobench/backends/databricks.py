"""Databricks' side of the macrobenchmark.

Branching is simulated as part 1 does it: Databricks has no database-level clone, so a branch is a
new schema into which every table of the parent is SHALLOW CLONE'd, and deleting one is DROP SCHEMA
CASCADE. A branch name here carries its catalog — `catalog.schema` — because the catalog is the
only place the schema can live and nothing else in the run would otherwise know it.

Two things follow from a limitation Databricks genuinely has: a shallow clone cannot itself be
shallow-cloned.

The root is a DEEP clone rather than a shallow one. That is setup, not measurement, and it leaves
the root holding real tables so that every timed step branch is a true SHALLOW CLONE — the same
operation part 1 times. A shallow root would make every step a nested clone and put the backend out
of the running entirely rather than only for the workloads that genuinely need depth.

Anything deeper than one level is simply not available. A workload that branches off a branch — the
data engineering chain — fails on its second step, and that is a fact about Databricks rather than
something for this adapter to work around.

The SQL is the same scripts Snowflake runs; the dialect-specific spellings were taken out of them
so one set serves both.
"""

import uuid
from collections.abc import Mapping

from src.branch.databricks import connect as open_connection
from src.branch.databricks import list_tables, split_namespace
from src.branch.sql import Connection, Cursor
from src.macrobench.backends.snowflake import _script, _statements
from src.macrobench.experiment import Action, Fixture

# A branch is itself a schema here, so the namespace is fixed by the branch rather than named
# separately. This is the schema of the usual base, kept only so the protocol has an answer.
DEFAULT_NAMESPACE = "tpch"


def _schema(branch: str) -> tuple[str, str]:
    """The catalog and schema a branch names, both quoted."""
    return split_namespace(branch)


def _use(cursor: Cursor, branch: str) -> None:
    """Point the session at a branch.

    Scripts and checks are written against unqualified table names, so the session context is what
    makes a statement land on the right branch. The namespace the driver passes is ignored: on this
    backend the branch *is* the schema, so there is nothing left for it to select.
    """
    catalog, schema = _schema(branch)
    cursor.execute(f"USE CATALOG {catalog}")
    cursor.execute(f"USE SCHEMA {schema}")


def connect() -> Connection:
    """Open a Databricks SQL warehouse connection, warmed up.

    The warmup keeps the warehouse resume out of the first measurement, the same way part 1 does it.
    """
    connection = open_connection()
    warmup = connection.cursor()
    warmup.execute("SELECT 1")
    warmup.fetchall()
    return connection


def _clone_tables(cursor: Cursor, source: str, destination: str, deep: bool) -> None:
    """Clone every table of one schema into another."""
    source_catalog, source_schema = _schema(source)
    target_catalog, target_schema = _schema(destination)
    kind = "DEEP" if deep else "SHALLOW"
    for table in list_tables(cursor, source_catalog, source_schema):
        cursor.execute(
            f"CREATE TABLE {target_catalog}.{target_schema}.{table} "
            f"{kind} CLONE {source_catalog}.{source_schema}.{table}"
        )


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


def materialize_fixture(
    client: Connection, branch: str, namespace: str, fixture: Fixture, cache: bool = False
) -> None:
    """Build the workload's fixture on the branch, and check it left the tables it owes."""
    cursor = client.cursor()
    _use(cursor, branch)
    for statement in _statements(_script(fixture.name), {}):
        cursor.execute(statement)

    catalog, schema = _schema(branch)
    materialized = {name.strip("`").lower() for name in list_tables(cursor, catalog, schema)}
    missing = {table for table in fixture.tables if table.lower() not in materialized}
    if missing:
        raise RuntimeError(f"fixture run left {branch} without: {', '.join(sorted(missing))}")


def create_branch(client: Connection, branch: str, from_ref: str) -> str:
    """Shallow clone every table of the parent schema into a new one. Exactly part 1's create."""
    catalog, schema = _schema(branch)
    cursor = client.cursor()
    cursor.execute(f"CREATE SCHEMA {catalog}.{schema}")
    _clone_tables(cursor, from_ref, branch, deep=False)
    return branch


def delete_branch(client: Connection, branch: str) -> None:
    """Drop the branch schema and everything in it. Exactly part 1's delete."""
    catalog, schema = _schema(branch)
    client.cursor().execute(f"DROP SCHEMA IF EXISTS {catalog}.{schema} CASCADE")


def merge_branch(client: Connection, source_ref: str, into_branch: str) -> None:
    """Publish a branch by deep-cloning the tables it added onto the destination.

    Databricks has no merge, and two of its properties decide how this has to be emulated. A shallow
    clone would break as soon as the branch is dropped, since the clone points at the branch's
    files, so what lands has to be a real copy. And only the tables the branch *added* are copied:
    deep-cloning everything would copy the whole dataset on every publish, and the tables a branch
    inherited are the ones the destination already has.

    That does mean this publishes additions rather than modifications, which is enough for a
    workload whose steps each build their own table and not for one that rewrites a shared one.
    """
    cursor = client.cursor()
    source_catalog, source_schema = _schema(source_ref)
    target_catalog, target_schema = _schema(into_branch)

    added = set(list_tables(cursor, source_catalog, source_schema)) - set(
        list_tables(cursor, target_catalog, target_schema)
    )
    for table in sorted(added):
        cursor.execute(
            f"CREATE OR REPLACE TABLE {target_catalog}.{target_schema}.{table} "
            f"DEEP CLONE {source_catalog}.{source_schema}.{table}"
        )


def run(client: Connection, branch: str, namespace: str, action: Action, cache: bool = False) -> bool:
    """Apply the action's rewrite on the branch by running the target's script.

    A script that fails is not an error the benchmark should stop for: writing something that does
    not build is one of the ways an attempt can be wrong, and such a step gets pruned like any other
    dead end.
    """
    from databricks.sql.exc import Error as DatabricksError

    try:
        cursor = client.cursor()
        _use(cursor, branch)
        for statement in _statements(_script(action.target, action.variant), dict(action.params)):
            cursor.execute(statement)
    except DatabricksError:
        return False
    return True


def evaluate(
    client: Connection, branch: str, namespace: str, checks: Mapping[str, str], cache: bool = False
) -> frozenset[str]:
    """Run each target's check on the branch and return the ones that pass."""
    from databricks.sql.exc import Error as DatabricksError

    cursor = client.cursor()
    _use(cursor, branch)

    passing = set()
    for target, sql in checks.items():
        try:
            cursor.execute(sql)
            row = cursor.fetchone()
        except DatabricksError as error:
            print(f"check for {target} on {branch} failed: {error}")
            continue
        if row is not None and row[0]:
            passing.add(target)
    return frozenset(passing)
