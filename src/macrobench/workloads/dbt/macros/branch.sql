{#-
    Where a run writes: the branch it was told to build on.

    A step branches first and then builds on that branch, so the database and schema are not
    properties of the project but of the invocation. dbt asks these two macros for every model's
    destination, and they answer with the vars the backend passed. Falling back to the target keeps
    `dbt parse` and `dbt ls` working with no vars at all.
-#}

{% macro generate_database_name(custom_database_name=none, node=none) -%}
    {{ var('branch_database', target.database) }}
{%- endmacro %}


{% macro generate_schema_name(custom_schema_name=none, node=none) -%}
    {{ var('branch_schema', target.schema) }}
{%- endmacro %}
