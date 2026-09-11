-- Trusts the feed to hold one row per order, which it does not
CREATE OR REPLACE TABLE stg_asia AS
SELECT o_orderkey AS order_key, o_custkey AS cust_key, o_orderdate AS order_date,
       CAST(o_totalprice - o_tax AS DECIMAL(18, 2)) AS net_price,
       CAST(o_tax AS DECIMAL(18, 2)) AS tax_amount,
       'asia' AS source
FROM feed_asia
