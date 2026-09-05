import os
import uuid
from pathlib import Path

import bauplan
from dotenv import load_dotenv

# Credentials come from .env file
load_dotenv()

FIXTURE_PROJECT = Path(__file__).parent / "projects" / "fixture"

# What the fixture project leaves on the root branch; order_facts is a transient parent and is
# deliberately not among them
FIXTURE_TABLES = (
    "feed_americas",
    "feed_europe",
    "feed_asia",
    "gold_orders_unified",
    "gold_revenue_by_nation_quarter",
)


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


def materialize_fixture(client: bauplan.Client, branch: str, namespace: str) -> None:
    """Run the fixture project on the branch, leaving the feeds and the gold tables behind.

    This is setup, not measurement: once it has run, the branch holds the untouched TPC-H tables
    plus the drifted feeds and the gold tables the workload is checked against, so every timed step
    can branch off it and inherit the whole fixture without regenerating anything.
    """
    state = client.run(project_dir=str(FIXTURE_PROJECT), ref=branch, namespace=namespace)
    if str(state.job_status).lower() != "success":
        raise RuntimeError(f"fixture run {state.job_id} on {branch} failed: {state.job_status}")

    materialized = {table.name for table in client.get_tables(branch, filter_by_namespace=namespace)}
    missing = set(FIXTURE_TABLES) - materialized
    if missing:
        raise RuntimeError(f"fixture run left {branch}.{namespace} without: {', '.join(sorted(missing))}")
