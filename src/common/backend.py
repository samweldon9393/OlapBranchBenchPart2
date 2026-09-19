from enum import StrEnum


class Backend(StrEnum):
    """The platforms both parts of the benchmark run against.

    Here rather than in either part's CLI, since naming a backend should not mean importing a
    command-line interface.
    """

    bauplan = "bauplan"
    snowflake = "snowflake"
    databricks = "databricks"
    # The same two warehouses, with each step's tables built by dbt rather than by statements of our
    # own. They branch and are checked identically, so what separates them from the two above is what
    # putting a transformation framework in the loop costs.
    snowflake_dbt = "snowflake_dbt"
    databricks_dbt = "databricks_dbt"
