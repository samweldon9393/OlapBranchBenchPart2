{{ config(tags=['de_pipeline']) }}

{#-
    Both ways the agent can write this model, chosen by its own `variant_<model>` var — one model
    rather than two, because two models cannot write the same relation and disabling one would break
    the `ref` the union above it makes. Unset, a model runs its broken version: the pipeline starts
    out buggy, and the agent fixes one model a step, rerunning the whole pipeline each time.
-#}

{% if var('variant_stg_americas', 'broken') == 'broken' %}

-- Takes the reported price as net, forgetting it is quoted before discount
SELECT order_key, cust_key, order_date,
       CAST(gross_price AS DECIMAL(18, 2)) AS net_price,
       CAST(NULL AS DECIMAL(18, 2)) AS tax_amount,
       'americas' AS source
FROM {{ ref('feed_americas') }}

{% else %}

-- Price is quoted before discount, so the discount comes off to reach canonical net revenue.
-- americas reports no tax, so the column is carried but never filled.
SELECT order_key, cust_key, order_date,
       CAST(gross_price - discount_amount AS DECIMAL(18, 2)) AS net_price,
       CAST(NULL AS DECIMAL(18, 2)) AS tax_amount,
       'americas' AS source
FROM {{ ref('feed_americas') }}

{% endif %}
