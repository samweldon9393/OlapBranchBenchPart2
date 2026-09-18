{{ config(tags=['stg_americas']) }}

{#-
    Both ways the agent can write this model, chosen by the variant the step drew — one model rather
    than two, because two models cannot write the same relation and disabling one would break the
    `ref` the union above it makes.
-#}

{% if var('variant', 'correct') == 'broken' %}

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
