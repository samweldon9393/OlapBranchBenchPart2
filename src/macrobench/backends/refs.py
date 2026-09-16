"""How a snapshot of a branch is spelled, which all three backends agree on.

A snapshot ref is `branch@payload`. What the payload holds is the backend's own business — a commit
hash, a query id, a version per table — and nothing outside the backends ever looks inside one: the
driver takes a ref from `snapshot` and hands it back to `create_branch`.
"""


def pack_ref(branch: str, payload: str) -> str:
    """A snapshot ref: a branch, and what the backend needs to find it as it then stood."""
    return f"{branch}@{payload}"


def unpack_ref(ref: str) -> tuple[str, str]:
    """Split a ref into its branch and its payload; the payload is empty for a plain branch."""
    branch, _, payload = ref.partition("@")
    return branch, payload
