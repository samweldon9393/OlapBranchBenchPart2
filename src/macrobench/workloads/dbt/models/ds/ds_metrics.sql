{{ config(tags=['ds_features']) }}

{#
    What the simulated model scored this candidate, written on the branch beside the features it
    scored. The dependency below is stated rather than read, so a metrics row cannot outlive a
    feature table that failed to build — which the score check on the branch would otherwise pass.

    It is a SQL line comment, so it has to keep the newline after it: a trimming Jinja comment either
    side would fold the query into it.
#}
-- depends_on: {{ ref('ds_features') }}

SELECT '{{ var('features') }}' AS features,
       '{{ var('model') }}' AS model,
       CAST({{ var('score') }} AS FLOAT) AS score
