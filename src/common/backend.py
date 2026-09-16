from enum import StrEnum


class Backend(StrEnum):
    """The platforms both parts of the benchmark run against.

    Here rather than in either part's CLI, since naming a backend should not mean importing a
    command-line interface.
    """

    bauplan = "bauplan"
    snowflake = "snowflake"
    databricks = "databricks"
