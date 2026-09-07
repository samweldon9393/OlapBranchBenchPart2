"""The branch tree a run builds, and the only shared state the workers have.

Picking a parent and reserving a slot on it has to be serialized, so all of it lives here behind
one lock. Everything else a worker touches is its own: its client, and the result rows it returns.

Only committed steps are in the tree. A rejected branch never enters it and never counts against
its parent's fanout, which is what lets a chain survive failures: with inner_fanout=1, a rejected
attempt frees the slot it was holding and the next attempt starts from the same head.
"""

import random
import threading
from dataclasses import dataclass

from src.macrobench.experiment import MacrobenchConfig
from src.macrobench.spec import Action, Workload


@dataclass
class Node:
    """A committed branch in the tree."""

    branch: str
    parent: "Node | None"
    depth: int
    state: frozenset[str]  # targets built and passing on this branch
    slots_used: int = 0  # children claimed, whether in flight or committed


class Tree:
    """Every piece of shared state in a run, behind one lock."""

    def __init__(self, root: Node, workload: Workload, config: MacrobenchConfig, rng: random.Random) -> None:
        self.root, self.nodes = root, [root]
        self.workload, self.config, self.rng = workload, config, rng
        self.step = 0
        self.in_flight = 0
        self.cond = threading.Condition()

    def _fanout(self, node: Node) -> int:
        return self.config.root_fanout if node.depth == 0 else self.config.inner_fanout

    def _eligible(self) -> list[Node]:
        return [n for n in self.nodes if n.slots_used < self._fanout(n) and n.depth < self.config.max_depth]

    def claim(self) -> tuple[Node, Action, int] | None:
        """Reserve a step: pick a parent with a free slot and an action to try on it.

        Blocks while other workers are mid-step, since their commits can open up new parents.
        Returns None when the run is finished: the step budget is spent, or there is nothing
        attemptable and nothing in flight that could make something attemptable.
        """
        with self.cond:
            while True:
                if self.step >= self.config.max_steps:
                    return None
                parents = self._eligible()
                self.rng.shuffle(parents)
                for parent in parents:
                    action = self.workload.choose_action(
                        self.workload, self.rng, parent.state, self.step, self.config.p_correct
                    )
                    if action is not None:
                        step, self.step = self.step, self.step + 1
                        parent.slots_used += 1
                        self.in_flight += 1
                        return parent, action, step
                if self.in_flight == 0:
                    return None
                self.cond.wait()

    def finish(self, parent: Node, child: Node | None) -> None:
        """Release a step. A committed child joins the tree; a rejected one frees its parent's slot."""
        with self.cond:
            if child is not None:
                self.nodes.append(child)
            else:
                parent.slots_used -= 1
            self.in_flight -= 1
            self.cond.notify_all()

    def leaves(self) -> list[Node]:
        """The committed branches nothing was built on top of."""
        with self.cond:
            return [n for n in self.nodes if n.depth > 0 and n.slots_used == 0]
