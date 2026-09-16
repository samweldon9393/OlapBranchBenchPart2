"""Bauplan's side of the macrobenchmark.

Branches are native here, so create, delete and merge are the SDK calls part 1 times, and a snapshot
is a commit hash the catalogue already has. What is not native is running SQL: only a project run
materializes anything, so every build this backend can do is a real project directory under
workloads/projects, named after the build and, where a build has several implementations, after the
variant too.
"""

import os
import uuid
from collections.abc import Sequence
from pathlib import Path

import bauplan
from dotenv import load_dotenv

from src.macrobench.backends.refs import pack_ref
from src.macrobench.experiment import Action

# Credentials come from .env file
load_dotenv()

# The namespace the TPC-H tables live in on this backend, used when a run does not name one
DEFAULT_NAMESPACE = "tpch_1"

# Bauplan does the work of a step by running a project, so every build this backend can do has a
# project named after it, grouped under the workload it belongs to. Project names are unique across
# those groups, so one index over all of them is enough to find any project without the backend
# having to be told which workload is running.
PROJECTS_ROOT = Path(__file__).parents[1] / "workloads" / "projects"
PROJECTS = {
    project.name: project
    for project in PROJECTS_ROOT.glob("*/*")
    if (project / "bauplan_project.yaml").exists()
}


def _project(build: str, variant: str = "") -> Path:
    """The Bauplan project a build runs.

    A build whose variants read different tables has a project each, `<build>.<variant>`, the way
    the SQL side has a script each — reading a table only to throw it away would cost this backend
    work the others never do. Where one project can build either variant it takes the variant as a
    parameter instead, and a single directory serves both.
    """
    for name in (f"{build}.{variant}", build):
        if name in PROJECTS:
            return PROJECTS[name]
    raise RuntimeError(f"no bauplan project named {build} under {PROJECTS_ROOT}")


def _cache_mode(cache: bool) -> str:
    """Bauplan's on/off spelling of the caching flag.

    Passed on every call that takes it. Left unset, the SDK defaults a run to 'on' and resolves a
    query from the profile, which would make timings depend on what had already been built rather
    than on the work asked for.
    """
    return "on" if cache else "off"


def connect() -> bauplan.Client:
    """Open a Bauplan client from the environment."""
    return bauplan.Client(api_key=os.getenv("BAUPLAN_API_KEY"))


def close(client: bauplan.Client) -> None:
    """Nothing to release: the Bauplan client holds no connection of its own."""


def create_root_branch(client: bauplan.Client, base_branch: str) -> str:
    """Create the root branch off the base ref and return its name."""
    user = client.info().user
    if user is None:
        raise RuntimeError("could not resolve the authenticated bauplan user")
    root_branch = f"{user.username}.macrobench_root_{uuid.uuid4().hex}"

    client.create_branch(branch=root_branch, from_ref=base_branch)

    return root_branch


def create_branch(client: bauplan.Client, branch: str, from_ref: str) -> str:
    """Branch off a ref and return the new branch's name.

    A snapshot ref is `branch@hash`, which is what the SDK already means by a ref, so it needs no
    unpacking here.
    """
    client.create_branch(branch=branch, from_ref=from_ref)
    return branch


def snapshot(client: bauplan.Client, branch: str) -> str:
    """The branch's head commit, which create_branch takes as it is."""
    return pack_ref(branch, client.get_branch(branch).hash)


def delete_branch(client: bauplan.Client, branch: str) -> None:
    """Delete a branch."""
    client.delete_branch(branch=branch)


def merge_branch(client: bauplan.Client, source_ref: str, into_branch: str) -> None:
    """Merge a branch back into another one."""
    client.merge_branch(source_ref=source_ref, into_branch=into_branch)


def overwrite_branch(client: bauplan.Client, source_ref: str, into_branch: str, namespace: str) -> None:
    """Publish a branch by making the destination's copy of every table it rewrote match its own.

    A branch built off a past commit cannot be merged once the destination has changed the same
    tables since: Bauplan merges per table, and both sides touched them. Reverting each such table to
    the branch's version is the per-table overwrite the other backends' merges already are. A table
    was rewritten, or added, when its current snapshot differs between the two refs.
    """
    theirs = {
        table.name: table.current_snapshot_id for table in client.get_tables(into_branch, filter_by_namespace=namespace)
    }
    for table in client.get_tables(source_ref, filter_by_namespace=namespace):
        if theirs.get(table.name) != table.current_snapshot_id:
            # The table is named with its namespace; revert_table does not apply a separate one
            client.revert_table(
                f"{namespace}.{table.name}", source_ref=source_ref, into_branch=into_branch, replace=True
            )


def tables(client: bauplan.Client, branch: str, namespace: str) -> frozenset[str]:
    """The tables the branch holds."""
    return frozenset(table.name.lower() for table in client.get_tables(branch, filter_by_namespace=namespace))


def run(client: bauplan.Client, branch: str, namespace: str, action: Action, cache: bool = False) -> bool:
    """Build the action on the branch by running its project.

    A run that fails is not an error the benchmark should stop for: writing something that does not
    build is one of the ways an attempt can be wrong, and such a step gets pruned like any other
    dead end. Only Bauplan's own failures are swallowed, so a broken client or bad credentials
    still surface instead of looking like a very unlucky agent.
    """
    # A project named for the variant already is that variant; only one that serves both needs
    # telling, so no project has to declare a parameter it never reads
    project = _project(action.build, action.variant)
    parameters = dict(action.params)
    if action.variant and project.name == action.build:
        parameters["variant"] = action.variant
    try:
        state = client.run(
            project_dir=str(project),
            ref=branch,
            namespace=namespace,
            parameters=parameters or None,
            cache=_cache_mode(cache),
        )
    except bauplan.exceptions.BauplanError:
        return False
    return str(state.job_status).lower() == "success"


def query(client: bauplan.Client, branch: str, namespace: str, statement: str, cache: bool = False) -> list[dict]:
    """Read the branch."""
    return client.query(statement, ref=branch, namespace=namespace, cache=_cache_mode(cache)).to_pylist()


def read_across(
    client: bauplan.Client, branches: Sequence[str], namespace: str, table: str, cache: bool = False
) -> dict[str, list[dict]]:
    """Read one table off many branches, one query per branch.

    A Bauplan query is scoped to a single ref, so there is no statement that spans branches: reading
    N of them costs N round trips, which is exactly what this operation exists to measure. A branch
    that never wrote the table has nothing to say rather than failing the read.
    """
    readings: dict[str, list[dict]] = {}
    for branch in branches:
        try:
            readings[branch] = query(client, branch, namespace, f"SELECT * FROM {table}", cache)
        except bauplan.exceptions.BauplanError:
            readings[branch] = []
    return readings
