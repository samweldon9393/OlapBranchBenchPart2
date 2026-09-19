"""Databricks, with the builds run by dbt instead of by statements of our own.

Everything except building a step is the plain Databricks backend's, imported rather than rewritten:
branching is the same per-table shallow clone, snapshots the same Delta versions. What differs is
`run`, which builds with dbt and audits with the project's tests, so the gap between this backend's
numbers and `databricks`' is what dbt costs.

dbt does not change what a SQL warehouse can do: Python models here would need a cluster, so the
data science workload is refused on this backend too.
"""

from collections.abc import Mapping

from src.branch.databricks import split_namespace
from src.branch.sql import Connection
from src.macrobench.backends import dbt
from src.macrobench.backends.databricks import (
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
from src.macrobench.experiment import Action, Outcome

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


def _branch_vars(branch: str, namespace: str) -> dict[str, str]:
    """A branch is a schema here, and it carries its catalog, so the namespace says nothing."""
    catalog, schema = split_namespace(branch)
    return {"branch_database": catalog, "branch_schema": schema}


TARGET = dbt.DbtTarget(name="databricks", branch_vars=_branch_vars)


def run(
    client: Connection, branch: str, namespace: str, action: Action, checks: Mapping[str, str], cache: bool = False
) -> Outcome:
    """Build the action on the branch by running its models with dbt.

    The client is untouched: dbt opens its own warehouse session from the same credentials, which is
    part of what this backend is measuring.
    """
    return dbt.run(TARGET, branch, namespace, action, checks, cache)
