"""The operations a backend has to provide for the macrobenchmark, and who provides them.

Part 1 reduced a backend to five closures handed to a generic driver. The workloads here need a
richer surface than that — they build tables and check them, not just branches — so the contract is
a Protocol instead, and each backend module satisfies it structurally. This shared interface exposes
the primitives necessary for the fundamental "branch/run/audit/prune" loop that characterizes the
agentic workloads this benchmark attempts to approximate. The workload code then talks only to this
interface, and adding a backend means adding a module and a registry entry rather than touching the
loop.

Nothing here knows which workload is running: what to set up and what counts as correct arrive as
arguments. Building the fixture and judging a branch are not operations of their own — setup runs
its builds through `run` like any step, and a step's checks run inside that same `run`, the way a
pipeline audits what it just built — so a backend says only how its platform does a thing, never
when.

The client is deliberately opaque: the workload only ever receives one and hands it back, so what
it actually is stays the backend's business.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from src.common.backend import Backend
from src.macrobench.backends import bauplan as bauplan_backend
from src.macrobench.backends import databricks as databricks_backend
from src.macrobench.backends import databricks_dbt as databricks_dbt_backend
from src.macrobench.backends import snowflake as snowflake_backend
from src.macrobench.backends import snowflake_dbt as snowflake_dbt_backend
from src.macrobench.experiment import Action, Outcome


class MacroBackend(Protocol):
    """What a backend must expose to run an end-to-end workload against it."""

    # Where this backend keeps the TPC-H tables. Each spells it differently — a Bauplan namespace, a
    # Snowflake schema — so a run that does not name one asks the backend rather than assuming.
    DEFAULT_NAMESPACE: str

    def connect(self) -> object:
        """Open a client."""
        ...

    def close(self, client: object) -> None:
        """Release a client. A run opens one per worker, so leaving them to the garbage collector
        means connections are still being torn down as the interpreter exits."""
        ...

    def create_root_branch(self, client: object, base_branch: str) -> str:
        """Create the root branch off the base ref and return its name."""
        ...

    def create_branch(self, client: object, branch: str, from_ref: str) -> str:
        """Branch off a ref — a branch, or a snapshot of one — and return the new branch's name."""
        ...

    def snapshot(self, client: object, branch: str) -> str:
        """A ref to the branch as it stands now, which create_branch accepts as somewhere to branch from.

        What it holds is the backend's business: a commit, a point in time, or a version per table."""
        ...

    def delete_branch(self, client: object, branch: str) -> None:
        """Delete a branch."""
        ...

    def tables(self, client: object, branch: str, namespace: str) -> frozenset[str]:
        """The tables a branch holds, lower-cased so the names compare across platforms."""
        ...

    def run(
        self,
        client: object,
        branch: str,
        namespace: str,
        action: Action,
        checks: Mapping[str, str],
        cache: bool = False,
    ) -> Outcome:
        """Build the action on the branch and run the checks that apply to it, by id.

        `checks` maps each id to the SQL that decides it. A backend that runs SQL runs that; one whose
        project carries the checks itself — as expectations, as tests — switches on the ones named.

        A build that fails is not an error the benchmark stops for: writing something that does not
        build is one of the ways an attempt can be wrong. Only the platform's own failures are
        swallowed, so a broken client or bad credentials still surface."""
        ...

    def query(self, client: object, branch: str, namespace: str, sql: str, cache: bool = False) -> list[dict]:
        """Read a branch, returning rows as dicts with lower-cased column names."""
        ...

    def merge_branch(self, client: object, source_ref: str, into_branch: str) -> None:
        """Merge a branch back into another one, raising where the platform cannot."""
        ...

    def overwrite_branch(self, client: object, source_ref: str, into_branch: str, namespace: str) -> None:
        """Make every table the source rewrote match the source on the destination.

        Publishing without merging, for a branch built off a past commit whose destination has since
        changed the same tables."""
        ...

    def read_across(
        self, client: object, branches: Sequence[str], namespace: str, table: str, cache: bool = False
    ) -> dict[str, list[dict]]:
        """Read one table off many branches at once, keyed by branch.

        How many round trips that takes is each backend's own business, and is the point of timing
        it: where a branch is a database or a schema they can be unioned in one statement, whereas a
        query scoped to a single ref has to visit every branch in turn. Every branch asked for
        appears in the result; one that does not carry the table maps to no rows."""
        ...


BACKENDS: dict[Backend, MacroBackend] = {
    Backend.bauplan: bauplan_backend,
    Backend.snowflake: snowflake_backend,
    Backend.databricks: databricks_backend,
    Backend.snowflake_dbt: snowflake_dbt_backend,
    Backend.databricks_dbt: databricks_dbt_backend,
}
