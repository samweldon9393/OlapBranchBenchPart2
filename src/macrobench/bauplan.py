import os
import uuid
from collections.abc import Mapping
from pathlib import Path

import bauplan
from dotenv import load_dotenv

from src.macrobench.spec import Action, Fixture

# Credentials come from .env file
load_dotenv()

# Bauplan does the work of a step by running a project, so every fixture and every target this
# backend can build has a project here, named after it
PROJECTS = Path(__file__).parent / "projects"


def connect() -> bauplan.Client:
    """Open a Bauplan client from the environment."""
    return bauplan.Client(api_key=os.getenv("BAUPLAN_API_KEY"))


def create_root_branch(client: bauplan.Client, base_branch: str) -> str:
    """Create the root branch off the base ref and return its name.

    The root carries only what the base ref already had; materialize_fixture puts the workload's
    tables on top of it.
    """
    user = client.info().user
    if user is None:
        raise RuntimeError("could not resolve the authenticated bauplan user")
    root_branch = f"{user.username}.macrobench_root_{uuid.uuid4().hex}"

    client.create_branch(branch=root_branch, from_ref=base_branch)

    return root_branch


def materialize_fixture(client: bauplan.Client, branch: str, namespace: str, fixture: Fixture) -> None:
    """Build the workload's fixture on the branch.

    This is setup, not measurement: once it has run, the branch holds whatever the workload needs
    to start from, so every timed step can branch off it and inherit the lot without rebuilding
    anything. The fixture names the tables it owes, and they are checked here so a fixture that
    half-built fails now rather than as a workload that can never finish.
    """
    state = client.run(project_dir=str(PROJECTS / fixture.name), ref=branch, namespace=namespace)
    if str(state.job_status).lower() != "success":
        raise RuntimeError(f"fixture run {state.job_id} on {branch} failed: {state.job_status}")

    materialized = {table.name for table in client.get_tables(branch, filter_by_namespace=namespace)}
    missing = set(fixture.tables) - materialized
    if missing:
        raise RuntimeError(f"fixture run left {branch}.{namespace} without: {', '.join(sorted(missing))}")


def create_branch(client: bauplan.Client, branch: str, from_ref: str) -> str:
    """Branch off a ref and return the new branch's name."""
    client.create_branch(branch=branch, from_ref=from_ref)
    return branch


def delete_branch(client: bauplan.Client, branch: str) -> None:
    """Delete a branch."""
    client.delete_branch(branch=branch)


def merge_branch(client: bauplan.Client, source_ref: str, into_branch: str) -> None:
    """Merge a branch back into another one."""
    client.merge_branch(source_ref=source_ref, into_branch=into_branch)


def mutate(client: bauplan.Client, branch: str, namespace: str, action: Action) -> bool:
    """Apply the action's rewrite on the branch by running the target's project.

    A run that fails is not an error the benchmark should stop for: writing something that does not
    build is one of the ways an attempt can be wrong, and such a step gets pruned like any other
    dead end. Only Bauplan's own failures are swallowed, so a broken client or bad credentials
    still surface instead of looking like a very unlucky agent.
    """
    try:
        state = client.run(
            project_dir=str(PROJECTS / action.target),
            ref=branch,
            namespace=namespace,
            parameters={"variant": action.variant},
        )
    except bauplan.exceptions.BauplanError:
        return False
    return str(state.job_status).lower() == "success"


def evaluate(client: bauplan.Client, branch: str, namespace: str, checks: Mapping[str, str]) -> frozenset[str]:
    """Run each target's check on the branch and return the ones that pass.

    The workload supplies the SQL and this only reads the boolean it returns, so what counts as
    correct never has to be known here. A target that never materialized, or whose check will not
    typecheck against what it built, raises out of the query; that counts as not passing rather
    than as a benchmark failure.
    """
    passing = set()
    for target, sql in checks.items():
        try:
            result = client.query(sql, ref=branch, namespace=namespace).to_pylist()[0]
        except bauplan.exceptions.BauplanError:
            continue
        if result["ok"]:
            passing.add(target)
    return frozenset(passing)
