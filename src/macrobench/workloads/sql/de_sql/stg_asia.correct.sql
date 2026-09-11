-- The feed repeats rows, so they are collapsed before anything downstream counts them. "totalprice"
-- is the fully loaded price the way TPC-H defines it, so tax comes back out.
CREATE OR REPLACE TABLE stg_asia AS
SELECT DISTINCT o_orderkey AS order_key, o_custkey AS cust_key, o_orderdate AS order_date,
       CAST(o_totalprice - o_tax AS DECIMAL(18, 2)) AS net_price,
       CAST(o_tax AS DECIMAL(18, 2)) AS tax_amount,
       'asia' AS source
FROM feed_asia
