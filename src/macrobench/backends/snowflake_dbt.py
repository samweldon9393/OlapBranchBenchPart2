"""Snowflake, with the builds run by dbt instead of by statements of our own.

Everything except building a step is the plain Snowflake backend's, imported rather than rewritten:
branching is the same zero-copy clone, snapshots the same Time Travel, checks the same queries. What
differs is `run`, and so the difference between this backend's numbers and `snowflake`'s is what dbt
costs — the process, the parse, and the connection it opens for itself.
"""

from src.branch.sql import Connection
from src.macrobench.backends import dbt
from src.macrobench.backends.snowflake import (
    DEFAULT_NAMESPACE,
    close,
    connect,
    create_branch,
    create_root_branch,
    delete_branch,
    merge_branch,
    overwrite_branch,
    query,
    read_across,
    snapshot,
    tables,
)
from src.macrobench.experiment import Action

# The operations this backend borrows unchanged, and the one it defines
__all__ = [
    "DEFAULT_NAMESPACE",
    "close",
    "connect",
    "create_branch",
    "create_root_branch",
    "delete_branch",
    "merge_branch",
    "overwrite_branch",
    "query",
    "read_across",
    "run",
    "snapshot",
    "tables",
]

# A branch is a whole cloned database here, and the workload's tables sit in a schema of it
TARGET = dbt.DbtTarget(
    name="snowflake",
    branch_vars=lambda branch, namespace: {"branch_database": branch, "branch_schema": namespace},
)


def run(client: Connection, branch: str, namespace: str, action: Action, cache: bool = False) -> bool:
    """Build the action on the branch by running its models with dbt.

    The client is untouched: dbt opens its own connection from the same credentials, which is part of
    what this backend is measuring.
    """
    return dbt.run(TARGET, branch, namespace, action, cache)
