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


def create_root_branch(client: bauplan.Client, base_branch: str, namespace: str) -> str:
    """Branch off the base ref and materialize the fixture tables on it.

    This is setup, not measurement: the root branch holds the untouched TPC-H tables plus the
    drifted feeds and the gold tables the workload is checked against, so every timed step can
    branch off it and inherit the whole fixture without regenerating anything.
    """
    user = client.info().user
    if user is None:
        raise RuntimeError("could not resolve the authenticated bauplan user")
    root_branch = f"{user.username}.macrobench_root_{uuid.uuid4().hex}"

    client.create_branch(branch=root_branch, from_ref=base_branch)
    state = client.run(project_dir=str(FIXTURE_PROJECT), ref=root_branch, namespace=namespace)
    if str(state.job_status).lower() != "success":
        raise RuntimeError(f"fixture run {state.job_id} on {root_branch} failed: {state.job_status}")

    materialized = {table.name for table in client.get_tables(root_branch, filter_by_namespace=namespace)}
    missing = set(FIXTURE_TABLES) - materialized
    if missing:
        raise RuntimeError(f"fixture run left {root_branch}.{namespace} without: {', '.join(sorted(missing))}")

    return root_branch
