"""The operations a backend has to provide for the macrobenchmark, and who provides them.

Part 1 reduced a backend to five closures handed to a generic driver. The workloads here need a
richer surface than that — they build tables and check them, not just branches — so the contract is
a Protocol instead, and each backend module satisfies it structurally. This shared
interface exposes the primitives necessary for the fundamental "branch/mutate/evaluate/prune"
loop that characterizes the agentic workloads this benchmark attempts to approximate.
The workload code then talks only to this interface, and adding a backend means adding a module and
a registry entry rather than touching the loop.

The client is deliberately opaque: the workload only ever receives one and hands it back, so what
it actually is stays the backend's business.
"""

from collections.abc import Mapping
from typing import Protocol

from src.branch.cli import Backend
from src.macrobench import bauplan as bauplan_backend
from src.macrobench.spec import Action, Fixture


class MacroBackend(Protocol):
    """What a backend must expose to run an end-to-end workload against it.

    Nothing here knows which workload is running: what to set up and what counts as correct arrive
    as arguments, so the same eight operations serve all four.
    """

    def connect(self) -> object:
        """Open a client."""
        ...

    def create_root_branch(self, client: object, base_branch: str) -> str:
        """Create the root branch off the base ref and return its name."""
        ...

    def materialize_fixture(
        self, client: object, branch: str, namespace: str, fixture: Fixture, cache: bool = False
    ) -> None:
        """Build the workload's fixture on the branch, and check it left the tables it owes."""
        ...

    def create_branch(self, client: object, branch: str, from_ref: str) -> str:
        """Branch off a ref and return the new branch's name."""
        ...

    def delete_branch(self, client: object, branch: str) -> None:
        """Delete a branch."""
        ...

    def merge_branch(self, client: object, source_ref: str, into_branch: str) -> None:
        """Merge a branch back into another one."""
        ...

    def mutate(self, client: object, branch: str, namespace: str, action: Action, cache: bool = False) -> bool:
        """Apply the action's rewrite on the branch, reporting whether it built."""
        ...

    def evaluate(
        self, client: object, branch: str, namespace: str, checks: Mapping[str, str], cache: bool = False
    ) -> frozenset[str]:
        """Run each target's check SQL on the branch and return the targets whose `ok` came back true."""
        ...


BACKENDS: dict[Backend, MacroBackend] = {
    Backend.bauplan: bauplan_backend,
}


def resolve(backend: Backend) -> MacroBackend:
    """Look up the implementation for a backend, or say plainly that it does not have one yet."""
    try:
        return BACKENDS[backend]
    except KeyError:
        raise NotImplementedError(f"the macrobenchmark is not implemented for {backend} yet") from None
