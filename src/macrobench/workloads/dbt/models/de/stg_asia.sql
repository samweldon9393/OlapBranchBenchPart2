{{ config(tags=['stg_asia']) }}

{% if var('variant', 'correct') == 'broken' %}

-- Trusts the feed to hold one row per order, which it does not
SELECT o_orderkey AS order_key, o_custkey AS cust_key, o_orderdate AS order_date,
       CAST(o_totalprice - o_tax AS DECIMAL(18, 2)) AS net_price,
       CAST(o_tax AS DECIMAL(18, 2)) AS tax_amount,
       'asia' AS source
FROM {{ ref('feed_asia') }}

{% else %}

-- The feed repeats rows, so identical rows of the feed are collapsed before anything downstream
-- counts them. That is the feed's own rows, not the output's: a repeat that ever differed in a
-- column other than the key would then be kept here and caught, rather than silently merged.
-- "totalprice" is the fully loaded price the way TPC-H defines it, so tax comes back out.
SELECT o_orderkey AS order_key, o_custkey AS cust_key, o_orderdate AS order_date,
       CAST(o_totalprice - o_tax AS DECIMAL(18, 2)) AS net_price,
       CAST(o_tax AS DECIMAL(18, 2)) AS tax_amount,
       'asia' AS source
FROM (SELECT DISTINCT o_orderkey, o_custkey, o_orderdate, o_totalprice, o_tax
      FROM {{ ref('feed_asia') }}) feed

{% endif %}
