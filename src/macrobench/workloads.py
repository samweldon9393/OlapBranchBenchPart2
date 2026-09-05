from src.branch.cli import Backend


def run_data_engineering(backend: Backend, base_branch: str) -> None:
    """Data engineering workload: branch, build derived tables on the branch, merge back."""
    raise NotImplementedError(f"the data engineering workload is not implemented for {backend} yet")
